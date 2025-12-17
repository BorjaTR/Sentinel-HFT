"""
FIX Protocol decoder for latency analysis.

FIX (Financial Information eXchange) is a text-based protocol
commonly used for order routing and execution.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from enum import Enum


class FIXMsgType(Enum):
    """Common FIX message types."""
    HEARTBEAT = '0'
    TEST_REQUEST = '1'
    RESEND_REQUEST = '2'
    REJECT = '3'
    SEQUENCE_RESET = '4'
    LOGOUT = '5'
    IOI = '6'
    ADVERTISEMENT = '7'
    EXECUTION_REPORT = '8'
    ORDER_CANCEL_REJECT = '9'
    LOGON = 'A'
    NEWS = 'B'
    EMAIL = 'C'
    NEW_ORDER_SINGLE = 'D'
    NEW_ORDER_LIST = 'E'
    ORDER_CANCEL_REQUEST = 'F'
    ORDER_REPLACE_REQUEST = 'G'
    ORDER_STATUS_REQUEST = 'H'
    ALLOCATION = 'J'
    LIST_CANCEL_REQUEST = 'K'
    LIST_EXECUTE = 'L'
    LIST_STATUS_REQUEST = 'M'
    LIST_STATUS = 'N'
    ALLOCATION_ACK = 'P'
    DONT_KNOW_TRADE = 'Q'
    QUOTE_REQUEST = 'R'
    QUOTE = 'S'
    SETTLEMENT_INSTRUCTIONS = 'T'
    MARKET_DATA_REQUEST = 'V'
    MARKET_DATA_SNAPSHOT = 'W'
    MARKET_DATA_INCREMENTAL = 'X'
    MARKET_DATA_REQUEST_REJECT = 'Y'
    QUOTE_CANCEL = 'Z'


@dataclass
class FIXMessage:
    """Parsed FIX message."""
    msg_type: str
    msg_type_name: str
    seq_num: int
    sender_comp_id: str
    target_comp_id: str
    sending_time: str
    fields: Dict[int, str]
    raw: str

    @property
    def is_application_msg(self) -> bool:
        """Check if this is an application (not session) message."""
        session_types = {'0', '1', '2', '3', '4', '5', 'A'}
        return self.msg_type not in session_types

    @property
    def is_market_data(self) -> bool:
        """Check if this is market data."""
        return self.msg_type in {'W', 'X', 'Y'}

    @property
    def is_order(self) -> bool:
        """Check if this is an order-related message."""
        return self.msg_type in {'D', 'E', 'F', 'G', '8', '9'}


class FIXDecoder:
    """
    Decode FIX protocol messages for latency analysis.

    Usage:
        decoder = FIXDecoder()
        msg = decoder.decode("8=FIX.4.4|9=100|35=D|...")
        print(msg.msg_type_name)  # "New Order Single"
    """

    # Tag names for common fields
    TAG_NAMES = {
        8: 'BeginString',
        9: 'BodyLength',
        35: 'MsgType',
        49: 'SenderCompID',
        56: 'TargetCompID',
        34: 'MsgSeqNum',
        52: 'SendingTime',
        10: 'CheckSum',
        # Order fields
        11: 'ClOrdID',
        37: 'OrderID',
        38: 'OrderQty',
        40: 'OrdType',
        44: 'Price',
        54: 'Side',
        55: 'Symbol',
        60: 'TransactTime',
        # Execution fields
        17: 'ExecID',
        20: 'ExecTransType',
        39: 'OrdStatus',
        150: 'ExecType',
        151: 'LeavesQty',
        14: 'CumQty',
        6: 'AvgPx',
    }

    MSG_TYPE_NAMES = {
        '0': 'Heartbeat',
        '1': 'Test Request',
        '2': 'Resend Request',
        '3': 'Reject',
        '4': 'Sequence Reset',
        '5': 'Logout',
        '6': 'IOI',
        '7': 'Advertisement',
        '8': 'Execution Report',
        '9': 'Order Cancel Reject',
        'A': 'Logon',
        'B': 'News',
        'C': 'Email',
        'D': 'New Order Single',
        'E': 'New Order List',
        'F': 'Order Cancel Request',
        'G': 'Order Replace Request',
        'H': 'Order Status Request',
        'J': 'Allocation',
        'K': 'List Cancel Request',
        'L': 'List Execute',
        'M': 'List Status Request',
        'N': 'List Status',
        'P': 'Allocation Ack',
        'Q': "Don't Know Trade",
        'R': 'Quote Request',
        'S': 'Quote',
        'T': 'Settlement Instructions',
        'V': 'Market Data Request',
        'W': 'Market Data Snapshot',
        'X': 'Market Data Incremental',
        'Y': 'Market Data Request Reject',
        'Z': 'Quote Cancel',
    }

    def __init__(self, delimiter: str = '\x01'):
        """
        Initialize decoder.

        Args:
            delimiter: Field separator (SOH by default, | for readable)
        """
        self.delimiter = delimiter

    def decode(self, data: str) -> Optional[FIXMessage]:
        """
        Decode a FIX message string.

        Args:
            data: Raw FIX message string

        Returns:
            Parsed FIXMessage or None if invalid
        """
        # Handle both SOH and | delimiters
        if '|' in data and self.delimiter == '\x01':
            data = data.replace('|', '\x01')

        fields = {}
        for part in data.split(self.delimiter):
            if '=' not in part:
                continue
            try:
                tag, value = part.split('=', 1)
                fields[int(tag)] = value
            except ValueError:
                continue

        if 35 not in fields:
            return None

        msg_type = fields[35]

        return FIXMessage(
            msg_type=msg_type,
            msg_type_name=self.MSG_TYPE_NAMES.get(msg_type, f'Unknown ({msg_type})'),
            seq_num=int(fields.get(34, 0)),
            sender_comp_id=fields.get(49, ''),
            target_comp_id=fields.get(56, ''),
            sending_time=fields.get(52, ''),
            fields=fields,
            raw=data,
        )

    def decode_bytes(self, data: bytes) -> Optional[FIXMessage]:
        """Decode FIX message from bytes."""
        try:
            return self.decode(data.decode('ascii'))
        except UnicodeDecodeError:
            return None

    def get_order_info(self, msg: FIXMessage) -> Dict[str, Any]:
        """Extract order information from a FIX message."""
        return {
            'cl_ord_id': msg.fields.get(11),
            'order_id': msg.fields.get(37),
            'symbol': msg.fields.get(55),
            'side': 'BUY' if msg.fields.get(54) == '1' else 'SELL',
            'order_qty': msg.fields.get(38),
            'price': msg.fields.get(44),
            'ord_type': msg.fields.get(40),
        }

    def get_exec_info(self, msg: FIXMessage) -> Dict[str, Any]:
        """Extract execution information from an Execution Report."""
        if msg.msg_type != '8':
            return {}

        return {
            'exec_id': msg.fields.get(17),
            'exec_type': msg.fields.get(150),
            'ord_status': msg.fields.get(39),
            'leaves_qty': msg.fields.get(151),
            'cum_qty': msg.fields.get(14),
            'avg_px': msg.fields.get(6),
        }

    def calculate_message_size(self, msg: FIXMessage) -> int:
        """Calculate approximate message size in bytes."""
        return len(msg.raw.encode('ascii'))

    @staticmethod
    def is_latency_critical(msg_type: str) -> bool:
        """Check if message type is latency-critical for HFT."""
        critical_types = {
            'D',  # New Order
            'F',  # Cancel
            'G',  # Replace
            '8',  # Execution Report
            'X',  # Market Data Incremental
            'W',  # Market Data Snapshot
        }
        return msg_type in critical_types
