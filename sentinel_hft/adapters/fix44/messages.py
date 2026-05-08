"""
FIX 4.4 tag-value parser + emitter.

Wire format: a FIX message is a sequence of tag=value fields delimited
by SOH (0x01). Every message starts with `8=FIX.4.4` then `9=<bodyLen>`,
ends with `10=<checksum>`. The checksum is the sum of all bytes up to
(but not including) the checksum tag, mod 256, formatted as zero-padded
3 digits.

This module is intentionally a small, tight implementation — the
contract surface is "round-trip" (parse(emit(m)) == m) and "well-formed
or typed error" (no exceptions other than FixParseError).

Tags supported as named constants are listed at the bottom of this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

SOH = b"\x01"
SOH_C = 0x01

BEGIN_STRING = b"FIX.4.4"


class FixParseError(Exception):
    """Raised on any malformed message. Carries a `kind` for taxonomy."""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


# -----------------------------------------------------------------------------
# Message dataclass
# -----------------------------------------------------------------------------

@dataclass
class FixMessage:
    """Ordered tag-value FIX message. Field order is preserved on emit."""
    fields: List[Tuple[int, bytes]] = field(default_factory=list)

    def msg_type(self) -> Optional[bytes]:
        for t, v in self.fields:
            if t == 35:
                return v
        return None

    def get(self, tag: int) -> Optional[bytes]:
        for t, v in self.fields:
            if t == tag:
                return v
        return None

    def get_int(self, tag: int) -> Optional[int]:
        v = self.get(tag)
        if v is None:
            return None
        try:
            return int(v)
        except ValueError:
            raise FixParseError("bad_int", f"tag {tag} value {v!r}")

    def get_str(self, tag: int) -> Optional[str]:
        v = self.get(tag)
        return v.decode("ascii") if v is not None else None

    def set(self, tag: int, value: bytes) -> None:
        for i, (t, _) in enumerate(self.fields):
            if t == tag:
                self.fields[i] = (tag, value)
                return
        self.fields.append((tag, value))

    def to_dict(self) -> Dict[int, bytes]:
        return {t: v for t, v in self.fields}


# -----------------------------------------------------------------------------
# Parser
# -----------------------------------------------------------------------------

def parse(buf: bytes) -> FixMessage:
    """Parse a single FIX message. Raise FixParseError on any malformation."""
    if not buf:
        raise FixParseError("empty", "input is empty")
    # Trim trailing SOH if present (it's required after the last field).
    if buf.endswith(SOH):
        body = buf[:-1]
    else:
        body = buf

    raw_fields = body.split(SOH)
    if len(raw_fields) < 3:
        raise FixParseError("too_few_fields", f"got {len(raw_fields)}")

    fields: List[Tuple[int, bytes]] = []
    for raw in raw_fields:
        if b"=" not in raw:
            raise FixParseError("no_equals", repr(raw))
        tag_b, _, value = raw.partition(b"=")
        try:
            tag = int(tag_b)
        except ValueError:
            raise FixParseError("bad_tag", repr(tag_b))
        if tag <= 0:
            raise FixParseError("non_positive_tag", str(tag))
        fields.append((tag, value))

    # Mandatory shape: 8=..., 9=..., 35=..., ..., 10=...
    if fields[0][0] != 8 or fields[0][1] != BEGIN_STRING:
        raise FixParseError("bad_begin_string", repr(fields[0]))
    if fields[1][0] != 9:
        raise FixParseError("missing_body_length", repr(fields[1]))
    try:
        body_length = int(fields[1][1])
    except ValueError:
        raise FixParseError("bad_body_length", repr(fields[1][1]))
    if fields[-1][0] != 10:
        raise FixParseError("missing_checksum", repr(fields[-1]))

    # Verify body length: sum of bytes from after 9=<n><SOH> to start of 10=...
    # We compute by reconstructing the on-the-wire body byte slice.
    # The split removed the SOHs, so total len = sum(raw)+len(raw)-1.
    # Easiest: re-emit and compare.
    expected_checksum = _checksum_over_bytes(_reemit_for_checksum(fields))
    given_checksum = fields[-1][1]
    if given_checksum != f"{expected_checksum:03d}".encode():
        raise FixParseError(
            "bad_checksum",
            f"expected {expected_checksum:03d}, got {given_checksum.decode('ascii', errors='replace')}",
        )

    # Verify body length: bytes between 9=<n><SOH> and 10=
    actual_body_length = _body_length(fields)
    if actual_body_length != body_length:
        raise FixParseError(
            "bad_body_length",
            f"declared {body_length}, computed {actual_body_length}",
        )

    return FixMessage(fields=fields)


def _reemit_for_checksum(fields: List[Tuple[int, bytes]]) -> bytes:
    """Concat all fields except the trailing 10= checksum, separated by SOH,
    INCLUDING the trailing SOH after the last data field. This is the byte
    range the FIX checksum is computed over.
    """
    out = bytearray()
    for t, v in fields[:-1]:
        out += str(t).encode("ascii") + b"=" + v + SOH
    return bytes(out)


def _body_length(fields: List[Tuple[int, bytes]]) -> int:
    """Body length is the byte count starting from the byte AFTER the
    trailing SOH of the 9= field, up to (but not including) the start
    of the 10= field. Equivalent: total of fields[2..-1] including their
    trailing SOHs.
    """
    n = 0
    for t, v in fields[2:-1]:
        n += len(str(t).encode("ascii")) + 1 + len(v) + 1   # tag + '=' + value + SOH
    return n


def _checksum_over_bytes(buf: bytes) -> int:
    return sum(buf) % 256


# -----------------------------------------------------------------------------
# Emitter
# -----------------------------------------------------------------------------

def emit(msg: FixMessage) -> bytes:
    """Serialise a FixMessage to wire bytes, recomputing 9 (body length)
    and 10 (checksum). The user only needs to populate 8, 35, and the
    body fields; 9 and 10 are written by emit.
    """
    fields_in = list(msg.fields)
    # Strip any user-supplied 9 / 10; we recompute.
    fields_in = [(t, v) for t, v in fields_in if t not in (9, 10)]
    if not fields_in or fields_in[0][0] != 8:
        # Auto-prepend BeginString if missing (helps callers).
        fields_in = [(8, BEGIN_STRING)] + [t for t in fields_in if t[0] != 8]
    # Layout: [8, 9, 35, ...rest..., 10]
    head = fields_in[0]
    rest = fields_in[1:]
    # 35 must come right after 9
    body_fields = rest

    # We need 9= placeholder to compute body length.
    # Build the body section first.
    body_bytes = bytearray()
    for t, v in body_fields:
        body_bytes += str(t).encode("ascii") + b"=" + v + SOH

    body_length = len(body_bytes)
    body_length_field = (9, str(body_length).encode("ascii"))

    pre = bytearray()
    pre += str(head[0]).encode("ascii") + b"=" + head[1] + SOH
    pre += str(body_length_field[0]).encode("ascii") + b"=" + body_length_field[1] + SOH
    pre += body_bytes

    checksum = sum(pre) % 256
    pre += b"10=" + f"{checksum:03d}".encode("ascii") + SOH
    return bytes(pre)


# -----------------------------------------------------------------------------
# Standard tag constants
# -----------------------------------------------------------------------------

# Header
T_BEGIN_STRING        = 8
T_BODY_LENGTH         = 9
T_MSG_TYPE            = 35
T_SENDER_COMP_ID      = 49
T_TARGET_COMP_ID      = 56
T_MSG_SEQ_NUM         = 34
T_SENDING_TIME        = 52

# Trailer
T_CHECKSUM            = 10

# Logon
T_ENCRYPT_METHOD      = 98
T_HEART_BT_INT        = 108
T_RESET_SEQ_NUM_FLAG  = 141

# Order
T_CL_ORD_ID           = 11
T_ORIG_CL_ORD_ID      = 41
T_HANDL_INST          = 21
T_SYMBOL              = 55
T_SIDE                = 54
T_TRANSACT_TIME       = 60
T_ORD_TYPE            = 40
T_ORDER_QTY           = 38
T_PRICE               = 44
T_TIME_IN_FORCE       = 59

# Execution Report
T_ORDER_ID            = 37
T_EXEC_ID             = 17
T_EXEC_TYPE           = 150
T_ORD_STATUS          = 39
T_LEAVES_QTY          = 151
T_CUM_QTY             = 14
T_AVG_PX              = 6
T_TEXT                = 58
T_ORD_REJ_REASON      = 103

# Resend / SeqReset
T_BEGIN_SEQ_NO        = 7
T_END_SEQ_NO          = 16
T_NEW_SEQ_NO          = 36
T_GAP_FILL_FLAG       = 123

# Test request
T_TEST_REQ_ID         = 112

# Heartbeat reply field
T_TEST_REQ_ID_RESP    = 112
