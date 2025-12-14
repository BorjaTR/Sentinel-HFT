"""
Trace record type constants.

Each trace record has a type field that determines how it should be processed:
- TX_EVENT: Normal transaction, contributes to latency statistics
- OVERFLOW: Indicates traces were dropped due to FIFO overflow
- HEARTBEAT: Liveness marker, doesn't affect latency stats
- CLOCK_SYNC: Cross-clock-domain synchronization marker
- RESET: Sequence number reset marker
"""


class RecordType:
    """Trace record type constants."""

    # Normal transaction - the only type that affects latency statistics
    TX_EVENT = 0x01

    # Overflow summary - data field contains count of traces lost
    OVERFLOW = 0x02

    # Heartbeat/liveness marker
    HEARTBEAT = 0x03

    # Clock synchronization marker (for multi-clock-domain systems)
    CLOCK_SYNC = 0x04

    # Sequence reset marker - indicates seq_no was reset
    RESET = 0x05

    @classmethod
    def name(cls, type_value: int) -> str:
        """Get human-readable name for record type."""
        names = {
            cls.TX_EVENT: 'TX_EVENT',
            cls.OVERFLOW: 'OVERFLOW',
            cls.HEARTBEAT: 'HEARTBEAT',
            cls.CLOCK_SYNC: 'CLOCK_SYNC',
            cls.RESET: 'RESET',
        }
        return names.get(type_value, f'UNKNOWN({type_value})')

    @classmethod
    def is_valid(cls, type_value: int) -> bool:
        """Check if type value is known."""
        return type_value in (
            cls.TX_EVENT,
            cls.OVERFLOW,
            cls.HEARTBEAT,
            cls.CLOCK_SYNC,
            cls.RESET,
        )
