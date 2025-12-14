"""
Sequence number tracking with proper u32 wrap handling.

CRITICAL: Python integers don't wrap! We must explicitly mask to u32.

This module provides:
- u32(): Constrain value to u32 range
- u32_distance(): Signed distance in u32 space (handles wrap)
- SequenceTracker: Detect drops vs reorders per core

Example of the bug we're fixing:
    # Python doesn't wrap
    >>> 0xFFFFFFFF + 1
    4294967296  # Wrong! Should be 0

    # With u32():
    >>> u32(0xFFFFFFFF + 1)
    0  # Correct!
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# u32 constants
U32_MAX = 0xFFFFFFFF           # 4,294,967,295
U32_HALF = 0x80000000          # 2,147,483,648 (for signed interpretation)
U32_MODULUS = U32_MAX + 1      # 2^32


def u32(val: int) -> int:
    """
    Constrain value to u32 range [0, 2^32-1].

    Examples:
        u32(0xFFFFFFFF) = 0xFFFFFFFF
        u32(0x100000000) = 0          # Wrapped!
        u32(-1) = 0xFFFFFFFF          # Python negative → u32 max
    """
    return val & U32_MAX


def u32_add(a: int, b: int) -> int:
    """Add two values in u32 space with wrap."""
    return (a + b) & U32_MAX


def u32_distance(from_seq: int, to_seq: int) -> int:
    """
    Compute signed distance from from_seq to to_seq in u32 space.

    This tells us how many steps forward (positive) or backward (negative)
    we need to go from from_seq to reach to_seq, accounting for wrap.

    Returns:
        Positive: to_seq is ahead (possible drops if > 1)
        Zero: to_seq equals from_seq (expected)
        Negative: to_seq is behind (reordering, not a drop!)

    Examples:
        u32_distance(5, 10) = 5          # 10 is 5 ahead of 5
        u32_distance(10, 5) = -5         # 5 is 5 behind 10
        u32_distance(0xFFFFFFFE, 1) = 3  # Wrap: FE→FF→0→1 = 3 steps
        u32_distance(1, 0xFFFFFFFE) = -3 # Wrap backward

    Algorithm:
        1. Compute unsigned difference: (to - from) mod 2^32
        2. If diff < 2^31: positive (forward)
        3. If diff >= 2^31: negative (backward), subtract 2^32
    """
    from_seq = u32(from_seq)
    to_seq = u32(to_seq)

    # Unsigned difference with wrap
    diff = u32(to_seq - from_seq)

    # Interpret as signed using two's complement logic:
    # If the unsigned diff is >= half the range, it's actually negative
    if diff >= U32_HALF:
        return diff - U32_MODULUS
    return diff


@dataclass
class DropEvent:
    """
    Record of detected trace drops.

    Attributes:
        core_id: Which core had the drop
        expected_seq: Sequence number we expected
        actual_seq: Sequence number we received
        dropped_count: How many traces were dropped
        timestamp: When the drop was detected (egress time)
        event_type: 'gap' (normal), 'wrap' (at u32 boundary)
    """
    core_id: int
    expected_seq: int
    actual_seq: int
    dropped_count: int
    timestamp: float
    event_type: str = 'gap'


@dataclass
class SequenceTracker:
    """
    Track sequence numbers per core with proper u32 wrap handling.

    This class detects:
    - Forward gaps (drops): expected seq 5, got seq 8 → dropped 3
    - Wrap handling: expected 0xFFFFFFFF, got 2 → dropped 2 (not billions!)
    - Reordering: expected seq 10, got seq 7 → reorder (not a drop!)

    Usage:
        tracker = SequenceTracker()
        for trace in traces:
            drop = tracker.check(trace.core_id, trace.seq_no, trace.t_egress)
            if drop:
                print(f"Dropped {drop.dropped_count} traces!")
    """

    # Per-core tracking: core_id → expected next sequence
    expected_seq: Dict[int, int] = field(default_factory=dict)

    # Per-core max seen (for progress tracking)
    max_seen_seq: Dict[int, int] = field(default_factory=dict)

    # Aggregate counters
    total_dropped: int = 0
    total_reorders: int = 0
    total_resets: int = 0

    # Detailed events for reporting
    drop_events: List[DropEvent] = field(default_factory=list)
    reorder_events: List[tuple] = field(default_factory=list)
    reset_events: List[tuple] = field(default_factory=list)

    def check(
        self,
        core_id: int,
        seq_no: int,
        timestamp: float
    ) -> Optional[DropEvent]:
        """
        Check a sequence number and detect drops/reorders.

        Call this for every trace received. Returns DropEvent if drops
        were detected, None otherwise.
        """
        seq = u32(seq_no)

        # First trace from this core - initialize tracking
        if core_id not in self.expected_seq:
            self.expected_seq[core_id] = u32_add(seq, 1)
            self.max_seen_seq[core_id] = seq
            return None

        expected = self.expected_seq[core_id]

        # Compute distance using modular arithmetic
        distance = u32_distance(expected, seq)

        if distance == 0:
            # Perfect: got exactly what we expected
            self.expected_seq[core_id] = u32_add(seq, 1)
            self._update_max_seen(core_id, seq)
            return None

        elif distance > 0:
            # Forward gap: we missed some traces
            dropped = distance

            # Detect wrap (expected near max, actual near zero)
            is_wrap = expected > 0xFFFF0000 and seq < 0x10000
            event_type = 'wrap' if is_wrap else 'gap'

            event = DropEvent(
                core_id=core_id,
                expected_seq=expected,
                actual_seq=seq,
                dropped_count=dropped,
                timestamp=timestamp,
                event_type=event_type,
            )

            self.drop_events.append(event)
            self.total_dropped += dropped

            # Update expected to continue from here
            self.expected_seq[core_id] = u32_add(seq, 1)
            self._update_max_seen(core_id, seq)

            return event

        else:
            # Negative distance: this is an old/reordered packet
            # NOT a drop - just arrived late
            self.total_reorders += 1
            self.reorder_events.append((core_id, expected, seq, timestamp))

            # Don't update expected - we're seeing an old packet
            return None

    def _update_max_seen(self, core_id: int, seq: int):
        """Update max seen sequence, handling wrap."""
        current_max = self.max_seen_seq.get(core_id, 0)
        if u32_distance(current_max, seq) > 0:
            self.max_seen_seq[core_id] = seq

    def handle_reset(self, core_id: int, new_seq: int, timestamp: float):
        """
        Handle explicit sequence reset (RESET record type).

        Call this when you receive a RESET record. This tells the tracker
        that the sequence was intentionally reset, not a drop.
        """
        old_expected = self.expected_seq.get(core_id, 0)

        self.total_resets += 1
        self.reset_events.append((core_id, old_expected, new_seq, timestamp))

        # Reset tracking for this core
        self.expected_seq[core_id] = u32_add(new_seq, 1)
        self.max_seen_seq[core_id] = new_seq

    def summary(self) -> dict:
        """Get summary statistics."""
        return {
            'total_dropped': self.total_dropped,
            'total_reorders': self.total_reorders,
            'total_resets': self.total_resets,
            'drop_events': len(self.drop_events),
            'cores_tracked': len(self.expected_seq),
        }
