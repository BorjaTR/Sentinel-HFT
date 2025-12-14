"""
Tests for Phase 3: Quantile Estimation.

CRITICAL TESTS:
1. test_percentile_accuracy - P99 must be accurate (<5% error)
2. test_merge_correctness - Merged digests must be correct
"""

import pytest
from sentinel_hft.streaming.quantiles import DDSketch, TDigestWrapper
from sentinel_hft.streaming.rolling_window import RollingWindowStats


class TestDDSketch:
    """Test DDSketch directly."""

    def test_uniform_distribution(self):
        """DDSketch on uniform 0-10000."""
        sketch = DDSketch(alpha=0.01)

        for i in range(10001):
            sketch.add(i)

        p50 = sketch.percentile(0.50)
        p90 = sketch.percentile(0.90)
        p99 = sketch.percentile(0.99)

        # True values: P50=5000, P90=9000, P99=9900
        # Allow 5% error
        assert 4750 <= p50 <= 5250, f"P50 = {p50}, expected ~5000"
        assert 8550 <= p90 <= 9450, f"P90 = {p90}, expected ~9000"
        assert 9405 <= p99 <= 10395, f"P99 = {p99}, expected ~9900"

    def test_merge(self):
        """Merged sketches produce correct percentiles."""
        s1 = DDSketch(alpha=0.01)
        s2 = DDSketch(alpha=0.01)

        for i in range(5000):
            s1.add(i)
        for i in range(5000, 10000):
            s2.add(i)

        s1.merge(s2)

        assert s1.count() == 10000

        p50 = s1.percentile(0.50)
        assert 4500 <= p50 <= 5500, f"P50 after merge = {p50}"

    def test_empty_sketch(self):
        """Empty sketch returns 0."""
        sketch = DDSketch()
        assert sketch.percentile(0.99) == 0.0
        assert sketch.count() == 0

    def test_single_value(self):
        """Single value returns approximately that value."""
        sketch = DDSketch()
        sketch.add(42)
        # DDSketch uses bucket quantization, so result is approximate
        assert 40 <= sketch.percentile(0.5) <= 44
        assert 40 <= sketch.percentile(0.99) <= 44


class TestTDigestWrapper:
    """Test TDigestWrapper (uses tdigest or DDSketch fallback)."""

    def test_percentile_accuracy(self):
        """
        CRITICAL TEST: Percentiles must be accurate.

        If this fails, the entire tool is useless - P99 would be wrong!
        """
        digest = TDigestWrapper()

        for i in range(10001):
            digest.add(i)

        p50 = digest.percentile(0.50)
        p99 = digest.percentile(0.99)
        p999 = digest.percentile(0.999)

        # Within 5% of true values
        assert 4750 <= p50 <= 5250, f"P50 = {p50}, expected ~5000"
        assert 9405 <= p99 <= 10000, f"P99 = {p99}, expected ~9900"
        assert 9900 <= p999 <= 10100, f"P99.9 = {p999}, expected ~9990"

    def test_merge_correctness(self):
        """
        CRITICAL TEST: Merge must preserve accuracy.

        This is essential for parallel processing and rolling windows.
        """
        d1 = TDigestWrapper()
        d2 = TDigestWrapper()

        for i in range(5000):
            d1.add(i)
        for i in range(5000, 10000):
            d2.add(i)

        d1.merge(d2)

        assert d1.count() == 10000

        p50 = d1.percentile(0.50)
        assert 4500 <= p50 <= 5500, f"P50 after merge = {p50}"

    def test_min_max_tracking(self):
        """Min and max are tracked correctly."""
        digest = TDigestWrapper()

        for v in [5, 100, 3, 200, 1, 50]:
            digest.add(v)

        assert digest.min == 1
        assert digest.max == 200


class TestRollingWindow:
    """Test rolling window statistics."""

    def test_sample_count_tracking(self):
        """Sample count is tracked correctly."""
        window = RollingWindowStats(
            window_seconds=10.0,
            bucket_seconds=1.0,
            clock_hz=1000,
        )

        for i in range(100):
            window.add(value=i, timestamp=i)

        assert window.sample_count == 100

    def test_bucket_expiration(self):
        """Old buckets are expired correctly."""
        window = RollingWindowStats(
            window_seconds=10.0,
            bucket_seconds=1.0,
            clock_hz=1,  # 1 Hz for easy math
        )

        # Add at t=0
        for i in range(10):
            window.add(value=i, timestamp=0)
        assert window.sample_count == 10

        # Add at t=15 (should expire t=0 bucket)
        for i in range(5):
            window.add(value=i, timestamp=15)

        assert window.sample_count == 5  # Old expired

    def test_percentile_across_buckets(self):
        """Percentile is computed correctly across buckets."""
        window = RollingWindowStats(
            window_seconds=10.0,
            bucket_seconds=1.0,
            clock_hz=1,
        )

        # Add values across multiple buckets
        for t in range(5):
            for v in range(10):
                window.add(value=v + t * 10, timestamp=t)

        # Should have 50 values: 0-49
        assert window.sample_count == 50

        p50 = window.percentile(0.5)
        # Median of 0-49 is ~24.5
        assert 20 <= p50 <= 30


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
