"""
V-Tamper — generate 100 tamper attempts against a reference chain and
assert all 100 are detected by `verify_chain`.

Pre-reg ship target (roadmap/pre_reg/phase_01.yml):
    PASS  100/100 tamper attempts detected
    FAIL  any single attempt undetected

Tamper families:
    T1  bit-flip in decision_bytes
    T2  bit-flip in stored head_after
    T3  segment swap (exchange two adjacent segments)
    T4  insert a fabricated segment with valid-looking hash
    T5  delete a segment (sequence gap)
    T6  replay (duplicate a segment)
    T7  truncate (drop the tail)

Each attempt is built deterministically from a seeded RNG so the run is
reproducible; the seed + the output JSON are committed into
verification/reports/v_tamper/.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import secrets
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from sentinel_hft.golden import (
    ChainSegment,
    ChainVerificationError,
    DECISION_BYTES,
    GoldenAuditChain,
    encode_decision,
    verify_chain,
)
from sentinel_hft.golden.risk_gate import (
    Decision,
    GateConfig,
    GoldenRiskGate,
    Order,
    OrderSide,
    OrderType,
    RejectReason,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# -----------------------------------------------------------------------------
# Build a non-trivial reference chain
# -----------------------------------------------------------------------------

def _build_reference_chain(key: bytes, seed: int, n: int = 200) -> GoldenAuditChain:
    """Run a small synthetic order stream through the golden gate, log
    every decision into the chain, return the populated chain.
    """
    rng = random.Random(seed)
    cfg = GateConfig(
        rate_max_tokens=10**6,
        rate_refill_rate=10**4,
        rate_refill_period=1,
        pos_max_long=10**8,
        pos_max_short=10**8,
        pos_max_notional=10**16,
        pos_max_order_qty=10**6,
        ff_enabled=True,
        ff_band_bps=300,
        ff_ref_price=10**10,
        allowlist_enabled=True,
        allowlist=tuple(range(1, 17)),
    )
    gate = GoldenRiskGate(cfg)
    chain = GoldenAuditChain(key)

    for i in range(n):
        gate.tick()
        symbol = rng.randint(1, 16) if rng.random() < 0.9 else rng.randint(100, 999)
        qty = rng.randint(1, 5_000)
        price = int(cfg.ff_ref_price * (1.0 + rng.uniform(-0.04, 0.04)))
        side = rng.choice([OrderSide.BUY, OrderSide.SELL])
        otype = OrderType.NEW if rng.random() > 0.05 else OrderType.HEARTBEAT
        order = Order(
            order_id=i,
            symbol_id=symbol,
            side=side,
            order_type=otype,
            quantity=qty,
            price=price,
            notional=qty * price,
        )
        d = gate.decide(order)
        chain.append(encode_decision(order, d, timestamp=i))

    return chain


# -----------------------------------------------------------------------------
# Tamper attempts
# -----------------------------------------------------------------------------

def _flip_bit_in_bytes(b: bytes, bit: int) -> bytes:
    arr = bytearray(b)
    byte = bit // 8
    mask = 1 << (bit % 8)
    arr[byte] ^= mask
    return bytes(arr)


def _t1_bitflip_decision(rng: random.Random, segs: List[ChainSegment]) -> List[ChainSegment]:
    out = [copy.deepcopy(s) for s in segs]
    idx = rng.randrange(len(out))
    bit = rng.randrange(DECISION_BYTES * 8)
    out[idx].decision_bytes = _flip_bit_in_bytes(out[idx].decision_bytes, bit)
    return out


def _t2_bitflip_head(rng: random.Random, segs: List[ChainSegment]) -> List[ChainSegment]:
    out = [copy.deepcopy(s) for s in segs]
    idx = rng.randrange(len(out))
    bit = rng.randrange(len(out[idx].head_after) * 8)
    out[idx].head_after = _flip_bit_in_bytes(out[idx].head_after, bit)
    return out


def _t3_swap_adjacent(rng: random.Random, segs: List[ChainSegment]) -> List[ChainSegment]:
    if len(segs) < 2:
        return [copy.deepcopy(s) for s in segs]
    out = [copy.deepcopy(s) for s in segs]
    i = rng.randrange(len(out) - 1)
    out[i], out[i + 1] = out[i + 1], out[i]
    return out


def _t4_insert_fabricated(rng: random.Random, segs: List[ChainSegment]) -> List[ChainSegment]:
    out = [copy.deepcopy(s) for s in segs]
    pos = rng.randrange(1, len(out))
    fake_decision = secrets.token_bytes(DECISION_BYTES)
    fake_head = secrets.token_bytes(len(out[0].head_after))
    fake = ChainSegment(
        seq=out[pos].seq,
        decision_bytes=fake_decision,
        head_after=fake_head,
    )
    # Insert and renumber subsequent segments to maintain superficial
    # monotonicity (so a sequence-gap detector alone wouldn't catch it).
    out.insert(pos, fake)
    for i in range(pos + 1, len(out)):
        out[i].seq = out[i - 1].seq + 1
    return out


def _t5_delete_one(rng: random.Random, segs: List[ChainSegment]) -> List[ChainSegment]:
    if len(segs) < 3:
        return [copy.deepcopy(s) for s in segs]
    out = [copy.deepcopy(s) for s in segs]
    pos = rng.randrange(1, len(out) - 1)
    del out[pos]
    # Do NOT renumber — leave the gap visible so the verifier catches it.
    return out


def _t6_replay(rng: random.Random, segs: List[ChainSegment]) -> List[ChainSegment]:
    if len(segs) < 2:
        return [copy.deepcopy(s) for s in segs]
    out = [copy.deepcopy(s) for s in segs]
    pos = rng.randrange(1, len(out))
    # Duplicate the prior segment in-place; the duplicate keeps its
    # seq number, creating a duplicate seq that the verifier should detect.
    out.insert(pos, copy.deepcopy(out[pos - 1]))
    # Renumber the tail so monotonicity is "almost" preserved (still a dup at pos-1)
    for i in range(pos + 1, len(out)):
        out[i].seq = out[i - 1].seq + 1
    return out


def _t7_truncate_tail(rng: random.Random, segs: List[ChainSegment]) -> List[ChainSegment]:
    """Truncation by itself is not a tamper if there's no expected length —
    but if the host has a recorded "head" value at a known seq, truncation
    changes the verified head. Here we simulate: tamper appends garbage
    after truncation so the verifier sees an incorrect tail head.
    """
    if len(segs) < 5:
        return [copy.deepcopy(s) for s in segs]
    drop = rng.randrange(1, max(2, len(segs) // 4))
    out = [copy.deepcopy(s) for s in segs[:-drop]]
    # Append a fabricated final segment claiming the original final seq.
    out.append(ChainSegment(
        seq=segs[-1].seq,
        decision_bytes=secrets.token_bytes(DECISION_BYTES),
        head_after=secrets.token_bytes(len(segs[0].head_after)),
    ))
    return out


TAMPERS: List[Tuple[str, Callable[[random.Random, List[ChainSegment]], List[ChainSegment]]]] = [
    ("T1_bitflip_decision",   _t1_bitflip_decision),
    ("T2_bitflip_head",       _t2_bitflip_head),
    ("T3_swap_adjacent",      _t3_swap_adjacent),
    ("T4_insert_fabricated",  _t4_insert_fabricated),
    ("T5_delete_one",         _t5_delete_one),
    ("T6_replay",             _t6_replay),
    ("T7_truncate_tail",      _t7_truncate_tail),
]


# -----------------------------------------------------------------------------
# Runner
# -----------------------------------------------------------------------------

def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-attempts", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path,
                    default=REPO_ROOT / "verification" / "reports" / "v_tamper" / "ci.json")
    args = ap.parse_args(argv)

    # Build the reference chain
    key = hashlib.sha256(b"v_tamper canonical key " + str(args.seed).encode()).digest()
    chain = _build_reference_chain(key, args.seed, n=200)
    segments = chain.segments

    # Sanity: original chain verifies cleanly
    try:
        verify_chain(key, segments)
    except ChainVerificationError as e:
        sys.stderr.write(f"reference chain failed self-verify: {e}\n")
        return 2

    rng = random.Random(args.seed)
    detail: List[Dict] = []
    detected = 0
    n = args.n_attempts

    t0 = time.perf_counter()
    for i in range(n):
        kind, fn = TAMPERS[i % len(TAMPERS)]
        tampered = fn(rng, segments)
        try:
            verify_chain(key, tampered)
            # Verified clean → tamper UNDETECTED.
            detail.append({"i": i, "kind": kind, "detected": False, "reason": None})
        except ChainVerificationError as e:
            detected += 1
            detail.append({"i": i, "kind": kind, "detected": True,
                           "reason": e.kind, "at_seq": e.at_seq})

    elapsed = time.perf_counter() - t0

    summary = {
        "schema_version": 1,
        "seed": args.seed,
        "n_attempts": n,
        "detected": detected,
        "undetected": n - detected,
        "ok": detected == n,
        "elapsed_s": round(elapsed, 3),
        "by_kind": {
            kind: {
                "tries": sum(1 for d in detail if d["kind"] == kind),
                "detected": sum(1 for d in detail if d["kind"] == kind and d["detected"]),
            }
            for kind, _ in TAMPERS
        },
        "details": detail[:30],   # cap so the file stays small
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))

    print(f"V-Tamper seed={args.seed} attempts={n}  {elapsed:.2f}s")
    for kind, _ in TAMPERS:
        b = summary["by_kind"][kind]
        print(f"  {kind:<24}  detected {b['detected']}/{b['tries']}")
    print(f"  total: {detected}/{n} detected")

    if detected != n:
        print("  FAIL: at least one tamper went undetected.")
        return 1
    print("  OK: all tampers detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
