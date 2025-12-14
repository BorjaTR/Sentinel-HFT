"""
Rolling window statistics using time-bucketed quantile sketches.

This provides "P99 over the last 60 seconds" without storing all values.
"""

from collections import deque
from dataclasses import dataclass
from typing import Optional

from .quantiles import TDigestWrapper


@dataclass
class WindowBucket:
    """A time bucket with its quantile sketch."""
    start_time: float
    digest: TDigestWrapper
    sample_count: int


class RollingWindowStats:
    """
    Rolling window percentiles using time-bucketed sketches.

    Memory: O(window_seconds / bucket_seconds * sketch_size)
    For 60s window with 1s buckets: ~60 sketches

    Example:
        window = RollingWindowStats(window_seconds=60.0, clock_hz=100_000_000)
        for trace in traces:
            window.add(trace.latency, trace.t_egress)
        p99 = window.percentile(0.99)  # P99 over last 60 seconds
    """

    def __init__(
        self,
        window_seconds: float = 60.0,
        bucket_seconds: float = 1.0,
        clock_hz: float = 100_000_000,
    ):
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if bucket_seconds <= 0:
            raise ValueError("bucket_seconds must be positive")
        if bucket_seconds > window_seconds:
            raise ValueError("bucket_seconds cannot exceed window_seconds")

        self.window_seconds = window_seconds
        self.bucket_seconds = bucket_seconds
        self.clock_hz = clock_hz

        self.buckets: deque = deque()
        self.current_bucket: Optional[WindowBucket] = None
        self._sample_count: int = 0

    def _timestamp_to_seconds(self, timestamp: int) -> float:
        """Convert cycles to seconds."""
        return timestamp / self.clock_hz

    def add(self, value: float, timestamp: int) -> None:
        """Add a value with its timestamp."""
        ts_sec = self._timestamp_to_seconds(timestamp)

        # Initialize first bucket
        if self.current_bucket is None:
            self.current_bucket = WindowBucket(
                start_time=ts_sec,
                digest=TDigestWrapper(),
                sample_count=0,
            )

        # Check if we need to rotate to new bucket
        bucket_end = self.current_bucket.start_time + self.bucket_seconds
        if ts_sec >= bucket_end:
            self.buckets.append(self.current_bucket)
            self.current_bucket = WindowBucket(
                start_time=ts_sec,
                digest=TDigestWrapper(),
                sample_count=0,
            )

        # Add to current bucket
        self.current_bucket.digest.add(value)
        self.current_bucket.sample_count += 1
        self._sample_count += 1

        # Expire old buckets
        self._expire_buckets(ts_sec)

    def _expire_buckets(self, current_time: float) -> None:
        """Remove buckets older than window."""
        cutoff = current_time - self.window_seconds

        while self.buckets and self.buckets[0].start_time < cutoff:
            expired = self.buckets.popleft()
            self._sample_count -= expired.sample_count

    @property
    def sample_count(self) -> int:
        """Total samples currently in window."""
        return self._sample_count

    def percentile(self, p: float) -> float:
        """Get percentile across entire window."""
        if self._sample_count == 0:
            return 0.0

        # Merge all bucket digests
        merged = TDigestWrapper()

        for bucket in self.buckets:
            merged.merge(bucket.digest)

        if self.current_bucket and self.current_bucket.sample_count > 0:
            merged.merge(self.current_bucket.digest)

        return merged.percentile(p)
