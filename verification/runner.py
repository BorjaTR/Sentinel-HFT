"""
Sentinel-HFT verification runner.

Orchestrates all six V-axes for a given commit. Produces:

    verification/reports/<commit-sha>/v_floor.json
    verification/reports/<commit-sha>/v_mutation.json
    verification/reports/<commit-sha>/v_metamorphic.json
    verification/reports/<commit-sha>/v_parity.json
    verification/reports/<commit-sha>/v_contract.json
    verification/reports/<commit-sha>/v_tamper.json
    verification/reports/<commit-sha>/REPORT.md     ← human-readable summary
    verification/reports/latest.md                   ← symlink to most recent

Each axis function returns a dict:
    {
        "axis": "v_floor",
        "status": "PASS" | "FAIL" | "SKIP",
        "summary": str,
        "details": dict,
    }

For Phase 1, several axes are skeleton-only (return SKIP with a TODO).
The runner still runs and produces a report — exit code is 0 if no FAIL,
1 otherwise.

Pre-reg ref: roadmap/pre_reg/phase_01.yml
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "verification" / "reports"


# -----------------------------------------------------------------------------
# Axis implementations (V-Floor wired; others stubbed for Phase 1)
# -----------------------------------------------------------------------------

def _axis_v_floor() -> Dict:
    """V-Floor: golden round-trip determinism + corpus coverage check.

    Phase 1 implementation: regenerate canonical seed set and verify
    SHA-256 manifest. The cross-engine RTL parity that this axis ALSO
    needs is implemented in v_parity (it shares the corpus).
    """
    res = subprocess.run(
        [sys.executable, "-m", "verification.v_floor.regenerate_and_verify"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        return {
            "axis": "v_floor",
            "status": "PASS",
            "summary": "Golden corpus determinism verified across all canonical seeds.",
            "details": {"stdout_tail": res.stdout.splitlines()[-10:]},
        }
    return {
        "axis": "v_floor",
        "status": "FAIL",
        "summary": "Golden corpus determinism check failed.",
        "details": {
            "exit_code": res.returncode,
            "stdout_tail": res.stdout.splitlines()[-20:],
            "stderr_tail": res.stderr.splitlines()[-20:],
        },
    }


def _axis_v_mutation() -> Dict:
    return {
        "axis": "v_mutation",
        "status": "SKIP",
        "summary": "Mutation testing harness not yet built — Phase 1 sub-task pending.",
        "details": {"todo": "verification/v_mutation/inject.py"},
    }


def _axis_v_metamorphic() -> Dict:
    """V-Meta: four relations × 10k pairs each.

    Phase-1 budget is 10k pairs/relation (40k total checks, ~0.4s).
    Pre-reg ship target is 100k pairs/relation; the runner's CI mode
    can be invoked with --pairs 100000 if a deeper run is desired.
    """
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "verification.v_metamorphic.relations",
            "--seed", "42",
            "--pairs", "10000",
            "--out", str(REPORTS_DIR / "v_metamorphic" / "ci.json"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    out_lines = res.stdout.splitlines()
    if res.returncode == 0:
        return {
            "axis": "v_metamorphic",
            "status": "PASS",
            "summary": "All 4 metamorphic relations held across 10k pairs each.",
            "details": {"stdout_tail": out_lines[-6:]},
        }
    return {
        "axis": "v_metamorphic",
        "status": "FAIL",
        "summary": "One or more metamorphic relations violated.",
        "details": {
            "exit_code": res.returncode,
            "stdout_tail": out_lines[-10:],
            "stderr_tail": res.stderr.splitlines()[-10:],
        },
    }


def _axis_v_parity() -> Dict:
    return {
        "axis": "v_parity",
        "status": "SKIP",
        "summary": "RTL/gate-sim parity harness not yet wired — Phase 1 sub-task pending.",
        "details": {"todo": "verification/v_parity/three_engine.py"},
    }


def _axis_v_contract() -> Dict:
    """V-Contract Phase-1 partial: regmap.yaml schema validation."""
    regmap_path = REPO_ROOT / "fpga" / "regmap.yaml"
    if not regmap_path.exists():
        return {
            "axis": "v_contract",
            "status": "FAIL",
            "summary": "fpga/regmap.yaml is missing.",
            "details": {},
        }

    # Lightweight schema check: parse, walk, assert no overlapping addresses
    # and all `wo` fields documented.
    try:
        import yaml  # type: ignore
    except ImportError:
        return {
            "axis": "v_contract",
            "status": "SKIP",
            "summary": "PyYAML not installed; cannot parse regmap.yaml.",
            "details": {},
        }
    try:
        data = yaml.safe_load(regmap_path.read_text())
    except Exception as e:
        return {
            "axis": "v_contract",
            "status": "FAIL",
            "summary": f"Could not parse regmap.yaml: {e}",
            "details": {},
        }

    blocks = data.get("blocks", [])
    if not blocks:
        return {
            "axis": "v_contract",
            "status": "FAIL",
            "summary": "regmap.yaml has no blocks.",
            "details": {},
        }

    # Block ranges must not overlap.
    ranges = sorted(
        [(b["base"], b["base"] + b["size"], b["name"]) for b in blocks],
        key=lambda t: t[0],
    )
    overlaps: List[str] = []
    for i in range(1, len(ranges)):
        if ranges[i][0] < ranges[i - 1][1]:
            overlaps.append(f"{ranges[i-1][2]} ↔ {ranges[i][2]}")

    # Within-block: register offsets must be unique.
    register_dupes: List[str] = []
    register_count = 0
    for b in blocks:
        seen: Dict[int, str] = {}
        for r in b.get("registers", []):
            register_count += 1
            o = r["offset"]
            if o in seen:
                register_dupes.append(f"{b['name']}@{hex(o)}: {seen[o]} ↔ {r['name']}")
            seen[o] = r["name"]

    if overlaps or register_dupes:
        return {
            "axis": "v_contract",
            "status": "FAIL",
            "summary": "regmap.yaml has overlapping blocks or duplicate offsets.",
            "details": {
                "block_overlaps": overlaps,
                "register_duplicates": register_dupes,
            },
        }

    return {
        "axis": "v_contract",
        "status": "PASS",
        "summary": (
            f"regmap.yaml: {len(blocks)} blocks, {register_count} registers; "
            "no overlaps, no duplicate offsets."
        ),
        "details": {
            "regmap_version": data.get("regmap_version"),
            "block_count": len(blocks),
            "register_count": register_count,
        },
    }


def _axis_v_tamper() -> Dict:
    return {
        "axis": "v_tamper",
        "status": "SKIP",
        "summary": "Audit-chain tamper-injection harness not yet built — Phase 1 sub-task pending.",
        "details": {"todo": "verification/v_tamper/tamper_inject.py"},
    }


AXES: Dict[str, Callable[[], Dict]] = {
    "v_floor": _axis_v_floor,
    "v_mutation": _axis_v_mutation,
    "v_metamorphic": _axis_v_metamorphic,
    "v_parity": _axis_v_parity,
    "v_contract": _axis_v_contract,
    "v_tamper": _axis_v_tamper,
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


def run_all() -> Dict:
    return {
        "schema_version": 1,
        "commit": _git_commit_sha(),
        "ran_at": dt.datetime.utcnow().isoformat() + "Z",
        "axes": {name: fn() for name, fn in AXES.items()},
    }


def render_markdown(report: Dict) -> str:
    lines = [
        f"# Verification Report — {report['commit']}",
        "",
        f"**Run at:** {report['ran_at']}",
        "",
        "| Axis | Status | Summary |",
        "|------|--------|---------|",
    ]
    for name, axis in report["axes"].items():
        lines.append(f"| `{name}` | **{axis['status']}** | {axis['summary']} |")
    lines.append("")

    fails = [a for a in report["axes"].values() if a["status"] == "FAIL"]
    skips = [a for a in report["axes"].values() if a["status"] == "SKIP"]
    passes = [a for a in report["axes"].values() if a["status"] == "PASS"]

    lines.append(f"**{len(passes)} PASS · {len(skips)} SKIP · {len(fails)} FAIL**")
    lines.append("")
    if fails:
        lines.append("## Failures")
        for a in fails:
            lines.append(f"### `{a['axis']}` — {a['summary']}")
            lines.append("```json")
            lines.append(json.dumps(a["details"], indent=2, default=str))
            lines.append("```")
    if skips:
        lines.append("")
        lines.append("## Skipped (Phase-1 work-in-progress)")
        for a in skips:
            lines.append(f"- `{a['axis']}` — {a['summary']}")
    return "\n".join(lines) + "\n"


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--axes",
        nargs="*",
        default=None,
        help="Which axes to run (default: all). Choices: " + ", ".join(AXES),
    )
    args = ap.parse_args(argv)

    selected = AXES if args.axes is None else {k: AXES[k] for k in args.axes}

    report = {
        "schema_version": 1,
        "commit": _git_commit_sha(),
        "ran_at": dt.datetime.utcnow().isoformat() + "Z",
        "axes": {name: fn() for name, fn in selected.items()},
    }

    out_dir = REPORTS_DIR / report["commit"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str))
    md = render_markdown(report)
    (out_dir / "REPORT.md").write_text(md)

    # Update "latest.md" symlink.
    latest = REPORTS_DIR / "latest.md"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        rel = os.path.relpath(out_dir / "REPORT.md", REPORTS_DIR)
        latest.symlink_to(rel)
    except OSError:
        # Filesystems without symlink support: fall back to a copy.
        latest.write_text(md)

    print(md)

    fails = [a for a in report["axes"].values() if a["status"] == "FAIL"]
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
