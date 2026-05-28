"""
Time-bound auditor tokens.

A token grants read access to a specific (from_seq, to_seq) range until
`expires_at`. The token is signed with ed25519 (or the HMAC fallback
from policy.signer); the store verifies the signature on every read
and refuses any token outside its declared window.

Tokens are NOT bearer-only — the store also logs every access into a
separate access ledger (`store.log_access`) so the audit system's
A-Chain axis can detect after-the-fact misuse.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
from dataclasses import dataclass, asdict
from typing import Tuple

from sentinel_hft.policy.signer import KeyPair, sign_blob, verify_blob, SigError


class TokenError(Exception):
    """Token failed verification (bad sig, expired, scope mismatch)."""


@dataclass
class AuditorToken:
    aud: str                    # auditor name
    from_seq: int
    to_seq: int
    issued_at: str              # ISO8601 UTC
    expires_at: str             # ISO8601 UTC
    sig_b64: str                # detached signature, base64

    def payload_bytes(self) -> bytes:
        d = {
            "aud": self.aud,
            "from_seq": self.from_seq,
            "to_seq": self.to_seq,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }
        return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_token(
    aud: str,
    from_seq: int,
    to_seq: int,
    keypair: KeyPair,
    expires_in_seconds: int = 3600,
) -> AuditorToken:
    now = dt.datetime.utcnow()
    issued_at = now.isoformat() + "Z"
    expires_at = (now + dt.timedelta(seconds=expires_in_seconds)).isoformat() + "Z"
    pre = AuditorToken(
        aud=aud, from_seq=from_seq, to_seq=to_seq,
        issued_at=issued_at, expires_at=expires_at,
        sig_b64="",
    )
    sig = sign_blob(pre.payload_bytes(), keypair)
    pre.sig_b64 = base64.b64encode(sig).decode("ascii")
    return pre


def verify_token(token: AuditorToken, pub: bytes) -> None:
    """Raise TokenError on any failure."""
    try:
        sig = base64.b64decode(token.sig_b64)
    except Exception:
        raise TokenError("malformed signature encoding")
    try:
        verify_blob(token.payload_bytes(), sig, pub)
    except SigError as e:
        raise TokenError(f"signature: {e}")
    # Expiry check
    try:
        exp = dt.datetime.fromisoformat(token.expires_at.rstrip("Z"))
    except Exception:
        raise TokenError("malformed expires_at")
    if dt.datetime.utcnow() > exp:
        raise TokenError("token expired")
