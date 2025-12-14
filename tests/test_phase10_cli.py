"""
Tests for Phase 10: CLI.

CRITICAL TESTS:
1. test_version - Version command works
2. test_regression_pass - Regression pass/fail logic
3. test_demo_creates_files - Demo creates expected files
"""

import pytest
import json
import struct
from pathlib import Path

# Skip all tests if typer not available
pytest.importorskip("typer")

from typer.testing import CliRunner
from sentinel_hft.cli.main import app
from sentinel_hft.formats.file_header import FileHeader


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_trace_file(tmp_path):
    """Create a sample trace file for testing."""
    trace_file = tmp_path / "test_traces.bin"

    # Write header
    header = FileHeader(version=1, record_size=48, clock_mhz=100)

    with open(trace_file, 'wb') as f:
        f.write(header.encode())

        # Write 100 traces
        for i in range(100):
            record = struct.pack(
                '<BBHIQQQHH',
                1,  # version
                1,  # record_type
                0,  # core_id
                i,  # seq_no
                i * 100,  # t_ingress
                i * 100 + 10 + (i % 5),  # t_egress
                0,  # data
                0,  # flags
                i,  # tx_id
            )
            record += b'\x00' * (48 - len(record))
            f.write(record)

    return trace_file


class TestVersion:
    """Test version command."""

    def test_version(self, runner):
        """Version command shows version."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "2.2.0" in result.stdout


class TestConfig:
    """Test config commands."""

    def test_config_init(self, runner):
        """Config init generates valid YAML."""
        result = runner.invoke(app, ["config", "init"])
        assert result.exit_code == 0
        assert "clock:" in result.stdout
        assert "frequency_mhz:" in result.stdout

    def test_config_validate_valid(self, runner, tmp_path):
        """Config validate passes for valid config."""
        config = tmp_path / "valid.yml"
        config.write_text("version: 1\nclock:\n  frequency_mhz: 100")

        result = runner.invoke(app, ["config", "validate", str(config)])
        assert result.exit_code == 0
        assert "Valid" in result.stdout

    def test_config_validate_missing_file(self, runner):
        """Config validate fails for missing file."""
        result = runner.invoke(app, ["config", "validate", "/nonexistent/file.yml"])
        assert result.exit_code == 1


class TestAnalyze:
    """Test analyze command."""

    def test_analyze_json_output(self, runner, sample_trace_file, tmp_path):
        """Analyze produces JSON output."""
        output = tmp_path / "report.json"

        result = runner.invoke(app, [
            "analyze", str(sample_trace_file),
            "-o", str(output),
            "-q"
        ])

        assert result.exit_code == 0
        assert output.exists()

        report = json.loads(output.read_text())
        assert 'latency' in report
        assert report['latency']['count'] == 100

    def test_analyze_table_output(self, runner, sample_trace_file):
        """Analyze produces table output."""
        result = runner.invoke(app, [
            "analyze", str(sample_trace_file),
            "-f", "table",
            "-q"
        ])

        assert result.exit_code == 0
        assert "P99" in result.stdout


class TestRegression:
    """Test regression command."""

    def test_regression_pass(self, runner, tmp_path):
        """
        CRITICAL TEST: Regression pass when within threshold.
        """
        metrics = {"latency": {"p99_cycles": 10}, "drops": {"total_drops": 0}}

        current = tmp_path / "current.json"
        baseline = tmp_path / "baseline.json"
        current.write_text(json.dumps(metrics))
        baseline.write_text(json.dumps(metrics))

        result = runner.invoke(app, ["regression", str(current), str(baseline)])
        assert result.exit_code == 0
        assert "PASSED" in result.stdout

    def test_regression_fail_p99(self, runner, tmp_path):
        """Regression fails when P99 exceeds threshold."""
        current = tmp_path / "current.json"
        baseline = tmp_path / "baseline.json"
        current.write_text(json.dumps({"latency": {"p99_cycles": 100}, "drops": {"total_drops": 0}}))
        baseline.write_text(json.dumps({"latency": {"p99_cycles": 10}, "drops": {"total_drops": 0}}))

        result = runner.invoke(app, ["regression", str(current), str(baseline)])
        assert result.exit_code == 1
        assert "FAILED" in result.stdout

    def test_regression_custom_threshold(self, runner, tmp_path):
        """Regression uses custom threshold."""
        current = tmp_path / "current.json"
        baseline = tmp_path / "baseline.json"
        current.write_text(json.dumps({"latency": {"p99_cycles": 12}, "drops": {"total_drops": 0}}))
        baseline.write_text(json.dumps({"latency": {"p99_cycles": 10}, "drops": {"total_drops": 0}}))

        # 20% regression with 25% threshold - should pass
        result = runner.invoke(app, [
            "regression", str(current), str(baseline),
            "--max-p99-regression", "25"
        ])
        assert result.exit_code == 0

    def test_regression_fail_on_drops(self, runner, tmp_path):
        """Regression fails when drops detected with --fail-on-drops."""
        current = tmp_path / "current.json"
        baseline = tmp_path / "baseline.json"
        current.write_text(json.dumps({"latency": {"p99_cycles": 10}, "drops": {"total_drops": 5}}))
        baseline.write_text(json.dumps({"latency": {"p99_cycles": 10}, "drops": {"total_drops": 0}}))

        result = runner.invoke(app, [
            "regression", str(current), str(baseline),
            "--fail-on-drops"
        ])
        assert result.exit_code == 1
        assert "dropped" in result.stdout.lower()

    def test_regression_output_file(self, runner, tmp_path):
        """Regression writes diff to output file."""
        current = tmp_path / "current.json"
        baseline = tmp_path / "baseline.json"
        output = tmp_path / "diff.json"
        current.write_text(json.dumps({"latency": {"p99_cycles": 10}, "drops": {"total_drops": 0}}))
        baseline.write_text(json.dumps({"latency": {"p99_cycles": 10}, "drops": {"total_drops": 0}}))

        result = runner.invoke(app, [
            "regression", str(current), str(baseline),
            "-o", str(output)
        ])

        assert result.exit_code == 0
        assert output.exists()

        diff = json.loads(output.read_text())
        assert 'p99' in diff
        assert diff['p99']['change_percent'] == 0.0


class TestDemo:
    """Test demo command."""

    def test_demo_creates_files(self, runner, tmp_path):
        """
        CRITICAL TEST: Demo creates expected files.
        """
        result = runner.invoke(app, ["demo", "-o", str(tmp_path)])

        assert result.exit_code == 0
        assert (tmp_path / "demo_traces.bin").exists()
        assert (tmp_path / "demo_report.json").exists()

    def test_demo_report_valid(self, runner, tmp_path):
        """Demo report is valid JSON."""
        runner.invoke(app, ["demo", "-o", str(tmp_path)])

        report = json.loads((tmp_path / "demo_report.json").read_text())

        assert 'latency' in report
        assert report['latency']['count'] == 10000
        assert report['latency']['p99_cycles'] >= 0


class TestLive:
    """Test live command."""

    def test_live_requires_source(self, runner):
        """Live requires --watch or --udp-port."""
        result = runner.invoke(app, ["live"])
        assert result.exit_code == 1
        assert "watch" in result.stdout.lower() or "udp" in result.stdout.lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
