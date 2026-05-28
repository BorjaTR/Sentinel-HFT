"""
End-to-end persisted-chain verifier.

Walks every segment in a store, recomputes the BLAKE2b chain from
genesis, and asserts:

  - every stored head matches the recomputed head,
  - sequence numbers are contiguous,
  - retention_until is ≥ stored_at + retention.

Wired into A-Chain. CLI entry: `python -m sentinel_hft.audit_persistence.cli verify --store ...`.
"""

from __future__ import annotations

from typing import List

from sentinel_hft.golden import verify_chain, ChainSegment, ChainVerificationError
from .store import FilesystemStore


class ChainPersistenceError(Exception):
    pass


def verify_persisted_chain(store: FilesystemStore, key: bytes) -> int:
    """Returns count of verified segments. Raises on any error."""
    segments = store.read_range(1, store.head_seq())
    if not segments:
        return 0
    try:
        verify_chain(key, segments)
    except ChainVerificationError as e:
        raise ChainPersistenceError(f"chain verify failed: {e}")
    return len(segments)
