"""Binary reader for a captured Hyperliquid tick stream.

Pairs with :mod:`sentinel_hft.hyperliquid.collector`. The on-disk
format is intentionally small and self-describing so the file can be
diffed between runs and scanned without the repo's installed code.

File layout
-----------

::

    [ 16-byte header ]
    [ record 0 ]
    [ record 1 ]
    ...

Header (16 bytes, little-endian):

* 4 bytes  -- magic ``b"HLTK"`` ("HyperLiquid TicKs")
* 2 bytes  -- format version (currently ``1``)
* 2 bytes  -- record size (currently ``96``)
* 8 bytes  -- base timestamp (ns); a reader can recompute wall-clock
              time by adding each record's ``wire_ts_ns`` delta.

Record (96 bytes, little-endian; ``struct`` format
``<QQIHBBddddddIH``):

* ``Q`` (u64) wire_ts_ns
* ``Q`` (u64) host_ts_ns
* ``I`` (u32) seq_no
* ``H`` (u16) symbol_id
* ``B`` (u8)  kind  (1=QUOTE, 2=TRADE)
* ``B`` (u8)  profile  (fixture-only, 0 on real captures)
* ``d`` (f64) bid_price
* ``d`` (f64) ask_price
* ``d`` (f64) bid_size
* ``d`` (f64) ask_size
* ``d`` (f64) trade_price
* ``d`` (f64) trade_size
* ``I`` (u32) taker_id_lo
* ``H`` (u16) taker_id_hi  (taker_id = hi << 32 | lo; HL user hashes fit easily)

Everything is in fixed byte order so a captured file is reproducible
across platforms. The reader rehydrates :class:`HLTickEvent` with the
full :class:`HyperliquidInstrument` dataclass (looked up by
``symbol_id`` in the HL universe).

Why not Parquet/Arrow?
----------------------

This format is meant for demo provenance ("this demo ran on a binary
file that was captured from the real wire"), not analytics. Arrow
would pull in 40MB of deps for no win; a flat struct keeps the package
importable with only the stdlib.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List

from ..deribit.fixture import TickKind
from .fixture import HLTickEvent
from .instruments import HL_DEFAULT_UNIVERSE, HyperliquidInstrument, hl_by_id


HL_TICK_MAGIC = b"HLTK"
HL_TICK_VERSION = 1
HL_TICK_HEADER_STRUCT = struct.Struct("<4sHHQ")
HL_TICK_HEADER_SIZE = 16
assert HL_TICK_HEADER_STRUCT.size == HL_TICK_HEADER_SIZE

HL_TICK_RECORD_STRUCT = struct.Struct("<QQIHBBddddddIH")
HL_TICK_RECORD_SIZE = HL_TICK_RECORD_STRUCT.size  # 96


@dataclass
class HLTickFileHeader:
    """Parsed header of an HL tick capture."""

    magic: bytes
    version: int
    record_size: int
    base_ts_ns: int

    @classmethod
    def decode(cls, data: bytes) -> "HLTickFileHeader":
        if len(data) != HL_TICK_HEADER_SIZE:
            raise ValueError(
                f"HL tick header must be {HL_TICK_HEADER_SIZE} bytes, "
                f"got {len(data)}"
            )
        magic, version, rec_size, base_ts_ns = HL_TICK_HEADER_STRUCT.unpack(data)
        if magic != HL_TICK_MAGIC:
            raise ValueError(
                f"not an HL tick capture (magic={magic!r})"
            )
        if rec_size != HL_TICK_RECORD_SIZE:
            raise ValueError(
                f"unexpected HL tick record size {rec_size}, "
                f"expected {HL_TICK_RECORD_SIZE}"
            )
        if version != HL_TICK_VERSION:
            raise ValueError(
                f"unsupported HL tick capture version {version}"
            )
        return cls(
            magic=magic, version=version,
            record_size=rec_size, base_ts_ns=base_ts_ns,
        )

    def encode(self) -> bytes:
        return HL_TICK_HEADER_STRUCT.pack(
            HL_TICK_MAGIC, self.version, self.record_size, self.base_ts_ns,
        )


# ---------------------------------------------------------------------
# Low-level (de)serialisation
# ---------------------------------------------------------------------


def pack_event(ev: HLTickEvent) -> bytes:
    """Serialise one :class:`HLTickEvent` to 96 bytes."""
    taker_lo = ev.taker_id & 0xFFFFFFFF
    taker_hi = (ev.taker_id >> 32) & 0xFFFF
    return HL_TICK_RECORD_STRUCT.pack(
        ev.wire_ts_ns,
        ev.host_ts_ns,
        ev.seq_no & 0xFFFFFFFF,
        ev.instrument.symbol_id,
        int(ev.kind),
        ev.profile & 0xFF,
        ev.bid_price,
        ev.ask_price,
        ev.bid_size,
        ev.ask_size,
        ev.trade_price,
        ev.trade_size,
        taker_lo,
        taker_hi,
    )


def unpack_event(
    data: bytes,
    *,
    universe_by_id: dict = None,
) -> HLTickEvent:
    """Decode a 96-byte record to an :class:`HLTickEvent`."""
    if len(data) != HL_TICK_RECORD_SIZE:
        raise ValueError(
            f"HL tick record must be {HL_TICK_RECORD_SIZE} bytes, "
            f"got {len(data)}"
        )
    universe_by_id = universe_by_id or hl_by_id()
    u = HL_TICK_RECORD_STRUCT.unpack(data)
    (wire_ts, host_ts, seq, sym_id, kind_i, prof,
     bid, ask, bsz, asz, trade_px, trade_sz,
     t_lo, t_hi) = u
    ins = universe_by_id.get(sym_id)
    if ins is None:
        raise ValueError(
            f"unknown symbol_id {sym_id:#06x} in HL capture"
        )
    return HLTickEvent(
        wire_ts_ns=wire_ts,
        host_ts_ns=host_ts,
        seq_no=seq,
        instrument=ins,
        kind=TickKind(kind_i),
        bid_price=bid,
        ask_price=ask,
        bid_size=bsz,
        ask_size=asz,
        trade_price=trade_px,
        trade_size=trade_sz,
        taker_id=(int(t_hi) << 32) | int(t_lo),
        profile=prof,
    )


# ---------------------------------------------------------------------
# High-level writers / readers
# ---------------------------------------------------------------------


def write_events(path, events, base_ts_ns: int = 0) -> int:
    """Write a header + stream of events to ``path``. Returns bytes written."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("wb") as f:
        header = HLTickFileHeader(
            magic=HL_TICK_MAGIC,
            version=HL_TICK_VERSION,
            record_size=HL_TICK_RECORD_SIZE,
            base_ts_ns=base_ts_ns,
        )
        f.write(header.encode())
        n += HL_TICK_HEADER_SIZE
        for ev in events:
            buf = pack_event(ev)
            f.write(buf)
            n += len(buf)
    return n


def read_events(path) -> Iterator[HLTickEvent]:
    """Yield :class:`HLTickEvent` records from a capture file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    universe_by_id = hl_by_id()
    with p.open("rb") as f:
        head = f.read(HL_TICK_HEADER_SIZE)
        if len(head) < HL_TICK_HEADER_SIZE:
            raise ValueError(f"HL capture too small: {p}")
        HLTickFileHeader.decode(head)  # raises on mismatch
        while True:
            buf = f.read(HL_TICK_RECORD_SIZE)
            if not buf:
                return
            if len(buf) != HL_TICK_RECORD_SIZE:
                raise ValueError(
                    f"truncated HL tick record in {p}: got {len(buf)}"
                )
            yield unpack_event(buf, universe_by_id=universe_by_id)


def count_events(path) -> int:
    """Fast count of events in a capture (no decoding)."""
    p = Path(path)
    size = p.stat().st_size
    if size < HL_TICK_HEADER_SIZE:
        return 0
    body = size - HL_TICK_HEADER_SIZE
    if body % HL_TICK_RECORD_SIZE != 0:
        raise ValueError(
            f"HL capture body not aligned: {body} % {HL_TICK_RECORD_SIZE}"
        )
    return body // HL_TICK_RECORD_SIZE


__all__ = [
    "HL_TICK_MAGIC",
    "HL_TICK_VERSION",
    "HL_TICK_HEADER_SIZE",
    "HL_TICK_RECORD_SIZE",
    "HLTickFileHeader",
    "pack_event",
    "unpack_event",
    "write_events",
    "read_events",
    "count_events",
]
