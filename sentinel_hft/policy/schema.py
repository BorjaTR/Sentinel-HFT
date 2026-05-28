"""
Policy YAML schema + validator.

Schema (v1):

    schema_version: 1
    name: "kr-prod-2026-05"
    description: "..."
    rate:
        max_tokens: 1024
        refill_rate: 32
        refill_period_cycles: 100
        enabled: true
    position:
        max_long_qty: 10_000_000
        max_short_qty: 10_000_000
        max_notional: 100_000_000_000_000
        max_order_qty: 1_000_000
        enabled: true
    kill_switch:
        armed: true
        auto_enabled: false
        loss_threshold: -1_000_000_000_000
    fat_finger:
        enabled: true
        band_bps: 300
        ref_price_fp8: 0
    allowlist:
        enabled: true
        symbols: [1, 2, 3, ...]   # symbol_ids; max 64

Required fields, types, and ranges are enforced. Extra fields are
rejected to prevent silent typos.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class PolicySchemaError(Exception):
    """Raised when a policy YAML doesn't validate."""


SCHEMA_VERSION = 1


@dataclass
class Policy:
    name: str
    description: str
    rate_max_tokens: int
    rate_refill_rate: int
    rate_refill_period: int
    rate_enabled: bool
    pos_max_long: int
    pos_max_short: int
    pos_max_notional: int
    pos_max_order_qty: int
    pos_enabled: bool
    kill_armed: bool
    kill_auto_enabled: bool
    kill_loss_threshold: int
    ff_enabled: bool
    ff_band_bps: int
    ff_ref_price: int
    allowlist_enabled: bool
    allowlist: Tuple[int, ...]


# Convenient alias so the public name "PolicySchema" survives import
# even though we use a dataclass-based representation below.
PolicySchema = Policy


def load_policy(path: Path) -> Policy:
    import yaml  # type: ignore
    raw = yaml.safe_load(path.read_text()) or {}
    return validate_policy(raw)


def validate_policy(raw: Dict[str, Any]) -> Policy:
    if not isinstance(raw, dict):
        raise PolicySchemaError("top-level must be a mapping")
    sv = raw.get("schema_version")
    if sv != SCHEMA_VERSION:
        raise PolicySchemaError(f"schema_version must be {SCHEMA_VERSION}, got {sv!r}")

    expected_top = {"schema_version", "name", "description", "rate", "position",
                    "kill_switch", "fat_finger", "allowlist"}
    extra = set(raw.keys()) - expected_top
    if extra:
        raise PolicySchemaError(f"unknown top-level keys: {sorted(extra)}")

    missing = expected_top - set(raw.keys()) - {"description"}   # description optional
    if missing:
        raise PolicySchemaError(f"missing top-level keys: {sorted(missing)}")

    name = _require_str(raw, "name")
    desc = raw.get("description", "")
    if not isinstance(desc, str):
        raise PolicySchemaError("description must be a string")

    rate = _require_dict(raw, "rate", {"max_tokens", "refill_rate", "refill_period_cycles", "enabled"})
    pos = _require_dict(raw, "position",
                        {"max_long_qty", "max_short_qty", "max_notional",
                         "max_order_qty", "enabled"})
    kill = _require_dict(raw, "kill_switch", {"armed", "auto_enabled", "loss_threshold"})
    ff = _require_dict(raw, "fat_finger", {"enabled", "band_bps", "ref_price_fp8"})
    al = _require_dict(raw, "allowlist", {"enabled", "symbols"})

    symbols = al["symbols"]
    if not isinstance(symbols, list):
        raise PolicySchemaError("allowlist.symbols must be a list")
    if len(symbols) > 64:
        raise PolicySchemaError("allowlist.symbols max 64 entries")
    for s in symbols:
        if not isinstance(s, int) or s <= 0 or s >= 2**32:
            raise PolicySchemaError(f"allowlist.symbols entry invalid: {s!r}")

    return Policy(
        name=name,
        description=desc,
        rate_max_tokens=_uint(rate, "max_tokens", 32),
        rate_refill_rate=_uint(rate, "refill_rate", 32),
        rate_refill_period=_uint(rate, "refill_period_cycles", 16),
        rate_enabled=_bool(rate, "enabled"),
        pos_max_long=_uint(pos, "max_long_qty", 64),
        pos_max_short=_uint(pos, "max_short_qty", 64),
        pos_max_notional=_uint(pos, "max_notional", 64),
        pos_max_order_qty=_uint(pos, "max_order_qty", 64),
        pos_enabled=_bool(pos, "enabled"),
        kill_armed=_bool(kill, "armed"),
        kill_auto_enabled=_bool(kill, "auto_enabled"),
        kill_loss_threshold=_int(kill, "loss_threshold", 64),
        ff_enabled=_bool(ff, "enabled"),
        ff_band_bps=_uint(ff, "band_bps", 16),
        ff_ref_price=_uint(ff, "ref_price_fp8", 64),
        allowlist_enabled=_bool(al, "enabled"),
        allowlist=tuple(symbols),
    )


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _require_str(d: Dict[str, Any], key: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v:
        raise PolicySchemaError(f"{key} must be a non-empty string")
    return v


def _require_dict(d: Dict[str, Any], key: str, expected_keys: set) -> Dict[str, Any]:
    v = d.get(key)
    if not isinstance(v, dict):
        raise PolicySchemaError(f"{key} must be a mapping")
    extra = set(v.keys()) - expected_keys
    if extra:
        raise PolicySchemaError(f"{key} has unknown keys: {sorted(extra)}")
    missing = expected_keys - set(v.keys())
    if missing:
        raise PolicySchemaError(f"{key} missing keys: {sorted(missing)}")
    return v


def _uint(d: Dict[str, Any], key: str, bits: int) -> int:
    v = d[key]
    if not isinstance(v, int) or v < 0 or v >= 2**bits:
        raise PolicySchemaError(f"{key} must be a non-negative {bits}-bit integer, got {v!r}")
    return v


def _int(d: Dict[str, Any], key: str, bits: int) -> int:
    v = d[key]
    lim = 2**(bits - 1)
    if not isinstance(v, int) or v < -lim or v >= lim:
        raise PolicySchemaError(f"{key} must be a signed {bits}-bit integer, got {v!r}")
    return v


def _bool(d: Dict[str, Any], key: str) -> bool:
    v = d[key]
    if not isinstance(v, bool):
        raise PolicySchemaError(f"{key} must be a boolean, got {v!r}")
    return v
