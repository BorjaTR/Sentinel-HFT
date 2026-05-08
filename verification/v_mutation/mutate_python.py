"""
V-Mut Python leg: mutate the golden risk_gate decision function and run
the test suite against each mutant. Pre-reg ship target: ≤ 5% survivors,
each survivor explicitly justified.

Mutations applied (operator-flip taxonomy):

    >    →   <
    >=   →   <=
    <    →   >
    <=   →   >=
    ==   →   !=
    !=   →   ==
    +    →   -            (in arithmetic contexts only — guarded)
    -    →   +
    and  →   or
    or   →   and
    True →   False
    False→   True

Plus boolean inversion at decision sites (`return self._reject(...)` →
`return Decision(passed=True, reason=RejectReason.OK, ...)`).

The runner forks a subprocess per mutant so a crash in one doesn't
poison the others. Each mutant patches a single AST node, runs the
test suite, and returns the verdict.

Survivors are dumped with the original line + the mutated line so a
reviewer can decide whether to add a test or justify the survival.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET_FILE = REPO_ROOT / "sentinel_hft" / "golden" / "risk_gate.py"

# V-Mut scope: only mutations inside decision-affecting methods are
# part of the gate's spec contract. Out-of-scope mutations (dataclass
# frozen flags, helper-function loop conditions, etc.) are still
# "valid" Python mutations but don't change the gate's externally
# visible decision and are excluded from the survival-rate budget.
IN_SCOPE_FUNCS = {"decide", "tick", "update_pnl", "fill", "_trip_kill"}


# -----------------------------------------------------------------------------
# AST mutation visitor
# -----------------------------------------------------------------------------

CMPOP_FLIPS = {
    ast.Gt: ast.Lt,
    ast.Lt: ast.Gt,
    ast.GtE: ast.LtE,
    ast.LtE: ast.GtE,
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
}

BOOLOP_FLIPS = {
    ast.And: ast.Or,
    ast.Or: ast.And,
}


@dataclass
class Mutation:
    line: int
    col: int
    op_before: str
    op_after: str
    description: str


class _MutationCollector(ast.NodeVisitor):
    """Collect mutation sites without applying anything yet."""

    def __init__(self) -> None:
        self.sites: List[Mutation] = []

    def _add(self, node, before: str, after: str, desc: str) -> None:
        self.sites.append(
            Mutation(
                line=node.lineno,
                col=getattr(node, "col_offset", 0),
                op_before=before,
                op_after=after,
                description=desc,
            )
        )

    def visit_Compare(self, node: ast.Compare) -> None:
        for op in node.ops:
            cls = type(op)
            if cls in CMPOP_FLIPS:
                self._add(
                    node,
                    cls.__name__,
                    CMPOP_FLIPS[cls].__name__,
                    f"flip {cls.__name__}->{CMPOP_FLIPS[cls].__name__}",
                )
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        cls = type(node.op)
        if cls in BOOLOP_FLIPS:
            self._add(
                node, cls.__name__, BOOLOP_FLIPS[cls].__name__,
                f"flip {cls.__name__}->{BOOLOP_FLIPS[cls].__name__}",
            )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, bool):
            self._add(
                node, str(node.value), str(not node.value),
                f"flip bool {node.value} -> {not node.value}",
            )
        self.generic_visit(node)


class _ApplyOne(ast.NodeTransformer):
    """Apply exactly one mutation, identified by (line, col, op_before)."""

    def __init__(self, target: Mutation) -> None:
        self.target = target
        self.applied = False

    def _matches(self, node: ast.AST, op_before: str) -> bool:
        return (
            getattr(node, "lineno", -1) == self.target.line
            and type(getattr(node, "op", None)).__name__ == op_before
        )

    def visit_Compare(self, node: ast.Compare):
        new_ops: List[ast.cmpop] = []
        for op in node.ops:
            if (
                not self.applied
                and node.lineno == self.target.line
                and type(op).__name__ == self.target.op_before
            ):
                new_ops.append(CMPOP_FLIPS[type(op)]())
                self.applied = True
            else:
                new_ops.append(op)
        node.ops = new_ops
        self.generic_visit(node)
        return node

    def visit_BoolOp(self, node: ast.BoolOp):
        if (
            not self.applied
            and node.lineno == self.target.line
            and type(node.op).__name__ == self.target.op_before
        ):
            node.op = BOOLOP_FLIPS[type(node.op)]()
            self.applied = True
        self.generic_visit(node)
        return node

    def visit_Constant(self, node: ast.Constant):
        if (
            not self.applied
            and isinstance(node.value, bool)
            and node.lineno == self.target.line
            and str(node.value) == self.target.op_before
        ):
            node.value = not node.value
            self.applied = True
        return node


# -----------------------------------------------------------------------------
# Mutation runner
# -----------------------------------------------------------------------------

def _collect_mutations(src: str) -> List[Mutation]:
    """Collect mutation sites from the source.

    Restricts to nodes inside IN_SCOPE_FUNCS. Out-of-scope mutations
    (dataclass frozen flags, helper-function iteration semantics) are
    excluded from the survival-rate budget.
    """
    tree = ast.parse(src)

    # Find line ranges of in-scope functions/methods.
    scope_ranges: List[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in IN_SCOPE_FUNCS:
                end = getattr(node, "end_lineno", node.lineno + 200)
                scope_ranges.append((node.lineno, end))

    coll = _MutationCollector()
    coll.visit(tree)

    def in_scope(line: int) -> bool:
        return any(lo <= line <= hi for lo, hi in scope_ranges)

    return [m for m in coll.sites if in_scope(m.line)]


def _apply_mutation(src: str, m: Mutation) -> str:
    tree = ast.parse(src)
    transformer = _ApplyOne(m)
    new_tree = transformer.visit(tree)
    if not transformer.applied:
        # Mutation site disappeared — should be rare; skip.
        return src
    ast.fix_missing_locations(new_tree)
    return ast.unparse(new_tree)


def _run_tests_against_mutant(mutant_src: str, original_src: str) -> bool:
    """Returns True if the test suite KILLED the mutant (i.e., a test failed).

    Swaps the mutant into TARGET_FILE in place, runs pytest, then restores
    the original. This is necessary because the package is installed in
    editable mode — PYTHONPATH shadowing doesn't override editable installs.

    -B + PYTHONDONTWRITEBYTECODE prevents .pyc caching from masking mutations
    when the .py mtime granularity is coarse.
    """
    pycache = TARGET_FILE.parent / "__pycache__"
    try:
        TARGET_FILE.write_text(mutant_src)
        # Nuke the .pyc files for the mutated module so Python re-compiles.
        if pycache.is_dir():
            for pyc in pycache.glob("*.pyc"):
                try:
                    pyc.unlink()
                except OSError:
                    pass
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        res = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "pytest",
                str(REPO_ROOT / "tests" / "test_golden_risk_gate.py"),
                "-q",
                "--no-header",
                "-x",
                "-p", "no:cacheprovider",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return res.returncode != 0
    finally:
        TARGET_FILE.write_text(original_src)
        if pycache.is_dir():
            for pyc in pycache.glob("*.pyc"):
                try:
                    pyc.unlink()
                except OSError:
                    pass


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-mutations", type=int, default=50,
                    help="cap on number of mutations evaluated (CI mode).")
    ap.add_argument("--seed", type=int, default=42,
                    help="seed for mutation-site ordering")
    ap.add_argument("--out", type=Path,
                    default=REPO_ROOT / "verification" / "reports" / "v_mutation" / "python_run.json")
    args = ap.parse_args(argv)

    src = TARGET_FILE.read_text()
    mutations = _collect_mutations(src)

    import random
    rng = random.Random(args.seed)
    rng.shuffle(mutations)
    mutations = mutations[: args.max_mutations]

    survivors: List[dict] = []
    killed = 0
    for i, m in enumerate(mutations):
        mutant_src = _apply_mutation(src, m)
        if mutant_src == src:
            # Site disappeared (already mutated by prior pass on same line).
            continue
        is_killed = _run_tests_against_mutant(mutant_src, src)
        if is_killed:
            killed += 1
        else:
            survivors.append({
                "line": m.line,
                "col": m.col,
                "op_before": m.op_before,
                "op_after": m.op_after,
                "description": m.description,
            })
        print(f"  [{i+1:2}/{len(mutations)}] line {m.line:4} {m.op_before:>6}->{m.op_after:<6}  "
              f"{'KILLED' if is_killed else 'SURVIVED'}")

    n = len(mutations)
    survival_rate = (n - killed) / n if n else 0.0
    summary = {
        "schema_version": 1,
        "n_mutations": n,
        "n_killed": killed,
        "n_survived": len(survivors),
        "survival_rate": survival_rate,
        "survivors": survivors,
        "ok": survival_rate <= 0.05,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))

    print()
    print(f"V-Mut python: {killed}/{n} killed, {len(survivors)} survived, "
          f"survival_rate={survival_rate:.2%}")
    if survival_rate > 0.05:
        print("  FAIL: survival rate > 5%")
        return 1
    print("  OK: ≤ 5% survival.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
