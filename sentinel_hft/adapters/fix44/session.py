"""
FIX 4.4 session manager.

Tracks sequence numbers, heartbeat timing, logon/logout state, and
generates the boilerplate header fields for outbound messages.

Designed for testability: time is injected via a `time_fn` callable
(default: time.time) so tests can drive the clock deterministically.
"""

from __future__ import annotations

import enum
import time as _time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from . import messages as M


class SessionState(enum.Enum):
    DISCONNECTED = "disconnected"
    LOGON_SENT   = "logon_sent"
    LOGGED_IN    = "logged_in"
    LOGOUT_SENT  = "logout_sent"


@dataclass
class FixSession:
    """A simple FIX 4.4 session — initiator side.

    The session tracks sequence numbers and heartbeat timing. It does
    not perform I/O — callers consume `outbound_msgs` and feed
    inbound bytes via `apply_inbound`.
    """
    sender: str
    target: str
    heartbeat_interval_s: int = 30
    time_fn: Callable[[], float] = _time.time

    # Sequence numbers (per FIX spec, monotonically increasing from 1)
    out_seq: int = 1
    in_seq: int = 1

    # State
    state: SessionState = SessionState.DISCONNECTED
    last_sent_at: float = 0.0
    last_received_at: float = 0.0

    # Outbound queue (bytes ready to send)
    _outbound: List[bytes] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Outbound helpers
    # ------------------------------------------------------------------

    def _stamp_header(self, msg: M.FixMessage, msg_type: bytes) -> M.FixMessage:
        msg.set(M.T_BEGIN_STRING, M.BEGIN_STRING)
        msg.set(M.T_MSG_TYPE, msg_type)
        msg.set(M.T_SENDER_COMP_ID, self.sender.encode("ascii"))
        msg.set(M.T_TARGET_COMP_ID, self.target.encode("ascii"))
        msg.set(M.T_MSG_SEQ_NUM, str(self.out_seq).encode("ascii"))
        msg.set(M.T_SENDING_TIME, _now_utc().encode("ascii"))
        return msg

    def _enqueue(self, msg: M.FixMessage, msg_type: bytes) -> bytes:
        # Ordering: 8, 9, 35, then header fields, then body. Easier to
        # build by setting tags in target order on a fresh message.
        wire = M.emit(self._stamp_header(msg, msg_type))
        self._outbound.append(wire)
        self.out_seq += 1
        self.last_sent_at = self.time_fn()
        return wire

    def send_logon(self, reset_seq: bool = True) -> bytes:
        m = M.FixMessage()
        m.set(M.T_ENCRYPT_METHOD, b"0")
        m.set(M.T_HEART_BT_INT, str(self.heartbeat_interval_s).encode("ascii"))
        if reset_seq:
            m.set(M.T_RESET_SEQ_NUM_FLAG, b"Y")
            self.out_seq = 1
            self.in_seq = 1
        wire = self._enqueue(m, b"A")
        self.state = SessionState.LOGON_SENT
        return wire

    def send_heartbeat(self, in_response_to_test: Optional[str] = None) -> bytes:
        m = M.FixMessage()
        if in_response_to_test:
            m.set(M.T_TEST_REQ_ID_RESP, in_response_to_test.encode("ascii"))
        return self._enqueue(m, b"0")

    def send_test_request(self, test_id: str) -> bytes:
        m = M.FixMessage()
        m.set(M.T_TEST_REQ_ID, test_id.encode("ascii"))
        return self._enqueue(m, b"1")

    def send_logout(self, reason: str = "") -> bytes:
        m = M.FixMessage()
        if reason:
            m.set(M.T_TEXT, reason.encode("ascii"))
        wire = self._enqueue(m, b"5")
        self.state = SessionState.LOGOUT_SENT
        return wire

    def send_execution_report(
        self,
        cl_ord_id: str,
        order_id: str,
        exec_id: str,
        exec_type: str,        # 0=New 4=Cancelled 8=Rejected
        ord_status: str,
        symbol: str,
        side: str,             # 1=Buy 2=Sell
        qty: int,
        price: int,
        text: str = "",
        ord_rej_reason: Optional[int] = None,
    ) -> bytes:
        m = M.FixMessage()
        m.set(M.T_CL_ORD_ID, cl_ord_id.encode("ascii"))
        m.set(M.T_ORDER_ID, order_id.encode("ascii"))
        m.set(M.T_EXEC_ID, exec_id.encode("ascii"))
        m.set(M.T_EXEC_TYPE, exec_type.encode("ascii"))
        m.set(M.T_ORD_STATUS, ord_status.encode("ascii"))
        m.set(M.T_SYMBOL, symbol.encode("ascii"))
        m.set(M.T_SIDE, side.encode("ascii"))
        m.set(M.T_LEAVES_QTY, str(qty).encode("ascii"))
        m.set(M.T_CUM_QTY, b"0")
        m.set(M.T_AVG_PX, b"0")
        m.set(M.T_ORDER_QTY, str(qty).encode("ascii"))
        m.set(M.T_PRICE, str(price).encode("ascii"))
        if text:
            m.set(M.T_TEXT, text.encode("ascii"))
        if ord_rej_reason is not None:
            m.set(M.T_ORD_REJ_REASON, str(ord_rej_reason).encode("ascii"))
        return self._enqueue(m, b"8")

    def send_business_reject(self, ref_seq: int, ref_msg_type: str, text: str) -> bytes:
        m = M.FixMessage()
        m.set(45, str(ref_seq).encode("ascii"))     # RefSeqNum
        m.set(372, ref_msg_type.encode("ascii"))    # RefMsgType
        m.set(380, b"0")                            # BusinessRejectReason: Other
        m.set(M.T_TEXT, text.encode("ascii"))
        return self._enqueue(m, b"j")

    # ------------------------------------------------------------------
    # Outbound queue accessor
    # ------------------------------------------------------------------

    def drain_outbound(self) -> List[bytes]:
        out = self._outbound
        self._outbound = []
        return out

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    def apply_inbound(self, msg: M.FixMessage) -> List[bytes]:
        """Update session state from one inbound parsed message; return
        any auto-generated outbound bytes (e.g. heartbeat in response to
        TestRequest, Logon ack on Logon, etc.).
        """
        self.last_received_at = self.time_fn()
        seq = msg.get_int(M.T_MSG_SEQ_NUM)
        if seq is None:
            return []
        # Reset behaviour on Logon with 141=Y
        msg_type = msg.get(M.T_MSG_TYPE)
        if msg_type == b"A":
            if msg.get(M.T_RESET_SEQ_NUM_FLAG) == b"Y":
                self.in_seq = 1
            self.in_seq = seq + 1
            self.state = SessionState.LOGGED_IN
            return self.drain_outbound()

        if seq < self.in_seq:
            # Lower-than-expected: ignore (or could send a reject)
            return []
        if seq > self.in_seq:
            # Sequence gap → request resend
            m = M.FixMessage()
            m.set(M.T_BEGIN_SEQ_NO, str(self.in_seq).encode("ascii"))
            m.set(M.T_END_SEQ_NO, b"0")
            self._enqueue(m, b"2")
            return self.drain_outbound()

        self.in_seq = seq + 1

        if msg_type == b"1":
            # TestRequest → reply with Heartbeat carrying TestReqID
            test_id = msg.get_str(M.T_TEST_REQ_ID) or ""
            self.send_heartbeat(in_response_to_test=test_id)
        elif msg_type == b"5":
            # Logout from peer
            self.state = SessionState.DISCONNECTED
        # Otherwise: caller deals with it (e.g. NewOrderSingle hits the gate)

        return self.drain_outbound()

    # ------------------------------------------------------------------
    # Heartbeat tick (caller invokes periodically)
    # ------------------------------------------------------------------

    def tick(self) -> List[bytes]:
        """Caller pulses this every second or so. Returns any bytes that
        need to go on the wire (heartbeat, TestRequest on inbound idle).
        """
        now = self.time_fn()
        if self.state == SessionState.LOGGED_IN:
            if now - self.last_sent_at >= self.heartbeat_interval_s:
                self.send_heartbeat()
            if now - self.last_received_at >= 2 * self.heartbeat_interval_s:
                # Two heartbeat intervals with no inbound — send a TestRequest.
                self.send_test_request("ping-" + str(int(now)))
        return self.drain_outbound()


def _now_utc() -> str:
    """FIX SendingTime in UTCTimestamp format: YYYYMMDD-HH:MM:SS.sss."""
    import datetime
    n = datetime.datetime.utcnow()
    return n.strftime("%Y%m%d-%H:%M:%S.") + f"{n.microsecond // 1000:03d}"
