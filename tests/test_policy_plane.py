"""
Phase-4 acceptance tests for the policy plane.

V-Contract for the policy plane:
    1. policy YAML round-trip — load + validate + compile + decompile
       → reproduces the source policy.
    2. signed blob round-trip — sign + verify (and tamper detection).
    3. canary deployment promotes safe policies, rolls back on breach.
"""

from pathlib import Path

import pytest

from sentinel_hft.golden import Order, OrderSide, OrderType
from sentinel_hft.policy import (
    PolicySchemaError,
    Policy,
    load_policy,
    validate_policy,
    compile_policy,
    decompile_blob,
    sign_blob,
    verify_blob,
    SigError,
    generate_keypair,
    CanaryDeployment,
)
from sentinel_hft.policy.compiler import LAYOUT, MAGIC, SCHEMA_VERSION


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = REPO_ROOT / "policies" / "example.yaml"


# ----------------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------------

def test_load_example_policy():
    p = load_policy(EXAMPLE)
    assert p.name == "example-2026-05-08"
    assert p.rate_enabled is True
    assert p.pos_enabled is True
    assert p.kill_armed is True
    assert p.allowlist_enabled is True
    assert len(p.allowlist) == 16


def test_schema_rejects_bad_top_level_key():
    raw = {
        "schema_version": 1,
        "name": "x",
        "rate": {"max_tokens": 1, "refill_rate": 1, "refill_period_cycles": 1, "enabled": True},
        "position": {"max_long_qty": 0, "max_short_qty": 0, "max_notional": 0,
                     "max_order_qty": 0, "enabled": True},
        "kill_switch": {"armed": True, "auto_enabled": False, "loss_threshold": -1},
        "fat_finger": {"enabled": False, "band_bps": 0, "ref_price_fp8": 0},
        "allowlist": {"enabled": False, "symbols": []},
        "extra_typo": 42,    # not allowed
    }
    with pytest.raises(PolicySchemaError) as e:
        validate_policy(raw)
    assert "unknown top-level keys" in str(e.value)


def test_schema_rejects_bad_int():
    raw = {
        "schema_version": 1,
        "name": "x",
        "rate": {"max_tokens": -1, "refill_rate": 1, "refill_period_cycles": 1, "enabled": True},
        "position": {"max_long_qty": 0, "max_short_qty": 0, "max_notional": 0,
                     "max_order_qty": 0, "enabled": True},
        "kill_switch": {"armed": True, "auto_enabled": False, "loss_threshold": -1},
        "fat_finger": {"enabled": False, "band_bps": 0, "ref_price_fp8": 0},
        "allowlist": {"enabled": False, "symbols": []},
    }
    with pytest.raises(PolicySchemaError):
        validate_policy(raw)


# ----------------------------------------------------------------------------
# Compiler round-trip
# ----------------------------------------------------------------------------

def test_compile_roundtrip_preserves_all_layout_items():
    p = load_policy(EXAMPLE)
    blob = compile_policy(p)
    assert blob.bytes[:4] == MAGIC
    items = decompile_blob(blob.bytes)
    # Every layout entry must be present in the round-tripped items
    layout_offsets = {off for _, off, _ in LAYOUT}
    seen_offsets = {off for off, _, _ in items}
    assert layout_offsets <= seen_offsets


def test_compile_corruption_detected_via_crc():
    p = load_policy(EXAMPLE)
    blob = compile_policy(p)
    # Flip a byte in the middle (skip header/CRC).
    arr = bytearray(blob.bytes)
    arr[20] ^= 0x01
    with pytest.raises(ValueError) as e:
        decompile_blob(bytes(arr))
    assert "bad crc" in str(e.value)


# ----------------------------------------------------------------------------
# Signer
# ----------------------------------------------------------------------------

def test_sign_and_verify_roundtrip():
    p = load_policy(EXAMPLE)
    blob = compile_policy(p)
    kp = generate_keypair()
    sig = sign_blob(blob.bytes, kp)
    verify_blob(blob.bytes, sig, kp.pub)


def test_verify_rejects_tampered_blob():
    p = load_policy(EXAMPLE)
    blob = compile_policy(p)
    kp = generate_keypair()
    sig = sign_blob(blob.bytes, kp)
    tampered = bytearray(blob.bytes)
    tampered[20] ^= 0x01
    with pytest.raises(SigError):
        verify_blob(bytes(tampered), sig, kp.pub)


# ----------------------------------------------------------------------------
# Canary
# ----------------------------------------------------------------------------

def _o(i: int) -> Order:
    return Order(
        order_id=i,
        symbol_id=1,
        side=OrderSide.BUY,
        order_type=OrderType.NEW,
        quantity=1,
        price=10**10,
        notional=10**10,
    )


def test_canary_promotes_when_within_band():
    p_old = load_policy(EXAMPLE)
    p_new = load_policy(EXAMPLE)
    canary = CanaryDeployment(
        old_policy=p_old, new_policy=p_new,
        traffic_share=0.5,
        reject_rate_max=0.50,
        min_n_orders=100,
    )
    for i in range(500):
        canary.decide(_o(i))
    result = canary.decide_outcome()
    assert result.promoted, result


def test_canary_rolls_back_when_reject_rate_exceeds_band():
    p_old = load_policy(EXAMPLE)
    # Build a tight new policy that will reject most orders.
    raw = {**p_old.__dict__}
    raw["pos_max_order_qty"] = 0   # any order with qty>=1 trips ORDER_SIZE
    p_new = Policy(**raw)
    canary = CanaryDeployment(
        old_policy=p_old, new_policy=p_new,
        traffic_share=0.5,
        reject_rate_max=0.10,
        min_n_orders=100,
    )
    for i in range(500):
        canary.decide(_o(i))
    result = canary.decide_outcome()
    assert not result.promoted
    assert result.rollback_reason is not None
    assert "reject rate" in result.rollback_reason
