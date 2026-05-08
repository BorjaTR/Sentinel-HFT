"""
Regenerate the V-Floor canonical seed set and verify SHA-256 determinism.

Reads verification/v_floor/MANIFEST.sha256, regenerates each declared seed,
hashes the produced JSON, and asserts equality. Fails (exit 1) on any
mismatch.

Manifest line format:
    <seed>  <orders>  <sha256>
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(__file__).resolve().parent / "MANIFEST.sha256"


def parse_manifest(path: Path) -> List[Tuple[int, int, str]]:
    out: List[Tuple[int, int, str]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"bad manifest line: {line}")
        seed, orders, sha = int(parts[0]), int(parts[1]), parts[2].lower()
        out.append((seed, orders, sha))
    return out


def regenerate_seed(seed: int, orders: int, out_path: Path) -> str:
    cmd = [
        sys.executable,
        "-m",
        "verification.v_floor.random_corpus",
        "--seed",
        str(seed),
        "--orders",
        str(orders),
        "--out",
        str(out_path),
    ]
    res = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        sys.stderr.write(f"regenerate seed={seed} FAILED:\n{res.stderr}")
        raise SystemExit(2)
    return _sha256_of(out_path)


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument(
        "--regenerate-only",
        action="store_true",
        help="Regenerate the manifest entries; do not assert hash equality. "
             "Use this only when intentionally updating canonical seeds.",
    )
    args = ap.parse_args(argv)

    if not args.manifest.exists():
        sys.stderr.write(f"missing manifest: {args.manifest}\n")
        return 2

    entries = parse_manifest(args.manifest)
    out_dir = REPO_ROOT / "verification" / "reports" / "v_floor"
    out_dir.mkdir(parents=True, exist_ok=True)

    failures: List[str] = []
    new_lines: List[str] = []

    for seed, orders, expected_sha in entries:
        out_path = out_dir / f"golden_seed{seed}_n{orders}.json"
        actual = regenerate_seed(seed, orders, out_path)
        status = "OK"
        if args.regenerate_only:
            new_lines.append(f"{seed}  {orders}  {actual}")
        else:
            if actual != expected_sha:
                failures.append(
                    f"  seed={seed} n={orders}: expected {expected_sha}, got {actual}"
                )
                status = "MISMATCH"
        print(f"  seed={seed} n={orders} sha={actual[:16]}…  {status}")

    if args.regenerate_only:
        args.manifest.write_text(
            "# Format: <seed>  <orders>  <sha256>\n"
            "# Regenerate with: python -m verification.v_floor.regenerate_and_verify --regenerate-only\n"
            + "\n".join(new_lines) + "\n"
        )
        print(f"\nManifest updated: {args.manifest}")
        return 0

    if failures:
        print("\nDETERMINISM CHECK FAILED:")
        for line in failures:
            print(line)
        return 1

    print(f"\nDeterminism check OK across {len(entries)} seeds.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
