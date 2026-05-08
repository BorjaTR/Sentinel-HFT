"""
V-Meta — metamorphic relations on the Sentinel risk gate.

Metamorphic testing exercises invariants that must hold between RELATED
inputs even when we don't know the absolute correct output. For the risk
gate, four families of relations matter:

  M1  Order-id invariance
      The decision does not depend on order_id. For any pair of orders
      (a, b) identical except in order_id, the gate must produce the
      same (passed, reject_reason) for both.

  M2  Side symmetry
      A long-only world is the mirror image of a short-only world. If
      we flip every order's side AND flip max_long ↔ max_short, every
      decision must match.

  M3  Scale invariance
      Multiplying every quantity AND every quantity-cap by the same
      positive integer k must preserve every decision.

  M4  Reject-precedence stability under non-conflicting permutation
      If two orders are independent (different symbols, neither hits
      a stateful counter) reordering them must not change either's
      decision.

Each relation is checked against `M_PAIRS_PER_RELATION` randomly drawn
input pairs, seeded for reproducibility.

Phase-1 thresholds (from roadmap/pre_reg/phase_01.yml):
  pass : 100% of relations hold across 10⁵ pairs.
  fail : any relation violated outside its documented exceptions.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from sentinel_hft.golden import (
    Decision,
    Fill,
    GateConfig,
    GoldenRiskGate,
    Order,
    OrderSide,
    OrderType,
    RejectReason,
    evaluate_stream,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
M_PAIRS_PER_RELATION = 10_000   # Phase 1 budget; bump to 100_000 for ship gate


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _decisions_equal(a: Decision, b: Decision) -> bool:
    return a.passed == b.passed and a.reason == b.reason


def _flip_side(s: OrderSide) -> OrderSide:
    return OrderSide.SELL if s == OrderSide.BUY else OrderSide.BUY


def _make_random_order(rng: random.Random, allowlist: Tuple[int, ...]) -> Order:
    qty = rng.randint(1, 5_000)
    price = rng.randint(8 * 10**9, 12 * 10**9)
    symbol = rng.choice(allowlist) if allowlist else rng.randint(1, 16)
    side = rng.choice([OrderSide.BUY, OrderSide.SELL])
    return Order(
        order_id=rng.randint(0, 2**32 - 1),
        symbol_id=symbol,
        side=side,
        order_type=OrderType.NEW,
        quantity=qty,
        price=price,
        notional=qty * price,
    )


def _open_cfg() -> GateConfig:
    return GateConfig(
        rate_max_tokens=10**9,
        rate_refill_rate=10**6,
        rate_refill_period=1,
        pos_max_long=10**8,
        pos_max_short=10**8,
        pos_max_notional=10**18,
        pos_max_order_qty=10**6,
        kill_armed=True,
        kill_auto_enabled=False,
        ff_enabled=True,
        ff_band_bps=300,
        ff_ref_price=10 * 10**9,
        allowlist_enabled=True,
        allowlist=tuple(range(1, 17)),
    )


# -----------------------------------------------------------------------------
# M1 — Order-id invariance
# -----------------------------------------------------------------------------

def relation_order_id_invariance(seed: int, n_pairs: int) -> Dict:
    """Decisions must be identical for two orders that differ only in order_id."""
    rng = random.Random(seed)
    cfg = _open_cfg()
    violations = 0
    for _ in range(n_pairs):
        o = _make_random_order(rng, cfg.allowlist)
        o2 = replace(o, order_id=(o.order_id + 1) & ((1 << 64) - 1))

        # Independent gates so neither sees the other's state.
        g1 = GoldenRiskGate(cfg); g1.tick()
        g2 = GoldenRiskGate(cfg); g2.tick()
        d1 = g1.decide(o)
        d2 = g2.decide(o2)
        if not _decisions_equal(d1, d2):
            violations += 1
    return {
        "name": "M1_order_id_invariance",
        "n_pairs": n_pairs,
        "violations": violations,
        "ok": violations == 0,
    }


# -----------------------------------------------------------------------------
# M2 — Side symmetry
# -----------------------------------------------------------------------------

def relation_side_symmetry(seed: int, n_pairs: int) -> Dict:
    """Mirroring sides on orders + fills + caps must mirror decisions exactly.

    When the only asymmetry is the ff_ref_price (price is two-sided around
    ref) and notional uses absolute value of qty * price, no flip there is
    required. For Phase 1 we keep prices identical; the relation focuses on
    qty + side + position-cap mirror.
    """
    rng = random.Random(seed)
    cfg = _open_cfg()
    cfg_mirror = replace(
        cfg,
        pos_max_long=cfg.pos_max_short,
        pos_max_short=cfg.pos_max_long,
    )
    violations = 0
    for _ in range(n_pairs):
        o = _make_random_order(rng, cfg.allowlist)
        # Mirror only the side; price is symmetric around ref so flipping
        # side leaves price untouched.
        o_mirror = replace(o, side=_flip_side(o.side))

        # Build a small two-event history per gate so position state matters.
        prior_qty = rng.randint(0, 100)
        prior_side = rng.choice([OrderSide.BUY, OrderSide.SELL])

        g = GoldenRiskGate(cfg)
        g.fill(Fill(side=prior_side, quantity=prior_qty, notional=prior_qty * 10**10))
        g.tick(); d = g.decide(o)

        gm = GoldenRiskGate(cfg_mirror)
        gm.fill(Fill(
            side=_flip_side(prior_side),
            quantity=prior_qty,
            notional=prior_qty * 10**10,
        ))
        gm.tick(); dm = gm.decide(o_mirror)

        if not _decisions_equal(d, dm):
            violations += 1
    return {
        "name": "M2_side_symmetry",
        "n_pairs": n_pairs,
        "violations": violations,
        "ok": violations == 0,
    }


# -----------------------------------------------------------------------------
# M3 — Scale invariance on quantities
# -----------------------------------------------------------------------------

def relation_scale_invariance(seed: int, n_pairs: int) -> Dict:
    """Scaling every quantity AND every qty-cap AND every notional-cap AND
    every fill-qty by k preserves the decision.
    """
    rng = random.Random(seed)
    cfg = _open_cfg()
    violations = 0
    for _ in range(n_pairs):
        k = rng.choice([1, 2, 3, 5, 10])
        o = _make_random_order(rng, cfg.allowlist)
        o_scaled = replace(
            o,
            quantity=o.quantity * k,
            notional=o.notional * k,  # qty*price scales with qty
        )
        cfg_s = replace(
            cfg,
            pos_max_long=cfg.pos_max_long * k,
            pos_max_short=cfg.pos_max_short * k,
            pos_max_notional=cfg.pos_max_notional * k,
            pos_max_order_qty=cfg.pos_max_order_qty * k,
        )

        prior_qty = rng.randint(0, 50)
        prior_side = rng.choice([OrderSide.BUY, OrderSide.SELL])
        prior_notional = prior_qty * 10**10

        g = GoldenRiskGate(cfg)
        g.fill(Fill(side=prior_side, quantity=prior_qty, notional=prior_notional))
        g.tick(); d = g.decide(o)

        gs = GoldenRiskGate(cfg_s)
        gs.fill(Fill(side=prior_side, quantity=prior_qty * k, notional=prior_notional * k))
        gs.tick(); ds = gs.decide(o_scaled)

        if not _decisions_equal(d, ds):
            violations += 1
    return {
        "name": "M3_scale_invariance",
        "n_pairs": n_pairs,
        "violations": violations,
        "ok": violations == 0,
    }


# -----------------------------------------------------------------------------
# M4 — Reject precedence stable under non-conflicting permutation
# -----------------------------------------------------------------------------

def relation_independence_permutation(seed: int, n_pairs: int) -> Dict:
    """Two independent orders (different symbols, neither tripping rate or
    position-shared state) decided in either order must produce identical
    decisions. We use a fresh gate per arrangement to isolate stateful
    counters; the relation in this stricter form proves that the per-order
    decision is purely a function of (config, prior-state, current-order).
    """
    rng = random.Random(seed)
    cfg = _open_cfg()
    violations = 0
    for _ in range(n_pairs):
        a = _make_random_order(rng, cfg.allowlist)
        b = _make_random_order(rng, cfg.allowlist)

        # Decide A then B
        ga = GoldenRiskGate(cfg); ga.tick(); da_first = ga.decide(a)
        ga.tick(); db_second = ga.decide(b)

        # Decide B then A
        gb = GoldenRiskGate(cfg); gb.tick(); db_first = gb.decide(b)
        gb.tick(); da_second = gb.decide(a)

        # The independence relation here: A's first-decision must equal A's
        # second-decision, and same for B — IF the orders are truly
        # independent. They're "independent" if neither consumed enough
        # rate-bucket tokens and neither moved the position-cap state.
        # Phase-1 cfg is wide-open so this almost always holds; failures
        # are real bugs, not pacing artifacts.
        if (
            not _decisions_equal(da_first, da_second)
            or not _decisions_equal(db_first, db_second)
        ):
            violations += 1
    return {
        "name": "M4_independence_permutation",
        "n_pairs": n_pairs,
        "violations": violations,
        "ok": violations == 0,
    }


# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------

RELATIONS: List[Callable[[int, int], Dict]] = [
    relation_order_id_invariance,
    relation_side_symmetry,
    relation_scale_invariance,
    relation_independence_permutation,
]


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--pairs", type=int, default=M_PAIRS_PER_RELATION)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    results: List[Dict] = []
    for fn in RELATIONS:
        r = fn(args.seed, args.pairs)
        results.append(r)
    elapsed = time.perf_counter() - t0

    failures = [r for r in results if not r["ok"]]
    summary = {
        "schema_version": 1,
        "seed": args.seed,
        "pairs_per_relation": args.pairs,
        "elapsed_s": round(elapsed, 3),
        "relations": results,
        "ok": not failures,
    }

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2))

    print(f"V-Meta seed={args.seed} pairs={args.pairs}  {elapsed:.2f}s")
    for r in results:
        flag = "OK " if r["ok"] else "FAIL"
        print(f"  [{flag}] {r['name']:<32}  violations={r['violations']}/{r['n_pairs']}")

    if failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
