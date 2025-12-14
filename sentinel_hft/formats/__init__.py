"""Trace format definitions and readers."""

from .file_header import FileHeader, HEADER_SIZE, MAGIC
from .record_types import RecordType
from .reader import TraceReader, TraceFile

__all__ = [
    'FileHeader',
    'HEADER_SIZE',
    'MAGIC',
    'RecordType',
    'TraceReader',
    'TraceFile',
]
