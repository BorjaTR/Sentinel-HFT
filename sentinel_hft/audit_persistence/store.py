"""
Persistence backends for audit-chain segments.

Phase-5 ships a filesystem store. Production deployments swap in an
S3-with-object-lock backend implementing the same protocol; the
filesystem store is faithful enough for V-Chain and A-Chain to verify
end-to-end without a real cloud bucket.

WORM property is enforced at the protocol level: `append` is the only
write method; segments are addressed by their monotonic sequence number
and the store refuses to overwrite an existing seq. Tampering at the
filesystem level is detected by V-Tamper / chain replay (see verifier.py).
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Protocol

from sentinel_hft.golden import ChainSegment


@dataclass
class RetentionPolicy:
    """How long a segment must be retained before it can be expunged.
    Phase-5 defaults to 7 years (US/UK regulator typical).
    """
    years: int = 7

    @property
    def seconds(self) -> int:
        return self.years * 365 * 24 * 3600


class Store(Protocol):
    def append(self, segment: ChainSegment, key: bytes) -> None: ...
    def read_range(self, from_seq: int, to_seq: int) -> List[ChainSegment]: ...
    def head_seq(self) -> int: ...


# -----------------------------------------------------------------------------
# Filesystem (append-only JSONL with rolling segment files)
# -----------------------------------------------------------------------------

@dataclass
class FilesystemStore:
    root: Path
    retention: RetentionPolicy = field(default_factory=RetentionPolicy)
    _max_seq: int = 0
    _key_id: Optional[str] = None

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        # Pick up existing max_seq if the store has been used before.
        for f in sorted(self.root.glob("seg-*.jsonl")):
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                d = json.loads(line)
                if d["seq"] > self._max_seq:
                    self._max_seq = d["seq"]

    def head_seq(self) -> int:
        return self._max_seq

    def append(self, segment: ChainSegment, key: bytes) -> None:
        if segment.seq <= self._max_seq:
            raise ValueError(f"refusing to overwrite seq={segment.seq} (head={self._max_seq})")
        # WORM emulation: write to a daily roll.
        day = dt.datetime.utcnow().strftime("%Y%m%d")
        fp = self.root / f"seg-{day}.jsonl"
        record = {
            "seq": segment.seq,
            "decision_hex": segment.decision_bytes.hex(),
            "head_hex": segment.head_after.hex(),
            "stored_at": dt.datetime.utcnow().isoformat() + "Z",
            "retention_until": (
                dt.datetime.utcnow()
                + dt.timedelta(seconds=self.retention.seconds)
            ).isoformat() + "Z",
            "key_id": self._key_id,
        }
        with fp.open("a") as f:
            f.write(json.dumps(record) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._max_seq = segment.seq

    def read_range(self, from_seq: int, to_seq: int) -> List[ChainSegment]:
        out: List[ChainSegment] = []
        for fp in sorted(self.root.glob("seg-*.jsonl")):
            for line in fp.read_text().splitlines():
                if not line.strip():
                    continue
                d = json.loads(line)
                if from_seq <= d["seq"] <= to_seq:
                    out.append(ChainSegment(
                        seq=d["seq"],
                        decision_bytes=bytes.fromhex(d["decision_hex"]),
                        head_after=bytes.fromhex(d["head_hex"]),
                    ))
        out.sort(key=lambda s: s.seq)
        return out

    def set_key_id(self, key_id: str) -> None:
        self._key_id = key_id

    # Access-ledger for A-Chain to walk
    def log_access(self, audience: str, range_seq: tuple) -> None:
        fp = self.root / "access_ledger.jsonl"
        with fp.open("a") as f:
            f.write(json.dumps({
                "ts": dt.datetime.utcnow().isoformat() + "Z",
                "aud": audience,
                "from_seq": range_seq[0],
                "to_seq": range_seq[1],
            }) + "\n")
