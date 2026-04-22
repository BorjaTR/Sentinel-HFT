"""Tests for the tamper-evident audit log.

Covers:
- Record binary round-trip (exact layout match the RTL claims)
- AuditLogger produces a valid hash chain (happy path)
- Verifier walks a clean chain with zero breaks
- Tampering with a record's payload is caught
- Deleting a record is caught
- Inserting a forged record is caught
- Rewiring prev_hash pointers is caught
- Non-monotonic seq/timestamp are flagged but don't halt the walk
- DORA bundle schema has the expected shape
- Dump_bundle writes a valid file we can re-parse
- CLI round-trip: generate + verify + dump
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sentinel_hft.audit import (  # noqa: E402
    AUDIT_RECORD_SIZE,
    AuditLogger,
    AuditRecord,
    BreakKind,
    RejectReason,
    RiskDecision,
    SEED_PREV_HASH,
    build_bundle,
    dump_bundle,
    read_records,
    verify,
    write_records,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decision(i: int, passed: bool = True,
                   reject_reason: int = int(RejectReason.OK),
                   kill_triggered: bool = False) -> RiskDecision:
    return RiskDecision(
        timestamp_ns=1_000_000 + i * 1_000,
        order_id=1000 + i,
        symbol_id=42,
        quantity=100,
        price=50_000_00000000,
        notional=5_000_000_00000000,
        passed=passed,
        reject_reason=reject_reason,
        kill_triggered=kill_triggered,
        tokens_remaining=50,
        position_after=100 * (i + 1),
        notional_after=5_000_000 * (i + 1),
    )


def _run_stream(n: int = 20, *, inject_kill_at: int = -1,
                inject_reject_at: int = -1) -> list:
    log = AuditLogger()
    for i in range(n):
        d = _make_decision(i)
        if i == inject_kill_at:
            d.kill_triggered = True
            d.passed = False
            d.reject_reason = int(RejectReason.KILL_SWITCH)
        elif i == inject_reject_at:
            d.passed = False
            d.reject_reason = int(RejectReason.POSITION_LIMIT)
        log.log(d)
    return log.records


# ---------------------------------------------------------------------------
# Record layout
# ---------------------------------------------------------------------------

class TestRecord:

    def test_record_size_is_96(self):
        assert AUDIT_RECORD_SIZE == 96

    def test_encode_decode_round_trip(self):
        rec = AuditRecord(
            seq_no=7, timestamp_ns=1_713_600_000_000_000_000,
            order_id=42, symbol_id=9,
            reject_reason=int(RejectReason.KILL_SWITCH),
            flags=0x0003,
            quantity=100, price=50000, notional=5_000_000,
            position_after=-500, notional_after=123,
            tokens_remaining=7, reserved=0,
            prev_hash_lo=b"\xaa" * 16,
        )
        buf = rec.encode()
        assert len(buf) == 96
        back = AuditRecord.decode(buf)
        assert back == rec
        # Signed round-trip.
        assert back.position_after == -500

    def test_encode_rejects_bad_prev_hash(self):
        rec = AuditRecord(
            seq_no=0, timestamp_ns=0, order_id=0, symbol_id=0,
            reject_reason=0, flags=0, quantity=0, price=0,
            notional=0, position_after=0, notional_after=0,
            tokens_remaining=0, reserved=0,
            prev_hash_lo=b"\xaa" * 8,  # wrong size
        )
        with pytest.raises(ValueError):
            rec.encode()

    def test_hash_lo_matches_first16_of_full_hash(self):
        rec = AuditRecord(
            seq_no=0, timestamp_ns=0, order_id=0, symbol_id=0,
            reject_reason=0, flags=1, quantity=100, price=10, notional=1000,
            position_after=0, notional_after=0, tokens_remaining=0,
            reserved=0, prev_hash_lo=SEED_PREV_HASH,
        )
        full = rec.full_hash()
        assert len(full) == 32
        assert rec.hash_lo() == full[:16]


# ---------------------------------------------------------------------------
# Happy-path logger + verifier
# ---------------------------------------------------------------------------

class TestHappyPath:

    def test_logger_chains_records(self):
        log = AuditLogger()
        for i in range(5):
            log.log(_make_decision(i))
        records = log.records
        assert len(records) == 5
        # First record seeds with zeros.
        assert records[0].prev_hash_lo == SEED_PREV_HASH
        # Each subsequent record chains to the previous.
        for prev, curr in zip(records, records[1:]):
            assert curr.prev_hash_lo == prev.hash_lo()

    def test_verify_clean_stream_has_no_breaks(self):
        recs = _run_stream(n=30)
        result = verify(recs)
        assert result.ok
        assert result.total_records == 30
        assert result.verified_records == 30
        assert result.breaks == []
        assert result.head_hash_lo == recs[-1].hash_lo()

    def test_empty_stream_is_ok(self):
        result = verify([])
        assert result.ok
        assert result.total_records == 0
        assert result.verified_records == 0

    def test_head_hash_lo_commits_entire_stream(self):
        """The logger's head_hash_lo should equal the low-128 of the
        last record. That property is what makes the head a
        'commitment': you can attest to the whole audit log by
        publishing 16 bytes."""
        log = AuditLogger()
        for i in range(10):
            log.log(_make_decision(i))
        assert log.head_hash_lo == log.records[-1].hash_lo()


# ---------------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------------

class TestTamperDetection:

    def test_payload_mutation_is_caught(self):
        """Mutating a record's quantity should invalidate its hash, so
        the *next* record's prev pointer no longer matches."""
        recs = _run_stream(n=10)
        # Forge record[4] with a different quantity but keep its
        # encoded-in prev_hash_lo (the attacker tries to slip in a
        # large order silently).
        tampered = AuditRecord(**{**recs[4].__dict__, "quantity": 999_999_999})
        forged = list(recs)
        forged[4] = tampered

        result = verify(forged)
        assert not result.ok
        # The break should appear at seq_no=5 because record 5's
        # prev_hash still points to the *original* record 4.
        prev_breaks = [b for b in result.breaks
                       if b.kind == BreakKind.PREV_HASH_MISMATCH]
        assert any(b.seq_no == 5 for b in prev_breaks)

    def test_deletion_is_caught(self):
        """Removing a record breaks the next record's prev pointer."""
        recs = _run_stream(n=10)
        forged = recs[:4] + recs[5:]  # delete record 4
        result = verify(forged)
        assert not result.ok
        # Record 5 now immediately follows record 3, and the seq is
        # non-monotonic AND the hash is wrong.
        assert any(b.kind == BreakKind.PREV_HASH_MISMATCH for b in result.breaks)
        assert any(b.kind == BreakKind.NON_MONOTONIC_SEQ for b in result.breaks)

    def test_insertion_is_caught(self):
        """Splicing in an attacker-forged record breaks the chain
        immediately at the insertion point."""
        recs = _run_stream(n=10)
        # Forged record with correct-looking shape but arbitrary prev.
        forged_rec = AuditRecord(
            seq_no=999, timestamp_ns=recs[5].timestamp_ns + 1,
            order_id=666, symbol_id=42,
            reject_reason=0, flags=1, quantity=1, price=1, notional=1,
            position_after=0, notional_after=0, tokens_remaining=0,
            reserved=0, prev_hash_lo=b"\x00" * 16,  # plausibly fake
        )
        forged = recs[:5] + [forged_rec] + recs[5:]
        result = verify(forged)
        assert not result.ok
        assert any(b.kind == BreakKind.PREV_HASH_MISMATCH for b in result.breaks)

    def test_rewired_prev_pointer_is_caught(self):
        """An attacker who rewrites one record's prev pointer to
        match its *own* hash still can't fix the next record. This
        guards against 'patch the link' attacks."""
        recs = _run_stream(n=10)
        # Replace record 5's prev_hash_lo with all-zeros; its payload
        # unchanged. The chain still breaks at record 5 because the
        # verifier recomputes and compares.
        tampered = AuditRecord(**{**recs[5].__dict__, "prev_hash_lo": b"\x00" * 16})
        forged = list(recs)
        forged[5] = tampered
        result = verify(forged)
        assert not result.ok
        assert any(
            b.kind == BreakKind.PREV_HASH_MISMATCH and b.seq_no == 5
            for b in result.breaks
        )

    def test_non_monotonic_timestamp_is_flagged_but_chain_still_verifies(self):
        """A backwards timestamp is flagged as a separate kind of
        break; it doesn't invalidate the hash chain itself."""
        log = AuditLogger()
        d0 = _make_decision(0)
        d0.timestamp_ns = 1_000_000
        log.log(d0)
        d1 = _make_decision(1)
        d1.timestamp_ns = 500  # goes backwards
        log.log(d1)
        d2 = _make_decision(2)
        d2.timestamp_ns = 2_000_000
        log.log(d2)
        result = verify(log.records)
        # Hash chain is clean.
        assert not any(b.kind == BreakKind.PREV_HASH_MISMATCH for b in result.breaks)
        # But a timestamp break is recorded.
        assert any(b.kind == BreakKind.NON_MONOTONIC_TIMESTAMP for b in result.breaks)


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

class TestFileIO:

    def test_write_and_read_round_trip(self, tmp_path):
        recs = _run_stream(n=20)
        path = tmp_path / "audit.bin"
        n = write_records(path, recs)
        assert n == 16 + 20 * AUDIT_RECORD_SIZE

        back = list(read_records(path))
        assert len(back) == 20
        for a, b in zip(recs, back):
            assert a == b

        # Round-tripped stream still verifies.
        assert verify(back).ok

    def test_read_rejects_wrong_magic(self, tmp_path):
        (tmp_path / "bad.bin").write_bytes(b"BADMAGIC" + b"\x00" * 88)
        with pytest.raises(ValueError, match="not an audit log"):
            list(read_records(tmp_path / "bad.bin"))


# ---------------------------------------------------------------------------
# DORA bundle
# ---------------------------------------------------------------------------

class TestDORABundle:

    def test_bundle_has_expected_top_level_keys(self):
        recs = _run_stream(n=20, inject_kill_at=12, inject_reject_at=7)
        bundle = build_bundle(recs, subject="KEYROCK/BE/LEI-549300XXXX",
                               environment="uat")
        assert set(bundle.keys()) >= {
            "metadata", "audit_chain", "summary",
            "kill_switch_events", "hard_rejections", "records",
        }

    def test_bundle_reports_head_hash_and_record_count(self):
        recs = _run_stream(n=15)
        bundle = build_bundle(recs)
        chain = bundle["audit_chain"]
        assert chain["record_count"] == 15
        assert chain["head_hash_lo_hex"] == recs[-1].hash_lo().hex()
        assert chain["seed_hex"] == "00" * 16
        assert chain["verification"]["ok"] is True

    def test_bundle_surfaces_kill_event(self):
        recs = _run_stream(n=20, inject_kill_at=10)
        bundle = build_bundle(recs)
        assert bundle["summary"]["kill_switch_events"] == 1
        assert len(bundle["kill_switch_events"]) == 1
        assert bundle["kill_switch_events"][0]["seq_no"] == 10
        assert bundle["kill_switch_events"][0]["reject_reason"] == "KILL_SWITCH"

    def test_bundle_separates_hard_rejects_from_rate_limits(self):
        log = AuditLogger()
        log.log(_make_decision(0))
        d1 = _make_decision(1, passed=False,
                            reject_reason=int(RejectReason.RATE_LIMITED))
        log.log(d1)
        d2 = _make_decision(2, passed=False,
                            reject_reason=int(RejectReason.POSITION_LIMIT))
        log.log(d2)
        bundle = build_bundle(log.records)
        # Hard rejects contains only the position-limit one.
        reasons = [r["reject_reason"] for r in bundle["hard_rejections"]]
        assert "POSITION_LIMIT" in reasons
        assert "RATE_LIMITED" not in reasons

    def test_bundle_reflects_tamper_in_verification(self):
        recs = _run_stream(n=10)
        # Mutate the final record's quantity silently.
        recs[5] = AuditRecord(**{**recs[5].__dict__, "quantity": 999})
        bundle = build_bundle(recs)
        v = bundle["audit_chain"]["verification"]
        assert v["ok"] is False
        kinds = {b["kind"] for b in v["breaks"]}
        assert "prev_hash_mismatch" in kinds

    def test_bundle_is_json_serialisable(self):
        recs = _run_stream(n=5)
        bundle = build_bundle(recs)
        s = json.dumps(bundle)
        # Should round-trip through JSON losslessly.
        back = json.loads(s)
        assert back["audit_chain"]["record_count"] == 5

    def test_dump_bundle_writes_valid_file(self, tmp_path):
        recs = _run_stream(n=8, inject_kill_at=3)
        out = tmp_path / "dora.json"
        head = dump_bundle(recs, out, subject="TEST")
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["audit_chain"]["head_hash_lo_hex"] == head
        assert data["summary"]["kill_switch_events"] == 1
        assert data["metadata"]["subject"] == "TEST"


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

class TestCLI:

    def test_audit_subcommand_round_trip(self, tmp_path):
        import subprocess

        env_root = Path(__file__).parent.parent
        log = tmp_path / "a.aud"
        out = tmp_path / "dora.json"

        # Generate
        r = subprocess.run(
            [sys.executable, "-m", "sentinel_hft.cli.main",
             "audit", "generate",
             "-n", "50",
             "--inject-kill-at", "20",
             "--inject-reject-at", "10",
             "-o", str(log),
             "-q"],
            cwd=env_root, capture_output=True, text=True,
        )
        assert r.returncode == 0, f"generate failed: {r.stderr}"
        assert log.exists()

        # Verify
        r = subprocess.run(
            [sys.executable, "-m", "sentinel_hft.cli.main",
             "audit", "verify",
             "-i", str(log),
             "-q"],
            cwd=env_root, capture_output=True, text=True,
        )
        assert r.returncode == 0, f"verify failed: {r.stderr}"

        # DORA bundle export
        r = subprocess.run(
            [sys.executable, "-m", "sentinel_hft.cli.main",
             "audit", "dora",
             "-i", str(log),
             "-o", str(out),
             "--subject", "TEST/LEI-549300",
             "--environment", "sim",
             "-q"],
            cwd=env_root, capture_output=True, text=True,
        )
        assert r.returncode == 0, f"dora export failed: {r.stderr}"
        assert out.exists()
        bundle = json.loads(out.read_text())
        assert bundle["metadata"]["subject"] == "TEST/LEI-549300"
        assert bundle["summary"]["kill_switch_events"] == 1
        assert bundle["audit_chain"]["record_count"] == 50
