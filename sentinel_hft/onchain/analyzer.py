"""Streaming analyzer for on-chain latency traces.

Consumes ``OnchainRecord`` instances one at a time and maintains per-
stage quantile sketches, overhead counters, venue/action breakdowns,
and flag-hit rates. API mirrors :class:`StreamingMetrics` from the
core package: ``add(record)`` then ``snapshot()``.

We use :class:`DDSketch` from ``sentinel_hft.streaming.quantiles`` --
the same quantile estimator the FPGA pipeline uses -- so memory stays
bounded and results are directly comparable across the two domains.

This module is deliberately independent of the FPGA trace format: it
does not import from ``adapters`` or ``formats``. That separation
matters because on-chain traces are produced by a client-side tracer
not an FPGA, and the pipelines should remain decomposable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional

from ..streaming.quantiles import DDSketch
from .record import (
    OnchainRecord,
    OnchainStage,
    OnchainVenue,
    OnchainAction,
    FLAG_REJECTED,
    FLAG_TIMEOUT,
    FLAG_REORG,
    FLAG_LANDED,
)


# Quantiles we always report. p50/p99/p999 for tail visibility.
DEFAULT_QUANTILES = (0.50, 0.90, 0.99, 0.999)


@dataclass
class StageSummary:
    """Quantile summary for a single pipeline stage."""

    stage: str
    count: int = 0
    sum_ns: int = 0
    min_ns: int = 0
    max_ns: int = 0
    p50_ns: float = 0.0
    p90_ns: float = 0.0
    p99_ns: float = 0.0
    p999_ns: float = 0.0

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "count": self.count,
            "sum_ns": self.sum_ns,
            "min_ns": self.min_ns,
            "max_ns": self.max_ns,
            "p50_ns": self.p50_ns,
            "p90_ns": self.p90_ns,
            "p99_ns": self.p99_ns,
            "p999_ns": self.p999_ns,
        }


@dataclass
class OnchainSnapshot:
    """Point-in-time view of the streaming analyzer state."""

    total_records: int = 0
    total_landed: int = 0
    total_rejected: int = 0
    total_timed_out: int = 0
    total_reorged: int = 0

    # Stage-wise quantile summaries, keyed by stage name.
    stages: Dict[str, StageSummary] = field(default_factory=dict)

    # End-to-end (client_ts -> included_ts) summary.
    total: StageSummary = field(default_factory=lambda: StageSummary("total"))

    # Unexplained overhead = total - sum(stages). Positive overhead is
    # the scheduler / GC / NUMA tax; negative means timestamp jitter.
    overhead: StageSummary = field(default_factory=lambda: StageSummary("overhead"))

    # Breakdowns for venue / action — counts only (quantiles across
    # every breakdown would blow up memory and rarely help).
    per_venue: Dict[str, int] = field(default_factory=dict)
    per_action: Dict[str, int] = field(default_factory=dict)

    def landed_rate(self) -> float:
        if self.total_records == 0:
            return 0.0
        return self.total_landed / self.total_records

    def rejection_rate(self) -> float:
        if self.total_records == 0:
            return 0.0
        return self.total_rejected / self.total_records

    def to_dict(self) -> dict:
        return {
            "total_records": self.total_records,
            "total_landed": self.total_landed,
            "total_rejected": self.total_rejected,
            "total_timed_out": self.total_timed_out,
            "total_reorged": self.total_reorged,
            "landed_rate": self.landed_rate(),
            "rejection_rate": self.rejection_rate(),
            "stages": {k: v.to_dict() for k, v in self.stages.items()},
            "total": self.total.to_dict(),
            "overhead": self.overhead.to_dict(),
            "per_venue": dict(self.per_venue),
            "per_action": dict(self.per_action),
        }


class _StageSketch:
    """Single stage's running stats + DDSketch for quantile estimation.

    Kept private so we can swap the quantile algorithm (e.g. for
    HdrHistogram) without breaking the outer API.
    """

    __slots__ = ("name", "sketch", "count", "sum_ns", "min_ns", "max_ns")

    def __init__(self, name: str, alpha: float = 0.01):
        self.name = name
        self.sketch = DDSketch(alpha=alpha)
        self.count = 0
        self.sum_ns = 0
        self.min_ns: Optional[int] = None
        self.max_ns: Optional[int] = None

    def add(self, value: int) -> None:
        # DDSketch requires strictly positive values; accept zero by
        # nudging to 1ns (sub-resolution anyway). Negative values
        # would indicate clock skew — skip them rather than corrupt
        # the sketch.
        if value < 0:
            return
        self.count += 1
        self.sum_ns += value
        self.min_ns = value if self.min_ns is None else min(self.min_ns, value)
        self.max_ns = value if self.max_ns is None else max(self.max_ns, value)
        self.sketch.add(max(1, value))

    def summary(self) -> StageSummary:
        # DDSketch.percentile expects a fraction in [0, 1].
        # DDSketch returns 0.0 for empty; we normalise to zero values.
        return StageSummary(
            stage=self.name,
            count=self.count,
            sum_ns=self.sum_ns,
            min_ns=self.min_ns or 0,
            max_ns=self.max_ns or 0,
            p50_ns=self.sketch.percentile(0.50) if self.count else 0.0,
            p90_ns=self.sketch.percentile(0.90) if self.count else 0.0,
            p99_ns=self.sketch.percentile(0.99) if self.count else 0.0,
            p999_ns=self.sketch.percentile(0.999) if self.count else 0.0,
        )


class OnchainMetrics:
    """Streaming analyzer. One instance per analysis run.

    Typical use::

        m = OnchainMetrics()
        for rec in iter_records(path):
            m.add(rec)
        snap = m.snapshot()
        print(snap.stages['sign'].p99_ns)
    """

    _STAGE_NAMES = ("rpc", "quote", "sign", "submit", "inclusion")

    def __init__(self, alpha: float = 0.01):
        self._alpha = alpha
        self._stage_sketches: Dict[str, _StageSketch] = {
            name: _StageSketch(name, alpha=alpha) for name in self._STAGE_NAMES
        }
        self._total = _StageSketch("total", alpha=alpha)
        self._overhead = _StageSketch("overhead", alpha=alpha)

        self._count = 0
        self._landed = 0
        self._rejected = 0
        self._timed_out = 0
        self._reorged = 0
        self._per_venue: Dict[str, int] = {}
        self._per_action: Dict[str, int] = {}

    # -- ingestion --------------------------------------------------------

    def add(self, rec: OnchainRecord) -> None:
        """Record a single on-chain trace."""
        self._count += 1
        if rec.flags & FLAG_LANDED:
            self._landed += 1
        if rec.flags & FLAG_REJECTED:
            self._rejected += 1
        if rec.flags & FLAG_TIMEOUT:
            self._timed_out += 1
        if rec.flags & FLAG_REORG:
            self._reorged += 1

        self._stage_sketches["rpc"].add(rec.d_rpc_ns)
        self._stage_sketches["quote"].add(rec.d_quote_ns)
        self._stage_sketches["sign"].add(rec.d_sign_ns)
        self._stage_sketches["submit"].add(rec.d_submit_ns)
        self._stage_sketches["inclusion"].add(rec.d_inclusion_ns)

        total = rec.total_ns
        self._total.add(total)
        self._overhead.add(rec.overhead_ns)

        venue_name = _venue_name(rec.venue)
        self._per_venue[venue_name] = self._per_venue.get(venue_name, 0) + 1
        action_name = _action_name(rec.action)
        self._per_action[action_name] = self._per_action.get(action_name, 0) + 1

    def add_many(self, records: Iterable[OnchainRecord]) -> None:
        for rec in records:
            self.add(rec)

    # -- output -----------------------------------------------------------

    def snapshot(self) -> OnchainSnapshot:
        stages = {name: sk.summary() for name, sk in self._stage_sketches.items()}
        return OnchainSnapshot(
            total_records=self._count,
            total_landed=self._landed,
            total_rejected=self._rejected,
            total_timed_out=self._timed_out,
            total_reorged=self._reorged,
            stages=stages,
            total=self._total.summary(),
            overhead=self._overhead.summary(),
            per_venue=dict(self._per_venue),
            per_action=dict(self._per_action),
        )

    # -- iteration helper -------------------------------------------------

    @staticmethod
    def iter_file(path) -> Iterator[OnchainRecord]:
        """Iterate records from a file written by ``write_records``."""
        from pathlib import Path
        from .record import (
            ONCHAIN_FILE_HEADER_STRUCT,
            ONCHAIN_FILE_HEADER_SIZE,
            ONCHAIN_MAGIC,
            ONCHAIN_RECORD_SIZE,
        )

        p = Path(path)
        with p.open("rb") as f:
            head = f.read(ONCHAIN_FILE_HEADER_SIZE)
            if len(head) < ONCHAIN_FILE_HEADER_SIZE:
                raise ValueError(f"File too small to contain header: {path}")
            magic, _ver, rec_size = ONCHAIN_FILE_HEADER_STRUCT.unpack(head)
            if magic != ONCHAIN_MAGIC:
                raise ValueError(
                    f"Not an on-chain trace file (magic={magic!r}): {path}"
                )
            if rec_size != ONCHAIN_RECORD_SIZE:
                raise ValueError(
                    f"Unexpected record size {rec_size} in {path}"
                )
            while True:
                buf = f.read(ONCHAIN_RECORD_SIZE)
                if not buf:
                    return
                if len(buf) != ONCHAIN_RECORD_SIZE:
                    raise ValueError(
                        f"Truncated record in {path}: got {len(buf)} bytes"
                    )
                yield OnchainRecord.decode(buf)


def write_records(path, records: Iterable[OnchainRecord]) -> int:
    """Write a header + record stream to ``path``. Returns bytes written."""
    from pathlib import Path
    from .record import (
        ONCHAIN_FILE_HEADER_STRUCT,
        ONCHAIN_FORMAT_VERSION,
        ONCHAIN_RECORD_SIZE,
        ONCHAIN_MAGIC,
    )

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("wb") as f:
        f.write(ONCHAIN_FILE_HEADER_STRUCT.pack(
            ONCHAIN_MAGIC, ONCHAIN_FORMAT_VERSION, ONCHAIN_RECORD_SIZE
        ))
        n += 16
        for r in records:
            buf = r.encode()
            f.write(buf)
            n += len(buf)
    return n


# -- helpers --------------------------------------------------------------


def _venue_name(v: int) -> str:
    try:
        return OnchainVenue(v).name.lower()
    except ValueError:
        return f"unknown_{v}"


def _action_name(a: int) -> str:
    try:
        return OnchainAction(a).name.lower()
    except ValueError:
        return f"unknown_{a}"


__all__ = [
    "OnchainMetrics",
    "OnchainSnapshot",
    "StageSummary",
    "write_records",
    "DEFAULT_QUANTILES",
]
