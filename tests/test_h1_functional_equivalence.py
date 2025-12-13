"""Test H1: Functional Equivalence Verification.

Verifies that the sentinel shell wrapper does not alter the functional
behavior of the wrapped core. The output data sequence should be
identical whether the core is wrapped or not.

Requirements:
- Output data sequence identical with/without shell
- No extra or missing transactions
- Shell is transparent to the data path
"""

import pytest
from pathlib import Path

from conftest import SimulationRunner, build_for_latency


class TestFunctionalEquivalence:
    """Test functional equivalence of wrapped vs unwrapped core."""

    @pytest.fixture(autouse=True)
    def setup(self, sim_dir: Path, deterministic_seed: int):
        self.sim_dir = sim_dir
        self.seed = deterministic_seed

    def test_equivalence_basic(self):
        """Verify basic functional equivalence."""
        runner = build_for_latency(self.sim_dir, 3)

        result = runner.run(
            test_name='equivalence',
            num_tx=100,
            output_file='trace_equiv.bin',
            seed=self.seed
        )

        assert result.returncode == 0, f"Test failed: {result.stdout}"
        assert "PASS" in result.stdout, f"Equivalence test did not pass: {result.stdout}"

    def test_equivalence_transaction_count(self):
        """Verify all transactions pass through."""
        runner = build_for_latency(self.sim_dir, 2)

        num_tx = 150

        result = runner.run(
            test_name='equivalence',
            num_tx=num_tx,
            output_file='trace_count.bin'
        )

        assert result.returncode == 0

        traces = runner.load_traces('trace_count.bin')
        assert len(traces) == num_tx, (
            f"Expected {num_tx} traces, got {len(traces)}"
        )

    @pytest.mark.parametrize("latency", [1, 2, 5, 10, 15])
    def test_equivalence_across_latencies(self, latency: int):
        """Verify equivalence holds for various core latencies."""
        runner = build_for_latency(self.sim_dir, latency)

        result = runner.run(
            test_name='equivalence',
            num_tx=50,
            output_file=f'trace_equiv_lat{latency}.bin',
            seed=self.seed
        )

        assert result.returncode == 0, (
            f"LATENCY={latency} failed: {result.stdout}"
        )
        assert "PASS" in result.stdout

    def test_equivalence_stress(self):
        """Stress test with many transactions."""
        runner = build_for_latency(self.sim_dir, 4)

        num_tx = 1000

        result = runner.run(
            test_name='equivalence',
            num_tx=num_tx,
            output_file='trace_stress.bin'
        )

        assert result.returncode == 0, f"Stress test failed: {result.stdout}"

        traces = runner.load_traces('trace_stress.bin')
        assert len(traces) == num_tx

    def test_no_extra_transactions(self):
        """Verify no spurious transactions are generated."""
        runner = build_for_latency(self.sim_dir, 3)

        num_tx = 75

        result = runner.run(
            test_name='equivalence',
            num_tx=num_tx,
            output_file='trace_extra.bin'
        )

        assert result.returncode == 0

        traces = runner.load_traces('trace_extra.bin')

        # Should have exactly num_tx traces
        assert len(traces) == num_tx, (
            f"Expected {num_tx} traces, got {len(traces)} (extra transactions?)"
        )

        # Verify tx_ids are sequential without gaps or duplicates
        tx_ids = [t.tx_id for t in traces]
        expected = list(range(num_tx))
        assert tx_ids == expected, (
            f"Transaction sequence mismatch: got {tx_ids[:10]}... expected {expected[:10]}..."
        )

    def test_no_missing_transactions(self):
        """Verify no transactions are lost through the shell."""
        runner = build_for_latency(self.sim_dir, 5)

        num_tx = 200

        result = runner.run(
            test_name='equivalence',
            num_tx=num_tx,
            output_file='trace_missing.bin'
        )

        assert result.returncode == 0

        traces = runner.load_traces('trace_missing.bin')

        # Check no gaps in tx_ids
        for i, trace in enumerate(traces):
            assert trace.tx_id == i, (
                f"Missing transaction: expected tx_id {i}, got {trace.tx_id}"
            )

    def test_shell_transparency(self):
        """Verify shell doesn't modify transaction order."""
        runner = build_for_latency(self.sim_dir, 2)

        result = runner.run(
            test_name='equivalence',
            num_tx=100,
            output_file='trace_order.bin',
            seed=0xCAFEBABE
        )

        assert result.returncode == 0

        traces = runner.load_traces('trace_order.bin')

        # Verify ordering by checking ingress timestamps are increasing
        prev_ingress = -1
        for i, trace in enumerate(traces):
            assert trace.t_ingress > prev_ingress, (
                f"Transaction order violated at trace {i}"
            )
            prev_ingress = trace.t_ingress

    def test_no_data_corruption(self):
        """Verify metadata passes through uncorrupted."""
        runner = build_for_latency(self.sim_dir, 3)

        result = runner.run(
            test_name='equivalence',
            num_tx=100,
            output_file='trace_corrupt.bin',
            seed=self.seed
        )

        assert result.returncode == 0

        traces = runner.load_traces('trace_corrupt.bin')

        # Verify no error flags set (would indicate corruption)
        for i, trace in enumerate(traces):
            assert trace.flags == 0, (
                f"Trace {i} has unexpected flags: {trace.flags:04x}"
            )

    @pytest.mark.parametrize("num_tx", [10, 100, 500])
    def test_equivalence_various_sizes(self, num_tx: int):
        """Verify equivalence for various transaction counts."""
        runner = build_for_latency(self.sim_dir, 2)

        result = runner.run(
            test_name='equivalence',
            num_tx=num_tx,
            output_file=f'trace_size_{num_tx}.bin',
            seed=self.seed
        )

        assert result.returncode == 0

        traces = runner.load_traces(f'trace_size_{num_tx}.bin')
        assert len(traces) == num_tx
