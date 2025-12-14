"""
Error codes for Sentinel-HFT.

Structured error codes for machine-parseable reports.

Format: E{category}{number}
- E1xxx: Data errors
- E2xxx: Analysis errors
- E3xxx: Configuration errors
- E4xxx: Export errors
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class ErrorCode(Enum):
    """Structured error codes."""

    # E1xxx: Data errors
    E1001_INVALID_MAGIC = "E1001"
    E1002_UNSUPPORTED_VERSION = "E1002"
    E1003_TRUNCATED_RECORD = "E1003"
    E1004_CRC_MISMATCH = "E1004"
    E1005_EMPTY_FILE = "E1005"
    E1006_HEADER_DECODE_FAILED = "E1006"

    # E2xxx: Analysis errors
    E2001_SEQUENCE_GAP = "E2001"
    E2002_SEQUENCE_WRAP_GAP = "E2002"
    E2003_HIGH_DROP_RATE = "E2003"
    E2004_OVERFLOW_DETECTED = "E2004"
    E2005_INSUFFICIENT_SAMPLES = "E2005"

    # E3xxx: Configuration errors
    E3001_INVALID_CONFIG = "E3001"
    E3002_MISSING_ENV_VAR = "E3002"
    E3003_VALIDATION_FAILED = "E3003"

    # E4xxx: Export errors
    E4001_PROMETHEUS_FAILED = "E4001"
    E4002_SLACK_FAILED = "E4002"
    E4003_FILE_WRITE_FAILED = "E4003"


# Error code metadata
ERROR_METADATA = {
    ErrorCode.E1001_INVALID_MAGIC: {
        'severity': 'error',
        'message': 'Invalid file magic number',
        'recoverable': False,
    },
    ErrorCode.E1002_UNSUPPORTED_VERSION: {
        'severity': 'error',
        'message': 'Unsupported format version',
        'recoverable': False,
    },
    ErrorCode.E1003_TRUNCATED_RECORD: {
        'severity': 'warning',
        'message': 'Record truncated or incomplete',
        'recoverable': True,
    },
    ErrorCode.E1004_CRC_MISMATCH: {
        'severity': 'error',
        'message': 'CRC checksum mismatch',
        'recoverable': True,
    },
    ErrorCode.E1005_EMPTY_FILE: {
        'severity': 'warning',
        'message': 'File contains no records',
        'recoverable': True,
    },
    ErrorCode.E1006_HEADER_DECODE_FAILED: {
        'severity': 'error',
        'message': 'Failed to decode file header',
        'recoverable': False,
    },
    ErrorCode.E2001_SEQUENCE_GAP: {
        'severity': 'warning',
        'message': 'Gap detected in sequence numbers',
        'recoverable': True,
    },
    ErrorCode.E2002_SEQUENCE_WRAP_GAP: {
        'severity': 'warning',
        'message': 'Gap detected across sequence wrap boundary',
        'recoverable': True,
    },
    ErrorCode.E2003_HIGH_DROP_RATE: {
        'severity': 'error',
        'message': 'Drop rate exceeds threshold',
        'recoverable': True,
    },
    ErrorCode.E2004_OVERFLOW_DETECTED: {
        'severity': 'warning',
        'message': 'FPGA overflow event detected',
        'recoverable': True,
    },
    ErrorCode.E2005_INSUFFICIENT_SAMPLES: {
        'severity': 'warning',
        'message': 'Insufficient samples for accurate percentiles',
        'recoverable': True,
    },
    ErrorCode.E3001_INVALID_CONFIG: {
        'severity': 'error',
        'message': 'Invalid configuration',
        'recoverable': False,
    },
    ErrorCode.E3002_MISSING_ENV_VAR: {
        'severity': 'warning',
        'message': 'Environment variable not set',
        'recoverable': True,
    },
    ErrorCode.E3003_VALIDATION_FAILED: {
        'severity': 'error',
        'message': 'Configuration validation failed',
        'recoverable': False,
    },
    ErrorCode.E4001_PROMETHEUS_FAILED: {
        'severity': 'warning',
        'message': 'Failed to export to Prometheus',
        'recoverable': True,
    },
    ErrorCode.E4002_SLACK_FAILED: {
        'severity': 'warning',
        'message': 'Failed to send Slack alert',
        'recoverable': True,
    },
    ErrorCode.E4003_FILE_WRITE_FAILED: {
        'severity': 'error',
        'message': 'Failed to write output file',
        'recoverable': True,
    },
}


@dataclass
class SentinelError:
    """
    Structured error with context.

    Example:
        error = SentinelError(
            code=ErrorCode.E2001_SEQUENCE_GAP,
            context={'core_id': 0, 'expected': 100, 'actual': 105},
        )
    """
    code: ErrorCode
    context: Optional[dict] = None

    @property
    def severity(self) -> str:
        return ERROR_METADATA.get(self.code, {}).get('severity', 'error')

    @property
    def message(self) -> str:
        base_msg = ERROR_METADATA.get(self.code, {}).get('message', 'Unknown error')
        if self.context:
            return f"{base_msg}: {self.context}"
        return base_msg

    @property
    def recoverable(self) -> bool:
        return ERROR_METADATA.get(self.code, {}).get('recoverable', False)

    def to_dict(self) -> dict:
        return {
            'code': self.code.value,
            'severity': self.severity,
            'message': self.message,
            'recoverable': self.recoverable,
            'context': self.context,
        }
