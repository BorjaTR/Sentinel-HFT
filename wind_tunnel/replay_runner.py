#!/usr/bin/env python3
"""Replay runner for Sentinel-HFT Wind Tunnel.

Orchestrates the complete replay workflow:
1. Load and convert input data to stimulus format
2. Build/configure Verilator simulation
3. Run simulation with stimulus
4. Collect and process traces
5. Compute metrics
6. Generate reports

Usage:
    from replay_runner import ReplayRunner

    runner = ReplayRunner(sim_dir=Path("sim"))
    result = runner.run(
        input_file=Path("market_data.csv"),
        output_dir=Path("results"),
        core_latency=3,
    )
    print(result.metrics)
"""

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'host'))

from trace_decode import decode_trace_file, TraceRecord
from metrics import MetricsEngine, FullMetrics
from report import ReportGenerator

from .input_formats import load_input, write_stimulus_binary, InputTransaction
from .trace_pipeline import TracePipeline, ValidationResult


@dataclass
class ReplayConfig:
    """Configuration for replay run."""
    # Simulation parameters
    core_latency: int = 1
    clock_period_ns: float = 10.0

    # Test parameters
    test_mode: str = "replay"

    # Analysis parameters
    anomaly_zscore: float = 3.0

    # Build options
    force_rebuild: bool = False

    # Output options
    json_stats: bool = True


@dataclass
class ReplayResult:
    """Result of a replay run."""
    success: bool
    metrics: Optional[FullMetrics] = None
    validation: Optional[ValidationResult] = None

    # Simulation output
    sim_returncode: int = 0
    sim_stdout: str = ""
    sim_stderr: str = ""

    # Paths
    trace_file: Optional[Path] = None
    stimulus_file: Optional[Path] = None

    # Counts
    input_transactions: int = 0
    output_traces: int = 0

    # Error
    error_message: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'success': self.success,
            'metrics': self.metrics.to_dict() if self.metrics else None,
            'validation': self.validation.to_dict() if self.validation else None,
            'sim_returncode': self.sim_returncode,
            'input_transactions': self.input_transactions,
            'output_traces': self.output_traces,
            'error_message': self.error_message,
        }


class ReplayRunner:
    """Orchestrate replay simulations."""

    def __init__(
        self,
        sim_dir: Path,
        project_root: Optional[Path] = None,
    ):
        """Initialize replay runner.

        Args:
            sim_dir: Path to simulation directory (contains Makefile)
            project_root: Project root path (auto-detected if None)
        """
        self.sim_dir = Path(sim_dir)

        if project_root is None:
            # Assume sim_dir is inside project root
            self.project_root = self.sim_dir.parent
        else:
            self.project_root = Path(project_root)

        self.obj_dir = self.sim_dir / 'obj_dir'
        self.exe_path = self.obj_dir / 'Vtb_sentinel_shell'

        # State
        self._built_latency: Optional[int] = None

    def build(self, latency: int, force: bool = False) -> bool:
        """Build simulation for specified latency.

        Args:
            latency: Core latency in cycles (CORE_LATENCY parameter)
            force: Force rebuild even if already built

        Returns:
            True if build succeeded
        """
        # Check if rebuild needed
        if not force and self._built_latency == latency and self.exe_path.exists():
            return True

        # Clean if rebuilding
        if self.obj_dir.exists():
            shutil.rmtree(self.obj_dir)

        # Build
        result = subprocess.run(
            ['make', f'CORE_LATENCY={latency}', 'all'],
            cwd=self.sim_dir,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"Build failed: {result.stderr}")
            return False

        self._built_latency = latency
        return self.exe_path.exists()

    def run(
        self,
        input_file: Path,
        output_dir: Path,
        config: Optional[ReplayConfig] = None,
    ) -> ReplayResult:
        """Run complete replay workflow.

        Args:
            input_file: Path to input transaction file (CSV or binary)
            output_dir: Directory for output files
            config: Replay configuration

        Returns:
            ReplayResult with metrics and status
        """
        if config is None:
            config = ReplayConfig()

        result = ReplayResult(success=False)

        # Ensure output directory exists
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Load and convert input data
        try:
            transactions = load_input(Path(input_file))
            result.input_transactions = len(transactions)

            if not transactions:
                result.error_message = "No transactions in input file"
                return result

        except Exception as e:
            result.error_message = f"Failed to load input: {e}"
            return result

        # Convert to binary stimulus
        stimulus_path = output_dir / 'stimulus.bin'
        try:
            write_stimulus_binary(transactions, stimulus_path)
            result.stimulus_file = stimulus_path
        except Exception as e:
            result.error_message = f"Failed to write stimulus: {e}"
            return result

        # Step 2: Build simulation
        if not self.build(config.core_latency, force=config.force_rebuild):
            result.error_message = "Failed to build simulation"
            return result

        # Step 3: Run simulation
        trace_path = output_dir / 'traces.bin'

        args = [
            str(self.exe_path),
            '--test', config.test_mode,
            '--stimulus', str(stimulus_path),
            '--output', str(trace_path),
            '--num-tx', str(len(transactions)),
        ]

        if config.json_stats:
            args.append('--json')
            args.extend(['--clock-ns', str(config.clock_period_ns)])

        try:
            sim_result = subprocess.run(
                args,
                cwd=self.sim_dir,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            result.sim_returncode = sim_result.returncode
            result.sim_stdout = sim_result.stdout
            result.sim_stderr = sim_result.stderr
            result.trace_file = trace_path

            if sim_result.returncode != 0:
                result.error_message = f"Simulation failed: {sim_result.stderr}"
                return result

        except subprocess.TimeoutExpired:
            result.error_message = "Simulation timed out"
            return result
        except Exception as e:
            result.error_message = f"Simulation error: {e}"
            return result

        # Step 4: Process traces
        try:
            if trace_path.exists():
                with open(trace_path, 'rb') as f:
                    traces = list(decode_trace_file(f))
                result.output_traces = len(traces)
            else:
                traces = []
        except Exception as e:
            result.error_message = f"Failed to decode traces: {e}"
            return result

        # Step 5: Validate traces
        pipeline = TracePipeline(clock_period_ns=config.clock_period_ns)
        try:
            result.validation = pipeline.validate(trace_path)
        except Exception as e:
            # Validation is optional, continue even if it fails
            pass

        # Step 6: Compute metrics
        engine = MetricsEngine(
            clock_period_ns=config.clock_period_ns,
            anomaly_zscore=config.anomaly_zscore,
        )

        try:
            # Convert trace records to format expected by MetricsEngine
            trace_dicts = []
            for t in traces:
                trace_dicts.append({
                    'tx_id': t.tx_id,
                    't_ingress': t.t_ingress,
                    't_egress': t.t_egress,
                    'latency_cycles': t.latency_cycles,
                    'flags': t.flags,
                })

            result.metrics = engine.compute_full(trace_dicts)
            result.metrics.trace_file = str(trace_path)
            result.metrics.trace_count = len(traces)

            # Add validation errors if present
            if result.validation:
                result.metrics.validation_errors = result.validation.errors
                result.metrics.trace_drops = result.validation.total_traces - len(traces)

        except Exception as e:
            result.error_message = f"Failed to compute metrics: {e}"
            return result

        result.success = True
        return result

    def run_with_reports(
        self,
        input_file: Path,
        output_dir: Path,
        config: Optional[ReplayConfig] = None,
        json_report: bool = True,
        markdown_report: bool = True,
        console_report: bool = True,
    ) -> ReplayResult:
        """Run replay and generate reports.

        Args:
            input_file: Path to input transaction file
            output_dir: Directory for output files and reports
            config: Replay configuration
            json_report: Generate JSON report
            markdown_report: Generate Markdown report
            console_report: Print to console

        Returns:
            ReplayResult with metrics
        """
        result = self.run(input_file, output_dir, config)

        if result.success and result.metrics:
            gen = ReportGenerator(title=f"Replay: {input_file.name}")

            if json_report:
                gen.to_json(result.metrics, output_dir / 'report.json')

            if markdown_report:
                gen.to_markdown(result.metrics, output_dir / 'report.md')

            if console_report:
                gen.to_stdout(result.metrics)

        return result

    def quick_run(
        self,
        input_file: Path,
        latency: int = 1,
        clock_ns: float = 10.0,
    ) -> Optional[FullMetrics]:
        """Quick replay for testing - uses temp directory.

        Args:
            input_file: Path to input file
            latency: Core latency
            clock_ns: Clock period in ns

        Returns:
            FullMetrics or None if failed
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ReplayConfig(
                core_latency=latency,
                clock_period_ns=clock_ns,
            )
            result = self.run(input_file, Path(tmpdir), config)

            if result.success:
                return result.metrics
            else:
                print(f"Quick run failed: {result.error_message}")
                return None


def run_replay(
    input_file: Path,
    output_dir: Path,
    sim_dir: Optional[Path] = None,
    latency: int = 1,
    clock_ns: float = 10.0,
) -> ReplayResult:
    """Convenience function for single replay.

    Args:
        input_file: Path to input transaction file
        output_dir: Output directory
        sim_dir: Simulation directory (auto-detected if None)
        latency: Core latency
        clock_ns: Clock period

    Returns:
        ReplayResult
    """
    if sim_dir is None:
        # Auto-detect from current file location
        sim_dir = Path(__file__).parent.parent / 'sim'

    runner = ReplayRunner(sim_dir)
    config = ReplayConfig(
        core_latency=latency,
        clock_period_ns=clock_ns,
    )

    return runner.run_with_reports(input_file, output_dir, config)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Run Sentinel-HFT replay')
    parser.add_argument('input', type=Path, help='Input transaction file')
    parser.add_argument('--output', '-o', type=Path, default=Path('replay_output'),
                       help='Output directory')
    parser.add_argument('--latency', '-l', type=int, default=1,
                       help='Core latency in cycles')
    parser.add_argument('--clock-ns', type=float, default=10.0,
                       help='Clock period in nanoseconds')
    parser.add_argument('--sim-dir', type=Path, default=None,
                       help='Simulation directory')

    args = parser.parse_args()

    result = run_replay(
        input_file=args.input,
        output_dir=args.output,
        sim_dir=args.sim_dir,
        latency=args.latency,
        clock_ns=args.clock_ns,
    )

    if result.success:
        print(f"\nReplay completed successfully!")
        print(f"  Input transactions: {result.input_transactions}")
        print(f"  Output traces: {result.output_traces}")
        print(f"  Reports saved to: {args.output}")
    else:
        print(f"\nReplay failed: {result.error_message}")
        sys.exit(1)
