"""
V-Parity comparator.

Reads:
  - golden JSON (from verification/v_floor/random_corpus.py)
  - rtl JSON (from drive_corpus.py)
And asserts byte-exact equality on (passed, reason) for every order.

Tokens-remaining / current_position / current_notional are NOT compared:
the cocotb wrapper does not expose them, and they are derived state that
V-Floor + V-Meta already cover via the golden.

Exit code:
  0  parity verified
  1  divergence detected (full diff in the output JSON)
  2  input file missing / unreadable
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List


def _load(p: Path) -> Dict:
    if not p.exists():
        sys.stderr.write(f"missing: {p}\n")
        sys.exit(2)
    return json.loads(p.read_text())


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", type=Path, required=True)
    ap.add_argument("--rtl",    type=Path, required=True)
    ap.add_argument("--out",    type=Path, required=True)
    args = ap.parse_args(argv)

    g = _load(args.golden)
    r = _load(args.rtl)

    if g["seed"] != r["seed"]:
        sys.stderr.write(
            f"seed mismatch: golden={g['seed']} rtl={r['seed']}\n"
        )
        return 1
    n = min(len(g["decisions"]), len(r["decisions"]))
    if len(g["decisions"]) != len(r["decisions"]):
        sys.stderr.write(
            f"decision count mismatch: golden={len(g['decisions'])} rtl={len(r['decisions'])}\n"
        )

    diffs: List[Dict] = []
    for i in range(n):
        gd = g["decisions"][i]
        rd = r["decisions"][i]
        if gd["passed"] != rd["passed"] or int(gd["reason"]) != int(rd["reason"]):
            diffs.append({
                "idx": i,
                "golden": {"passed": gd["passed"], "reason": int(gd["reason"])},
                "rtl":    {"passed": rd["passed"], "reason": int(rd["reason"])},
            })
            if len(diffs) >= 50:    # cap reported diffs to keep output small
                break

    summary = {
        "schema_version": 1,
        "seed": g["seed"],
        "n_compared": n,
        "n_diffs": len(diffs),
        "first_50_diffs": diffs,
        "ok": len(diffs) == 0 and len(g["decisions"]) == len(r["decisions"]),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))

    if summary["ok"]:
        print(f"V-Parity OK: {n} orders, 0 diffs.")
        return 0

    print(f"V-Parity FAIL: {summary['n_diffs']} diffs over {n} orders. "
          f"First diffs at indices: {[d['idx'] for d in diffs[:5]]}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
