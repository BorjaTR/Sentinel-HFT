"""Sentinel-HFT Wind Tunnel - Replay infrastructure for RTL simulation."""

from .input_formats import (
    InputTransaction,
    parse_csv,
    parse_binary,
    detect_format,
    load_input,
    write_stimulus_binary,
)

from .trace_pipeline import (
    EnrichedTrace,
    ValidationResult,
    TracePipeline,
)

from .replay_runner import (
    ReplayConfig,
    ReplayResult,
    ReplayRunner,
    run_replay,
)

__all__ = [
    # Input formats
    'InputTransaction',
    'parse_csv',
    'parse_binary',
    'detect_format',
    'load_input',
    'write_stimulus_binary',
    # Trace pipeline
    'EnrichedTrace',
    'ValidationResult',
    'TracePipeline',
    # Replay runner
    'ReplayConfig',
    'ReplayResult',
    'ReplayRunner',
    'run_replay',
]
