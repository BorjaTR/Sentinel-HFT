"""
Sentinel gate adapter for FIX 4.4.

Wires a FixSession to a GoldenRiskGate (or a real RTL gate, via the
Phase-3 host bridge). Drives orders synchronously through the gate;
emits ExecutionReports on reject; passes accepts through to a
downstream callback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional

from sentinel_hft.golden import (
    Decision,
    GateConfig,
    GoldenRiskGate,
    Order,
    OrderSide,
    OrderType,
    RejectReason,
)

from . import messages as M
from .session import FixSession


# FIX side codes
_FIX_SIDE_TO_GATE = {b"1": OrderSide.BUY, b"2": OrderSide.SELL}
_FIX_ORDTYPE_TO_GATE = {
    b"1": OrderType.NEW,           # Market
    b"2": OrderType.NEW,           # Limit
}


# Gate reject → FIX OrdRejReason (RTS 6 mapping; documented in regulations)
_REJECT_TO_REASON: dict = {
    RejectReason.RATE_LIMITED:    99,    # broker option
    RejectReason.POSITION_LIMIT:  3,
    RejectReason.NOTIONAL_LIMIT:  3,
    RejectReason.ORDER_SIZE:      18,
    RejectReason.KILL_SWITCH:     6,
    RejectReason.FAT_FINGER:      18,
    RejectReason.ALLOWLIST_BLOCK: 1,
    RejectReason.INVALID_ORDER:   2,
}


@dataclass
class SentinelGateAdapter:
    session: FixSession
    gate: GoldenRiskGate
    on_accept: Optional[Callable[[bytes], None]] = None    # downstream callback
    exec_id_seq: int = 1
    _symbol_to_id: dict = field(default_factory=dict)

    def feed(self, raw: bytes) -> List[bytes]:
        """Parse one or more FIX messages from `raw`, drive them through
        session state + gate. Return any bytes that should hit the wire
        (auto-replies, exec reports).
        """
        out: List[bytes] = []
        # Split a buffer that may contain multiple messages.
        for msg_bytes in _split_messages(raw):
            try:
                msg = M.parse(msg_bytes)
            except M.FixParseError as e:
                # Malformed inbound: log + reject. Cannot send proper FIX
                # reject without sequence-num context; drop and continue.
                continue
            out.extend(self.session.apply_inbound(msg))
            mt = msg.get(M.T_MSG_TYPE)
            if mt == b"D":
                out.extend(self._handle_new_order(msg))
            elif mt == b"F":
                out.extend(self._handle_cancel(msg))
            elif mt == b"G":
                out.extend(self._handle_replace(msg))
        return out

    # ------------------------------------------------------------------
    # NewOrderSingle
    # ------------------------------------------------------------------

    def _handle_new_order(self, msg: M.FixMessage) -> List[bytes]:
        cl_ord_id = msg.get_str(M.T_CL_ORD_ID) or ""
        symbol_str = msg.get_str(M.T_SYMBOL) or ""
        side_b = msg.get(M.T_SIDE)
        ordtype_b = msg.get(M.T_ORD_TYPE)
        qty = msg.get_int(M.T_ORDER_QTY) or 0
        price_str = msg.get_str(M.T_PRICE) or "0"
        try:
            price_int = int(round(float(price_str) * 1e8))
        except ValueError:
            price_int = 0

        if side_b not in _FIX_SIDE_TO_GATE:
            return self._business_reject(msg, "unknown side")
        if ordtype_b not in _FIX_ORDTYPE_TO_GATE:
            return self._business_reject(msg, "unknown ordtype")

        symbol_id = self._intern_symbol(symbol_str)

        order = Order(
            order_id=hash(cl_ord_id) & ((1 << 64) - 1),
            symbol_id=symbol_id,
            side=_FIX_SIDE_TO_GATE[side_b],
            order_type=_FIX_ORDTYPE_TO_GATE[ordtype_b],
            quantity=qty,
            price=price_int,
            notional=qty * price_int,
        )

        self.gate.tick()
        decision = self.gate.decide(order)
        return self._emit_for_decision(cl_ord_id, symbol_str, side_b, qty, price_int, decision)

    # ------------------------------------------------------------------
    # Cancel / Replace pass-through (Phase-2 minimum)
    # ------------------------------------------------------------------

    def _handle_cancel(self, msg: M.FixMessage) -> List[bytes]:
        # Phase-2 simply emits a Cancelled ExecutionReport without round-
        # tripping to a real exchange (no exchange in scope).
        cl_ord_id = msg.get_str(M.T_CL_ORD_ID) or ""
        symbol_str = msg.get_str(M.T_SYMBOL) or ""
        side_b = msg.get(M.T_SIDE) or b"1"
        qty = msg.get_int(M.T_ORDER_QTY) or 0
        return [
            self.session.send_execution_report(
                cl_ord_id=cl_ord_id,
                order_id=cl_ord_id,
                exec_id=str(self._next_exec_id()),
                exec_type="4",
                ord_status="4",
                symbol=symbol_str,
                side=side_b.decode("ascii"),
                qty=qty,
                price=0,
            )
        ]

    def _handle_replace(self, msg: M.FixMessage) -> List[bytes]:
        # Replace = treat as NewOrderSingle for risk-gate purposes.
        return self._handle_new_order(msg)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _emit_for_decision(
        self,
        cl_ord_id: str,
        symbol: str,
        side_b: bytes,
        qty: int,
        price_int: int,
        decision: Decision,
    ) -> List[bytes]:
        side_s = side_b.decode("ascii")
        if decision.passed:
            # Pass through the underlying NewOrderSingle to downstream and
            # acknowledge with ExecutionReport (39=0, 150=0).
            if self.on_accept is not None:
                self.on_accept(b"NEW " + cl_ord_id.encode("ascii"))
            return [
                self.session.send_execution_report(
                    cl_ord_id=cl_ord_id,
                    order_id=cl_ord_id,
                    exec_id=str(self._next_exec_id()),
                    exec_type="0",
                    ord_status="0",
                    symbol=symbol,
                    side=side_s,
                    qty=qty,
                    price=price_int,
                )
            ]
        # Reject path: ExecutionReport 39=8 / 150=8 with text + reject reason.
        rej_reason = _REJECT_TO_REASON.get(decision.reason, 99)
        return [
            self.session.send_execution_report(
                cl_ord_id=cl_ord_id,
                order_id=cl_ord_id,
                exec_id=str(self._next_exec_id()),
                exec_type="8",
                ord_status="8",
                symbol=symbol,
                side=side_s,
                qty=qty,
                price=price_int,
                text=f"sentinel: {decision.reason.name}",
                ord_rej_reason=rej_reason,
            )
        ]

    def _next_exec_id(self) -> int:
        eid = self.exec_id_seq
        self.exec_id_seq += 1
        return eid

    def _intern_symbol(self, symbol: str) -> int:
        if symbol not in self._symbol_to_id:
            self._symbol_to_id[symbol] = len(self._symbol_to_id) + 1
        return self._symbol_to_id[symbol]

    def _business_reject(self, msg: M.FixMessage, text: str) -> List[bytes]:
        ref_seq = msg.get_int(M.T_MSG_SEQ_NUM) or 0
        ref_mt = msg.get_str(M.T_MSG_TYPE) or "?"
        return [self.session.send_business_reject(ref_seq, ref_mt, text)]


# -----------------------------------------------------------------------------
# Buffer splitter
# -----------------------------------------------------------------------------

def _split_messages(buf: bytes) -> Iterable[bytes]:
    """Split a possibly-concatenated FIX byte buffer into per-message slices.

    A FIX message ends after `10=NNN<SOH>`. We scan for `10=` followed by
    three digits and a SOH.
    """
    i = 0
    n = len(buf)
    while i < n:
        # Find "10=" preceded by SOH
        idx = buf.find(b"\x0110=", i)
        if idx < 0:
            # No more terminators; emit remainder if non-empty.
            if i < n:
                yield buf[i:]
            return
        # The end of this message is idx+1 (start of "10=") plus 7 bytes
        # ("10=NNN<SOH>") = idx + 8. Total length = idx + 1 + 7.
        end = idx + 1 + 7
        if end > n:
            yield buf[i:]
            return
        yield buf[i:end]
        i = end
