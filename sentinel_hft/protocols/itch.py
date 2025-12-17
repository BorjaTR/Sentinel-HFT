"""
ITCH Protocol decoder for latency analysis.

NASDAQ ITCH is a binary protocol for market data dissemination.
This decoder handles ITCH 5.0 format.
"""

import struct
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from enum import Enum


class ITCHMsgType(Enum):
    """ITCH 5.0 message types."""
    SYSTEM_EVENT = 'S'
    STOCK_DIRECTORY = 'R'
    STOCK_TRADING_ACTION = 'H'
    REG_SHO = 'Y'
    MARKET_PARTICIPANT_POSITION = 'L'
    MWCB_DECLINE_LEVEL = 'V'
    MWCB_STATUS = 'W'
    IPO_QUOTING_PERIOD = 'K'
    LULD_AUCTION_COLLAR = 'J'
    ADD_ORDER = 'A'
    ADD_ORDER_MPID = 'F'
    ORDER_EXECUTED = 'E'
    ORDER_EXECUTED_PRICE = 'C'
    ORDER_CANCEL = 'X'
    ORDER_DELETE = 'D'
    ORDER_REPLACE = 'U'
    TRADE = 'P'
    CROSS_TRADE = 'Q'
    BROKEN_TRADE = 'B'
    NOII = 'I'


@dataclass
class ITCHMessage:
    """Parsed ITCH message."""
    msg_type: str
    msg_type_name: str
    timestamp_ns: int
    stock: Optional[str]
    fields: Dict[str, Any]
    raw_size: int

    @property
    def is_order_msg(self) -> bool:
        """Check if this is an order-related message."""
        return self.msg_type in {'A', 'F', 'E', 'C', 'X', 'D', 'U'}

    @property
    def is_trade_msg(self) -> bool:
        """Check if this is a trade message."""
        return self.msg_type in {'P', 'Q', 'B'}


class ITCHDecoder:
    """
    Decode NASDAQ ITCH 5.0 protocol messages.

    Usage:
        decoder = ITCHDecoder()
        msg = decoder.decode(binary_data)
        print(msg.msg_type_name)  # "Add Order"
    """

    MSG_TYPE_NAMES = {
        'S': 'System Event',
        'R': 'Stock Directory',
        'H': 'Stock Trading Action',
        'Y': 'Reg SHO',
        'L': 'Market Participant Position',
        'V': 'MWCB Decline Level',
        'W': 'MWCB Status',
        'K': 'IPO Quoting Period',
        'J': 'LULD Auction Collar',
        'A': 'Add Order',
        'F': 'Add Order (MPID)',
        'E': 'Order Executed',
        'C': 'Order Executed (Price)',
        'X': 'Order Cancel',
        'D': 'Order Delete',
        'U': 'Order Replace',
        'P': 'Trade (Non-Cross)',
        'Q': 'Cross Trade',
        'B': 'Broken Trade',
        'I': 'NOII',
    }

    # Message sizes (ITCH 5.0)
    MSG_SIZES = {
        'S': 12,
        'R': 39,
        'H': 25,
        'Y': 20,
        'L': 26,
        'V': 35,
        'W': 12,
        'K': 28,
        'J': 35,
        'A': 36,
        'F': 40,
        'E': 31,
        'C': 36,
        'X': 23,
        'D': 19,
        'U': 35,
        'P': 44,
        'Q': 40,
        'B': 19,
        'I': 50,
    }

    def __init__(self):
        """Initialize decoder."""
        pass

    def decode(self, data: bytes, offset: int = 0) -> Optional[ITCHMessage]:
        """
        Decode an ITCH message from binary data.

        Args:
            data: Binary message data
            offset: Offset into data buffer

        Returns:
            Parsed ITCHMessage or None if invalid
        """
        if len(data) < offset + 1:
            return None

        msg_type = chr(data[offset])
        if msg_type not in self.MSG_SIZES:
            return None

        expected_size = self.MSG_SIZES[msg_type]
        if len(data) < offset + expected_size:
            return None

        # Parse based on message type
        fields = {}
        stock = None
        timestamp_ns = 0

        if msg_type == 'A':  # Add Order
            fields = self._parse_add_order(data[offset:offset + expected_size])
            stock = fields.get('stock')
            timestamp_ns = fields.get('timestamp', 0)

        elif msg_type == 'F':  # Add Order MPID
            fields = self._parse_add_order_mpid(data[offset:offset + expected_size])
            stock = fields.get('stock')
            timestamp_ns = fields.get('timestamp', 0)

        elif msg_type == 'E':  # Order Executed
            fields = self._parse_order_executed(data[offset:offset + expected_size])
            timestamp_ns = fields.get('timestamp', 0)

        elif msg_type == 'X':  # Order Cancel
            fields = self._parse_order_cancel(data[offset:offset + expected_size])
            timestamp_ns = fields.get('timestamp', 0)

        elif msg_type == 'D':  # Order Delete
            fields = self._parse_order_delete(data[offset:offset + expected_size])
            timestamp_ns = fields.get('timestamp', 0)

        elif msg_type == 'P':  # Trade
            fields = self._parse_trade(data[offset:offset + expected_size])
            stock = fields.get('stock')
            timestamp_ns = fields.get('timestamp', 0)

        elif msg_type == 'S':  # System Event
            fields = self._parse_system_event(data[offset:offset + expected_size])
            timestamp_ns = fields.get('timestamp', 0)

        else:
            # Generic parse - just extract timestamp
            if len(data) >= offset + 11:
                timestamp_ns = self._parse_timestamp(data[offset + 5:offset + 11])
                fields = {'timestamp': timestamp_ns}

        return ITCHMessage(
            msg_type=msg_type,
            msg_type_name=self.MSG_TYPE_NAMES.get(msg_type, f'Unknown ({msg_type})'),
            timestamp_ns=timestamp_ns,
            stock=stock,
            fields=fields,
            raw_size=expected_size,
        )

    def _parse_timestamp(self, data: bytes) -> int:
        """Parse 6-byte ITCH timestamp (nanoseconds since midnight)."""
        # 6-byte big-endian timestamp
        return struct.unpack('>Q', b'\x00\x00' + data)[0]

    def _parse_add_order(self, data: bytes) -> Dict[str, Any]:
        """Parse Add Order (A) message."""
        return {
            'timestamp': self._parse_timestamp(data[5:11]),
            'order_ref': struct.unpack('>Q', data[11:19])[0],
            'side': chr(data[19]),
            'shares': struct.unpack('>I', data[20:24])[0],
            'stock': data[24:32].decode('ascii').strip(),
            'price': struct.unpack('>I', data[32:36])[0] / 10000,
        }

    def _parse_add_order_mpid(self, data: bytes) -> Dict[str, Any]:
        """Parse Add Order MPID (F) message."""
        return {
            'timestamp': self._parse_timestamp(data[5:11]),
            'order_ref': struct.unpack('>Q', data[11:19])[0],
            'side': chr(data[19]),
            'shares': struct.unpack('>I', data[20:24])[0],
            'stock': data[24:32].decode('ascii').strip(),
            'price': struct.unpack('>I', data[32:36])[0] / 10000,
            'mpid': data[36:40].decode('ascii').strip(),
        }

    def _parse_order_executed(self, data: bytes) -> Dict[str, Any]:
        """Parse Order Executed (E) message."""
        return {
            'timestamp': self._parse_timestamp(data[5:11]),
            'order_ref': struct.unpack('>Q', data[11:19])[0],
            'shares': struct.unpack('>I', data[19:23])[0],
            'match_number': struct.unpack('>Q', data[23:31])[0],
        }

    def _parse_order_cancel(self, data: bytes) -> Dict[str, Any]:
        """Parse Order Cancel (X) message."""
        return {
            'timestamp': self._parse_timestamp(data[5:11]),
            'order_ref': struct.unpack('>Q', data[11:19])[0],
            'canceled_shares': struct.unpack('>I', data[19:23])[0],
        }

    def _parse_order_delete(self, data: bytes) -> Dict[str, Any]:
        """Parse Order Delete (D) message."""
        return {
            'timestamp': self._parse_timestamp(data[5:11]),
            'order_ref': struct.unpack('>Q', data[11:19])[0],
        }

    def _parse_trade(self, data: bytes) -> Dict[str, Any]:
        """Parse Trade (P) message."""
        return {
            'timestamp': self._parse_timestamp(data[5:11]),
            'order_ref': struct.unpack('>Q', data[11:19])[0],
            'side': chr(data[19]),
            'shares': struct.unpack('>I', data[20:24])[0],
            'stock': data[24:32].decode('ascii').strip(),
            'price': struct.unpack('>I', data[32:36])[0] / 10000,
            'match_number': struct.unpack('>Q', data[36:44])[0],
        }

    def _parse_system_event(self, data: bytes) -> Dict[str, Any]:
        """Parse System Event (S) message."""
        return {
            'timestamp': self._parse_timestamp(data[5:11]),
            'event_code': chr(data[11]),
        }

    def get_message_size(self, msg_type: str) -> int:
        """Get expected message size for a message type."""
        return self.MSG_SIZES.get(msg_type, 0)

    @staticmethod
    def is_latency_critical(msg_type: str) -> bool:
        """Check if message type is latency-critical for HFT."""
        # Order messages and trades are most critical
        critical_types = {'A', 'F', 'E', 'C', 'X', 'D', 'U', 'P'}
        return msg_type in critical_types

    def estimate_processing_budget_ns(self, msg_type: str, target_freq_mhz: float = 100) -> int:
        """
        Estimate processing budget for a message type.

        Args:
            msg_type: ITCH message type
            target_freq_mhz: Target processing frequency

        Returns:
            Budget in nanoseconds
        """
        # Base budget: one message per cycle at target frequency
        base_ns = 1000 / target_freq_mhz

        # Adjust by message complexity
        complexity = {
            'A': 1.5,  # Add Order - needs book update
            'F': 1.6,  # Add Order MPID - slightly more
            'E': 2.0,  # Execution - triggers order flow
            'C': 2.0,  # Execution with price
            'X': 1.0,  # Cancel - simple
            'D': 0.8,  # Delete - simplest
            'U': 2.5,  # Replace - most complex
            'P': 1.2,  # Trade - book update
            'S': 0.5,  # System - minimal
        }

        return int(base_ns * complexity.get(msg_type, 1.0))
