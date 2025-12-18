#!/usr/bin/env python3
"""
Sentinel-HFT Feature Verification Script

Run: python scripts/test_all.py
Pass: All checks green, exit 0
Fail: Any check red, exit 1
"""

import subprocess
import sys
import tempfile
import json
import shutil
from pathlib import Path

# Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.temp_dir = None

    def setup(self):
        """Create temp directory for test artifacts."""
        self.temp_dir = Path(tempfile.mkdtemp(prefix="sentinel_test_"))
        print(f"\n{BOLD}Test artifacts: {self.temp_dir}{RESET}\n")
        return self.temp_dir

    def cleanup(self):
        """Remove temp directory."""
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def run(self, name: str, cmd: list, check_output: callable = None) -> bool:
        """Run a test command."""
        print(f"  {name}... ", end="", flush=True)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            # Check custom validation if provided
            if check_output:
                success, message = check_output(result)
            else:
                success = result.returncode == 0
                message = result.stderr if not success else ""

            if success:
                print(f"{GREEN}PASS{RESET}")
                self.passed += 1
                return True
            else:
                print(f"{RED}FAIL{RESET}")
                if message:
                    print(f"      {message[:100]}")
                self.failed += 1
                return False

        except subprocess.TimeoutExpired:
            print(f"{RED}TIMEOUT{RESET}")
            self.failed += 1
            return False
        except Exception as e:
            print(f"{RED}ERROR: {e}{RESET}")
            self.failed += 1
            return False

    def run_expect_fail(self, name: str, cmd: list) -> bool:
        """Run a test that should fail (exit code != 0)."""
        print(f"  {name}... ", end="", flush=True)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                print(f"{GREEN}PASS (correctly failed){RESET}")
                self.passed += 1
                return True
            else:
                print(f"{RED}FAIL (should have failed){RESET}")
                self.failed += 1
                return False
        except Exception as e:
            print(f"{RED}ERROR: {e}{RESET}")
            self.failed += 1
            return False

    def section(self, name: str):
        """Print section header."""
        print(f"\n{BOLD}{'─' * 50}{RESET}")
        print(f"{BOLD}{name}{RESET}")
        print(f"{BOLD}{'─' * 50}{RESET}")

    def summary(self):
        """Print final summary."""
        total = self.passed + self.failed
        print(f"\n{BOLD}{'═' * 50}{RESET}")
        print(f"{BOLD}SUMMARY{RESET}")
        print(f"{BOLD}{'═' * 50}{RESET}")
        print(f"  Passed:  {GREEN}{self.passed}{RESET}")
        print(f"  Failed:  {RED}{self.failed}{RESET}")
        print(f"  Total:   {total}")

        if self.failed == 0:
            print(f"\n{GREEN}{BOLD}ALL TESTS PASSED{RESET}\n")
            return 0
        else:
            print(f"\n{RED}{BOLD}TESTS FAILED{RESET}\n")
            return 1


def main():
    t = TestRunner()
    temp = t.setup()

    CLI = ["python", "-m", "sentinel_hft.cli.main"]

    # ═══════════════════════════════════════════════════════════════
    # SECTION 1: Basic CLI
    # ═══════════════════════════════════════════════════════════════
    t.section("1. Basic CLI")

    t.run("CLI runs", CLI + ["--help"])

    t.run("Version command", CLI + ["version"],
          lambda r: (r.returncode == 0 and "Sentinel-HFT" in r.stdout, ""))

    # ═══════════════════════════════════════════════════════════════
    # SECTION 2: Demo Data Generation
    # ═══════════════════════════════════════════════════════════════
    t.section("2. Demo Data Generation")

    demo_dir = temp / "demo"
    t.run("Generate demo data", CLI + ["demo-setup", "-o", str(demo_dir)])

    # Verify files were created
    baseline = demo_dir / "traces" / "baseline.bin"
    incident = demo_dir / "traces" / "incident.bin"

    t.run("Baseline trace exists", ["test", "-f", str(baseline)])
    t.run("Incident trace exists", ["test", "-f", str(incident)])
    t.run("Baseline size > 1MB", ["test", "-s", str(baseline)],
          lambda r: (baseline.stat().st_size > 1_000_000, f"Size: {baseline.stat().st_size}"))

    # ═══════════════════════════════════════════════════════════════
    # SECTION 3: Trace Analysis
    # ═══════════════════════════════════════════════════════════════
    t.section("3. Trace Analysis")

    baseline_report = temp / "baseline.json"
    incident_report = temp / "incident.json"

    t.run("Analyze baseline", CLI + ["analyze", str(baseline), "-o", str(baseline_report), "-q"])
    t.run("Analyze incident", CLI + ["analyze", str(incident), "-o", str(incident_report), "-q"])

    # Verify report contents
    def check_baseline_p99(r):
        try:
            with open(baseline_report) as f:
                data = json.load(f)
            p99 = data.get("latency", {}).get("p99_cycles", 0)
            # Baseline should be around 85-95ns
            return (80 < p99 < 100, f"P99={p99}")
        except Exception as e:
            return (False, str(e))

    t.run("Baseline P99 in expected range", ["true"], check_baseline_p99)

    def check_incident_p99(r):
        try:
            with open(incident_report) as f:
                data = json.load(f)
            p99 = data.get("latency", {}).get("p99_cycles", 0)
            # Incident should be around 130-160ns
            return (120 < p99 < 170, f"P99={p99}")
        except Exception as e:
            return (False, str(e))

    t.run("Incident P99 shows regression", ["true"], check_incident_p99)

    # Output formats
    t.run("JSON output format", CLI + ["analyze", str(baseline), "-f", "json", "-q"])
    t.run("Table output format", CLI + ["analyze", str(baseline), "-f", "table", "-q"])

    # ═══════════════════════════════════════════════════════════════
    # SECTION 4: Regression Detection
    # ═══════════════════════════════════════════════════════════════
    t.section("4. Regression Detection")

    # Should detect regression (exit code 1)
    t.run_expect_fail("Detects regression (incident vs baseline)",
                      CLI + ["regression", str(incident_report), str(baseline_report)])

    # Same file should pass (exit code 0)
    t.run("No regression (baseline vs baseline)",
          CLI + ["regression", str(baseline_report), str(baseline_report)])

    # Custom threshold that allows the regression
    t.run("Custom threshold (100% allowed)",
          CLI + ["regression", str(incident_report), str(baseline_report),
                 "--max-p99-regression", "100"])

    # ═══════════════════════════════════════════════════════════════
    # SECTION 5: Pattern Detection
    # ═══════════════════════════════════════════════════════════════
    t.section("5. Pattern Detection")

    def check_pattern_detected(r):
        # Should detect FIFO_BACKPRESSURE with reasonable confidence
        output = r.stdout + r.stderr
        has_pattern = "FIFO_BACKPRESSURE" in output or "backpressure" in output.lower()
        return (has_pattern, "Pattern not detected")

    t.run("Detects FIFO_BACKPRESSURE pattern",
          CLI + ["prescribe", str(incident)],
          check_pattern_detected)

    # ═══════════════════════════════════════════════════════════════
    # SECTION 6: Fix Generation
    # ═══════════════════════════════════════════════════════════════
    t.section("6. Fix Generation")

    fix_dir = temp / "fix"
    t.run("Generate fix pack",
          CLI + ["prescribe", str(incident), "--export", str(fix_dir)])

    # Verify fix files
    t.run("RTL file generated", ["test", "-f", str(fix_dir / "elastic_buffer.sv")])
    t.run("Testbench generated", ["test", "-f", str(fix_dir / "elastic_buffer_tb.sv")])
    t.run("Integration guide generated", ["test", "-f", str(fix_dir / "INTEGRATION_GUIDE.md")])
    t.run("Summary JSON generated", ["test", "-f", str(fix_dir / "fixpack_summary.json")])

    # Verify fix summary contents
    def check_fix_summary(r):
        try:
            with open(fix_dir / "fixpack_summary.json") as f:
                data = json.load(f)
            has_pattern = data.get("pattern") == "FIFO_BACKPRESSURE"
            has_confidence = data.get("confidence", 0) > 0.5
            return (has_pattern and has_confidence, f"Pattern: {data.get('pattern')}")
        except Exception as e:
            return (False, str(e))

    t.run("Fix summary has correct pattern", ["true"], check_fix_summary)

    # ═══════════════════════════════════════════════════════════════
    # SECTION 7: Fix Verification
    # ═══════════════════════════════════════════════════════════════
    t.section("7. Fix Verification")

    t.run("Verify fix pack", CLI + ["verify", str(fix_dir)])
    t.run("Verify with trace", CLI + ["verify", str(fix_dir), "--trace", str(incident)])

    # ═══════════════════════════════════════════════════════════════
    # SECTION 8: Bisect
    # ═══════════════════════════════════════════════════════════════
    t.section("8. Trace Bisect")

    # Create timeline directory with multiple traces
    timeline_dir = demo_dir / "traces"

    def check_bisect_finds_regression(r):
        output = r.stdout + r.stderr
        # Should identify the regression point
        found_regression = "regression" in output.lower() or "first bad" in output.lower()
        return (found_regression, "Bisect didn't find regression point")

    t.run("Bisect finds regression point",
          CLI + ["bisect", str(timeline_dir)],
          check_bisect_finds_regression)

    # ═══════════════════════════════════════════════════════════════
    # SECTION 9: Benchmark History
    # ═══════════════════════════════════════════════════════════════
    t.section("9. Benchmark History")

    t.run("Record baseline benchmark",
          CLI + ["benchmark", "record", str(baseline), "--name", "test-baseline"])

    t.run("Record incident benchmark",
          CLI + ["benchmark", "record", str(incident), "--tag", "incident"])

    t.run("View benchmark history", CLI + ["benchmark", "history"])

    t.run("Compare benchmarks",
          CLI + ["benchmark", "compare", "test-baseline", str(incident)])

    # ═══════════════════════════════════════════════════════════════
    # SECTION 10: End-to-End Demo
    # ═══════════════════════════════════════════════════════════════
    t.section("10. End-to-End Demo")

    t.run("Non-interactive demo completes",
          CLI + ["demo-e2e", "--non-interactive", "-o", str(temp / "e2e_demo")])

    # ═══════════════════════════════════════════════════════════════
    # SECTION 11: Edge Cases
    # ═══════════════════════════════════════════════════════════════
    t.section("11. Edge Cases")

    # Invalid file
    t.run_expect_fail("Rejects invalid trace file",
                      CLI + ["analyze", "/nonexistent/file.bin"])

    # Empty arguments
    t.run("Handles missing arguments gracefully",
          CLI + ["analyze"],
          lambda r: (r.returncode != 0, "Should fail without args"))

    # ═══════════════════════════════════════════════════════════════
    # CLEANUP & SUMMARY
    # ═══════════════════════════════════════════════════════════════

    # Optional: keep artifacts on failure for debugging
    if t.failed == 0:
        t.cleanup()
        print(f"(Cleaned up {temp})")
    else:
        print(f"\n{YELLOW}Artifacts preserved for debugging: {temp}{RESET}")

    return t.summary()


if __name__ == "__main__":
    sys.exit(main())
