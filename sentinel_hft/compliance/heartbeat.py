"""
Compliance heartbeat — daily empty-but-signed bundle.

Writes one envelope per day, whether or not anything fired. The point
is to give a regulator a continuous "no incident today" record
anchored to the audit chain, so that an absence of events is a
positive assertion rather than silence.

Envelope fields (stable, JSON-safe)::

    {
      "schema": "sentinel-hft/compliance-heartbeat/1",
      "trading_date": "YYYY-MM-DD",
      "generated_at": "YYYY-MM-DDTHH:MM:SS+00:00",
      "jurisdiction": "Global",
      "subject": "sentinel-hft",
      "environment": "sim" | "prod" | ...,
      "crosswalk_count": <int>,
      "live_counter_keys": [ ... ],
      "counters": {                # all zeros on an empty day
        "mifid_otr": { "total_orders": 0, ... },
        "cftc_self_trade": { "checked": 0, ... },
        "finra_fat_finger": { "checked": 0, ... },
        "sec_cat": { "total_records": 0 },
        "mar_abuse": { "alerts": 0 }
      },
      "incident_count": 0,
      "worst_severity": "ok",
      "audit": {
        "head_hash_lo_hex": <str or "">,
        "record_count": <int>
      },
      "envelope_hash_sha256": <sha256 of the canonical body>
    }

The envelope is written to::

    out/compliance/heartbeat/YYYY-MM-DD.json

Run daily at 00:05 UTC via cron / systemd timer / the Cowork
scheduled-task system. Example crontab entry::

    5 0 * * *  python3 -m sentinel_hft.compliance.heartbeat \\
                --output-root /var/lib/sentinel-hft/out

CLI::

    python3 -m sentinel_hft.compliance.heartbeat \\
        [--date YYYY-MM-DD] \\
        [--output-root PATH] \\
        [--audit PATH_TO_AUDIT.AUD] \\
        [--environment sim|prod|...] \\
        [--jurisdiction EU|US|CH|SG|Global]

Exit codes:
  0  bundle written
  1  unexpected error (stack trace on stderr)
  2  audit chain break detected (bundle is still written with the
     ``chain_ok=False`` flag set so the regulator has evidence of
     the break anchored to today's heartbeat)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from sentinel_hft.compliance.crosswalk import (
    crosswalk_as_dict,
    live_counter_keys,
)
from sentinel_hft.compliance.stack import ComplianceStack


HEARTBEAT_SCHEMA = "sentinel-hft/compliance-heartbeat/1"


def _zero_counter_shape() -> Dict[str, Any]:
    """Snapshot of a fresh ComplianceStack — all counters at zero.

    Wrapping the stack in a with-block ensures no CAT NDJSON file is
    left open on disk.
    """
    with ComplianceStack(cat_output_path=None) as stack:
        return stack.snapshot().as_dict()


def _audit_tail(audit_path: Optional[Path]) -> Dict[str, Any]:
    """Walk ``audit.aud`` and return the head hash + record count.

    Returns a dict with ``head_hash_lo_hex``, ``record_count``, and
    ``chain_ok``. If the file is missing or empty, returns zeros with
    ``chain_ok=True`` — absence of a chain is not a break.
    """
    if audit_path is None or not audit_path.exists():
        return {
            "head_hash_lo_hex": "",
            "record_count": 0,
            "chain_ok": True,
            "source": None,
        }

    # Lazy import so the heartbeat can still run on a host that only
    # has the compliance stack (not the full audit reader).
    try:
        from sentinel_hft.audit.record import read_records
        from sentinel_hft.audit.verifier import verify as verify_chain
    except ImportError:
        return {
            "head_hash_lo_hex": "",
            "record_count": 0,
            "chain_ok": True,
            "source": str(audit_path),
            "note": "audit module not importable; chain unverified",
        }

    try:
        records = list(read_records(audit_path))
        result = verify_chain(records)
        head_hex = result.head_hash_lo.hex() if result.head_hash_lo else ""
        return {
            "head_hash_lo_hex": head_hex,
            "record_count": int(result.verified_records or 0),
            "chain_ok": bool(result.ok),
            "source": str(audit_path),
        }
    except Exception as e:  # pragma: no cover - defensive
        return {
            "head_hash_lo_hex": "",
            "record_count": 0,
            "chain_ok": False,
            "source": str(audit_path),
            "error": f"{type(e).__name__}: {e}",
        }


def build_bundle(
    *,
    trading_date: str,
    jurisdiction: str = "Global",
    subject: str = "sentinel-hft",
    environment: str = "sim",
    audit_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Produce the heartbeat envelope dict.

    Deterministic for a given ``(trading_date, counters, audit_tail)``
    except for ``generated_at`` which is always the wall-clock time.
    """
    counters = _zero_counter_shape()
    audit = _audit_tail(audit_path)
    body: Dict[str, Any] = {
        "schema": HEARTBEAT_SCHEMA,
        "trading_date": trading_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "jurisdiction": jurisdiction,
        "subject": subject,
        "environment": environment,
        "crosswalk_count": len(crosswalk_as_dict()),
        "live_counter_keys": list(live_counter_keys()),
        "counters": counters,
        "incident_count": 0,
        "worst_severity": "ok",
        "audit": {
            "head_hash_lo_hex": audit["head_hash_lo_hex"],
            "record_count": audit["record_count"],
            "chain_ok": audit["chain_ok"],
            "source": audit.get("source"),
        },
    }
    if "error" in audit:
        body["audit"]["error"] = audit["error"]
    if "note" in audit:
        body["audit"]["note"] = audit["note"]

    # Canonical envelope hash: sort keys, no whitespace. Excludes the
    # generated_at field so replay of the same trading-day on two
    # machines yields the same hash (modulo audit tail changes).
    for_hash = {k: v for k, v in body.items() if k != "generated_at"}
    canonical = json.dumps(for_hash, sort_keys=True, separators=(",", ":"))
    body["envelope_hash_sha256"] = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    return body


def write_bundle(
    bundle: Dict[str, Any],
    output_root: Path,
) -> Path:
    """Write ``<output_root>/compliance/heartbeat/<date>.json``.

    Returns the written path. Overwrites an existing bundle for the
    same date — the new bundle carries the current audit tail so it's
    always the freshest snapshot.
    """
    out_dir = output_root / "compliance" / "heartbeat"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{bundle['trading_date']}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2, sort_keys=True)
        f.write("\n")
    return out_path


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Emit the daily compliance heartbeat bundle.",
    )
    p.add_argument(
        "--date",
        default=None,
        help="Trading date YYYY-MM-DD (default: today, UTC).",
    )
    p.add_argument(
        "--output-root",
        default="out",
        help="Root directory for artifacts (default: ./out).",
    )
    p.add_argument(
        "--audit",
        default=None,
        help=(
            "Path to an ``audit.aud`` file whose head-hash should be "
            "embedded. Optional; if omitted the bundle still signs "
            "itself but reports an empty audit tail."
        ),
    )
    p.add_argument(
        "--jurisdiction",
        default="Global",
        help="Primary regulatory tag (EU|US|CH|SG|Global).",
    )
    p.add_argument(
        "--subject",
        default="sentinel-hft",
        help="Subject label (default: sentinel-hft).",
    )
    p.add_argument(
        "--environment",
        default="sim",
        help="Environment tag (sim|prod|stage|...).",
    )
    p.add_argument(
        "--stdout",
        action="store_true",
        help="Also print the envelope to stdout for log ingestion.",
    )
    args = p.parse_args(argv)

    trading_date = args.date or date.today().isoformat()
    audit_path = Path(args.audit) if args.audit else None
    output_root = Path(args.output_root)

    try:
        bundle = build_bundle(
            trading_date=trading_date,
            jurisdiction=args.jurisdiction,
            subject=args.subject,
            environment=args.environment,
            audit_path=audit_path,
        )
        written = write_bundle(bundle, output_root)
    except Exception:  # pragma: no cover - defensive
        traceback.print_exc()
        return 1

    chain_ok = bool(bundle["audit"].get("chain_ok", True))
    rel = os.path.relpath(written)
    msg = (
        f"[compliance-heartbeat] {trading_date}  wrote {rel}  "
        f"hash={bundle['envelope_hash_sha256'][:16]}  "
        f"chain_ok={chain_ok}"
    )
    print(msg, file=sys.stderr)

    if args.stdout:
        print(json.dumps(bundle, indent=2, sort_keys=True))

    return 0 if chain_ok else 2


if __name__ == "__main__":
    sys.exit(main())
