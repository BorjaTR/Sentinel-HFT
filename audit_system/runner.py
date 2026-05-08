"""
Sentinel-HFT audit runner.

Orchestrates the six A-axes for a given period (default: current month).
Reads a pre-registration file, runs the active axes, emits a markdown +
JSON report.

Usage:
    python -m audit_system.runner --period 2026-05
    python -m audit_system.runner                   # current UTC month

Pre-reg path: audit_system/pre_reg/audit_<YYYY_MM>.yml
Report path:  audit_system/reports/audit_<YYYY_MM>.md (+ .json)

Phase 1 implementation: A-Spec (regmap-version + traceability replay),
A-Coverage (clause→test mapping). The other axes return SKIP with TODOs;
they activate as later phases land.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
PRE_REG_DIR = REPO_ROOT / "audit_system" / "pre_reg"
REPORTS_DIR = REPO_ROOT / "audit_system" / "reports"


# -----------------------------------------------------------------------------
# Axes
# -----------------------------------------------------------------------------

def _axis_a_spec(pre_reg: Dict) -> Dict:
    """Hash regmap.yaml + key RTL files; compare to pre-reg if declared."""
    files = pre_reg.get("a_spec", {}).get("files", [])
    if not files:
        # default Phase-1 set (extended 2026-05-08 with v2 composer + new modules)
        files = [
            "fpga/regmap.yaml",
            "rtl/risk_pkg.sv",
            "rtl/risk_gate.sv",
            "rtl/risk_gate_v2.sv",
            "rtl/position_limiter.sv",
            "rtl/rate_limiter.sv",
            "rtl/kill_switch.sv",
            "rtl/fat_finger_band.sv",
            "rtl/symbol_allowlist.sv",
            "rtl/risk_audit_log.sv",
        ]
    hashes: Dict[str, str] = {}
    missing: List[str] = []
    for rel in files:
        p = REPO_ROOT / rel
        if not p.exists():
            missing.append(rel)
            continue
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        hashes[rel] = h
    if missing:
        return {
            "axis": "a_spec",
            "status": "FAIL",
            "summary": f"{len(missing)} declared files missing.",
            "details": {"missing": missing, "hashes": hashes},
        }

    expected = pre_reg.get("a_spec", {}).get("expected_hashes", {})
    if expected:
        diffs = [k for k, v in expected.items() if hashes.get(k) != v]
        if diffs:
            return {
                "axis": "a_spec",
                "status": "WARN",
                "summary": f"{len(diffs)} files diverged from pre-reg expected hashes.",
                "details": {"diffs": diffs, "hashes": hashes},
            }
    return {
        "axis": "a_spec",
        "status": "PASS",
        "summary": f"All {len(hashes)} declared files present.",
        "details": {"hashes": hashes},
    }


def _axis_a_forward(pre_reg: Dict) -> Dict:
    return {
        "axis": "a_forward",
        "status": "SKIP",
        "summary": "A-Forward inactive until Phase 8 (replay harness).",
        "details": {},
    }


def _axis_a_coverage(pre_reg: Dict) -> Dict:
    """Map each rule in pre-reg.rules_enforced to ≥1 test."""
    rules = pre_reg.get("a_coverage", {}).get("rules", [])
    if not rules:
        # Phase-1 default: read from roadmap/pre_reg/phase_01.yml
        try:
            import yaml  # type: ignore
            phase1 = yaml.safe_load((REPO_ROOT / "roadmap" / "pre_reg" / "phase_01.yml").read_text())
            rules = phase1.get("scope_in", {}).get("rules_enforced", [])
        except Exception as e:
            return {
                "axis": "a_coverage",
                "status": "FAIL",
                "summary": f"Could not load Phase-1 rules list: {e}",
                "details": {},
            }
    if not rules:
        return {
            "axis": "a_coverage",
            "status": "FAIL",
            "summary": "No rules declared.",
            "details": {},
        }

    # Crude clause→test mapping: grep test files for the rule name (or
    # substrings). Phase-1 mapping table; refined later.
    rule_to_substrings = {
        "notional_cap_per_order": ["ORDER_SIZE", "max_order_qty"],
        "notional_cap_aggregated_rolling": ["NOTIONAL_LIMIT", "max_notional"],
        "position_cap_aggregated": ["POSITION_LIMIT", "long_cap", "max_long", "max_short"],
        "order_rate_cap": ["RATE_LIMITED", "rate_limit", "rate_max_tokens"],
        "fat_finger_price_band": ["FAT_FINGER", "fat_finger", "ff_band_bps"],
        "symbol_allowlist": ["ALLOWLIST_BLOCK", "allowlist"],
        "kill_switch_state": ["KILL_SWITCH", "kill_active", "kill_armed"],
    }

    test_dir = REPO_ROOT / "tests"
    test_text = ""
    for f in test_dir.rglob("test_*.py"):
        try:
            test_text += f.read_text()
        except Exception:
            pass

    results: Dict[str, Dict] = {}
    failed: List[str] = []
    for r in rules:
        substrings = rule_to_substrings.get(r, [r])
        hits = [s for s in substrings if s in test_text]
        results[r] = {"matched": hits, "ok": bool(hits)}
        if not hits:
            failed.append(r)

    if failed:
        return {
            "axis": "a_coverage",
            "status": "FAIL",
            "summary": f"{len(failed)}/{len(rules)} rules without a matching test.",
            "details": {"per_rule": results, "uncovered": failed},
        }
    return {
        "axis": "a_coverage",
        "status": "PASS",
        "summary": f"All {len(rules)} declared rules have ≥1 test.",
        "details": {"per_rule": results},
    }


def _axis_a_drift(pre_reg: Dict) -> Dict:
    return {
        "axis": "a_drift",
        "status": "SKIP",
        "summary": (
            "A-Drift requires per-period latency/reject distributions. "
            "Activates when the build runs on real hardware (Phase 1 close → 6)."
        ),
        "details": {},
    }


def _axis_a_chain(pre_reg: Dict) -> Dict:
    return {
        "axis": "a_chain",
        "status": "SKIP",
        "summary": (
            "A-Chain inactive until audit chain is logging real decisions on "
            "hardware (Phase 1 close → Phase 5 persistence)."
        ),
        "details": {},
    }


def _axis_a_bias(pre_reg: Dict) -> Dict:
    return {
        "axis": "a_bias",
        "status": "SKIP",
        "summary": (
            "A-Bias inactive until decision corpus is large enough for "
            "Bonferroni-corrected χ² (activates Phase 8 with replay)."
        ),
        "details": {},
    }


AXES: Dict[str, Callable[[Dict], Dict]] = {
    "a_spec": _axis_a_spec,
    "a_forward": _axis_a_forward,
    "a_coverage": _axis_a_coverage,
    "a_drift": _axis_a_drift,
    "a_chain": _axis_a_chain,
    "a_bias": _axis_a_bias,
}


# -----------------------------------------------------------------------------
# Runner
# -----------------------------------------------------------------------------

def _git_commit_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()[:12]
    except Exception:
        return "unknown"


def _load_prereg(period: str) -> Dict:
    p = PRE_REG_DIR / f"audit_{period.replace('-', '_')}.yml"
    if not p.exists():
        # Acceptable in Phase-1 — emit a default.
        return {
            "period": period,
            "axes_active": ["a_spec", "a_coverage"],  # only what's wired
        }
    try:
        import yaml  # type: ignore
        return yaml.safe_load(p.read_text()) or {}
    except Exception as e:
        sys.stderr.write(f"could not parse pre-reg: {e}\n")
        return {"period": period, "axes_active": ["a_spec", "a_coverage"]}


def _verdict(report: Dict) -> str:
    statuses = [a["status"] for a in report["axes"].values() if a["status"] != "SKIP"]
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    if "PASS" in statuses:
        return "PASS"
    return "INCOMPLETE"


def _render(report: Dict) -> str:
    lines = [
        f"# Audit Report — {report['period']}",
        "",
        f"**Commit:** `{report['commit']}`",
        f"**Run at:** {report['ran_at']}",
        f"**Verdict:** **{report['verdict']}**",
        "",
        "| Axis | Status | Summary |",
        "|------|--------|---------|",
    ]
    for name, axis in report["axes"].items():
        lines.append(f"| `{name}` | **{axis['status']}** | {axis['summary']} |")
    lines.append("")

    fails = [a for a in report["axes"].values() if a["status"] == "FAIL"]
    if fails:
        lines.append("## Failures")
        for a in fails:
            lines.append(f"### `{a['axis']}` — {a['summary']}")
            lines.append("```json")
            lines.append(json.dumps(a["details"], indent=2, default=str))
            lines.append("```")
    return "\n".join(lines) + "\n"


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--period",
        type=str,
        default=None,
        help="YYYY-MM, defaults to current UTC month",
    )
    args = ap.parse_args(argv)

    period = args.period or dt.datetime.utcnow().strftime("%Y-%m")
    pre_reg = _load_prereg(period)
    active = pre_reg.get("axes_active", list(AXES.keys()))

    axis_results: Dict[str, Dict] = {}
    for name, fn in AXES.items():
        if name not in active:
            axis_results[name] = {
                "axis": name,
                "status": "SKIP",
                "summary": "Not in this audit's axes_active list.",
                "details": {},
            }
        else:
            axis_results[name] = fn(pre_reg)

    report = {
        "schema_version": 1,
        "period": period,
        "commit": _git_commit_sha(),
        "ran_at": dt.datetime.utcnow().isoformat() + "Z",
        "axes": axis_results,
    }
    report["verdict"] = _verdict(report)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_md = REPORTS_DIR / f"audit_{period.replace('-', '_')}.md"
    out_json = REPORTS_DIR / f"audit_{period.replace('-', '_')}.json"
    out_json.write_text(json.dumps(report, indent=2, default=str))
    md = _render(report)
    out_md.write_text(md)

    print(md)
    return 1 if report["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
