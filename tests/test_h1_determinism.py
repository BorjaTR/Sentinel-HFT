"""Test H1: Determinism Verification.

Verifies that running the same input sequence twice produces
bit-identical trace output.

Requirement:
- Same input + same RNG seed = identical trace byte streams (SHA256 hash match)
"""

import hashlib
import pytest
from pathlib import Path

from conftest import SimulationRunner, build_for_latency


class TestDeterminism:
    """Test deterministic behavior of the sentinel shell."""

    @pytest.fixture(autouse=True)
    def setup(self, sim_dir: Path, deterministic_seed: int):
        self.sim_dir = sim_dir
        self.seed = deterministic_seed

    def _hash_trace_file(self, filepath: Path) -> str:
        """Compute SHA256 hash of trace file."""
        with open(filepath, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()

    def test_determinism_basic(self):
        """Verify two runs with same seed produce identical traces."""
        runner = build_for_latency(self.sim_dir, 3)

        trace_file1 = 'trace_det_run1.bin'
        trace_file2 = 'trace_det_run2.bin'

        # Run 1
        result1 = runner.run(
            test_name='determinism',
            num_tx=100,
            output_file=trace_file1,
            seed=self.seed
        )
        assert result1.returncode == 0, f"Run 1 failed: {result1.stdout}"
        hash1 = self._hash_trace_file(self.sim_dir / trace_file1)

        # Run 2 (same seed)
        result2 = runner.run(
            test_name='determinism',
            num_tx=100,
            output_file=trace_file2,
            seed=self.seed
        )
        assert result2.returncode == 0, f"Run 2 failed: {result2.stdout}"
        hash2 = self._hash_trace_file(self.sim_dir / trace_file2)

        # Verify hashes match
        assert hash1 == hash2, (
            f"Trace hashes differ: {hash1} vs {hash2}"
        )

    def test_determinism_different_seeds(self):
        """Verify different seeds produce different traces."""
        runner = build_for_latency(self.sim_dir, 3)

        trace_file1 = 'trace_seed1.bin'
        trace_file2 = 'trace_seed2.bin'

        # Run with seed 1
        result1 = runner.run(
            test_name='determinism',
            num_tx=100,
            output_file=trace_file1,
            seed=0x12345678
        )
        assert result1.returncode == 0
        hash1 = self._hash_trace_file(self.sim_dir / trace_file1)

        # Run with different seed
        result2 = runner.run(
            test_name='determinism',
            num_tx=100,
            output_file=trace_file2,
            seed=0xABCDEF00
        )
        assert result2.returncode == 0
        hash2 = self._hash_trace_file(self.sim_dir / trace_file2)

        # Hashes should differ (different input data)
        assert hash1 != hash2, (
            f"Different seeds should produce different traces"
        )

    @pytest.mark.parametrize("latency", [1, 5, 10])
    def test_determinism_across_latencies(self, latency: int):
        """Verify determinism holds for different core latencies."""
        runner = build_for_latency(self.sim_dir, latency)

        trace_file1 = f'trace_det_lat{latency}_1.bin'
        trace_file2 = f'trace_det_lat{latency}_2.bin'

        result1 = runner.run(
            test_name='determinism',
            num_tx=50,
            output_file=trace_file1,
            seed=self.seed
        )
        assert result1.returncode == 0

        result2 = runner.run(
            test_name='determinism',
            num_tx=50,
            output_file=trace_file2,
            seed=self.seed
        )
        assert result2.returncode == 0

        hash1 = self._hash_trace_file(self.sim_dir / trace_file1)
        hash2 = self._hash_trace_file(self.sim_dir / trace_file2)

        assert hash1 == hash2, (
            f"Non-deterministic behavior at LATENCY={latency}"
        )

    def test_determinism_large_run(self):
        """Verify determinism with larger transaction count."""
        runner = build_for_latency(self.sim_dir, 2)

        trace_file1 = 'trace_large1.bin'
        trace_file2 = 'trace_large2.bin'

        result1 = runner.run(
            test_name='determinism',
            num_tx=1000,
            output_file=trace_file1,
            seed=self.seed
        )
        assert result1.returncode == 0

        result2 = runner.run(
            test_name='determinism',
            num_tx=1000,
            output_file=trace_file2,
            seed=self.seed
        )
        assert result2.returncode == 0

        hash1 = self._hash_trace_file(self.sim_dir / trace_file1)
        hash2 = self._hash_trace_file(self.sim_dir / trace_file2)

        assert hash1 == hash2

    def test_trace_record_consistency(self):
        """Verify trace records are byte-for-byte identical across runs."""
        runner = build_for_latency(self.sim_dir, 4)

        result1 = runner.run(
            test_name='determinism',
            num_tx=50,
            output_file='trace_rec1.bin',
            seed=self.seed
        )
        assert result1.returncode == 0

        result2 = runner.run(
            test_name='determinism',
            num_tx=50,
            output_file='trace_rec2.bin',
            seed=self.seed
        )
        assert result2.returncode == 0

        traces1 = runner.load_traces('trace_rec1.bin')
        traces2 = runner.load_traces('trace_rec2.bin')

        assert len(traces1) == len(traces2), "Trace count mismatch"

        for i, (t1, t2) in enumerate(zip(traces1, traces2)):
            assert t1.tx_id == t2.tx_id, f"Trace {i}: tx_id mismatch"
            assert t1.t_ingress == t2.t_ingress, f"Trace {i}: t_ingress mismatch"
            assert t1.t_egress == t2.t_egress, f"Trace {i}: t_egress mismatch"
            assert t1.flags == t2.flags, f"Trace {i}: flags mismatch"
            assert t1.opcode == t2.opcode, f"Trace {i}: opcode mismatch"
            assert t1.meta == t2.meta, f"Trace {i}: meta mismatch"
