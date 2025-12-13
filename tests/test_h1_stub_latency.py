"""Test H1: Stub Latency Core Verification.

Verifies that the sentinel shell correctly measures latency through
the stub_latency_core for various LATENCY parameter values.

Requirements:
- t_egress - t_ingress == LATENCY for all traces
- tx_id strictly increasing (0, 1, 2, ...)
- trace_drop_count == 0 (no drops under normal conditions)
"""

import pytest
from pathlib import Path

from conftest import SimulationRunner, build_for_latency


class TestStubLatency:
    """Test latency measurement for various core latencies."""

    @pytest.fixture(autouse=True)
    def setup(self, sim_dir: Path):
        self.sim_dir = sim_dir

    @pytest.mark.parametrize("latency", [1, 2, 7, 19])
    def test_latency_measurement(self, latency: int):
        """Verify latency measurement equals configured core latency."""
        runner = build_for_latency(self.sim_dir, latency)

        num_tx = 100
        trace_file = f'trace_latency_{latency}.bin'

        result = runner.run(
            test_name='latency',
            num_tx=num_tx,
            output_file=trace_file
        )

        assert result.returncode == 0, f"Test failed: {result.stdout}\n{result.stderr}"
        assert "PASS" in result.stdout, f"Test did not pass: {result.stdout}"

        # Load and verify traces
        traces = runner.load_traces(trace_file)
        assert len(traces) == num_tx, f"Expected {num_tx} traces, got {len(traces)}"

        # Verify all latencies match
        for i, trace in enumerate(traces):
            measured_latency = trace.latency_cycles
            assert measured_latency == latency, (
                f"Trace {i}: expected latency {latency}, got {measured_latency}"
            )

    @pytest.mark.parametrize("latency", [1, 2, 7, 19])
    def test_tx_id_strictly_increasing(self, latency: int):
        """Verify transaction IDs are strictly increasing from 0."""
        runner = build_for_latency(self.sim_dir, latency)

        num_tx = 100
        trace_file = f'trace_txid_{latency}.bin'

        result = runner.run(
            test_name='latency',
            num_tx=num_tx,
            output_file=trace_file
        )

        assert result.returncode == 0

        traces = runner.load_traces(trace_file)
        assert len(traces) == num_tx

        # Verify tx_id sequence
        for i, trace in enumerate(traces):
            assert trace.tx_id == i, (
                f"Expected tx_id {i}, got {trace.tx_id}"
            )

    @pytest.mark.parametrize("latency", [1, 2, 7, 19])
    def test_no_trace_drops(self, latency: int):
        """Verify no traces are dropped under normal operation."""
        runner = build_for_latency(self.sim_dir, latency)

        result = runner.run(
            test_name='latency',
            num_tx=100,
            output_file=f'trace_drops_{latency}.bin'
        )

        assert result.returncode == 0
        assert "Trace drops: 0" in result.stdout, (
            f"Expected 0 trace drops, got: {result.stdout}"
        )

    def test_latency_consistency(self):
        """Verify all traces have identical latency (for fixed-latency core)."""
        runner = build_for_latency(self.sim_dir, 5)

        num_tx = 500  # More transactions for statistical confidence
        trace_file = 'trace_consistency.bin'

        result = runner.run(
            test_name='latency',
            num_tx=num_tx,
            output_file=trace_file
        )

        assert result.returncode == 0

        traces = runner.load_traces(trace_file)

        # Collect unique latencies
        unique_latencies = set(t.latency_cycles for t in traces)
        assert len(unique_latencies) == 1, (
            f"Expected single latency value, got: {unique_latencies}"
        )
        assert 5 in unique_latencies, (
            f"Expected latency of 5, got: {unique_latencies}"
        )

    def test_timestamp_ordering(self):
        """Verify timestamps are monotonically increasing."""
        runner = build_for_latency(self.sim_dir, 3)

        result = runner.run(
            test_name='latency',
            num_tx=100,
            output_file='trace_timestamps.bin'
        )

        assert result.returncode == 0

        traces = runner.load_traces('trace_timestamps.bin')

        # Verify ingress timestamps are increasing
        prev_ingress = -1
        for i, trace in enumerate(traces):
            assert trace.t_ingress > prev_ingress, (
                f"Trace {i}: t_ingress {trace.t_ingress} not > {prev_ingress}"
            )
            prev_ingress = trace.t_ingress

        # Verify egress timestamps are increasing
        prev_egress = -1
        for i, trace in enumerate(traces):
            assert trace.t_egress > prev_egress, (
                f"Trace {i}: t_egress {trace.t_egress} not > {prev_egress}"
            )
            prev_egress = trace.t_egress

    def test_egress_after_ingress(self):
        """Verify egress always happens after ingress (t_egress >= t_ingress)."""
        runner = build_for_latency(self.sim_dir, 10)

        result = runner.run(
            test_name='latency',
            num_tx=200,
            output_file='trace_ordering.bin'
        )

        assert result.returncode == 0

        traces = runner.load_traces('trace_ordering.bin')

        for i, trace in enumerate(traces):
            assert trace.t_egress >= trace.t_ingress, (
                f"Trace {i}: t_egress ({trace.t_egress}) < t_ingress ({trace.t_ingress})"
            )
