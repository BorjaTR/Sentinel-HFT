"""
Behavioral golden model for the Sentinel BLAKE2b-keyed audit chain.

Mirrors the semantics of `rtl/risk_audit_log.sv`. This module is the
reference V-Tamper compares the deployed chain logic against.

Chain construction:
    head_0    = BLAKE2b(key, b"\\x00" * 32)         # genesis
    head_n+1  = BLAKE2b(key, head_n || decision_n)
    seq_n+1   = seq_n + 1

A chain segment is the tuple:
    (seq, decision_bytes, head_after)

Verification:
    Walk the segments in order. For each segment i, recompute
    head'_i = BLAKE2b(key, head_{i-1} || decision_i)
    Assert head'_i == head_i. Assert seq_i == seq_{i-1} + 1.
    Any mismatch = chain tampered.

Decision bytes encoding (24 bytes, fixed):
    [0:8]   little-endian u64 order_id
    [8:12]  little-endian u32 symbol_id
    [12]    side (1=BUY, 2=SELL)
    [13]    order_type (1=NEW, 2=CANCEL, 3=MODIFY, 15=HEARTBEAT)
    [14]    passed (0/1)
    [15]    reject_reason (u8)
    [16:24] little-endian u64 timestamp (cycles since boot)

This encoding is the same one risk_audit_log.sv emits onto its hash
input. V-Parity (when run on RTL) will assert that the bytes the RTL
emits match what this module computes for the same decisions.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import List, Tuple

from .risk_gate import Decision, Order, RejectReason


# -----------------------------------------------------------------------------
# Encoding
# -----------------------------------------------------------------------------

DECISION_BYTES = 24
HEAD_BYTES = 32
GENESIS_INPUT = b"\x00" * HEAD_BYTES


def encode_decision(order: Order, decision: Decision, timestamp: int) -> bytes:
    """Pack a (order, decision) into the 24-byte chain payload."""
    out = bytearray(DECISION_BYTES)
    out[0:8]   = int(order.order_id).to_bytes(8, "little")
    out[8:12]  = int(order.symbol_id).to_bytes(4, "little")
    out[12]    = int(order.side) & 0xFF
    out[13]    = int(order.order_type) & 0xFF
    out[14]    = 1 if decision.passed else 0
    out[15]    = int(decision.reason) & 0xFF
    out[16:24] = (int(timestamp) & ((1 << 64) - 1)).to_bytes(8, "little")
    return bytes(out)


# -----------------------------------------------------------------------------
# Chain
# -----------------------------------------------------------------------------

@dataclass
class ChainSegment:
    seq: int
    decision_bytes: bytes
    head_after: bytes        # 32 bytes


class GoldenAuditChain:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("key must be 32 bytes")
        self._key = key
        self._head = self._hash(GENESIS_INPUT)
        self._seq = 0
        self._segments: List[ChainSegment] = []

    @property
    def head(self) -> bytes:
        return self._head

    @property
    def seq(self) -> int:
        return self._seq

    @property
    def segments(self) -> List[ChainSegment]:
        return list(self._segments)

    def _hash(self, data: bytes) -> bytes:
        return hashlib.blake2b(data, digest_size=HEAD_BYTES, key=self._key).digest()

    def append(self, decision_bytes: bytes) -> ChainSegment:
        if len(decision_bytes) != DECISION_BYTES:
            raise ValueError("decision_bytes must be DECISION_BYTES long")
        new_head = self._hash(self._head + decision_bytes)
        self._seq += 1
        seg = ChainSegment(
            seq=self._seq,
            decision_bytes=decision_bytes,
            head_after=new_head,
        )
        self._head = new_head
        self._segments.append(seg)
        return seg


# -----------------------------------------------------------------------------
# Verification
# -----------------------------------------------------------------------------

class ChainVerificationError(Exception):
    """Raised when a chain replay disagrees with the recorded heads."""

    def __init__(self, kind: str, at_seq: int, detail: str = "") -> None:
        super().__init__(f"{kind} at seq={at_seq}: {detail}")
        self.kind = kind
        self.at_seq = at_seq
        self.detail = detail


def verify_chain(key: bytes, segments: List[ChainSegment]) -> None:
    """Replay a chain from genesis. Raise ChainVerificationError on tamper."""
    if len(key) != 32:
        raise ValueError("key must be 32 bytes")
    expected_head = hashlib.blake2b(
        GENESIS_INPUT, digest_size=HEAD_BYTES, key=key
    ).digest()
    expected_seq = 0
    for s in segments:
        expected_seq += 1
        if s.seq != expected_seq:
            raise ChainVerificationError(
                "sequence_gap", at_seq=s.seq,
                detail=f"expected {expected_seq}, got {s.seq}",
            )
        recomputed = hashlib.blake2b(
            expected_head + s.decision_bytes,
            digest_size=HEAD_BYTES,
            key=key,
        ).digest()
        if recomputed != s.head_after:
            raise ChainVerificationError(
                "hash_mismatch", at_seq=s.seq,
                detail="recomputed head does not match stored head",
            )
        expected_head = s.head_after
