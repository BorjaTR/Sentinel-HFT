"""
Phase-7: regulator evidence packs.

A pack is a clause-indexed bundle of evidence for a regulator over a
date range. The generator pulls from:

    - audit-chain segments (Phase 5)
    - drill results (existing)
    - active policy version (Phase 4)
    - gate decision counters

…and emits a signed JSON manifest. Each clause cites a specific evidence
item by hash, so the auditor can independently verify any claim.

Templates live in `evidence/templates/<regulator>.yaml`. Phase 7 ships
templates for SEC Reg SCI, MiFID II RTS 6, FCA SYSC 19F.6, ASIC RG 241,
MAS Notice SFA 04-N09. Each template lists clauses + the evidence types
expected per clause.
"""

from .generator import (
    EvidencePack,
    PackBuilder,
    load_template,
    PackError,
)

__all__ = [
    "EvidencePack",
    "PackBuilder",
    "load_template",
    "PackError",
]
