"""
Phase-5: audit-chain persistence.

A chain segment is the (seq, decision_bytes, head_after) tuple emitted
by `sentinel_hft.golden.audit_chain`. Persistence lands those segments
into a WORM-graded store with retention metadata, plus an auditor read
API gated by a time-bound signed token.

The default backend is a filesystem store under `audit_data/` that
writes append-only JSONL segments. A second backend (`s3_object_lock`)
is sketched for production; both implement the same `Store` protocol.

Auditor token: a signed JSON record `{aud, scope, expires_at, sig}`
where `scope` is `[from_seq, to_seq]`. Tokens cannot be backdated, and
each read of the chain is logged into an access ledger that the audit
system's A-Chain axis walks during a periodic audit.
"""

from .store import Store, FilesystemStore, RetentionPolicy
from .tokens import (
    AuditorToken,
    sign_token,
    verify_token,
    TokenError,
)
from .verifier import verify_persisted_chain, ChainPersistenceError

__all__ = [
    "Store",
    "FilesystemStore",
    "RetentionPolicy",
    "AuditorToken",
    "sign_token",
    "verify_token",
    "TokenError",
    "verify_persisted_chain",
    "ChainPersistenceError",
]
