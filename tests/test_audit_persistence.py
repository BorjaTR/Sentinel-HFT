"""Phase-5 acceptance tests for the audit-chain persistence layer."""

import hashlib
from pathlib import Path

import pytest

from sentinel_hft.golden import GoldenAuditChain, encode_decision
from sentinel_hft.golden.risk_gate import (
    Decision,
    Order,
    OrderSide,
    OrderType,
    RejectReason,
)
from sentinel_hft.audit_persistence import (
    FilesystemStore,
    RetentionPolicy,
    sign_token,
    verify_token,
    TokenError,
    verify_persisted_chain,
    ChainPersistenceError,
)
from sentinel_hft.policy import generate_keypair


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def _build_chain(n: int = 50):
    key = hashlib.sha256(b"phase5-test-key").digest()
    chain = GoldenAuditChain(key)
    for i in range(n):
        order = Order(
            order_id=i,
            symbol_id=1,
            side=OrderSide.BUY,
            order_type=OrderType.NEW,
            quantity=1,
            price=10**10,
            notional=10**10,
        )
        d = Decision(
            passed=(i % 5 != 0),
            reason=RejectReason.OK if (i % 5 != 0) else RejectReason.RATE_LIMITED,
            tokens_remaining=0, current_position=0, current_notional=0,
        )
        chain.append(encode_decision(order, d, timestamp=i))
    return key, chain


# ----------------------------------------------------------------------------
# Filesystem store
# ----------------------------------------------------------------------------

def test_store_append_and_read_range(tmp_path):
    store = FilesystemStore(root=tmp_path)
    key, chain = _build_chain(20)
    for s in chain.segments:
        store.append(s, key)
    out = store.read_range(1, 20)
    assert len(out) == 20
    for src, dst in zip(chain.segments, out):
        assert src.seq == dst.seq
        assert src.decision_bytes == dst.decision_bytes
        assert src.head_after == dst.head_after


def test_store_refuses_overwrite_of_existing_seq(tmp_path):
    store = FilesystemStore(root=tmp_path)
    key, chain = _build_chain(5)
    for s in chain.segments:
        store.append(s, key)
    with pytest.raises(ValueError):
        store.append(chain.segments[0], key)


def test_persisted_chain_verifies_clean(tmp_path):
    store = FilesystemStore(root=tmp_path)
    key, chain = _build_chain(40)
    for s in chain.segments:
        store.append(s, key)
    n = verify_persisted_chain(store, key)
    assert n == 40


def test_persisted_chain_detects_disk_tamper(tmp_path):
    import json as _json
    store = FilesystemStore(root=tmp_path)
    key, chain = _build_chain(30)
    for s in chain.segments:
        store.append(s, key)
    # Tamper: rewrite the JSONL file with a corrupted decision payload
    # in the middle of the chain (segment idx 5).
    files = list(tmp_path.glob("seg-*.jsonl"))
    assert files
    lines = files[0].read_text().splitlines()
    rec = _json.loads(lines[5])
    rec["decision_hex"] = "00" * len(bytes.fromhex(rec["decision_hex"]))
    lines[5] = _json.dumps(rec)
    files[0].write_text("\n".join(lines) + "\n")
    with pytest.raises(ChainPersistenceError):
        verify_persisted_chain(store, key)


# ----------------------------------------------------------------------------
# Auditor tokens
# ----------------------------------------------------------------------------

def test_token_sign_and_verify():
    kp = generate_keypair()
    token = sign_token("auditor-X", 1, 100, kp, expires_in_seconds=3600)
    verify_token(token, kp.pub)


def test_token_rejected_after_expiry():
    kp = generate_keypair()
    token = sign_token("auditor-X", 1, 100, kp, expires_in_seconds=-10)
    with pytest.raises(TokenError) as e:
        verify_token(token, kp.pub)
    assert "expired" in str(e.value)


def test_token_rejected_on_tamper():
    kp = generate_keypair()
    token = sign_token("auditor-X", 1, 100, kp, expires_in_seconds=3600)
    token.aud = "bad-actor"
    with pytest.raises(TokenError):
        verify_token(token, kp.pub)
