"""Pytest fixtures and configuration for H1 tests."""

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import List, Optional
import random

import pytest

# Add host module to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'host'))

from trace_decode import TraceRecord, decode_trace_file
from metrics import compute_metrics, LatencyMetrics


# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
SIM_DIR = PROJECT_ROOT / 'sim'
RTL_DIR = PROJECT_ROOT / 'rtl'


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return project root path."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def sim_dir() -> Path:
    """Return simulation directory path."""
    return SIM_DIR


class SimulationRunner:
    """Helper class to build and run RTL simulations."""

    def __init__(self, sim_dir: Path, latency: int = 1):
        self.sim_dir = sim_dir
        self.latency = latency
        self.exe_path: Optional[Path] = None
        self._built = False

    def build(self, force: bool = False) -> bool:
        """Build the simulation executable for the configured latency."""
        obj_dir = self.sim_dir / 'obj_dir'
        self.exe_path = obj_dir / 'Vtb_sentinel_shell'

        # Check if rebuild needed
        if not force and self._built and self.exe_path.exists():
            return True

        # Clean and rebuild
        if obj_dir.exists():
            shutil.rmtree(obj_dir)

        result = subprocess.run(
            ['make', f'CORE_LATENCY={self.latency}', 'all'],
            cwd=self.sim_dir,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print(f"Build failed:\n{result.stderr}")
            return False

        self._built = True
        return self.exe_path.exists()

    def run(self,
            test_name: str,
            num_tx: int = 100,
            output_file: str = 'trace_output.bin',
            seed: Optional[int] = None,
            bp_cycles: int = 10,
            extra_args: Optional[List[str]] = None) -> subprocess.CompletedProcess:
        """Run simulation with specified parameters."""
        if not self.exe_path or not self.exe_path.exists():
            raise RuntimeError("Simulation not built. Call build() first.")

        args = [
            str(self.exe_path),
            '--test', test_name,
            '--num-tx', str(num_tx),
            '--output', output_file,
        ]

        if seed is not None:
            args.extend(['--seed', str(seed)])

        if bp_cycles != 10:
            args.extend(['--bp-cycles', str(bp_cycles)])

        if extra_args:
            args.extend(extra_args)

        return subprocess.run(
            args,
            cwd=self.sim_dir,
            capture_output=True,
            text=True
        )

    def load_traces(self, trace_file: str = 'trace_output.bin') -> List[TraceRecord]:
        """Load trace records from binary file."""
        trace_path = self.sim_dir / trace_file
        if not trace_path.exists():
            return []

        with open(trace_path, 'rb') as f:
            return list(decode_trace_file(f))


@pytest.fixture
def sim_runner(sim_dir: Path) -> SimulationRunner:
    """Create a simulation runner with default latency."""
    runner = SimulationRunner(sim_dir, latency=1)
    return runner


@pytest.fixture
def deterministic_seed() -> int:
    """Fixed seed for reproducible tests."""
    return 0xDEADBEEF


@pytest.fixture
def temp_trace_file(tmp_path: Path) -> Path:
    """Temporary file for trace output."""
    return tmp_path / 'traces.bin'


def build_for_latency(sim_dir: Path, latency: int) -> SimulationRunner:
    """Build simulation for specific latency."""
    runner = SimulationRunner(sim_dir, latency=latency)
    assert runner.build(), f"Failed to build for LATENCY={latency}"
    return runner
