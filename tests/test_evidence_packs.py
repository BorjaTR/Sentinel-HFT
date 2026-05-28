"""Phase-7 acceptance tests for the regulator evidence-pack generator."""

import json
from pathlib import Path

import pytest

from sentinel_hft.evidence import (
    EvidencePack,
    PackBuilder,
    load_template,
    PackError,
)
from sentinel_hft.evidence.generator import verify_pack
from sentinel_hft.policy import generate_keypair


REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "evidence" / "templates"


def _full_builder(reg: str):
    template = load_template(reg, TEMPLATES_DIR)
    pb = PackBuilder(template=template)
    for c in template["clauses"]:
        cid = c["id"]
        if "chain_slice" in c.get("required_evidence", []):
            pb.add_chain_slice(cid, from_seq=1, to_seq=10000, head_hash_hex="ab" * 32)
        if "drill_result" in c.get("required_evidence", []):
            pb.add_drill_result(cid, name="kill_switch", passed=True, evidence_hash_hex="cd" * 32)
        if "counter" in c.get("required_evidence", []):
            pb.add_counter(cid, total=10000, rejected=42)
    return pb


def test_load_template_for_known_regulators():
    for reg in ("mifid_ii_rts_6", "sec_reg_sci", "fca_sysc_19f6"):
        t = load_template(reg, TEMPLATES_DIR)
        assert "clauses" in t
        assert all("id" in c for c in t["clauses"])


def test_load_template_unknown_regulator_raises():
    with pytest.raises(PackError):
        load_template("not_a_real_reg", TEMPLATES_DIR)


def test_pack_build_validates_required_evidence_present():
    pb = _full_builder("mifid_ii_rts_6")
    pack = pb.build(
        regulator="MIFID_II_RTS_6",
        period_from="2026-04-01",
        period_to="2026-04-30",
        policy_name="example-2026-05-08",
        policy_blob_hash="ee" * 32,
    )
    assert len(pack.clauses) >= 4
    for c in pack.clauses:
        assert c["evidence"], f"clause {c['id']} has no evidence"


def test_pack_build_raises_when_evidence_missing():
    template = load_template("mifid_ii_rts_6", TEMPLATES_DIR)
    pb = PackBuilder(template=template)
    # Don't add anything → missing evidence error
    with pytest.raises(PackError):
        pb.build(
            regulator="MIFID_II_RTS_6",
            period_from="...",
            period_to="...",
            policy_name="x",
            policy_blob_hash="ff" * 32,
        )


def test_pack_sign_and_verify_roundtrip():
    pb = _full_builder("sec_reg_sci")
    pack = pb.build(
        regulator="SEC_REG_SCI",
        period_from="2026-04-01",
        period_to="2026-04-30",
        policy_name="example",
        policy_blob_hash="ee" * 32,
    )
    kp = generate_keypair()
    pack.sign(kp)
    verify_pack(pack)


def test_pack_signature_rejects_tamper():
    pb = _full_builder("fca_sysc_19f6")
    pack = pb.build(
        regulator="FCA_SYSC_19F6",
        period_from="2026-04-01",
        period_to="2026-04-30",
        policy_name="example",
        policy_blob_hash="ee" * 32,
    )
    kp = generate_keypair()
    pack.sign(kp)
    # Tamper with a clause title after signing
    pack.clauses[0]["title"] = "TAMPERED"
    with pytest.raises(PackError):
        verify_pack(pack)
