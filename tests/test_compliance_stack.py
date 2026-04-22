"""Workstream 3 -- ComplianceStack end-to-end tests.

The stack aggregates the five live-counter primitives and the MAR
detector into a single ``observe(intent, decision, ts_ns, trader_id)``
surface. The HL runner calls it for every NEW / CANCEL intent.

These tests drive synthetic intents through ``ComplianceStack`` and
assert the four observable behaviours:

* OTR ratio ticks orders + trades correctly,
* the fat-finger guard fires above 500 bps deviation and stays silent
  below it,
* the self-trade guard fires only on an opposite-side cross against
  the same trader's own resting order,
* MAR fires on a layering burst (>=30 same-side cancels held >5 ms
  inside the 200 ms window),
* the CAT NDJSON feed is well-formed and one record is emitted per
  intent,
* ``ComplianceSnapshot.as_dict()`` keys match the ``ComplianceSnapshot``
  field set exactly.

Pure-Python; no FastAPI, no network. Sub-second runtime.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from sentinel_hft.compliance.stack import (
    ComplianceSnapshot,
    ComplianceStack,
)


# ---------------------------------------------------------------------
# Local mirrors of the runner-side enums (kept private to stack.py).
# Side: 1 = buy, 2 = sell. Action: 1 = NEW, 2 = CANCEL.
# ---------------------------------------------------------------------

SIDE_BUY = 1
SIDE_SELL = 2
ACTION_NEW = 1
ACTION_CANCEL = 2

NS_PER_MS = 1_000_000


def _intent(
    *,
    order_id: int,
    side: int = SIDE_BUY,
    action: int = ACTION_NEW,
    price: float = 100.0,
    quantity: float = 1.0,
    symbol_id: int = 1,
) -> Any:
    """Build a duck-typed intent the stack can consume via getattr()."""
    return SimpleNamespace(
        order_id=order_id,
        side=side,
        action=action,
        price=price,
        quantity=quantity,
        symbol_id=symbol_id,
    )


def _passed_decision() -> Any:
    return SimpleNamespace(passed=True, reject_reason=0)


def _rejected_decision(reason: int = 1) -> Any:
    return SimpleNamespace(passed=False, reject_reason=reason)


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture
def stack(tmp_path: Path) -> ComplianceStack:
    """A fresh stack writing CAT to a temp NDJSON file."""
    cat_path = tmp_path / "cat_feed.ndjson"
    s = ComplianceStack(cat_output_path=str(cat_path))
    yield s
    s.close()


# ---------------------------------------------------------------------
# Snapshot shape
# ---------------------------------------------------------------------


def test_snapshot_keys_match_dataclass_fields(stack: ComplianceStack):
    """The wire payload at /api/compliance/snapshot-shape derives from
    ``ComplianceSnapshot.as_dict()``. The keys must match the dataclass
    field set exactly so the typescript ComplianceSnapshot type stays
    in sync."""
    snap = stack.snapshot()
    assert isinstance(snap, ComplianceSnapshot)
    expected = {f.name for f in dataclasses.fields(ComplianceSnapshot)}
    payload = snap.as_dict()
    assert set(payload.keys()) == expected
    assert expected == {
        "mifid_otr",
        "cftc_self_trade",
        "finra_fat_finger",
        "sec_cat",
        "mar_abuse",
    }
    # All values are dicts (possibly empty).
    for value in payload.values():
        assert isinstance(value, dict)


def test_snapshot_is_json_safe(stack: ComplianceStack):
    payload = stack.as_dict()
    assert json.loads(json.dumps(payload)) == payload


# ---------------------------------------------------------------------
# OTR counter
# ---------------------------------------------------------------------


def test_otr_counts_orders_and_trades(stack: ComplianceStack):
    """Each NEW intent ticks the OTR numerator; on_trade ticks the
    denominator. With 4 NEWs and 1 trade the global ratio is 4."""
    for i in range(4):
        stack.observe(
            intent=_intent(order_id=100 + i),
            decision=_passed_decision(),
            ts_ns=i * NS_PER_MS,
        )
    stack.on_trade(symbol_id=1, price=100.0, ts_ns=0)
    snap = stack.snapshot().mifid_otr
    assert snap["total_orders"] == 4
    assert snap["total_trades"] == 1
    # Global ratio is orders / max(trades, 1) = 4 / 1.
    assert snap["global_ratio"] == 4.0
    assert snap["would_trip"] == 0  # under the 100:1 threshold


# ---------------------------------------------------------------------
# Fat-finger guard
# ---------------------------------------------------------------------


def test_fat_finger_does_not_fire_below_500_bps(stack: ComplianceStack):
    """A 200 bps deviation (2 %) sits inside the default 500 bps guard."""
    # Seed a reference price.
    stack.on_trade(symbol_id=1, price=100.0, ts_ns=0)
    # A NEW at 102 (200 bps above ref) must NOT flag.
    stack.observe(
        intent=_intent(order_id=1, price=102.0),
        decision=_passed_decision(),
        ts_ns=NS_PER_MS,
    )
    snap = stack.snapshot().finra_fat_finger
    assert snap["checked"] == 1
    assert snap["rejected"] == 0
    assert snap["worst_deviation_bps"] == pytest.approx(200.0, abs=0.01)


def test_fat_finger_fires_above_500_bps(stack: ComplianceStack):
    """A 600 bps deviation (6 %) exceeds the 500 bps guard."""
    stack.on_trade(symbol_id=1, price=100.0, ts_ns=0)
    stack.observe(
        intent=_intent(order_id=1, price=106.0),
        decision=_passed_decision(),
        ts_ns=NS_PER_MS,
    )
    snap = stack.snapshot().finra_fat_finger
    assert snap["checked"] == 1
    assert snap["rejected"] == 1
    assert snap["worst_deviation_bps"] == pytest.approx(600.0, abs=0.01)


# ---------------------------------------------------------------------
# Self-trade guard
# ---------------------------------------------------------------------


def test_self_trade_does_not_fire_on_same_side(stack: ComplianceStack):
    """Two BUYs at adjacent prices on the same instrument do not
    self-cross — only opposite-side intents can."""
    stack.observe(
        intent=_intent(order_id=1, side=SIDE_BUY, price=100.0),
        decision=_passed_decision(),
        ts_ns=0,
    )
    stack.observe(
        intent=_intent(order_id=2, side=SIDE_BUY, price=100.5),
        decision=_passed_decision(),
        ts_ns=NS_PER_MS,
    )
    snap = stack.snapshot().cftc_self_trade
    # Both intents pass the check (same trader, same side -> no cross).
    assert snap["checked"] == 2
    assert snap["rejected"] == 0
    assert snap["resting_orders"] == 2


def test_self_trade_fires_on_opposite_side_cross(stack: ComplianceStack):
    """Resting BUY @ 100 must trip an incoming SELL @ 99
    (sell_px <= buy_px)."""
    # First, lay down a resting BUY at 100.
    stack.observe(
        intent=_intent(order_id=1, side=SIDE_BUY, price=100.0),
        decision=_passed_decision(),
        ts_ns=0,
    )
    # Now an incoming SELL at 99 -> would self-cross.
    stack.observe(
        intent=_intent(order_id=2, side=SIDE_SELL, price=99.0),
        decision=_passed_decision(),
        ts_ns=NS_PER_MS,
    )
    snap = stack.snapshot().cftc_self_trade
    assert snap["checked"] == 2
    assert snap["rejected"] == 1


# ---------------------------------------------------------------------
# MAR spoofing / layering detector
# ---------------------------------------------------------------------


def test_mar_fires_on_layering_burst(stack: ComplianceStack):
    """30 same-side NEW-then-CANCEL events within 200 ms, each held
    >5 ms on the book, must trip MAR. Default thresholds:
    min_cancelled=30, window_ns=2e8, min_time_on_book_ns=5e6."""
    base_ns = 10 * NS_PER_MS  # leave room for "place" timestamps
    # Place 30 NEWs at t = 0..29 ms (well inside the 200 ms window).
    for i in range(30):
        stack.observe(
            intent=_intent(order_id=1000 + i, side=SIDE_BUY, price=100.0),
            decision=_passed_decision(),
            ts_ns=i * NS_PER_MS,
        )
    # Cancel each at place_time + 6 ms (>5 ms time-on-book).
    last_alert_seen = False
    for i in range(30):
        cancel_ts = (i * NS_PER_MS) + 6 * NS_PER_MS
        stack.observe(
            intent=_intent(
                order_id=1000 + i,
                side=SIDE_BUY,
                action=ACTION_CANCEL,
            ),
            decision=_passed_decision(),
            ts_ns=cancel_ts,
        )
    snap = stack.snapshot().mar_abuse
    # 30 cancels — the 30th (or earlier) trip should fire one alert.
    assert snap["alerts"] >= 1
    assert snap["orders_seen"] == 30
    assert snap["cancels_seen"] == 30


def test_mar_does_not_fire_below_threshold(stack: ComplianceStack):
    """Below ``min_cancelled`` (default 30) no alert."""
    for i in range(10):
        stack.observe(
            intent=_intent(order_id=2000 + i, side=SIDE_BUY, price=100.0),
            decision=_passed_decision(),
            ts_ns=i * NS_PER_MS,
        )
    for i in range(10):
        stack.observe(
            intent=_intent(
                order_id=2000 + i,
                side=SIDE_BUY,
                action=ACTION_CANCEL,
            ),
            decision=_passed_decision(),
            ts_ns=(i * NS_PER_MS) + 6 * NS_PER_MS,
        )
    snap = stack.snapshot().mar_abuse
    assert snap["alerts"] == 0


# ---------------------------------------------------------------------
# CAT NDJSON feed
# ---------------------------------------------------------------------


def test_cat_emits_one_record_per_event(tmp_path: Path):
    """One MENO per passed NEW, one MEOR per rejected NEW, one MECR
    per CANCEL. Records are well-formed NDJSON with the documented
    eventType vocabulary."""
    cat_path = tmp_path / "cat_feed.ndjson"
    with ComplianceStack(cat_output_path=str(cat_path)) as stack:
        # Passed NEW -> MENO
        stack.observe(
            intent=_intent(order_id=1, side=SIDE_BUY, price=100.0),
            decision=_passed_decision(),
            ts_ns=NS_PER_MS,
        )
        # Rejected NEW -> MEOR
        stack.observe(
            intent=_intent(order_id=2, side=SIDE_SELL, price=200.0),
            decision=_rejected_decision(reason=1),
            ts_ns=2 * NS_PER_MS,
        )
        # CANCEL -> MECR
        stack.observe(
            intent=_intent(order_id=1, action=ACTION_CANCEL),
            decision=_passed_decision(),
            ts_ns=3 * NS_PER_MS,
        )

    raw = cat_path.read_text(encoding="utf-8").splitlines()
    assert len(raw) == 3, raw

    decoded = [json.loads(line) for line in raw]
    event_types = [r["eventType"] for r in decoded]
    assert event_types == ["MENO", "MEOR", "MECR"]

    # Every record has the documented top-level keys.
    required = {
        "eventType", "eventTypeName", "eventTimestamp",
        "eventTimestampNs", "orderID", "symbol", "side", "price",
        "quantity", "orderType", "timeInForce",
    }
    for rec in decoded:
        assert required.issubset(rec.keys()), (
            f"missing keys in {rec.get('eventType')}: "
            f"{required - set(rec.keys())}"
        )

    # MEOR carries the reject reason; MENO does not.
    meor = next(r for r in decoded if r["eventType"] == "MEOR")
    assert "rejectReason" in meor
    meno = next(r for r in decoded if r["eventType"] == "MENO")
    assert "rejectReason" not in meno


def test_cat_snapshot_counts_match_emitted(tmp_path: Path):
    cat_path = tmp_path / "cat_feed.ndjson"
    with ComplianceStack(cat_output_path=str(cat_path)) as stack:
        for i in range(5):
            stack.observe(
                intent=_intent(order_id=10 + i, price=100.0),
                decision=_passed_decision(),
                ts_ns=i * NS_PER_MS,
            )
        snap = stack.snapshot().sec_cat
        assert snap["total_records"] == 5
        # by_event_type aggregates by MENO/MECR/MEOR/...
        assert snap["by_event_type"].get("MENO") == 5
        assert snap["output_path"] == str(cat_path)


# ---------------------------------------------------------------------
# observe() return contract
# ---------------------------------------------------------------------


def test_observe_returns_documented_keys(stack: ComplianceStack):
    """``observe`` returns a fixed-shape dict so the runner can surface
    compliance flags in its trace."""
    flags = stack.observe(
        intent=_intent(order_id=1, price=100.0),
        decision=_passed_decision(),
        ts_ns=NS_PER_MS,
    )
    expected = {
        "would_reject_otr",
        "would_reject_self_trade",
        "would_reject_fat_finger",
        "mar_alert",
    }
    assert set(flags.keys()) == expected
    for v in flags.values():
        assert isinstance(v, bool)


def test_stack_never_flips_decision_passed(stack: ComplianceStack):
    """The stack is observational: a passed decision must remain passed
    after observe() returns. (We pass a mutable namespace and inspect.)"""
    decision = _passed_decision()
    stack.observe(
        intent=_intent(order_id=1, price=100.0),
        decision=decision,
        ts_ns=NS_PER_MS,
    )
    assert decision.passed is True
