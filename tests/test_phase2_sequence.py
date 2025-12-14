"""
Tests for Phase 2: Sequence Tracking.

CRITICAL TESTS:
1. test_clean_wrap_no_drops - Wrap at 0xFFFFFFFF→0 produces ZERO drops
2. test_reorder_not_counted_as_drop - Reorders are NOT counted as drops
"""

import pytest
from sentinel_hft.streaming.sequence import (
    u32, u32_add, u32_distance,
    SequenceTracker, DropEvent,
    U32_MAX, U32_HALF,
)


class TestU32Arithmetic:
    """Test u32 modular arithmetic functions."""

    def test_u32_basic(self):
        """Basic u32 constraint."""
        assert u32(0) == 0
        assert u32(100) == 100
        assert u32(U32_MAX) == U32_MAX

    def test_u32_wrap(self):
        """u32 wraps at 2^32."""
        assert u32(U32_MAX + 1) == 0
        assert u32(U32_MAX + 2) == 1
        assert u32(U32_MAX + 100) == 99

    def test_u32_negative(self):
        """Python negatives become high u32 values."""
        assert u32(-1) == U32_MAX
        assert u32(-2) == U32_MAX - 1

    def test_u32_add(self):
        """u32 addition with wrap."""
        assert u32_add(1, 2) == 3
        assert u32_add(U32_MAX, 1) == 0  # Wrap!
        assert u32_add(U32_MAX, 2) == 1
        assert u32_add(U32_MAX - 5, 10) == 4

    def test_u32_distance_forward(self):
        """Forward distance (positive = ahead)."""
        assert u32_distance(0, 5) == 5
        assert u32_distance(100, 200) == 100
        # Note: u32_distance(0, U32_MAX) returns -1 because U32_MAX >= U32_HALF,
        # which means going from 0 to MAX is interpreted as 1 step backward.
        # This is correct signed u32 distance behavior.

    def test_u32_distance_backward(self):
        """Backward distance (negative = behind/reorder)."""
        assert u32_distance(5, 0) == -5
        assert u32_distance(200, 100) == -100

    def test_u32_distance_wrap_forward(self):
        """
        Forward distance across wrap boundary.

        From 0xFFFFFFFE to 1:
        FE → FF → 0 → 1 = 3 steps forward
        """
        assert u32_distance(0xFFFFFFFE, 1) == 3
        assert u32_distance(0xFFFFFFFF, 0) == 1
        assert u32_distance(0xFFFFFFFF, 5) == 6

    def test_u32_distance_wrap_backward(self):
        """
        Backward distance across wrap boundary.

        From 1 to 0xFFFFFFFE:
        1 → 0 → FF → FE = 3 steps backward
        """
        assert u32_distance(1, 0xFFFFFFFE) == -3
        assert u32_distance(0, 0xFFFFFFFF) == -1
        assert u32_distance(5, 0xFFFFFFFF) == -6


class TestSequenceTrackerBasic:
    """Test basic sequence tracking."""

    def test_first_trace_initializes(self):
        """First trace from a core initializes tracking."""
        tracker = SequenceTracker()

        drop = tracker.check(core_id=0, seq_no=100, timestamp=0)

        assert drop is None
        assert tracker.expected_seq[0] == 101
        assert tracker.total_dropped == 0

    def test_consecutive_sequences_no_drops(self):
        """Consecutive sequences produce no drops."""
        tracker = SequenceTracker()

        for seq in range(100):
            drop = tracker.check(core_id=0, seq_no=seq, timestamp=0)
            assert drop is None

        assert tracker.total_dropped == 0
        assert tracker.total_reorders == 0

    def test_gap_detected_as_drop(self):
        """Gaps in sequence are detected as drops."""
        tracker = SequenceTracker()

        tracker.check(0, 0, 0)
        tracker.check(0, 1, 0)
        tracker.check(0, 2, 0)

        # Skip 3, 4 - should detect as 2 drops
        drop = tracker.check(0, 5, 0)

        assert drop is not None
        assert drop.dropped_count == 2
        assert drop.expected_seq == 3
        assert drop.actual_seq == 5

        assert tracker.total_dropped == 2

    def test_multiple_cores_independent(self):
        """Each core is tracked independently."""
        tracker = SequenceTracker()

        # Core 0: seq 0, 1, 2
        tracker.check(0, 0, 0)
        tracker.check(0, 1, 0)
        tracker.check(0, 2, 0)

        # Core 1: seq 0, 1, 5 (gap of 3)
        tracker.check(1, 0, 0)
        tracker.check(1, 1, 0)
        drop = tracker.check(1, 5, 0)

        assert drop is not None
        assert drop.core_id == 1
        assert drop.dropped_count == 3

        # Core 0 should still be fine
        drop0 = tracker.check(0, 3, 0)
        assert drop0 is None

        assert tracker.total_dropped == 3  # Only core 1's drops


class TestSequenceWrap:
    """Test u32 wrap handling - CRITICAL!"""

    def test_clean_wrap_no_drops(self):
        """
        CRITICAL TEST: Wrap at 0xFFFFFFFF → 0 produces ZERO drops.

        This is the most important test. If this fails, we'll report
        billions of fake drops every ~72 minutes at 1M traces/sec.
        """
        tracker = SequenceTracker()

        # Approach the wrap boundary
        for seq in [0xFFFFFFFD, 0xFFFFFFFE, 0xFFFFFFFF]:
            drop = tracker.check(core_id=0, seq_no=seq, timestamp=0)
            assert drop is None, f"Unexpected drop at seq 0x{seq:08X}"

        # Cross the wrap boundary
        for seq in [0, 1, 2]:
            drop = tracker.check(core_id=0, seq_no=seq, timestamp=0)
            assert drop is None, f"Unexpected drop at seq {seq} after wrap"

        # CRITICAL: Must have zero drops
        assert tracker.total_dropped == 0, \
            f"Clean wrap produced {tracker.total_dropped} fake drops!"
        assert tracker.total_reorders == 0

    def test_gap_across_wrap_detected(self):
        """Gap that spans wrap boundary is detected correctly."""
        tracker = SequenceTracker()

        # At 0xFFFFFFFE, next expected is 0xFFFFFFFF
        tracker.check(0, 0xFFFFFFFE, 0)

        # Skip to 2: missed 0xFFFFFFFF, 0, 1 = 3 traces
        drop = tracker.check(0, 2, 0)

        assert drop is not None
        assert drop.dropped_count == 3
        assert drop.event_type == 'wrap'


class TestReordering:
    """Test reorder detection - CRITICAL!"""

    def test_reorder_not_counted_as_drop(self):
        """
        CRITICAL TEST: Out-of-order packets are NOT counted as drops.

        UDP can deliver packets out of order. If we see seq 5 before seq 4,
        that's reordering, NOT a drop.
        """
        tracker = SequenceTracker()

        tracker.check(0, 0, 0)
        tracker.check(0, 1, 0)
        tracker.check(0, 3, 0)  # Skip 2 → initial gap (1 drop)
        tracker.check(0, 2, 0)  # Late arrival of 2 → REORDER, not drop!
        tracker.check(0, 4, 0)  # Normal

        assert tracker.total_dropped == 1, \
            f"Expected 1 drop (initial gap), got {tracker.total_dropped}"
        assert tracker.total_reorders == 1, \
            f"Expected 1 reorder (late seq 2), got {tracker.total_reorders}"

    def test_very_old_packet_is_reorder(self):
        """Very old packets arriving late are reorders."""
        tracker = SequenceTracker()

        # Process 0-99 normally
        for seq in range(100):
            tracker.check(0, seq, 0)

        # Now receive seq 50 again (very late!)
        drop = tracker.check(0, 50, 0)

        assert drop is None  # NOT a drop
        assert tracker.total_dropped == 0
        assert tracker.total_reorders == 1


class TestReset:
    """Test explicit reset handling."""

    def test_explicit_reset_not_a_drop(self):
        """Explicit RESET record doesn't count as drop."""
        tracker = SequenceTracker()

        tracker.check(0, 100, 0)
        tracker.check(0, 101, 0)

        # Explicit reset to 0 (not a drop!)
        tracker.handle_reset(0, 0, 0)

        # Continue from 0
        drop = tracker.check(0, 1, 0)

        assert drop is None
        assert tracker.total_dropped == 0
        assert tracker.total_resets == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
