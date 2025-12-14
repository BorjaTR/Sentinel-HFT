"""Trace pipeline for Sentinel-HFT.

Provides streaming trace processing with validation and enrichment.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'host'))

from trace_decode import TraceRecord, decode_trace_file
from .input_formats import InputTransaction


@dataclass
class EnrichedTrace:
    """Trace record with computed fields."""
    # Original fields
    tx_id: int
    t_ingress: int
    t_egress: int
    flags: int
    opcode: int
    meta: int

    # Computed fields
    latency_cycles: int
    latency_ns: float          # Using clock period

    # Optional enrichment
    input_timestamp_ns: Optional[int] = None  # From input data
    queue_time_ns: Optional[float] = None     # Time waiting in queue

    @classmethod
    def from_trace(cls, trace: TraceRecord, clock_period_ns: float = 10.0) -> 'EnrichedTrace':
        """Create EnrichedTrace from TraceRecord.

        Args:
            trace: Raw trace record
            clock_period_ns: Clock period for time conversion

        Returns:
            EnrichedTrace with computed latency
        """
        latency = trace.t_egress - trace.t_ingress
        return cls(
            tx_id=trace.tx_id,
            t_ingress=trace.t_ingress,
            t_egress=trace.t_egress,
            flags=trace.flags,
            opcode=trace.opcode,
            meta=trace.meta,
            latency_cycles=latency,
            latency_ns=latency * clock_period_ns,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        result = {
            'tx_id': self.tx_id,
            't_ingress': self.t_ingress,
            't_egress': self.t_egress,
            'flags': self.flags,
            'opcode': self.opcode,
            'meta': self.meta,
            'latency_cycles': self.latency_cycles,
            'latency_ns': self.latency_ns,
        }
        if self.input_timestamp_ns is not None:
            result['input_timestamp_ns'] = self.input_timestamp_ns
        if self.queue_time_ns is not None:
            result['queue_time_ns'] = self.queue_time_ns
        return result


@dataclass
class ValidationResult:
    """Result of trace validation."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Statistics
    total_traces: int = 0
    valid_traces: int = 0
    duplicate_tx_ids: int = 0
    out_of_order: int = 0
    negative_latency: int = 0
    with_flags: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'valid': self.valid,
            'errors': self.errors,
            'warnings': self.warnings,
            'total_traces': self.total_traces,
            'valid_traces': self.valid_traces,
            'duplicate_tx_ids': self.duplicate_tx_ids,
            'out_of_order': self.out_of_order,
            'negative_latency': self.negative_latency,
            'with_flags': self.with_flags,
        }


class TracePipeline:
    """Process trace stream with validation and enrichment."""

    def __init__(self, clock_period_ns: float = 10.0):
        """Initialize pipeline.

        Args:
            clock_period_ns: Clock period for time conversion (default: 10ns = 100MHz)
        """
        self.clock_period_ns = clock_period_ns

    def process(self, trace_file: Path) -> Iterator[EnrichedTrace]:
        """Stream enriched traces from file.

        Args:
            trace_file: Path to binary trace file

        Yields:
            EnrichedTrace objects
        """
        with open(trace_file, 'rb') as f:
            for trace in decode_trace_file(f):
                yield EnrichedTrace.from_trace(trace, self.clock_period_ns)

    def process_all(self, trace_file: Path) -> list[EnrichedTrace]:
        """Load all traces from file.

        Args:
            trace_file: Path to binary trace file

        Returns:
            List of EnrichedTrace objects
        """
        return list(self.process(trace_file))

    def validate(self, trace_file: Path) -> ValidationResult:
        """Validate trace file for correctness.

        Checks:
        - tx_id is monotonically increasing
        - No duplicate tx_ids
        - t_egress >= t_ingress (non-negative latency)
        - Flags are valid

        Args:
            trace_file: Path to trace file

        Returns:
            ValidationResult with details
        """
        result = ValidationResult(valid=True)
        seen_tx_ids = set()
        last_tx_id = -1

        for trace in self.process(trace_file):
            result.total_traces += 1

            # Check for duplicate tx_id
            if trace.tx_id in seen_tx_ids:
                result.duplicate_tx_ids += 1
                result.errors.append(f"Duplicate tx_id: {trace.tx_id}")
                result.valid = False
            seen_tx_ids.add(trace.tx_id)

            # Check for out-of-order tx_id
            if trace.tx_id <= last_tx_id:
                result.out_of_order += 1
                result.warnings.append(
                    f"Out of order tx_id: {trace.tx_id} after {last_tx_id}"
                )
            last_tx_id = trace.tx_id

            # Check for negative latency
            if trace.latency_cycles < 0:
                result.negative_latency += 1
                result.errors.append(
                    f"Negative latency for tx_id {trace.tx_id}: {trace.latency_cycles}"
                )
                result.valid = False

            # Check flags
            if trace.flags != 0:
                result.with_flags += 1
                if trace.flags & 0x0001:  # FLAG_TRACE_DROPPED
                    result.warnings.append(f"tx_id {trace.tx_id} has TRACE_DROPPED flag")
                if trace.flags & 0x0002:  # FLAG_CORE_ERROR
                    result.warnings.append(f"tx_id {trace.tx_id} has CORE_ERROR flag")
                if trace.flags & 0x0004:  # FLAG_INFLIGHT_UNDER
                    result.errors.append(f"tx_id {trace.tx_id} has INFLIGHT_UNDER flag")
                    result.valid = False

            result.valid_traces += 1

        return result

    def filter(
        self,
        traces: Iterator[EnrichedTrace],
        min_latency: Optional[int] = None,
        max_latency: Optional[int] = None,
        opcodes: Optional[set[int]] = None,
        flags_mask: Optional[int] = None,
    ) -> Iterator[EnrichedTrace]:
        """Filter trace stream by criteria.

        Args:
            traces: Input trace stream
            min_latency: Minimum latency in cycles (inclusive)
            max_latency: Maximum latency in cycles (inclusive)
            opcodes: Set of opcodes to include (None = all)
            flags_mask: Only include traces with these flags set

        Yields:
            Filtered traces
        """
        for trace in traces:
            # Filter by latency
            if min_latency is not None and trace.latency_cycles < min_latency:
                continue
            if max_latency is not None and trace.latency_cycles > max_latency:
                continue

            # Filter by opcode
            if opcodes is not None and trace.opcode not in opcodes:
                continue

            # Filter by flags
            if flags_mask is not None and (trace.flags & flags_mask) != flags_mask:
                continue

            yield trace

    def correlate_with_input(
        self,
        traces: Iterator[EnrichedTrace],
        input_data: list[InputTransaction],
    ) -> Iterator[EnrichedTrace]:
        """Enrich traces with input data (timestamps, queue time).

        Correlates traces with input transactions by tx_id to add:
        - input_timestamp_ns: When the transaction was scheduled to arrive
        - queue_time_ns: Time between input timestamp and ingress

        Args:
            traces: Input trace stream
            input_data: List of input transactions (must be sorted by timestamp)

        Yields:
            Enriched traces with input correlation
        """
        # Build lookup by index (tx_id corresponds to input index)
        for trace in traces:
            if trace.tx_id < len(input_data):
                input_tx = input_data[trace.tx_id]
                trace.input_timestamp_ns = input_tx.timestamp_ns

                # Calculate queue time (ingress cycle to ns, minus input timestamp)
                ingress_ns = trace.t_ingress * self.clock_period_ns
                trace.queue_time_ns = ingress_ns - input_tx.timestamp_ns

            yield trace

    def get_latencies(self, trace_file: Path) -> list[int]:
        """Extract just latency values from trace file.

        Convenience method for metrics computation.

        Args:
            trace_file: Path to trace file

        Returns:
            List of latency values in cycles
        """
        return [t.latency_cycles for t in self.process(trace_file)]
