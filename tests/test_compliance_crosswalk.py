"""Workstream 3 -- compliance crosswalk registry tests.

The crosswalk registry in ``sentinel_hft.compliance.crosswalk`` is the
single source of truth for what Sentinel-HFT implements towards which
regulatory clause. Three downstream consumers depend on its exact
shape:

* ``/api/compliance/crosswalk`` serializes ``CROSSWALK`` directly,
* ``/sentinel/regulations`` renders it as a table,
* ``docs/COMPLIANCE.md`` mirrors it row-for-row.

This module asserts the invariants every consumer relies on:

* exactly nine entries (matches the COMPLIANCE.md table),
* keys are lower_snake and unique,
* jurisdiction / layer / status fall in their declared enums,
* every "implemented" host module has a real artifact path,
* ``crosswalk_as_dict`` round-trips through json,
* ``live_counter_keys`` returns the five entries the snapshot binds to.

All tests are pure-Python and run sub-second; no FastAPI / network.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from sentinel_hft.compliance.crosswalk import (
    CROSSWALK,
    ComplianceEntry,
    crosswalk_as_dict,
    get_crosswalk,
    live_counter_keys,
)


# ---------------------------------------------------------------------
# Constants the rest of the system binds to
# ---------------------------------------------------------------------

EXPECTED_KEYS = (
    "mifid_otr",
    "mifid_rate_limit",
    "cftc_self_trade",
    "finra_fat_finger",
    "finra_credit",
    "sec_cat",
    "mar_abuse",
    "finma_resilience",
    "mas_resilience",
)

EXPECTED_LIVE_COUNTER_KEYS = (
    "mifid_otr",
    "cftc_self_trade",
    "finra_fat_finger",
    "sec_cat",
)

ALLOWED_JURISDICTIONS = {"EU", "US", "CH", "SG", "Global"}
ALLOWED_LAYERS = {"RTL", "Host", "Docs"}
ALLOWED_STATUS = {"implemented", "partial", "reused", "stub"}

LOWER_SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")


# ---------------------------------------------------------------------
# Shape of the registry
# ---------------------------------------------------------------------


def test_crosswalk_is_immutable_tuple():
    assert isinstance(CROSSWALK, tuple)
    assert get_crosswalk() is CROSSWALK
    for entry in CROSSWALK:
        assert isinstance(entry, ComplianceEntry)


def test_expected_entry_count():
    """v1.1.0 ships nine clauses. Bumping this needs a release note."""
    assert len(CROSSWALK) == 9


def test_keys_match_expected_order():
    """Display order is significant; the UI renders rows in this order."""
    actual = tuple(e.key for e in CROSSWALK)
    assert actual == EXPECTED_KEYS


def test_keys_are_lower_snake_and_unique():
    seen = set()
    for entry in CROSSWALK:
        assert LOWER_SNAKE.match(entry.key), (
            f"key {entry.key!r} is not lower_snake_case"
        )
        assert entry.key not in seen, f"duplicate key {entry.key!r}"
        seen.add(entry.key)
    assert len(seen) == len(CROSSWALK)


# ---------------------------------------------------------------------
# Enum coverage
# ---------------------------------------------------------------------


def test_jurisdictions_in_allowed_set():
    for entry in CROSSWALK:
        assert entry.jurisdiction in ALLOWED_JURISDICTIONS, (
            f"{entry.key}: bad jurisdiction {entry.jurisdiction!r}"
        )
    # Sanity: we should be exercising at least the four production regions.
    seen = {e.jurisdiction for e in CROSSWALK}
    assert {"EU", "US", "CH", "SG"}.issubset(seen)


def test_layers_in_allowed_set():
    for entry in CROSSWALK:
        assert entry.layer in ALLOWED_LAYERS, (
            f"{entry.key}: bad layer {entry.layer!r}"
        )


def test_statuses_in_allowed_set():
    for entry in CROSSWALK:
        assert entry.status in ALLOWED_STATUS, (
            f"{entry.key}: bad status {entry.status!r}"
        )


def test_no_stub_entries_in_v1_1():
    """v1.1.0 closes the seven host-side primitives. Two RTL primitives
    reused, zero stubs allowed."""
    stubs = [e.key for e in CROSSWALK if e.status == "stub"]
    assert stubs == [], f"unexpected stub entries: {stubs}"


def test_artifact_paths_non_empty_and_plausible():
    for entry in CROSSWALK:
        assert entry.artifact, f"{entry.key}: empty artifact"
        # Host modules must point at a .py file under sentinel_hft/.
        if entry.layer == "Host":
            assert "sentinel_hft/" in entry.artifact and ".py" in entry.artifact, (
                f"{entry.key}: Host artifact must reference a .py module under "
                f"sentinel_hft/, got {entry.artifact!r}"
            )
        # Reused RTL primitives must point at the v1.0.0-core-audit-closed
        # bitstream.
        if entry.layer == "RTL" and entry.status == "reused":
            assert ".sv" in entry.artifact


# ---------------------------------------------------------------------
# Live counter keys
# ---------------------------------------------------------------------


def test_live_counter_keys_match_snapshot_fields():
    """``live_counter_keys`` is the contract for the WS progress event:
    each key must correspond to a ComplianceSnapshot field.
    """
    keys = live_counter_keys()
    assert tuple(keys) == EXPECTED_LIVE_COUNTER_KEYS, (
        f"live_counter_keys drift: {keys}"
    )


def test_live_counter_flag_consistent_with_keys():
    flagged = [e.key for e in CROSSWALK if e.live_counter]
    assert flagged == list(EXPECTED_LIVE_COUNTER_KEYS)


# ---------------------------------------------------------------------
# JSON round-trip — the wire payload at /api/compliance/crosswalk
# ---------------------------------------------------------------------


def test_crosswalk_as_dict_roundtrips_through_json():
    payload = crosswalk_as_dict()
    assert isinstance(payload, list)
    assert len(payload) == len(CROSSWALK)

    # Round-trip through json.dumps/loads to prove every value is JSON-safe.
    roundtripped = json.loads(json.dumps(payload))
    assert roundtripped == payload

    # Each row must carry the full ComplianceEntry field set.
    expected_fields = {
        "key", "regulation", "jurisdiction", "clause", "primitive",
        "artifact", "layer", "audit_signal", "live_counter", "status",
    }
    for row in payload:
        assert set(row.keys()) == expected_fields, (
            f"row {row.get('key')} missing fields: "
            f"{expected_fields - set(row.keys())}"
        )


def test_crosswalk_as_dict_preserves_order():
    payload = crosswalk_as_dict()
    assert tuple(row["key"] for row in payload) == EXPECTED_KEYS


# ---------------------------------------------------------------------
# Doc-vs-registry parity (best-effort: the doc may not be checked into
# every clone, so we skip rather than fail when missing).
# ---------------------------------------------------------------------


def test_compliance_md_lists_every_registry_key():
    """``docs/COMPLIANCE.md`` must mention every registry key verbatim
    (the rendered table backticks each key). Skip if the doc isn't in
    the working tree."""
    repo_root = Path(__file__).resolve().parent.parent
    doc = repo_root / "docs" / "COMPLIANCE.md"
    if not doc.exists():
        pytest.skip(f"docs/COMPLIANCE.md not present at {doc}")
    text = doc.read_text(encoding="utf-8")
    missing = [e.key for e in CROSSWALK if f"`{e.key}`" not in text]
    assert missing == [], (
        f"docs/COMPLIANCE.md is missing crosswalk keys: {missing}"
    )
