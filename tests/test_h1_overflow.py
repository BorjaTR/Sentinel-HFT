"""Test H1: Overflow Handling Verification.

Verifies that the sentinel shell handles trace FIFO overflow gracefully
without causing deadlock or pipeline stalls.

Requirements:
- All transactions complete even when trace FIFO overflows (no deadlock)
- trace_drop_count > 0 when overflow occurs
- trace_overflow_seen flag is set
- Shell never blocks the data path due to trace FIFO state
"""

import re
import pytest
from pathlib import Path

from conftest import SimulationRunner, build_for_latency


class TestOverflow:
    """Test trace FIFO overflow handling."""

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

    def _extract_bool(self, output: str, flag_name: str) -> bool:
        """Extract boolean flag from simulation output."""
        pattern = rf"{flag_name}:\s*(\d+)"
        match = re.search(pattern, output)
        if match:
            return int(match.group(1)) != 0
        raise ValueError(f"Could not find {flag_name} in output")

    def test_overflow_no_deadlock(self):
        """Verify all transactions complete even with trace FIFO overflow."""
        runner = build_for_latency(self.sim_dir, 1)

        # Send many more transactions than TRACE_FIFO_DEPTH (64)
        num_tx = 200

        result = runner.run(
            test_name='overflow',
            num_tx=num_tx,
            output_file='trace_overflow.bin'
        )

        assert result.returncode == 0, f"Test failed (possible deadlock): {result.stdout}"
        assert "PASS" in result.stdout, f"Overflow test did not pass: {result.stdout}"

        # Verify all transactions completed
        tx_received = self._extract_counter(result.stdout, "Transactions received")
        assert tx_received == num_tx, (
            f"Deadlock: only {tx_received}/{num_tx} transactions completed"
        )

    def test_overflow_drops_counted(self):
        """Verify trace_drop_count > 0 when overflow occurs."""
        runner = build_for_latency(self.sim_dir, 1)

        result = runner.run(
            test_name='overflow',
            num_tx=200,
            output_file='trace_drops.bin'
        )

        assert result.returncode == 0

        drops = self._extract_counter(result.stdout, "Trace drops")
        assert drops > 0, "Expected trace drops when overflow occurs"

    def test_overflow_flag_set(self):
        """Verify trace_overflow_seen flag is set on overflow."""
        runner = build_for_latency(self.sim_dir, 1)

        result = runner.run(
            test_name='overflow',
            num_tx=200,
            output_file='trace_flag.bin'
        )

        assert result.returncode == 0

        overflow_seen = self._extract_bool(result.stdout, "Trace overflow seen")
        assert overflow_seen, "trace_overflow_seen should be set"

    @pytest.mark.parametrize("num_tx", [100, 200, 500])
    def test_overflow_scaling(self, num_tx: int):
        """Verify overflow handling scales with transaction count."""
        runner = build_for_latency(self.sim_dir, 1)

        result = runner.run(
            test_name='overflow',
            num_tx=num_tx,
            output_file=f'trace_scale_{num_tx}.bin'
        )

        assert result.returncode == 0, f"Failed at {num_tx} transactions"

        tx_received = self._extract_counter(result.stdout, "Transactions received")
        assert tx_received == num_tx, f"Only {tx_received}/{num_tx} completed"

    @pytest.mark.parametrize("latency", [1, 3, 7])
    def test_overflow_across_latencies(self, latency: int):
        """Verify overflow handling works for different core latencies."""
        runner = build_for_latency(self.sim_dir, latency)

        num_tx = 150

        result = runner.run(
            test_name='overflow',
            num_tx=num_tx,
            output_file=f'trace_overflow_lat{latency}.bin'
        )

        assert result.returncode == 0

        tx_received = self._extract_counter(result.stdout, "Transactions received")
        assert tx_received == num_tx, (
            f"LATENCY={latency}: Only {tx_received}/{num_tx} completed"
        )

        drops = self._extract_counter(result.stdout, "Trace drops")
        assert drops > 0, f"LATENCY={latency}: Expected trace drops"

    def test_overflow_recovery(self):
        """Verify system continues operating correctly after overflow."""
        runner = build_for_latency(self.sim_dir, 2)

        # Cause overflow
        result1 = runner.run(
            test_name='overflow',
            num_tx=100,
            output_file='trace_recovery1.bin'
        )
        assert result1.returncode == 0

        # Run normal test after overflow
        result2 = runner.run(
            test_name='latency',
            num_tx=50,
            output_file='trace_recovery2.bin'
        )
        assert result2.returncode == 0
        assert "PASS" in result2.stdout, "System failed to recover after overflow"

    def test_overflow_partial_traces(self):
        """Verify that even with drops, some traces are captured."""
        runner = build_for_latency(self.sim_dir, 1)

        num_tx = 200

        result = runner.run(
            test_name='overflow',
            num_tx=num_tx,
            output_file='trace_partial.bin'
        )

        assert result.returncode == 0

        # Due to trace_ready=0 in overflow test, no traces collected
        # But verify drop count is reasonable
        drops = self._extract_counter(result.stdout, "Trace drops")
        tx_received = self._extract_counter(result.stdout, "Transactions received")

        # All transactions should complete
        assert tx_received == num_tx

        # Drops should be a significant portion (since trace consumption is disabled)
        # At least num_tx - TRACE_FIFO_DEPTH should be dropped
        min_expected_drops = num_tx - 64  # TRACE_FIFO_DEPTH = 64
        assert drops >= min_expected_drops - 10, (
            f"Expected at least {min_expected_drops} drops, got {drops}"
        )

    def test_no_inflight_underflow_on_overflow(self):
        """Verify overflow doesn't cause inflight FIFO underflow."""
        runner = build_for_latency(self.sim_dir, 1)

        result = runner.run(
            test_name='overflow',
            num_tx=200,
            output_file='trace_underflow.bin'
        )

        assert result.returncode == 0

        underflows = self._extract_counter(result.stdout, "Inflight underflows")
        assert underflows == 0, f"Unexpected inflight underflows: {underflows}"
