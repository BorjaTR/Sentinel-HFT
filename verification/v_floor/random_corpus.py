"""
V-Floor random corpus generator + golden-only run.

The same corpus is fed to:
  - the Python golden model (this file's `golden_run`)
  - the Verilator-built RTL sim (sim/sim_risk → tools/v_floor_rtl_run.cpp)
  - the post-synth gate-level sim (Phase 1 stretch)

A pass requires every (decision, reason) tuple to match across engines.

Usage:
    python -m verification.v_floor.random_corpus --orders 1_000_000 --seed 42 \
        --out verification/reports/v_floor/golden_seed42.json

The CI hook then runs the RTL leg against the same JSON and a parity check.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, List, Tuple

from sentinel_hft.golden import (
    Decision,
    Fill,
    GateConfig,
    GoldenRiskGate,
    Order,
    OrderSide,
    OrderType,
    RejectReason,
)


# -------------------------------------------------------------------------
# Default config — generous limits so the corpus exercises every reject path
# -------------------------------------------------------------------------

DEFAULT_CFG = GateConfig(
    # Rate: tight enough to fire on bursts.
    rate_max_tokens=64,
    rate_refill_rate=4,
    rate_refill_period=10,
    # Position: tight enough that POSITION_LIMIT fires under a few tens of
    # accumulated fills.
    # All four position-family caps tuned so each one can fire under the
    # corpus distribution defined below:
    #   - pos_max_order_qty: tight enough that the 1% "oversize" tail
    #     reliably hits ORDER_SIZE.
    #   - pos_max_long/short: tight enough that POSITION_LIMIT fires after
    #     a few accepted fills.
    #   - pos_max_notional: just generous enough that it fires only on the
    #     occasional very-large-notional order, not on every order.
    pos_max_long=10_000,
    pos_max_short=10_000,
    # Notional cap pegged effectively-off here: it pre-empts POSITION_LIMIT
    # in the gate's check order, so leaving it generous lets the random
    # corpus actually exercise the position path. NOTIONAL_LIMIT is
    # exercised by the deterministic scenario in test_golden_risk_gate.py.
    pos_max_notional=10**18,
    pos_max_order_qty=50_000,
    # Kill switch: auto-trigger DISABLED in the random corpus — once tripped
    # it would dominate the rest of the run because kill is sticky. The
    # KILL_SWITCH path is exercised by the deterministic scenarios in
    # tests/test_golden_risk_gate.py instead.
    kill_armed=True,
    kill_auto_enabled=False,
    kill_loss_threshold=-(10**9),
    ff_enabled=True,
    ff_band_bps=500,                  # 5%
    ff_ref_price=10_000_000_000,       # $100 fixed-point
    allowlist_enabled=True,
    allowlist=tuple(range(1, 17)),    # symbols 1..16 allowed
)


# Reject reasons that the random corpus is not designed to exercise. The
# histogram warner ignores these.
#   - OK is the success label, not a reject reason.
#   - INVALID_ORDER and DISABLED are reserved for future paths.
#   - KILL_SWITCH is intentionally exercised by deterministic scenarios in
#     tests/test_golden_risk_gate.py (sticky-state would dominate any random
#     corpus once tripped).
NOT_EXERCISED_BY_RANDOM_CORPUS = {
    "OK",                  # success label, not a reject reason
    "INVALID_ORDER",       # reserved for future malformed-order paths
    "DISABLED",            # only fires when a sub-module is disabled
    "KILL_SWITCH",         # sticky once tripped → covered by deterministic test
    "NOTIONAL_LIMIT",      # pre-empts POSITION_LIMIT in gate order → covered by deterministic test
}


# -------------------------------------------------------------------------
# Corpus generator
# -------------------------------------------------------------------------

def generate_corpus(
    n_orders: int,
    seed: int,
    cfg: GateConfig = DEFAULT_CFG,
) -> Tuple[List[Order], List[Tuple[int, Fill]], List[Tuple[int, int]]]:
    """Build a deterministic random corpus of orders + fills + pnl updates.

    Distribution is intentionally hostile: skewed prices to exercise
    fat-finger, occasional out-of-allowlist symbols, sporadic large
    quantities for size rejects, occasional p&l excursions for auto-kill.
    """
    rng = random.Random(seed)
    orders: List[Order] = []
    fills: List[Tuple[int, Fill]] = []
    pnl_updates: List[Tuple[int, int]] = []

    cur_pnl = 0
    for i in range(n_orders):
        # 5% heartbeats, 5% cancels, 90% news
        otype_roll = rng.random()
        if otype_roll < 0.05:
            otype = OrderType.HEARTBEAT
        elif otype_roll < 0.10:
            otype = OrderType.CANCEL
        else:
            otype = OrderType.NEW

        # Symbol: 92% in allowlist, 8% outside.
        if rng.random() < 0.08:
            symbol = rng.randint(100, 999)   # outside the 1..16 allowlist
        else:
            symbol = rng.randint(1, 16)

        side = rng.choice([OrderSide.BUY, OrderSide.SELL])

        # Price: 90% within fat-finger band, 10% outside.
        ref = cfg.ff_ref_price
        if rng.random() < 0.10:
            # Outside band: ±10–30% off ref.
            mult = 1.0 + rng.choice([1, -1]) * rng.uniform(0.10, 0.30)
        else:
            # Inside band: ±0–4%
            mult = 1.0 + rng.uniform(-0.04, 0.04)
        price = max(1, int(ref * mult))

        # Quantity distribution:
        #   - 96% small (1..500) → most orders pass on size, exercise other paths.
        #   - 3% medium (500..40_000) → contribute to position fills.
        #   - 1% oversize (60_000..250_000) → trip ORDER_SIZE (cap = 50_000).
        size_roll = rng.random()
        if size_roll < 0.96:
            qty = rng.randint(1, 500)
        elif size_roll < 0.99:
            qty = rng.randint(500, 40_000)
        else:
            qty = rng.randint(60_000, 250_000)

        notional = qty * price
        orders.append(
            Order(
                order_id=i,
                symbol_id=symbol,
                side=side,
                order_type=otype,
                quantity=qty,
                price=price,
                notional=notional,
            )
        )

        # Sporadic fills (~30% of orders trigger a partial fill on the same
        # symbol/side at a small fraction of the quantity).
        if rng.random() < 0.30 and otype == OrderType.NEW:
            fill_qty = max(1, qty // 10)
            fills.append(
                (
                    i,
                    Fill(
                        side=side,
                        quantity=fill_qty,
                        notional=fill_qty * price,
                    ),
                )
            )

        # Sporadic P&L updates (~5%).
        if rng.random() < 0.05:
            cur_pnl += rng.randint(-(10**8), 10**8)
            pnl_updates.append((i, cur_pnl))

    return orders, fills, pnl_updates


# -------------------------------------------------------------------------
# Golden run
# -------------------------------------------------------------------------

def golden_run(
    orders: Iterable[Order],
    fills: List[Tuple[int, Fill]],
    pnl_updates: List[Tuple[int, int]],
    cfg: GateConfig = DEFAULT_CFG,
) -> List[Decision]:
    gate = GoldenRiskGate(cfg)
    decisions: List[Decision] = []
    f_iter = iter(fills)
    p_iter = iter(pnl_updates)
    next_fill = next(f_iter, None)
    next_pnl = next(p_iter, None)

    for idx, order in enumerate(orders):
        gate.tick()
        d = gate.decide(order)
        decisions.append(d)
        while next_fill is not None and next_fill[0] == idx:
            gate.fill(next_fill[1])
            next_fill = next(f_iter, None)
        while next_pnl is not None and next_pnl[0] == idx:
            gate.update_pnl(next_pnl[1])
            next_pnl = next(p_iter, None)

    return decisions


# -------------------------------------------------------------------------
# JSON serialisation (the parity tools read this back)
# -------------------------------------------------------------------------

def serialise(
    orders: List[Order],
    fills: List[Tuple[int, Fill]],
    pnl_updates: List[Tuple[int, int]],
    decisions: List[Decision],
    seed: int,
    cfg: GateConfig,
) -> dict:
    return {
        "schema_version": 1,
        "seed": seed,
        "n_orders": len(orders),
        "config": _serialise_cfg(cfg),
        "orders": [_serialise_order(o) for o in orders],
        "fills": [
            {"after_idx": idx, "side": int(f.side), "qty": f.quantity, "notional": f.notional}
            for idx, f in fills
        ],
        "pnl_updates": [
            {"after_idx": idx, "pnl_signed": pnl} for idx, pnl in pnl_updates
        ],
        "decisions": [_serialise_decision(d) for d in decisions],
    }


def _serialise_cfg(cfg: GateConfig) -> dict:
    d = asdict(cfg)
    d["allowlist"] = list(cfg.allowlist)
    return d


def _serialise_order(o: Order) -> dict:
    return {
        "order_id": o.order_id,
        "symbol_id": o.symbol_id,
        "side": int(o.side),
        "order_type": int(o.order_type),
        "qty": o.quantity,
        "price": o.price,
        "notional": o.notional,
    }


def _serialise_decision(d: Decision) -> dict:
    return {
        "passed": d.passed,
        "reason": int(d.reason),
        "tokens_remaining": d.tokens_remaining,
        "current_position": d.current_position,
        "current_notional": d.current_notional,
    }


# -------------------------------------------------------------------------
# Reject-reason histogram (proves the corpus exercises every code path)
# -------------------------------------------------------------------------

def histogram(decisions: List[Decision]) -> dict:
    h: dict = {r.name: 0 for r in RejectReason}
    h["PASS"] = 0
    for d in decisions:
        if d.passed:
            h["PASS"] += 1
        else:
            h[d.reason.name] += 1
    return h


# -------------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------------

def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="V-Floor random corpus + golden run.")
    ap.add_argument("--orders", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    args.out.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    orders, fills, pnls = generate_corpus(args.orders, args.seed)
    t_gen = time.perf_counter() - t0

    t0 = time.perf_counter()
    decisions = golden_run(orders, fills, pnls)
    t_run = time.perf_counter() - t0

    blob = serialise(orders, fills, pnls, decisions, args.seed, DEFAULT_CFG)
    with args.out.open("w") as f:
        json.dump(blob, f)

    h = histogram(decisions)

    print(f"V-Floor corpus seed={args.seed} n={args.orders}")
    print(f"  generation: {t_gen:.2f}s  golden run: {t_run:.2f}s")
    print(f"  written: {args.out}")
    print(f"  histogram: {h}")

    # Sanity: every reject code that the random corpus is designed to
    # exercise should appear at least once.
    missing = [
        name
        for name, count in h.items()
        if count == 0 and name not in NOT_EXERCISED_BY_RANDOM_CORPUS
    ]
    if missing:
        print(f"  WARNING: corpus did not exercise: {missing}")
        return 1
    print("  ok: every targeted reject path exercised at least once.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
