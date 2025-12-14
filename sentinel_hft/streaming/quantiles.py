"""
Streaming quantile estimation.

This module provides memory-efficient percentile computation:
- DDSketch: Pure Python with guaranteed error bounds
- TDigestWrapper: Uses tdigest library if available, DDSketch fallback

DDSketch reference: https://arxiv.org/abs/1908.10693
"""

import math
from typing import Dict


class DDSketch:
    """
    DDSketch for streaming quantile estimation.

    DDSketch provides guaranteed relative error bounds. With alpha=0.01,
    the returned percentile is guaranteed to be within 1% of the true value.

    Memory usage: O(log(max/min) / log(1 + alpha))
    For typical latency data (1-10000 cycles), this is ~300-400 buckets.

    Example:
        sketch = DDSketch(alpha=0.01)  # 1% relative error
        for latency in latencies:
            sketch.add(latency)
        p99 = sketch.percentile(0.99)
    """

    def __init__(self, alpha: float = 0.01):
        """
        Initialize DDSketch.

        Args:
            alpha: Relative error bound (0.01 = 1% error)
        """
        if not 0 < alpha < 1:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")

        self.alpha = alpha

        # gamma = (1 + alpha) / (1 - alpha)
        # Bucket boundaries: bucket i covers [gamma^(i-1), gamma^i)
        self.gamma = (1 + alpha) / (1 - alpha)
        self.log_gamma = math.log(self.gamma)

        # Buckets for positive, negative, and zero values
        self.positive_buckets: Dict[int, int] = {}
        self.negative_buckets: Dict[int, int] = {}
        self.zero_count: int = 0

        # Statistics
        self._count: int = 0
        self._min: float = float('inf')
        self._max: float = float('-inf')

    def _bucket_index(self, value: float) -> int:
        """Map a positive value to its bucket index."""
        if value <= 0:
            return 0
        return math.ceil(math.log(value) / self.log_gamma)

    def _bucket_value(self, index: int) -> float:
        """
        Get representative value for a bucket.

        Returns geometric midpoint to minimize relative error.
        """
        if index <= 0:
            return 0.0
        lower = self.gamma ** (index - 1)
        upper = self.gamma ** index
        return math.sqrt(lower * upper)

    def add(self, value: float) -> None:
        """Add a value to the sketch."""
        self._count += 1
        self._min = min(self._min, value)
        self._max = max(self._max, value)

        if value > 0:
            idx = self._bucket_index(value)
            self.positive_buckets[idx] = self.positive_buckets.get(idx, 0) + 1
        elif value < 0:
            idx = self._bucket_index(-value)
            self.negative_buckets[idx] = self.negative_buckets.get(idx, 0) + 1
        else:
            self.zero_count += 1

    def percentile(self, p: float) -> float:
        """
        Get value at percentile p.

        Args:
            p: Percentile as fraction (0.0 to 1.0)

        Returns:
            Estimated value, guaranteed within alpha relative error.
        """
        if self._count == 0:
            return 0.0

        p = max(0.0, min(1.0, p))

        if p == 0:
            return self._min
        if p == 1:
            return self._max

        target_rank = p * self._count
        cumulative = 0

        # Walk through negative buckets (descending)
        for idx in sorted(self.negative_buckets.keys(), reverse=True):
            cumulative += self.negative_buckets[idx]
            if cumulative >= target_rank:
                return -self._bucket_value(idx)

        # Zero bucket
        cumulative += self.zero_count
        if cumulative >= target_rank:
            return 0.0

        # Walk through positive buckets (ascending)
        for idx in sorted(self.positive_buckets.keys()):
            cumulative += self.positive_buckets[idx]
            if cumulative >= target_rank:
                return self._bucket_value(idx)

        return self._max

    def merge(self, other: 'DDSketch') -> None:
        """Merge another DDSketch into this one."""
        if abs(self.alpha - other.alpha) > 1e-9:
            raise ValueError(
                f"Cannot merge sketches with different alpha: "
                f"{self.alpha} vs {other.alpha}"
            )

        for idx, count in other.positive_buckets.items():
            self.positive_buckets[idx] = self.positive_buckets.get(idx, 0) + count

        for idx, count in other.negative_buckets.items():
            self.negative_buckets[idx] = self.negative_buckets.get(idx, 0) + count

        self.zero_count += other.zero_count
        self._count += other._count
        self._min = min(self._min, other._min)
        self._max = max(self._max, other._max)

    def count(self) -> int:
        """Number of values added."""
        return self._count


# Try to use tdigest library for potentially better accuracy
_USE_TDIGEST = False
try:
    from tdigest import TDigest as _TDigestLib
    _USE_TDIGEST = True
except ImportError:
    _TDigestLib = None


class TDigestWrapper:
    """
    Wrapper with consistent API regardless of tdigest availability.

    Uses tdigest library if installed, otherwise falls back to DDSketch.
    """

    def __init__(self, compression: float = 100):
        """
        Initialize quantile estimator.

        Args:
            compression: For tdigest, controls accuracy/memory tradeoff.
        """
        self.compression = compression
        self._count = 0
        self._min = float('inf')
        self._max = float('-inf')

        if _USE_TDIGEST:
            self._impl = _TDigestLib(delta=compression)
            self._is_tdigest = True
        else:
            self._impl = DDSketch(alpha=0.01)
            self._is_tdigest = False

    def add(self, value: float) -> None:
        """Add a value."""
        self._count += 1
        self._min = min(self._min, value)
        self._max = max(self._max, value)

        if self._is_tdigest:
            self._impl.update(value)
        else:
            self._impl.add(value)

    def percentile(self, p: float) -> float:
        """Get percentile (p in 0.0-1.0)."""
        if self._count == 0:
            return 0.0

        p = max(0.001, min(0.999, p))

        if self._is_tdigest:
            # tdigest uses 0-100 scale
            return self._impl.percentile(p * 100)
        else:
            return self._impl.percentile(p)

    def merge(self, other: 'TDigestWrapper') -> None:
        """Merge another estimator into this one."""
        if self._is_tdigest and other._is_tdigest:
            self._impl = self._impl + other._impl
        elif not self._is_tdigest and not other._is_tdigest:
            self._impl.merge(other._impl)
        else:
            raise ValueError("Cannot merge TDigest with DDSketch")

        self._count += other._count
        self._min = min(self._min, other._min)
        self._max = max(self._max, other._max)

    def count(self) -> int:
        return self._count

    @property
    def min(self) -> float:
        return self._min if self._count > 0 else 0.0

    @property
    def max(self) -> float:
        return self._max if self._count > 0 else 0.0
