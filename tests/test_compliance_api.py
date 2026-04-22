"""Workstream 3 -- /api/compliance/* REST contract tests.

The three compliance endpoints mounted by ``sentinel_hft.server.demo_api``
are stateless and read-mostly. The UI binds tightly to their shape, so
this module asserts the wire contract:

    GET /api/compliance/crosswalk         -> {entries[], live_counter_keys[], count}
    GET /api/compliance/live-counter-keys -> {keys[]}
    GET /api/compliance/snapshot-shape    -> ComplianceSnapshot.as_dict()

Each endpoint must round-trip cleanly through TestClient and stay in
parity with the underlying registry / dataclass.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from sentinel_hft.compliance import ComplianceSnapshot
from sentinel_hft.compliance.crosswalk import (
    CROSSWALK,
    crosswalk_as_dict,
    live_counter_keys,
)
from sentinel_hft.server.app import app


# ---------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------
# /api/compliance/crosswalk
# ---------------------------------------------------------------------


def test_crosswalk_endpoint_count_matches_registry(client: TestClient):
    r = client.get("/api/compliance/crosswalk")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert set(payload.keys()) == {"entries", "live_counter_keys", "count"}
    assert payload["count"] == len(CROSSWALK)
    assert len(payload["entries"]) == len(CROSSWALK)


def test_crosswalk_endpoint_payload_matches_registry(client: TestClient):
    """The wire payload must equal ``crosswalk_as_dict()`` row-for-row.
    Any drift breaks the /sentinel/regulations table."""
    r = client.get("/api/compliance/crosswalk")
    payload = r.json()
    expected = crosswalk_as_dict()
    assert payload["entries"] == expected
    # Order is significant — the UI renders rows in this order.
    assert (
        [row["key"] for row in payload["entries"]]
        == [row["key"] for row in expected]
    )


def test_crosswalk_endpoint_live_counter_keys_match_helper(
        client: TestClient):
    r = client.get("/api/compliance/crosswalk")
    payload = r.json()
    assert payload["live_counter_keys"] == live_counter_keys()


# ---------------------------------------------------------------------
# /api/compliance/live-counter-keys
# ---------------------------------------------------------------------


def test_live_counter_keys_endpoint(client: TestClient):
    r = client.get("/api/compliance/live-counter-keys")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert set(payload.keys()) == {"keys"}
    assert payload["keys"] == live_counter_keys()


def test_live_counter_keys_endpoint_subset_of_snapshot_fields(
        client: TestClient):
    """Every live_counter key must be a real ComplianceSnapshot field."""
    r = client.get("/api/compliance/live-counter-keys")
    payload = r.json()
    snap_fields = {f.name for f in dataclasses.fields(ComplianceSnapshot)}
    assert set(payload["keys"]).issubset(snap_fields)


# ---------------------------------------------------------------------
# /api/compliance/snapshot-shape
# ---------------------------------------------------------------------


def test_snapshot_shape_endpoint_keys_match_dataclass(client: TestClient):
    r = client.get("/api/compliance/snapshot-shape")
    assert r.status_code == 200, r.text
    payload = r.json()
    expected = {f.name for f in dataclasses.fields(ComplianceSnapshot)}
    assert set(payload.keys()) == expected


def test_snapshot_shape_endpoint_values_are_dicts(client: TestClient):
    r = client.get("/api/compliance/snapshot-shape")
    payload = r.json()
    for key, value in payload.items():
        assert isinstance(value, dict), (
            f"snapshot field {key!r} must be a dict, got {type(value)!r}"
        )


def test_snapshot_shape_endpoint_zero_state(client: TestClient):
    """Before any drill runs, the counter blocks must be at their
    zero-state (no fills, no rejects, no alerts). The UI uses this
    payload to render the dashboard with empty cells."""
    r = client.get("/api/compliance/snapshot-shape")
    payload = r.json()
    # mifid_otr starts at zero orders / zero trades.
    assert payload["mifid_otr"]["total_orders"] == 0
    assert payload["mifid_otr"]["total_trades"] == 0
    # cftc_self_trade has no traders yet.
    assert payload["cftc_self_trade"]["checked"] == 0
    assert payload["cftc_self_trade"]["rejected"] == 0
    # finra_fat_finger has no checks yet.
    assert payload["finra_fat_finger"]["checked"] == 0
    assert payload["finra_fat_finger"]["rejected"] == 0
    # mar_abuse has no alerts.
    assert payload["mar_abuse"]["alerts"] == 0


def test_snapshot_shape_endpoint_is_json_safe(client: TestClient):
    r = client.get("/api/compliance/snapshot-shape")
    assert r.headers.get("content-type", "").startswith("application/json")
    # Round-trip — assert no NaN / inf escapes that would break the UI's
    # JSON.parse.
    payload = r.json()
    assert json.loads(json.dumps(payload)) == payload
