"""
Smoke tests for the Phase-1 behavioral golden model.

These are the V-Floor seed tests. The 10^6-order randomized corpus runs
through verification/v_floor/random_corpus.py (not in this file).
"""

import pytest

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


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def open_cfg() -> GateConfig:
    """Loose config — most orders pass."""
    return GateConfig(
        rate_max_tokens=10_000,
        rate_refill_rate=1_000,
        rate_refill_period=10,
        pos_max_long=10**9,
        pos_max_short=10**9,
        pos_max_notional=10**15,
        pos_max_order_qty=10**8,
        kill_armed=True,
        ff_enabled=False,
        allowlist_enabled=False,
    )


def _order(
    side: OrderSide = OrderSide.BUY,
    qty: int = 100,
    price: int = 10_000_000_000,   # $100 fixed-point
    symbol: int = 1,
    oid: int = 1,
    otype: OrderType = OrderType.NEW,
) -> Order:
    return Order(
        order_id=oid,
        symbol_id=symbol,
        side=side,
        order_type=otype,
        quantity=qty,
        price=price,
        notional=qty * price,
    )


# ------------------------------------------------------------------
# Basic acceptance
# ------------------------------------------------------------------

def test_simple_buy_passes(open_cfg):
    g = GoldenRiskGate(open_cfg)
    g.tick()
    d = g.decide(_order())
    assert d.passed
    assert d.reason == RejectReason.OK


def test_heartbeat_always_passes_even_on_tripped_kill(open_cfg):
    g = GoldenRiskGate(open_cfg)
    g.trip_kill()
    g.tick()
    d = g.decide(_order(otype=OrderType.HEARTBEAT))
    assert d.passed
    assert d.reason == RejectReason.OK


# ------------------------------------------------------------------
# Reject precedence: kill > rate > position > fat-finger > allowlist
# ------------------------------------------------------------------

def test_kill_switch_takes_precedence(open_cfg):
    g = GoldenRiskGate(open_cfg)
    g.trip_kill()
    g.tick()
    d = g.decide(_order())
    assert not d.passed
    assert d.reason == RejectReason.KILL_SWITCH


def test_rate_limiter_rejects_when_empty():
    cfg = GateConfig(
        rate_max_tokens=1,
        rate_refill_rate=0,
        rate_refill_period=10**9,  # effectively never
        pos_max_long=10**9,
        pos_max_short=10**9,
        pos_max_notional=10**15,
        pos_max_order_qty=10**8,
        ff_enabled=False,
        allowlist_enabled=False,
    )
    g = GoldenRiskGate(cfg)
    g.tick()
    assert g.decide(_order(oid=1)).passed
    g.tick()
    d = g.decide(_order(oid=2))
    assert not d.passed
    assert d.reason == RejectReason.RATE_LIMITED


def test_per_order_size_rejects_oversized(open_cfg):
    g = GoldenRiskGate(open_cfg)
    g.tick()
    too_big = _order(qty=open_cfg.pos_max_order_qty + 1)
    d = g.decide(too_big)
    assert not d.passed
    assert d.reason == RejectReason.ORDER_SIZE


def test_notional_cap_rejects_when_aggregate_exceeds():
    cfg = GateConfig(
        pos_max_long=10**9,
        pos_max_short=10**9,
        pos_max_notional=1_000,  # tiny
        pos_max_order_qty=10**6,
        ff_enabled=False,
        allowlist_enabled=False,
    )
    g = GoldenRiskGate(cfg)
    g.tick()
    d = g.decide(_order(qty=1, price=2_000, symbol=1))
    assert not d.passed
    assert d.reason == RejectReason.NOTIONAL_LIMIT


def test_position_long_cap():
    cfg = GateConfig(
        pos_max_long=100,
        pos_max_short=10**9,
        pos_max_notional=10**15,
        pos_max_order_qty=10**8,
        ff_enabled=False,
        allowlist_enabled=False,
    )
    g = GoldenRiskGate(cfg)
    g.tick()
    # First buy of 50 should pass (projected long = 50 ≤ 100).
    assert g.decide(_order(qty=50, oid=1)).passed
    g.fill(Fill(side=OrderSide.BUY, quantity=50, notional=50))
    g.tick()
    # Next buy of 60 would project long to 110 > 100 → reject.
    d = g.decide(_order(qty=60, oid=2))
    assert not d.passed
    assert d.reason == RejectReason.POSITION_LIMIT


def test_buy_unwinds_short_before_extending_long():
    cfg = GateConfig(
        pos_max_long=100,
        pos_max_short=10**9,
        pos_max_notional=10**15,
        pos_max_order_qty=10**8,
        ff_enabled=False,
        allowlist_enabled=False,
    )
    g = GoldenRiskGate(cfg)
    # Build a short position of 80.
    g.fill(Fill(side=OrderSide.SELL, quantity=80, notional=80))
    g.tick()
    # A buy of 150 would project: unwind 80 short → 70 extra long → ≤ 100 → pass.
    d = g.decide(_order(qty=150))
    assert d.passed, d


# ------------------------------------------------------------------
# Fat-finger band
# ------------------------------------------------------------------

def test_fat_finger_blocks_outside_band():
    cfg = GateConfig(
        ff_enabled=True,
        ff_band_bps=100,            # 1.00%
        ff_ref_price=10_000_000_000,  # $100 fixed-point
        pos_max_long=10**9,
        pos_max_short=10**9,
        pos_max_notional=10**15,
        pos_max_order_qty=10**8,
        allowlist_enabled=False,
    )
    g = GoldenRiskGate(cfg)
    g.tick()
    # 1.5% above ref → reject
    d = g.decide(_order(price=int(cfg.ff_ref_price * 1.015)))
    assert not d.passed
    assert d.reason == RejectReason.FAT_FINGER


def test_fat_finger_passes_within_band():
    cfg = GateConfig(
        ff_enabled=True,
        ff_band_bps=100,
        ff_ref_price=10_000_000_000,
        pos_max_long=10**9,
        pos_max_short=10**9,
        pos_max_notional=10**15,
        pos_max_order_qty=10**8,
        allowlist_enabled=False,
    )
    g = GoldenRiskGate(cfg)
    g.tick()
    d = g.decide(_order(price=int(cfg.ff_ref_price * 1.005)))
    assert d.passed


# ------------------------------------------------------------------
# Allowlist
# ------------------------------------------------------------------

def test_allowlist_rejects_unknown_symbol(open_cfg):
    cfg = GateConfig(**{**open_cfg.__dict__, "allowlist_enabled": True, "allowlist": (1, 2, 3)})
    g = GoldenRiskGate(cfg)
    g.tick()
    d = g.decide(_order(symbol=999))
    assert not d.passed
    assert d.reason == RejectReason.ALLOWLIST_BLOCK


def test_allowlist_passes_known_symbol(open_cfg):
    cfg = GateConfig(**{**open_cfg.__dict__, "allowlist_enabled": True, "allowlist": (1, 2, 3)})
    g = GoldenRiskGate(cfg)
    g.tick()
    d = g.decide(_order(symbol=2))
    assert d.passed


# ------------------------------------------------------------------
# Auto kill via P&L
# ------------------------------------------------------------------

def test_auto_kill_fires_below_loss_threshold(open_cfg):
    cfg = GateConfig(**{
        **open_cfg.__dict__,
        "kill_auto_enabled": True,
        "kill_loss_threshold": -1000,
    })
    g = GoldenRiskGate(cfg)
    g.tick()
    g.update_pnl(-2000)
    assert g.kill_active
    d = g.decide(_order())
    assert not d.passed
    assert d.reason == RejectReason.KILL_SWITCH


# ------------------------------------------------------------------
# Stream helper
# ------------------------------------------------------------------

def test_stream_helper_processes_in_order(open_cfg):
    orders = [_order(oid=i) for i in range(5)]
    decisions = evaluate_stream(open_cfg, orders)
    assert len(decisions) == 5
    assert all(d.passed for d in decisions)


# ------------------------------------------------------------------
# V-Mut survivors → targeted tests
#
# The mutation runner (verification/v_mutation/mutate_python.py) found
# six operator-flip mutations in the golden that the original suite
# didn't catch. The tests below close those gaps. Comments tag which
# mutation site each test kills.
# ------------------------------------------------------------------

def test_default_config_has_expected_safe_defaults():
    """Kills mutation: GateConfig.allowlist_enabled default flipped True->False.
    Defaults are part of the contract — flipping them silently disables
    a rule.
    """
    c = GateConfig()
    assert c.rate_enabled is True
    assert c.pos_enabled is True
    assert c.kill_armed is True
    assert c.ff_enabled is True
    assert c.allowlist_enabled is True


def test_token_bucket_does_not_overrefill():
    """Kills mutation: refill check `>=` flipped to `<=` (line ~165).

    The gate should NOT refill on every cycle. With period=1000 and
    refill_rate=0 (no refills at all expected over the test horizon),
    the bucket must drain to zero. The mutated `<=` would refill almost
    every cycle (cycles_since_refill <= period is true until reset),
    which would mask drain.
    """
    cfg = GateConfig(
        rate_max_tokens=5,
        rate_refill_rate=0,         # no refill ever in this test
        rate_refill_period=1000,
        pos_max_long=10**9,
        pos_max_short=10**9,
        pos_max_notional=10**18,
        pos_max_order_qty=10**8,
        ff_enabled=False,
        allowlist_enabled=False,
    )
    g = GoldenRiskGate(cfg)
    # Drain the bucket completely.
    for i in range(5):
        g.tick()
        d = g.decide(_order(oid=i))
        assert d.passed, f"order {i}: bucket has tokens, should pass"
    # Now bucket is empty. The next order MUST be rate-limited.
    g.tick()
    d = g.decide(_order(oid=99))
    assert not d.passed, "bucket drained — next order must be rate-limited"
    assert d.reason == RejectReason.RATE_LIMITED


def test_kill_armed_false_disables_kill_check():
    """Kills mutation: `cfg.kill_armed and tripped` BoolOp flip (line ~176).
    If the kill switch is disarmed, even a tripped state must not block.
    """
    cfg = GateConfig(
        kill_armed=False,
        rate_enabled=False,
        pos_enabled=False,
        ff_enabled=False,
        allowlist_enabled=False,
    )
    g = GoldenRiskGate(cfg)
    g.trip_kill()    # public API; cfg.kill_armed=False means it should not block
    g.tick()
    d = g.decide(_order())
    assert d.passed, "disarmed kill must not block"


def test_position_short_cap_symmetric():
    """Kills mutation: short-side cap check `>` flipped to `<` (line ~279)."""
    cfg = GateConfig(
        pos_max_long=10**9,
        pos_max_short=100,        # tight on the short side
        pos_max_notional=10**15,
        pos_max_order_qty=10**8,
        ff_enabled=False,
        allowlist_enabled=False,
    )
    g = GoldenRiskGate(cfg)
    g.tick()
    # First sell of 50 should pass.
    assert g.decide(_order(side=OrderSide.SELL, qty=50, oid=1)).passed
    g.fill(Fill(side=OrderSide.SELL, quantity=50, notional=50))
    g.tick()
    # Next sell of 60 would project short to 110 > 100 → reject.
    d = g.decide(_order(side=OrderSide.SELL, qty=60, oid=2))
    assert not d.passed
    assert d.reason == RejectReason.POSITION_LIMIT


def test_fat_finger_disabled_when_ref_price_zero():
    """Kills mutation: `ff_enabled and ff_ref_price > 0` BoolOp flip (line ~284).
    A zero reference price is the documented disable for fat-finger.
    """
    cfg = GateConfig(
        ff_enabled=True,
        ff_band_bps=1,            # absurdly tight; would reject everything
        ff_ref_price=0,           # but zero ref disables the check
        pos_max_long=10**9,
        pos_max_short=10**9,
        pos_max_notional=10**18,
        pos_max_order_qty=10**8,
        allowlist_enabled=False,
    )
    g = GoldenRiskGate(cfg)
    g.tick()
    d = g.decide(_order(price=10**12))    # absurd price, but ff is disabled
    assert d.passed, "ff with ref_price=0 must not reject"


def test_allowlist_disabled_when_tuple_empty():
    """Kills mutation: `allowlist_enabled and allowlist` BoolOp flip (line ~294).
    An empty allowlist tuple is the documented disable.
    """
    cfg = GateConfig(
        allowlist_enabled=True,
        allowlist=(),             # empty → disabled
        pos_max_long=10**9,
        pos_max_short=10**9,
        pos_max_notional=10**15,
        pos_max_order_qty=10**8,
        ff_enabled=False,
    )
    g = GoldenRiskGate(cfg)
    g.tick()
    d = g.decide(_order(symbol=999))
    assert d.passed, "empty allowlist must not reject"


def test_token_bucket_does_not_refill_before_period_elapses():
    """Kills mutation: tick() refill check `>=` flipped to `<=` (line ~165).

    With period=1000, the refill should NOT have fired by tick 2. Mutated
    `<=` would refill every tick (counter ≤ period is True from cycle 0),
    masking depletion.
    """
    cfg = GateConfig(
        rate_max_tokens=2,
        rate_refill_rate=100,        # would dwarf bucket if refill leaks
        rate_refill_period=1000,
        pos_max_long=10**9,
        pos_max_short=10**9,
        pos_max_notional=10**18,
        pos_max_order_qty=10**8,
        ff_enabled=False,
        allowlist_enabled=False,
    )
    g = GoldenRiskGate(cfg)
    # Tick + decide twice (drain bucket 2→0).
    for i in range(2):
        g.tick()
        d = g.decide(_order(oid=i))
        assert d.passed, f"order {i} should pass while bucket has tokens"
    # Third order: bucket is empty, period=1000 not yet elapsed (we've only
    # ticked 3 times total). Original gate: rate-limited. Mutated: would
    # have refilled on every tick → tokens > 0 → pass.
    g.tick()
    d = g.decide(_order(oid=99))
    assert not d.passed, "third order must be rate-limited (no refill yet)"
    assert d.reason == RejectReason.RATE_LIMITED


def test_auto_kill_does_not_fire_when_disarmed_or_disabled():
    """Kills mutation: auto-kill 3-way And in update_pnl flipped to Or (line ~176).

    With kill_armed=True but kill_auto_enabled=False, the gate must NOT
    auto-trip. Original: T and F and X = False → no trip. Mutated to Or:
    T or F or X = True → would trip. Assert kill stays inactive.
    """
    cfg = GateConfig(
        kill_armed=True,
        kill_auto_enabled=False,    # auto-trigger disabled
        kill_loss_threshold=-100,
    )
    g = GoldenRiskGate(cfg)
    g.update_pnl(-99999)            # well below threshold
    assert not g.kill_active, "auto-kill must not fire when disabled"
