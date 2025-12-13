"""Test H1: Backpressure Counter Verification.

Verifies that backpressure counters accurately track cycles where
valid is asserted but ready is not.

Requirements:
- in_backpressure_cycles increments when in_valid && !in_ready
- out_backpressure_cycles increments when out_valid && !out_ready
- Counter values should match expected backpressure duration
"""

import re
import pytest
from pathlib import Path

from conftest import SimulationRunner, build_for_latency


class TestBackpressure:
    """Test backpressure counter accuracy."""

    @pytest.fixture(autouse=True)
    def setup(self, sim_dir: Path):
        self.sim_dir = sim_dir

    def _extract_counter(self, output: str, counter_name: str) -> int:
        """Extract counter value from simulation output."""
        pattern = rf"{counter_name}:\s*(\d+)"
        match = re.search(pattern, output)
        if match:
            return int(match.group(1))
        raise ValueError(f"Could not find {counter_name} in output")

    def test_backpressure_basic(self):
        """Verify backpressure counter increments under backpressure."""
        runner = build_for_latency(self.sim_dir, 2)

        bp_cycles = 20

        result = runner.run(
            test_name='backpressure',
            num_tx=10,
            output_file='trace_bp.bin',
            bp_cycles=bp_cycles
        )

        assert result.returncode == 0, f"Test failed: {result.stdout}"

        # Extract counter value
        in_bp = self._extract_counter(result.stdout, "In backpressure cycles")

        # Counter should be at least bp_cycles (might be more due to pipeline)
        assert in_bp >= bp_cycles - 5, (
            f"Expected at least {bp_cycles-5} backpressure cycles, got {in_bp}"
        )

    @pytest.mark.parametrize("bp_cycles", [5, 10, 25, 50])
    def test_backpressure_various_durations(self, bp_cycles: int):
        """Verify backpressure counters for various durations."""
        runner = build_for_latency(self.sim_dir, 1)

        result = runner.run(
            test_name='backpressure',
            num_tx=10,
            output_file=f'trace_bp_{bp_cycles}.bin',
            bp_cycles=bp_cycles
        )

        assert result.returncode == 0

        in_bp = self._extract_counter(result.stdout, "In backpressure cycles")

        # Allow some tolerance for pipeline timing
        assert bp_cycles - 5 <= in_bp <= bp_cycles + 10, (
            f"Backpressure cycles {in_bp} not within expected range "
            f"[{bp_cycles-5}, {bp_cycles+10}]"
        )

    def test_no_backpressure_baseline(self):
        """Verify minimal backpressure when system is not stressed."""
        runner = build_for_latency(self.sim_dir, 1)

        result = runner.run(
            test_name='latency',  # Use latency test which doesn't force BP
            num_tx=50,
            output_file='trace_no_bp.bin'
        )

        assert result.returncode == 0

        in_bp = self._extract_counter(result.stdout, "In backpressure cycles")
        out_bp = self._extract_counter(result.stdout, "Out backpressure cycles")

        # With no intentional backpressure, counters should be low
        # (might have some due to pipeline effects)
        assert in_bp < 50, f"Unexpected input backpressure: {in_bp}"
        assert out_bp < 50, f"Unexpected output backpressure: {out_bp}"

    def test_backpressure_counter_scales(self):
        """Verify backpressure counter scales with applied backpressure."""
        runner = build_for_latency(self.sim_dir, 3)

        # Run with increasing backpressure and verify counter scales
        results = []
        for bp_cycles in [10, 20, 30]:
            result = runner.run(
                test_name='backpressure',
                num_tx=10,
                output_file=f'trace_bp_scale_{bp_cycles}.bin',
                bp_cycles=bp_cycles
            )

            assert result.returncode == 0

            in_bp = self._extract_counter(result.stdout, "In backpressure cycles")
            results.append((bp_cycles, in_bp))

        # Verify that higher requested BP leads to higher measured BP
        # (Each run is independent, so we compare relative values)
        for i in range(1, len(results)):
            prev_req, prev_bp = results[i-1]
            curr_req, curr_bp = results[i]
            assert curr_bp >= prev_bp, (
                f"Higher BP request ({curr_req}) should give >= counter than ({prev_req}): "
                f"{curr_bp} vs {prev_bp}"
            )

    def test_output_backpressure(self):
        """Verify output backpressure counter when downstream is slow."""
        runner = build_for_latency(self.sim_dir, 1)

        # The backpressure test applies backpressure by setting out_ready=0
        result = runner.run(
            test_name='backpressure',
            num_tx=10,
            output_file='trace_out_bp.bin',
            bp_cycles=30
        )

        assert result.returncode == 0

        # Extract counters
        out_bp = self._extract_counter(result.stdout, "Out backpressure cycles")

        # Should have some output backpressure due to test design
        # (test forces out_ready=0 which causes output backpressure)
        assert out_bp > 0, f"Expected output backpressure, got {out_bp}"

    @pytest.mark.parametrize("latency", [1, 5, 10])
    def test_backpressure_across_latencies(self, latency: int):
        """Verify backpressure tracking works for different core latencies."""
        runner = build_for_latency(self.sim_dir, latency)

        bp_cycles = 15

        result = runner.run(
            test_name='backpressure',
            num_tx=10,
            output_file=f'trace_bp_lat{latency}.bin',
            bp_cycles=bp_cycles
        )

        assert result.returncode == 0

        in_bp = self._extract_counter(result.stdout, "In backpressure cycles")

        # Backpressure should be tracked regardless of latency
        assert in_bp >= bp_cycles - 5, (
            f"LATENCY={latency}: Expected ~{bp_cycles} BP cycles, got {in_bp}"
        )
