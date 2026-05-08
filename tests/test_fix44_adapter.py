"""
Phase-2 V-Protocol acceptance tests for the FIX 4.4 adapter.
"""

import pytest

from sentinel_hft.adapters.fix44 import (
    FixMessage,
    FixParseError,
    parse,
    emit,
    FixSession,
    SessionState,
    SentinelGateAdapter,
)
from sentinel_hft.adapters.fix44 import messages as M
from sentinel_hft.golden import (
    GateConfig,
    GoldenRiskGate,
    OrderSide,
    OrderType,
    RejectReason,
)


# ----------------------------------------------------------------------------
# Round-trip: parse(emit(m)) == m
# ----------------------------------------------------------------------------

def _build_logon():
    m = FixMessage()
    m.set(M.T_BEGIN_STRING, M.BEGIN_STRING)
    m.set(M.T_MSG_TYPE, b"A")
    m.set(M.T_SENDER_COMP_ID, b"CLIENT")
    m.set(M.T_TARGET_COMP_ID, b"BROKER")
    m.set(M.T_MSG_SEQ_NUM, b"1")
    m.set(M.T_SENDING_TIME, b"20260508-08:00:00.000")
    m.set(M.T_ENCRYPT_METHOD, b"0")
    m.set(M.T_HEART_BT_INT, b"30")
    return m


def _build_new_order(seq=2, cl_ord_id="C1", symbol="AAPL", side="1", qty=100, price="150.50"):
    m = FixMessage()
    m.set(M.T_BEGIN_STRING, M.BEGIN_STRING)
    m.set(M.T_MSG_TYPE, b"D")
    m.set(M.T_SENDER_COMP_ID, b"CLIENT")
    m.set(M.T_TARGET_COMP_ID, b"BROKER")
    m.set(M.T_MSG_SEQ_NUM, str(seq).encode("ascii"))
    m.set(M.T_SENDING_TIME, b"20260508-08:00:01.000")
    m.set(M.T_CL_ORD_ID, cl_ord_id.encode("ascii"))
    m.set(M.T_HANDL_INST, b"1")
    m.set(M.T_SYMBOL, symbol.encode("ascii"))
    m.set(M.T_SIDE, side.encode("ascii"))
    m.set(M.T_TRANSACT_TIME, b"20260508-08:00:01.000")
    m.set(M.T_ORD_TYPE, b"2")
    m.set(M.T_ORDER_QTY, str(qty).encode("ascii"))
    m.set(M.T_PRICE, price.encode("ascii"))
    return m


def test_round_trip_logon():
    m = _build_logon()
    wire = emit(m)
    m2 = parse(wire)
    # Compare body fields (parser will have added 9 + 10).
    body_in = [(t, v) for t, v in m.fields if t not in (9, 10)]
    body_out = [(t, v) for t, v in m2.fields if t not in (9, 10)]
    assert body_in == body_out


def test_round_trip_new_order():
    m = _build_new_order()
    wire = emit(m)
    m2 = parse(wire)
    body_in = [(t, v) for t, v in m.fields if t not in (9, 10)]
    body_out = [(t, v) for t, v in m2.fields if t not in (9, 10)]
    assert body_in == body_out


def test_round_trip_100_random_messages():
    import random
    rng = random.Random(42)
    for i in range(100):
        m = _build_new_order(
            seq=i + 1,
            cl_ord_id=f"O{i}",
            symbol=rng.choice(["AAPL", "MSFT", "BTC-USD", "TSLA", "X"]),
            side=rng.choice(["1", "2"]),
            qty=rng.randint(1, 10_000),
            price=f"{rng.uniform(1, 10000):.2f}",
        )
        wire = emit(m)
        m2 = parse(wire)
        body_in = [(t, v) for t, v in m.fields if t not in (9, 10)]
        body_out = [(t, v) for t, v in m2.fields if t not in (9, 10)]
        assert body_in == body_out, f"round-trip failed at {i}"


# ----------------------------------------------------------------------------
# Checksum validation
# ----------------------------------------------------------------------------

def test_corrupted_checksum_raises():
    wire = emit(_build_logon())
    bad = wire[:-4] + b"999\x01"      # rewrite checksum to 999
    with pytest.raises(FixParseError) as e:
        parse(bad)
    assert e.value.kind == "bad_checksum"


def test_truncated_message_raises():
    wire = emit(_build_logon())
    with pytest.raises(FixParseError):
        parse(wire[:10])


def test_empty_buffer_raises():
    with pytest.raises(FixParseError):
        parse(b"")


# ----------------------------------------------------------------------------
# End-to-end: order → gate → decision → ExecutionReport
# ----------------------------------------------------------------------------

@pytest.fixture
def open_gate():
    return GoldenRiskGate(GateConfig(
        rate_max_tokens=10**6,
        rate_refill_rate=10**4,
        rate_refill_period=1,
        pos_max_long=10**8,
        pos_max_short=10**8,
        pos_max_notional=10**18,
        pos_max_order_qty=10**6,
        ff_enabled=False,
        allowlist_enabled=False,
    ))


def test_accepted_order_emits_new_exec_report(open_gate):
    sess = FixSession(sender="CLIENT", target="BROKER")
    sess.state = SessionState.LOGGED_IN
    accepted = []
    adapter = SentinelGateAdapter(sess, open_gate, on_accept=accepted.append)
    wire = emit(_build_new_order(seq=1))
    out_bytes_list = adapter.feed(wire)
    assert len(out_bytes_list) == 1
    out = parse(out_bytes_list[0])
    assert out.get(M.T_MSG_TYPE) == b"8"
    assert out.get(M.T_EXEC_TYPE) == b"0"     # New
    assert out.get(M.T_ORD_STATUS) == b"0"
    assert accepted == [b"NEW C1"]


def test_killed_gate_rejects_with_exec_report():
    cfg = GateConfig(
        rate_enabled=False, pos_enabled=False,
        ff_enabled=False, allowlist_enabled=False,
        kill_armed=True,
    )
    g = GoldenRiskGate(cfg)
    g.trip_kill()

    sess = FixSession(sender="CLIENT", target="BROKER")
    sess.state = SessionState.LOGGED_IN
    adapter = SentinelGateAdapter(sess, g)
    out_bytes_list = adapter.feed(emit(_build_new_order(seq=1)))
    assert len(out_bytes_list) == 1
    out = parse(out_bytes_list[0])
    assert out.get(M.T_EXEC_TYPE) == b"8"     # Rejected
    assert out.get(M.T_ORD_STATUS) == b"8"
    text = out.get(M.T_TEXT) or b""
    assert b"KILL_SWITCH" in text


def test_unknown_side_business_reject(open_gate):
    sess = FixSession(sender="CLIENT", target="BROKER")
    sess.state = SessionState.LOGGED_IN
    adapter = SentinelGateAdapter(sess, open_gate)
    m = _build_new_order(seq=1)
    m.set(M.T_SIDE, b"7")    # invalid
    out_bytes_list = adapter.feed(emit(m))
    out = parse(out_bytes_list[0])
    assert out.get(M.T_MSG_TYPE) == b"j"    # BusinessMessageReject


# ----------------------------------------------------------------------------
# Fuzz: 10 000 random byte sequences must not crash the parser
# ----------------------------------------------------------------------------

def test_parser_does_not_crash_on_random_bytes():
    import random
    rng = random.Random(42)
    crashes = 0
    parsed_ok = 0
    for _ in range(10_000):
        n = rng.randint(0, 256)
        buf = bytes(rng.randint(0, 255) for _ in range(n))
        try:
            parse(buf)
            parsed_ok += 1
        except FixParseError:
            pass
        except Exception:
            crashes += 1
    assert crashes == 0, f"{crashes} non-FixParseError exceptions"


# ----------------------------------------------------------------------------
# Session sequence-num behaviour
# ----------------------------------------------------------------------------

def test_session_logon_sets_state_logged_in():
    sess = FixSession(sender="CLIENT", target="BROKER")
    sess.send_logon()
    assert sess.state == SessionState.LOGON_SENT

    # Inbound logon ack
    inbound = _build_logon()
    inbound.set(M.T_SENDER_COMP_ID, b"BROKER")
    inbound.set(M.T_TARGET_COMP_ID, b"CLIENT")
    sess.apply_inbound(inbound)
    assert sess.state == SessionState.LOGGED_IN


def test_session_test_request_triggers_heartbeat():
    sess = FixSession(sender="CLIENT", target="BROKER")
    sess.state = SessionState.LOGGED_IN
    sess.in_seq = 5
    m = FixMessage()
    m.set(M.T_BEGIN_STRING, M.BEGIN_STRING)
    m.set(M.T_MSG_TYPE, b"1")
    m.set(M.T_SENDER_COMP_ID, b"BROKER")
    m.set(M.T_TARGET_COMP_ID, b"CLIENT")
    m.set(M.T_MSG_SEQ_NUM, b"5")
    m.set(M.T_SENDING_TIME, b"20260508-08:00:00.000")
    m.set(M.T_TEST_REQ_ID, b"ping1")
    out = sess.apply_inbound(m)
    assert len(out) == 1
    parsed = parse(out[0])
    assert parsed.get(M.T_MSG_TYPE) == b"0"           # Heartbeat
    assert parsed.get(M.T_TEST_REQ_ID_RESP) == b"ping1"
