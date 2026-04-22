"""Workstream 5 -- sidecar alert-chain tests.

Verifies:
* Round-trip encode/decode of single records.
* Hash-chain integrity over a multi-record file.
* Detection of mutated records.
* Detection of deleted records.
* Detection of inserted records.
* Re-open recovers seq + prev_hash for further appends.
* Severity round-trips between str and code.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sentinel_hft.audit.alert_log import (
    ALERT_HEADER_SIZE,
    ALERT_HEADER_STRUCT,
    ALERT_MAGIC,
    ALERT_FORMAT_VERSION,
    AlertChain,
    AlertRecord,
    SEVERITY_ALERT,
    SEVERITY_WARN,
    read_alerts,
    severity_from_str,
    severity_to_str,
    verify_chain,
)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _populate(path: Path, n: int = 5) -> None:
    chain = AlertChain.open(path)
    try:
        for i in range(n):
            chain.append(
                detector="latency_zscore",
                severity="warn" if i % 2 == 0 else "alert",
                detail=f"stage=core latency={1000 + i}ns z={4 + 0.1*i:.2f}",
                score=4.0 + 0.1 * i,
                stage="core",
                timestamp_ns=1_700_000_000_000_000_000 + i * 1_000_000,
                window_n=100 + i,
            )
    finally:
        chain.close()


# ---------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------


def test_encode_decode_round_trip() -> None:
    rec = AlertRecord(
        seq_no=42,
        timestamp_ns=1_700_000_000_123_456_789,
        severity=SEVERITY_ALERT,
        detector="fill_quality_sprt",
        stage=None,
        detail="SPRT accepts H1: bad-fill-rate >> 5%",
        score=4.73,
        window_n=23,
        flags=0,
        prev_hash_lo=b"\xab" * 16,
    )
    rec.full_hash_lo = rec.hash_lo()
    buf = rec.encode()
    got = AlertRecord.decode(buf)
    assert got.seq_no == rec.seq_no
    assert got.timestamp_ns == rec.timestamp_ns
    assert got.severity == rec.severity
    assert got.detector == rec.detector
    assert got.stage is None
    assert got.detail == rec.detail
    # Q32 fixed point round-trip is exact within 1 ulp.
    assert abs(got.score - rec.score) < 1e-9
    assert got.window_n == rec.window_n
    assert got.prev_hash_lo == rec.prev_hash_lo
    assert got.full_hash_lo == rec.full_hash_lo


def test_severity_str_round_trip() -> None:
    assert severity_from_str("warn") == SEVERITY_WARN
    assert severity_from_str("ALERT") == SEVERITY_ALERT
    assert severity_to_str(SEVERITY_ALERT) == "alert"
    with pytest.raises(ValueError):
        severity_from_str("nope")


# ---------------------------------------------------------------------
# Chain integrity
# ---------------------------------------------------------------------


def test_chain_verifies_clean(tmp_path: Path) -> None:
    p = tmp_path / "alerts.alog"
    _populate(p, n=10)
    res = verify_chain(p)
    assert res.chain_ok is True
    assert res.n_records == 10
    assert len(res.head_hash_lo_hex) == 32
    assert res.bad_index is None


def test_chain_seq_no_monotonic(tmp_path: Path) -> None:
    p = tmp_path / "alerts.alog"
    _populate(p, n=5)
    seqs = [r.seq_no for r in read_alerts(p)]
    assert seqs == [0, 1, 2, 3, 4]


def test_mutated_record_breaks_chain(tmp_path: Path) -> None:
    p = tmp_path / "alerts.alog"
    _populate(p, n=5)
    raw = p.read_bytes()
    # Find the second record's score field and bit-flip one byte.
    # Header is 16 bytes. First record framing lives at offset 16.
    off = ALERT_HEADER_SIZE
    (framing0,) = struct.unpack("<I", raw[off:off + 4])
    off += framing0
    # Now we are at record #1's framing. Flip a byte deep in the
    # prev_hash region (offset 41..57 of the prefix). Avoid touching
    # any length field, which would otherwise corrupt framing and
    # raise during decode rather than during verify.
    target = off + 50
    mutated = bytearray(raw)
    mutated[target] ^= 0x01
    p.write_bytes(bytes(mutated))
    res = verify_chain(p)
    assert res.chain_ok is False
    assert res.bad_index is not None
    # Mutating record #1's payload breaks either its own full_hash
    # check, the next record's prev pointer, or (if we hit a length
    # field) the decoder.
    assert (
        res.bad_reason in ("full_hash mismatch", "prev_hash mismatch")
        or res.bad_reason.startswith("decode error:")
    )


def test_deleted_record_breaks_chain(tmp_path: Path) -> None:
    p = tmp_path / "alerts.alog"
    _populate(p, n=4)
    raw = p.read_bytes()
    # Strip the second record (index 1).
    off = ALERT_HEADER_SIZE
    (framing0,) = struct.unpack("<I", raw[off:off + 4])
    rec0_end = off + framing0
    (framing1,) = struct.unpack("<I", raw[rec0_end:rec0_end + 4])
    rec1_end = rec0_end + framing1
    truncated = raw[:rec0_end] + raw[rec1_end:]
    p.write_bytes(truncated)
    res = verify_chain(p)
    assert res.chain_ok is False
    assert res.bad_reason == "prev_hash mismatch"


def test_inserted_record_breaks_chain(tmp_path: Path) -> None:
    p = tmp_path / "alerts.alog"
    _populate(p, n=3)
    # Now hand-craft a fake record with a junk prev_hash and splice it
    # in front of record #1.
    bad = AlertRecord(
        seq_no=99,
        timestamp_ns=0,
        severity=SEVERITY_WARN,
        detector="injected",
        stage=None,
        detail="forged",
        score=0.0,
        prev_hash_lo=b"\xff" * 16,        # wrong on purpose
    )
    bad.full_hash_lo = bad.hash_lo()
    raw = p.read_bytes()
    off = ALERT_HEADER_SIZE
    (framing0,) = struct.unpack("<I", raw[off:off + 4])
    rec0_end = off + framing0
    spliced = raw[:rec0_end] + bad.encode() + raw[rec0_end:]
    p.write_bytes(spliced)
    res = verify_chain(p)
    assert res.chain_ok is False
    # Either the inserted record's prev fails immediately, or the
    # subsequent record's prev fails.
    assert res.bad_reason in ("prev_hash mismatch", "full_hash mismatch")


# ---------------------------------------------------------------------
# Re-open / append
# ---------------------------------------------------------------------


def test_reopen_continues_chain(tmp_path: Path) -> None:
    p = tmp_path / "alerts.alog"
    _populate(p, n=3)
    chain = AlertChain.open(p)
    rec = chain.append(
        detector="reject_rate_cusum",
        severity="alert",
        detail="cusum=5.7 reject_rate=50%",
        score=5.7,
        timestamp_ns=1_700_000_999_000_000_000,
    )
    chain.close()
    assert rec.seq_no == 3
    res = verify_chain(p)
    assert res.chain_ok is True
    assert res.n_records == 4


def test_empty_chain_verifies(tmp_path: Path) -> None:
    p = tmp_path / "alerts.alog"
    chain = AlertChain.open(p)
    chain.close()
    res = verify_chain(p)
    assert res.chain_ok is True
    assert res.n_records == 0


def test_context_manager(tmp_path: Path) -> None:
    p = tmp_path / "alerts.alog"
    with AlertChain.open(p) as chain:
        chain.append(
            detector="x", severity="info", detail="d", score=0.0,
            timestamp_ns=1, stage="s",
        )
    res = verify_chain(p)
    assert res.chain_ok is True
    assert res.n_records == 1


# ---------------------------------------------------------------------
# Bad header
# ---------------------------------------------------------------------


def test_rejects_unknown_magic(tmp_path: Path) -> None:
    p = tmp_path / "bogus.alog"
    p.write_bytes(ALERT_HEADER_STRUCT.pack(b"XXXX", ALERT_FORMAT_VERSION, 0))
    with pytest.raises(ValueError):
        list(read_alerts(p))


def test_rejects_unknown_version(tmp_path: Path) -> None:
    p = tmp_path / "bogus.alog"
    p.write_bytes(ALERT_HEADER_STRUCT.pack(ALERT_MAGIC, 999, 0))
    with pytest.raises(ValueError):
        list(read_alerts(p))
