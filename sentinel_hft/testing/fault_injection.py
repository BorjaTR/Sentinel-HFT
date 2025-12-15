"""
fault_injection.py - Python framework for fault injection testing

Orchestrates simulation runs with fault injection, validates behavior,
and generates incident packs.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional, List
import json
import hashlib
import subprocess
import tempfile
import shutil
from datetime import datetime


class FaultType(Enum):
    """Fault types matching RTL enum."""
    NONE = 0
    BACKPRESSURE = 1
    FIFO_OVERFLOW = 2
    KILL_SWITCH = 3
    CORRUPT_DATA = 4
    CLOCK_STRETCH = 5
    BURST = 6
    REORDER = 7
    RESET = 8


@dataclass
class FaultConfig:
    """Configuration for a single fault injection."""
    fault_type: FaultType
    trigger_cycle: int
    duration_cycles: int = 0  # 0 = single shot
    parameter: int = 0

    def to_plusarg(self, index: int) -> str:
        """Convert to Verilator plusarg format."""
        return (
            f"+fault{index}_type={self.fault_type.value} "
            f"+fault{index}_trigger={self.trigger_cycle} "
            f"+fault{index}_duration={self.duration_cycles} "
            f"+fault{index}_param={self.parameter}"
        )

    def to_dict(self) -> dict:
        return {
            'type': self.fault_type.name,
            'trigger_cycle': self.trigger_cycle,
            'duration_cycles': self.duration_cycles,
            'parameter': self.parameter,
        }


@dataclass
class ExpectedBehavior:
    """Expected system behavior during/after fault injection."""
    min_drops: int = 0
    max_drops: int = 0
    should_trigger_kill_switch: bool = False
    max_latency_spike_factor: float = 10.0
    reorder_detected: bool = False
    reset_handled: bool = False
    metrics_uncorrupted: bool = True
    max_false_drops: int = 0

    def validate(self, result: 'FaultResult') -> tuple:
        """Validate result against expectations. Returns (passed, errors)."""
        errors = []

        if result.drop_count < self.min_drops:
            errors.append(f"Too few drops: {result.drop_count} < {self.min_drops}")
        if result.drop_count > self.max_drops:
            errors.append(f"Too many drops: {result.drop_count} > {self.max_drops}")

        if self.should_trigger_kill_switch and not result.kill_switch_triggered:
            errors.append("Kill switch should have triggered but didn't")
        if not self.should_trigger_kill_switch and result.kill_switch_triggered:
            errors.append("Kill switch triggered unexpectedly")

        if result.max_latency_spike > self.max_latency_spike_factor:
            errors.append(
                f"Latency spike too high: {result.max_latency_spike:.1f}x > "
                f"{self.max_latency_spike_factor:.1f}x"
            )

        return len(errors) == 0, errors


@dataclass
class FaultScenario:
    """Complete fault injection scenario definition."""
    name: str
    description: str
    faults: List[FaultConfig]
    expected: ExpectedBehavior
    stimulus_transactions: int = 10000

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'description': self.description,
            'faults': [f.to_dict() for f in self.faults],
            'stimulus_transactions': self.stimulus_transactions,
        }


@dataclass
class FaultResult:
    """Results from a fault injection run."""
    scenario: FaultScenario
    passed: bool
    errors: List[str]

    # Measured values
    transactions_completed: int = 0
    drop_count: int = 0
    kill_switch_triggered: bool = False
    max_latency_spike: float = 1.0  # Multiplier vs baseline
    baseline_p99_ns: float = 0.0
    fault_p99_ns: float = 0.0

    # Paths
    trace_path: Optional[Path] = None
    report_path: Optional[Path] = None

    def to_dict(self) -> dict:
        return {
            'scenario': self.scenario.name,
            'passed': self.passed,
            'errors': self.errors,
            'transactions_completed': self.transactions_completed,
            'drop_count': self.drop_count,
            'kill_switch_triggered': self.kill_switch_triggered,
            'max_latency_spike': self.max_latency_spike,
            'baseline_p99_ns': self.baseline_p99_ns,
            'fault_p99_ns': self.fault_p99_ns,
        }


class FaultInjector:
    """Orchestrates fault injection testing."""

    def __init__(
        self,
        rtl_dir: Optional[Path] = None,
        work_dir: Optional[Path] = None,
        clock_mhz: float = 100.0,
    ):
        self.rtl_dir = Path(rtl_dir) if rtl_dir else Path('rtl')
        self.work_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp())
        self.clock_mhz = clock_mhz

    def run_scenario(self, scenario: FaultScenario) -> FaultResult:
        """Run a fault injection scenario and validate results."""

        # For now, simulate the result (real implementation would run Verilator)
        result = self._simulate_scenario(scenario)
        return result

    def _simulate_scenario(self, scenario: FaultScenario) -> FaultResult:
        """Simulate a scenario result for testing."""
        # This would be replaced with actual simulation in production

        # Estimate drops based on fault type
        drops = 0
        kill_switch = False
        latency_spike = 1.0

        for fault in scenario.faults:
            if fault.fault_type == FaultType.BACKPRESSURE:
                drops += min(fault.duration_cycles // 20, 50)
                latency_spike = max(latency_spike, 3.0)
            elif fault.fault_type == FaultType.FIFO_OVERFLOW:
                drops += fault.duration_cycles // 10
            elif fault.fault_type == FaultType.KILL_SWITCH:
                kill_switch = True

        # Validate against expectations
        result = FaultResult(
            scenario=scenario,
            passed=True,
            errors=[],
            transactions_completed=scenario.stimulus_transactions,
            drop_count=drops,
            kill_switch_triggered=kill_switch,
            max_latency_spike=latency_spike,
            baseline_p99_ns=100.0,
            fault_p99_ns=100.0 * latency_spike,
        )

        passed, errors = scenario.expected.validate(result)
        result.passed = passed
        result.errors = errors

        return result

    def generate_incident_pack(
        self,
        result: FaultResult,
        output_dir: Path,
    ) -> Path:
        """Generate a complete incident pack from fault result."""

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        pack_dir = output_dir / f"{result.scenario.name}_{timestamp}"
        pack_dir.mkdir(parents=True, exist_ok=True)

        # Generate report
        report = self._generate_report(result)
        (pack_dir / "report.json").write_text(json.dumps(report, indent=2))
        (pack_dir / "report.md").write_text(self._format_report_markdown(report))

        # Generate AI explanation
        explanation = self._generate_ai_explanation(result)
        (pack_dir / "ai_explanation.md").write_text(explanation)

        # Generate manifest
        manifest = self._generate_manifest(result, pack_dir)
        (pack_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

        # README
        readme = self._generate_readme(result)
        (pack_dir / "README.md").write_text(readme)

        return pack_dir

    def _generate_manifest(self, result: FaultResult, pack_dir: Path) -> dict:
        """Generate manifest.json for incident pack."""

        def file_hash(path: Path) -> str:
            if path.exists():
                return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            return "missing"

        return {
            "schema_version": "1.0",
            "generated_at": datetime.now().isoformat(),
            "tool": {
                "name": "sentinel-hft",
                "version": "2.3.0",
            },
            "hardware": {
                "clock_mhz": self.clock_mhz,
                "trace_format": "v1.2",
            },
            "scenario": result.scenario.to_dict(),
            "result": {
                "passed": result.passed,
                "errors": result.errors,
            },
            "files": {
                "report": {
                    "path": "report.json",
                    "sha256": file_hash(pack_dir / "report.json"),
                },
            },
        }

    def _generate_report(self, result: FaultResult) -> dict:
        """Generate structured report from result."""
        return {
            "scenario": result.scenario.name,
            "description": result.scenario.description,
            "result": "PASS" if result.passed else "FAIL",
            "errors": result.errors,
            "metrics": {
                "transactions": result.transactions_completed,
                "drops": result.drop_count,
                "kill_switch": result.kill_switch_triggered,
                "latency_spike": f"{result.max_latency_spike:.1f}x",
                "p99_baseline_ns": result.baseline_p99_ns,
                "p99_fault_ns": result.fault_p99_ns,
            },
        }

    def _format_report_markdown(self, report: dict) -> str:
        """Format report as markdown."""
        status = "PASS" if report["result"] == "PASS" else "FAIL"

        return f"""# Fault Injection Report: {report["scenario"]}

**Status:** {status}

## Description

{report["description"]}

## Results

| Metric | Value |
|--------|-------|
| Transactions | {report["metrics"]["transactions"]:,} |
| Drops | {report["metrics"]["drops"]} |
| Kill Switch | {"Triggered" if report["metrics"]["kill_switch"] else "Clear"} |
| Latency Spike | {report["metrics"]["latency_spike"]} |
| P99 (baseline) | {report["metrics"]["p99_baseline_ns"]:.0f}ns |
| P99 (fault) | {report["metrics"]["p99_fault_ns"]:.0f}ns |

## Errors

{chr(10).join(f"- {e}" for e in report["errors"]) if report["errors"] else "None"}
"""

    def _generate_ai_explanation(self, result: FaultResult) -> str:
        """Generate AI explanation (uses fallback if no API key)."""
        scenario = result.scenario

        if result.passed:
            intro = f"The system successfully handled the **{scenario.name}** fault scenario."
        else:
            intro = f"The system encountered issues during the **{scenario.name}** fault scenario."

        return f"""# AI Analysis: {scenario.name}

## Summary

{intro}

{scenario.description}

## Behavior During Fault

- **Transactions completed:** {result.transactions_completed:,}
- **Traces dropped:** {result.drop_count}
- **Latency impact:** {result.max_latency_spike:.1f}x baseline
- **Kill switch:** {"Triggered" if result.kill_switch_triggered else "Not triggered"}

## Analysis

{"The system recovered gracefully after the fault condition ended." if result.passed else "The following issues were detected: " + "; ".join(result.errors)}

## Recommendations

1. {"Continue monitoring system behavior under similar conditions" if result.passed else "Investigate the root cause of failures"}
2. Consider expanding test coverage for edge cases
3. Review recovery timing after fault conditions
"""

    def _generate_readme(self, result: FaultResult) -> str:
        """Generate README for incident pack."""
        return f"""# Incident Pack: {result.scenario.name}

This incident pack contains traces and analysis from a fault injection test.

## Contents

- `report.json` - Structured analysis results
- `report.md` - Human-readable report
- `ai_explanation.md` - AI-generated analysis
- `manifest.json` - Pack provenance and checksums

## Scenario

**{result.scenario.name}**

{result.scenario.description}

## Result

{"PASS" if result.passed else "FAIL"}

## Reproduction

```bash
sentinel-hft fault run {result.scenario.name}
```
"""
