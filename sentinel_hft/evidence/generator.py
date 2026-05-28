"""
Evidence-pack generator.

A pack manifest is a JSON document of the form:

    {
      "schema_version": 1,
      "regulator": "MIFID_II_RTS_6",
      "period": {"from": "...", "to": "..."},
      "policy": {"name": "...", "blob_hash": "..."},
      "clauses": [
        {
          "id": "RTS6.1.1",
          "title": "...",
          "evidence": [
            {"kind": "chain_slice", "from_seq": 1, "to_seq": 100, "head_hash": "..."},
            {"kind": "drill_result", "name": "kill_switch", "passed": true, "hash": "..."},
            ...
          ]
        }, ...
      ],
      "signature_b64": "...",
      "pubkey_hex": "..."
    }

Templates list the evidence kinds expected per clause. The builder
validates every clause has the required evidence before signing.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sentinel_hft.policy.signer import KeyPair, sign_blob, verify_blob, SigError


class PackError(Exception):
    pass


SCHEMA_VERSION = 1


@dataclass
class EvidencePack:
    regulator: str
    period_from: str
    period_to: str
    policy_name: str
    policy_blob_hash: str
    clauses: List[Dict[str, Any]] = field(default_factory=list)
    signature_b64: Optional[str] = None
    pubkey_hex: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "regulator": self.regulator,
            "period": {"from": self.period_from, "to": self.period_to},
            "policy": {"name": self.policy_name, "blob_hash": self.policy_blob_hash},
            "clauses": self.clauses,
            "signature_b64": self.signature_b64,
            "pubkey_hex": self.pubkey_hex,
        }

    def payload_bytes(self) -> bytes:
        d = self.to_dict()
        # Signature does not cover itself.
        d_for_sig = {**d, "signature_b64": None, "pubkey_hex": None}
        return json.dumps(d_for_sig, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def sign(self, kp: KeyPair) -> None:
        sig = sign_blob(self.payload_bytes(), kp)
        self.signature_b64 = base64.b64encode(sig).decode("ascii")
        self.pubkey_hex = kp.pub.hex()


def load_template(reg: str, templates_dir: Path) -> Dict[str, Any]:
    import yaml  # type: ignore
    fp = templates_dir / f"{reg.lower()}.yaml"
    if not fp.exists():
        raise PackError(f"no template for regulator {reg!r}: expected {fp}")
    return yaml.safe_load(fp.read_text())


@dataclass
class PackBuilder:
    template: Dict[str, Any]
    chain_slices: Dict[str, Any] = field(default_factory=dict)   # clause_id -> slice
    drill_results: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    counters: Dict[str, int] = field(default_factory=dict)

    def add_chain_slice(self, clause_id: str, from_seq: int, to_seq: int, head_hash_hex: str) -> None:
        self.chain_slices[clause_id] = {
            "kind": "chain_slice",
            "from_seq": from_seq,
            "to_seq": to_seq,
            "head_hash": head_hash_hex,
        }

    def add_drill_result(self, clause_id: str, name: str, passed: bool, evidence_hash_hex: str) -> None:
        self.drill_results.setdefault(clause_id, []).append({
            "kind": "drill_result",
            "name": name,
            "passed": passed,
            "hash": evidence_hash_hex,
        })

    def add_counter(self, clause_id: str, **kwargs: int) -> None:
        for name, value in kwargs.items():
            self.counters[f"{clause_id}::{name}"] = value

    def build(
        self,
        regulator: str,
        period_from: str,
        period_to: str,
        policy_name: str,
        policy_blob_hash: str,
    ) -> EvidencePack:
        pack = EvidencePack(
            regulator=regulator,
            period_from=period_from,
            period_to=period_to,
            policy_name=policy_name,
            policy_blob_hash=policy_blob_hash,
        )
        for c in self.template.get("clauses", []):
            cid = c["id"]
            evidence: List[Dict[str, Any]] = []
            if "chain_slice" in c.get("required_evidence", []):
                if cid not in self.chain_slices:
                    raise PackError(f"clause {cid}: missing chain_slice")
                evidence.append(self.chain_slices[cid])
            if "drill_result" in c.get("required_evidence", []):
                drs = self.drill_results.get(cid, [])
                if not drs:
                    raise PackError(f"clause {cid}: missing drill_result")
                evidence.extend(drs)
            if "counter" in c.get("required_evidence", []):
                ctrs = {k.split("::", 1)[1]: v for k, v in self.counters.items()
                        if k.startswith(cid + "::")}
                if not ctrs:
                    raise PackError(f"clause {cid}: missing counters")
                evidence.append({"kind": "counter", "values": ctrs})
            pack.clauses.append({
                "id": cid,
                "title": c.get("title", ""),
                "evidence": evidence,
            })
        return pack


def verify_pack(pack: EvidencePack) -> None:
    if not pack.signature_b64 or not pack.pubkey_hex:
        raise PackError("pack is unsigned")
    sig = base64.b64decode(pack.signature_b64)
    pub = bytes.fromhex(pack.pubkey_hex)
    try:
        verify_blob(pack.payload_bytes(), sig, pub)
    except SigError as e:
        raise PackError(f"signature verify failed: {e}")
