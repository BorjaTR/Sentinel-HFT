"""Tests for H3 Risk Controls.

Tests risk control logic with Python reference implementations that
validate the RTL behavior.
"""

import pytest
from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional


# ============================================================================
# Constants (matching risk_pkg.sv)
# ============================================================================

class OrderSide(IntEnum):
    BUY = 0x01
    SELL = 0x02


class OrderType(IntEnum):
    NEW = 0x1
    CANCEL = 0x2
    MODIFY = 0x3
    HEARTBEAT = 0xF


class RiskReject(IntEnum):
    OK = 0x00
    RATE_LIMITED = 0x01
    POSITION_LIMIT = 0x02
    NOTIONAL_LIMIT = 0x03
    ORDER_SIZE = 0x04
    KILL_SWITCH = 0x05
    INVALID_ORDER = 0x06
    DISABLED = 0xFF


# ============================================================================
# Reference Implementations
# ============================================================================

@dataclass
class TokenBucket:
    """Reference implementation of token bucket rate limiter."""
    max_tokens: int
    refill_rate: int
    refill_period: int
    enabled: bool = True

    def __post_init__(self):
        self.tokens = self.max_tokens if self.enabled else 0
        self.refill_counter = self.refill_period

    def tick(self) -> None:
        """Simulate one clock cycle."""
        if not self.enabled:
            return

        self.refill_counter -= 1
        if self.refill_counter == 0:
            self.refill_counter = self.refill_period
            self.tokens = min(self.tokens + self.refill_rate, self.max_tokens)

    def try_consume(self, order_type: OrderType, tokens_required: int = 1) -> bool:
        """Try to consume tokens for an order."""
        # Heartbeats always pass
        if order_type == OrderType.HEARTBEAT:
            return True

        # Disabled means all pass
        if not self.enabled:
            return True

        if self.tokens >= tokens_required:
            self.tokens -= tokens_required
            return True
        return False


@dataclass
class PositionTracker:
    """Reference implementation of position limiter."""
    max_long: int
    max_short: int
    max_notional: int
    max_order_qty: int
    enabled: bool = True

    def __post_init__(self):
        self.long_qty = 0
        self.short_qty = 0
        self.notional = 0

    def check_order(self, side: OrderSide, order_type: OrderType,
                   qty: int, notional: int) -> RiskReject:
        """Check if order would violate limits."""
        # Cancels always pass
        if order_type == OrderType.CANCEL:
            return RiskReject.OK

        # Disabled means all pass
        if not self.enabled:
            return RiskReject.OK

        # Check single order size
        if qty > self.max_order_qty:
            return RiskReject.ORDER_SIZE

        # Project position after fill
        if side == OrderSide.BUY:
            projected_long = self.long_qty + qty
            if projected_long > self.max_long:
                return RiskReject.POSITION_LIMIT
        else:
            projected_short = self.short_qty + qty
            if projected_short > self.max_short:
                return RiskReject.POSITION_LIMIT

        # Check notional
        if self.notional + notional > self.max_notional:
            return RiskReject.NOTIONAL_LIMIT

        return RiskReject.OK

    def apply_fill(self, side: OrderSide, qty: int, notional: int) -> None:
        """Update position after a fill."""
        if side == OrderSide.BUY:
            self.long_qty += qty
        else:
            self.short_qty += qty
        self.notional += notional

    @property
    def net_position(self) -> int:
        """Return net position (long - short)."""
        return self.long_qty - self.short_qty


@dataclass
class KillSwitch:
    """Reference implementation of kill switch."""
    armed: bool = True
    auto_enabled: bool = False
    loss_threshold: int = 0

    def __post_init__(self):
        self.triggered = False

    def trigger(self) -> None:
        """Manually trigger kill switch."""
        if self.armed:
            self.triggered = True

    def reset(self) -> None:
        """Reset kill switch (requires explicit action)."""
        self.triggered = False

    def check_pnl(self, pnl: int, is_loss: bool) -> None:
        """Check P&L and auto-trigger if threshold exceeded."""
        if self.armed and self.auto_enabled and is_loss:
            if pnl >= self.loss_threshold:
                self.triggered = True

    def check_order(self) -> bool:
        """Return True if order passes (kill switch not triggered)."""
        return not self.triggered


# ============================================================================
# Token Bucket Tests
# ============================================================================

class TestTokenBucket:
    """Test token bucket rate limiter."""

    def test_basic_consumption(self):
        """Test basic token consumption."""
        bucket = TokenBucket(max_tokens=10, refill_rate=1, refill_period=100)

        # Should have 10 tokens initially
        assert bucket.tokens == 10

        # Consume 5 tokens
        for _ in range(5):
            assert bucket.try_consume(OrderType.NEW) is True

        assert bucket.tokens == 5

    def test_exhaustion(self):
        """Test bucket exhaustion."""
        bucket = TokenBucket(max_tokens=5, refill_rate=1, refill_period=100)

        # Drain the bucket
        for _ in range(5):
            assert bucket.try_consume(OrderType.NEW) is True

        # Next should fail
        assert bucket.try_consume(OrderType.NEW) is False
        assert bucket.tokens == 0

    def test_refill(self):
        """Test token refill."""
        bucket = TokenBucket(max_tokens=10, refill_rate=2, refill_period=5)

        # Drain bucket
        for _ in range(10):
            bucket.try_consume(OrderType.NEW)

        assert bucket.tokens == 0

        # Tick until refill
        for _ in range(5):
            bucket.tick()

        # Should have 2 tokens now
        assert bucket.tokens == 2

    def test_refill_caps_at_max(self):
        """Test that refill doesn't exceed max tokens."""
        bucket = TokenBucket(max_tokens=10, refill_rate=20, refill_period=1)

        # Consume 1 token
        bucket.try_consume(OrderType.NEW)
        assert bucket.tokens == 9

        # Tick to refill
        bucket.tick()

        # Should be capped at max
        assert bucket.tokens == 10

    def test_heartbeat_bypass(self):
        """Test that heartbeats bypass rate limit."""
        bucket = TokenBucket(max_tokens=0, refill_rate=0, refill_period=100)
        bucket.tokens = 0  # Force empty

        # Heartbeat should still pass
        assert bucket.try_consume(OrderType.HEARTBEAT) is True
        assert bucket.tokens == 0  # No tokens consumed

    def test_disabled_mode(self):
        """Test that disabled limiter passes everything."""
        bucket = TokenBucket(max_tokens=10, refill_rate=1, refill_period=100, enabled=False)

        # Should pass even though bucket is empty
        for _ in range(100):
            assert bucket.try_consume(OrderType.NEW) is True


# ============================================================================
# Position Limiter Tests
# ============================================================================

class TestPositionTracker:
    """Test position limiter."""

    def test_basic_position_tracking(self):
        """Test basic position tracking."""
        tracker = PositionTracker(
            max_long=1000, max_short=1000,
            max_notional=1_000_000, max_order_qty=100
        )

        # Buy 100
        assert tracker.check_order(OrderSide.BUY, OrderType.NEW, 100, 10000) == RiskReject.OK
        tracker.apply_fill(OrderSide.BUY, 100, 10000)

        assert tracker.long_qty == 100
        assert tracker.net_position == 100

    def test_position_limit_exceeded(self):
        """Test position limit enforcement."""
        tracker = PositionTracker(
            max_long=1000, max_short=500,
            max_notional=1_000_000, max_order_qty=100
        )

        # Build up position to near limit
        tracker.long_qty = 950

        # Order that would exceed limit
        assert tracker.check_order(OrderSide.BUY, OrderType.NEW, 100, 10000) == RiskReject.POSITION_LIMIT

        # Smaller order should pass
        assert tracker.check_order(OrderSide.BUY, OrderType.NEW, 50, 5000) == RiskReject.OK

    def test_order_size_limit(self):
        """Test single order size limit."""
        tracker = PositionTracker(
            max_long=10000, max_short=10000,
            max_notional=100_000_000, max_order_qty=100
        )

        # Order too large
        assert tracker.check_order(OrderSide.BUY, OrderType.NEW, 101, 10100) == RiskReject.ORDER_SIZE

        # Max size OK
        assert tracker.check_order(OrderSide.BUY, OrderType.NEW, 100, 10000) == RiskReject.OK

    def test_notional_limit(self):
        """Test notional limit enforcement."""
        tracker = PositionTracker(
            max_long=10000, max_short=10000,
            max_notional=100_000, max_order_qty=1000
        )

        # Build up notional
        tracker.notional = 90_000

        # Order that would exceed notional
        assert tracker.check_order(OrderSide.BUY, OrderType.NEW, 50, 15000) == RiskReject.NOTIONAL_LIMIT

        # Smaller notional should pass
        assert tracker.check_order(OrderSide.BUY, OrderType.NEW, 50, 5000) == RiskReject.OK

    def test_cancel_always_passes(self):
        """Test that cancels always pass position checks."""
        tracker = PositionTracker(
            max_long=0, max_short=0,
            max_notional=0, max_order_qty=0
        )

        # Even with zero limits, cancel should pass
        assert tracker.check_order(OrderSide.BUY, OrderType.CANCEL, 1000, 100000) == RiskReject.OK

    def test_net_position_calculation(self):
        """Test net position calculation."""
        tracker = PositionTracker(
            max_long=1000, max_short=1000,
            max_notional=1_000_000, max_order_qty=500
        )

        # Long 300
        tracker.apply_fill(OrderSide.BUY, 300, 30000)
        assert tracker.net_position == 300

        # Short 100
        tracker.apply_fill(OrderSide.SELL, 100, 10000)
        assert tracker.net_position == 200  # 300 - 100

        # Short another 250
        tracker.apply_fill(OrderSide.SELL, 250, 25000)
        assert tracker.net_position == -50  # 300 - 350


# ============================================================================
# Kill Switch Tests
# ============================================================================

class TestKillSwitch:
    """Test kill switch."""

    def test_manual_trigger(self):
        """Test manual kill switch trigger."""
        ks = KillSwitch(armed=True)

        assert ks.check_order() is True

        ks.trigger()

        assert ks.check_order() is False

    def test_requires_armed(self):
        """Test that trigger requires armed state."""
        ks = KillSwitch(armed=False)

        ks.trigger()

        # Should not be triggered since not armed
        assert ks.check_order() is True

    def test_reset(self):
        """Test kill switch reset."""
        ks = KillSwitch(armed=True)

        ks.trigger()
        assert ks.check_order() is False

        ks.reset()
        assert ks.check_order() is True

    def test_auto_trigger_on_loss(self):
        """Test auto-trigger on P&L loss threshold."""
        ks = KillSwitch(armed=True, auto_enabled=True, loss_threshold=10000)

        # Loss below threshold
        ks.check_pnl(5000, is_loss=True)
        assert ks.check_order() is True

        # Loss at threshold
        ks.check_pnl(10000, is_loss=True)
        assert ks.check_order() is False

    def test_auto_trigger_requires_loss_flag(self):
        """Test that auto-trigger requires is_loss flag."""
        ks = KillSwitch(armed=True, auto_enabled=True, loss_threshold=10000)

        # Large P&L but not flagged as loss
        ks.check_pnl(50000, is_loss=False)
        assert ks.check_order() is True  # Should not trigger

    def test_sticky_until_reset(self):
        """Test that trigger is sticky until explicit reset."""
        ks = KillSwitch(armed=True)

        ks.trigger()

        # Multiple orders should all be rejected
        for _ in range(100):
            assert ks.check_order() is False

        # P&L changes don't reset it
        ks.check_pnl(0, is_loss=False)
        assert ks.check_order() is False

        # Only explicit reset works
        ks.reset()
        assert ks.check_order() is True


# ============================================================================
# Integration Tests (Risk Gate Logic)
# ============================================================================

class TestRiskGateLogic:
    """Test combined risk gate logic."""

    def test_reject_priority_kill_first(self):
        """Test that kill switch has highest priority."""
        # All limits would fail
        bucket = TokenBucket(max_tokens=0, refill_rate=0, refill_period=100)
        bucket.tokens = 0
        tracker = PositionTracker(max_long=0, max_short=0, max_notional=0, max_order_qty=0)
        ks = KillSwitch(armed=True)
        ks.trigger()

        # Kill switch should be the reject reason
        if not ks.check_order():
            reject = RiskReject.KILL_SWITCH
        elif not bucket.try_consume(OrderType.NEW):
            reject = RiskReject.RATE_LIMITED
        else:
            reject = tracker.check_order(OrderSide.BUY, OrderType.NEW, 100, 10000)

        assert reject == RiskReject.KILL_SWITCH

    def test_reject_priority_rate_second(self):
        """Test that rate limit is second priority after kill switch."""
        bucket = TokenBucket(max_tokens=0, refill_rate=0, refill_period=100)
        bucket.tokens = 0
        tracker = PositionTracker(max_long=0, max_short=0, max_notional=0, max_order_qty=0)
        ks = KillSwitch(armed=True)  # Not triggered

        # Determine reject reason with priority
        if not ks.check_order():
            reject = RiskReject.KILL_SWITCH
        elif not bucket.try_consume(OrderType.NEW):
            reject = RiskReject.RATE_LIMITED
        else:
            reject = tracker.check_order(OrderSide.BUY, OrderType.NEW, 100, 10000)

        assert reject == RiskReject.RATE_LIMITED

    def test_all_pass(self):
        """Test order passing all checks."""
        bucket = TokenBucket(max_tokens=100, refill_rate=1, refill_period=100)
        tracker = PositionTracker(max_long=1000, max_short=1000,
                                  max_notional=1_000_000, max_order_qty=100)
        ks = KillSwitch(armed=True)

        # Check all stages
        assert ks.check_order() is True
        assert bucket.try_consume(OrderType.NEW) is True
        assert tracker.check_order(OrderSide.BUY, OrderType.NEW, 50, 5000) == RiskReject.OK


# ============================================================================
# Trace Flag Tests
# ============================================================================

class TestTraceFlags:
    """Test trace flag constants match expected values."""

    # From risk_pkg.sv
    FLAG_RISK_RATE_LIMITED = 0x0100
    FLAG_RISK_POSITION_LIMIT = 0x0200
    FLAG_RISK_NOTIONAL_LIMIT = 0x0400
    FLAG_RISK_KILL_SWITCH = 0x0800
    FLAG_RISK_REJECTED = 0x1000

    def test_flag_values(self):
        """Test flag values are in bits 8-15."""
        assert self.FLAG_RISK_RATE_LIMITED & 0xFF00 == self.FLAG_RISK_RATE_LIMITED
        assert self.FLAG_RISK_POSITION_LIMIT & 0xFF00 == self.FLAG_RISK_POSITION_LIMIT
        assert self.FLAG_RISK_NOTIONAL_LIMIT & 0xFF00 == self.FLAG_RISK_NOTIONAL_LIMIT
        assert self.FLAG_RISK_KILL_SWITCH & 0xFF00 == self.FLAG_RISK_KILL_SWITCH
        assert self.FLAG_RISK_REJECTED & 0xFF00 == self.FLAG_RISK_REJECTED

    def test_flags_dont_overlap(self):
        """Test flags don't overlap."""
        flags = [
            self.FLAG_RISK_RATE_LIMITED,
            self.FLAG_RISK_POSITION_LIMIT,
            self.FLAG_RISK_NOTIONAL_LIMIT,
            self.FLAG_RISK_KILL_SWITCH,
            self.FLAG_RISK_REJECTED,
        ]

        for i, f1 in enumerate(flags):
            for f2 in flags[i+1:]:
                assert f1 & f2 == 0, f"Flags {f1:04x} and {f2:04x} overlap"

    def test_combine_flags(self):
        """Test combining multiple flags."""
        combined = self.FLAG_RISK_REJECTED | self.FLAG_RISK_RATE_LIMITED

        assert combined & self.FLAG_RISK_REJECTED != 0
        assert combined & self.FLAG_RISK_RATE_LIMITED != 0
        assert combined & self.FLAG_RISK_POSITION_LIMIT == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
