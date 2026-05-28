"""
Policy → register-blob compiler (and the inverse).

The blob is a deterministic byte serialisation of the policy fields,
keyed by register-map offset. Layout is documented in
`fpga/regmap.yaml`. The blob is what the FPGA bridge writes into BAR0
on policy activation.

Format (Phase-4 v1):

    Magic:    4 bytes  b"SPB1"     (Sentinel Policy Blob v1)
    SchemaV:  4 bytes  uint32 LE   (policy schema_version)
    Body:     N bytes  packed (offset, width_bytes, value) tuples
    CRC:      4 bytes  uint32 LE   (CRC32 of the body)

The exact tuple layout is intentionally simple — V-Contract ensures
the regmap.yaml offsets are stable, so the codegen here can be
upgraded together with the YAML.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Iterable, List, Tuple

from .schema import Policy

MAGIC = b"SPB1"
SCHEMA_VERSION = 1


@dataclass
class PolicyBlob:
    bytes: bytes
    items: List[Tuple[int, int, int]]   # (offset, width_bytes, value)


# Register layout — must mirror fpga/regmap.yaml entries.
# Offsets here are FPGA BAR offsets in bytes.
LAYOUT = [
    ("rate_max_tokens",     0x0100, 4),
    ("rate_refill_rate",    0x0104, 4),
    ("rate_refill_period",  0x0108, 2),
    ("rate_enabled",        0x010A, 1),
    ("pos_max_long",        0x0200, 8),
    ("pos_max_short",       0x0208, 8),
    ("pos_max_notional",    0x0210, 8),
    ("pos_max_order_qty",   0x0218, 8),
    ("pos_enabled",         0x0220, 1),
    ("kill_armed",          0x0300, 1),
    ("kill_auto_enabled",   0x0301, 1),
    ("kill_loss_threshold", 0x0308, 8),    # signed, two's-complement encoding
    ("ff_enabled",          0x0400, 1),
    ("ff_band_bps",         0x0404, 2),
    ("ff_ref_price",        0x0410, 8),
    ("allowlist_enabled",   0x0500, 1),
]


def compile_policy(p: Policy) -> PolicyBlob:
    items: List[Tuple[int, int, int]] = []
    for attr, off, width in LAYOUT:
        v = getattr(p, attr)
        if isinstance(v, bool):
            v = 1 if v else 0
        if width == 1 or width == 2 or width == 4:
            items.append((off, width, int(v) & ((1 << (8 * width)) - 1)))
        elif width == 8:
            # Signed 64-bit two's-complement encoding.
            iv = int(v) & ((1 << 64) - 1)
            items.append((off, width, iv))
        else:
            raise ValueError(f"unsupported width {width}")

    # Allowlist slots — 64 entries × 4 bytes at offset 0x0510.
    al = list(p.allowlist) + [0] * (64 - len(p.allowlist))
    for i, sym in enumerate(al):
        items.append((0x0510 + 4 * i, 4, int(sym) & 0xFFFFFFFF))

    body = bytearray()
    for off, width, val in items:
        body += struct.pack("<II", off, width)
        body += int(val).to_bytes(width, "little")

    head = MAGIC + struct.pack("<I", SCHEMA_VERSION)
    crc = zlib.crc32(body) & 0xFFFFFFFF
    blob = head + bytes(body) + struct.pack("<I", crc)
    return PolicyBlob(bytes=blob, items=items)


def decompile_blob(blob: bytes) -> List[Tuple[int, int, int]]:
    """Inverse of compile_policy. Used by V-Contract round-trip tests."""
    if blob[:4] != MAGIC:
        raise ValueError("bad magic")
    sv = struct.unpack_from("<I", blob, 4)[0]
    if sv != SCHEMA_VERSION:
        raise ValueError(f"schema mismatch: blob={sv} runtime={SCHEMA_VERSION}")
    body_end = len(blob) - 4
    body = blob[8:body_end]
    crc_actual = zlib.crc32(body) & 0xFFFFFFFF
    crc_declared = struct.unpack_from("<I", blob, body_end)[0]
    if crc_actual != crc_declared:
        raise ValueError(f"bad crc: declared {crc_declared:08x} actual {crc_actual:08x}")
    items: List[Tuple[int, int, int]] = []
    pos = 0
    while pos < len(body):
        off, width = struct.unpack_from("<II", body, pos)
        pos += 8
        if width not in (1, 2, 4, 8):
            raise ValueError(f"bad width {width}")
        val = int.from_bytes(body[pos:pos + width], "little")
        pos += width
        items.append((off, width, val))
    return items
