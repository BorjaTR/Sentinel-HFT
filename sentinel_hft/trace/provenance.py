"""
Trace provenance tracking for reproducible comparisons.
"""

import hashlib
import json
import os
import subprocess
import struct
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import socket


@dataclass
class Provenance:
    """Provenance metadata for a trace file."""

    # Source identification
    git_sha: Optional[str] = None
    git_branch: Optional[str] = None
    git_dirty: bool = False
    build_id: Optional[str] = None

    # Configuration
    config_hash: Optional[str] = None
    config_summary: Optional[Dict[str, Any]] = None

    # Input data
    stimulus_hash: Optional[str] = None
    stimulus_description: Optional[str] = None

    # Environment
    clock_mhz: float = 100.0
    trace_format: str = "1.2"
    timestamp: Optional[str] = None
    hostname: Optional[str] = None

    # Custom
    tags: list = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def capture(cls,
                config_file: Optional[Path] = None,
                stimulus_file: Optional[Path] = None,
                clock_mhz: float = 100.0,
                trace_format: str = "1.2",
                tags: list = None,
                extra: dict = None) -> "Provenance":
        """
        Capture current environment provenance.
        Call this when generating a trace file.
        """
        prov = cls()

        # Git information
        prov.git_sha = cls._get_git_sha()
        prov.git_branch = cls._get_git_branch()
        prov.git_dirty = cls._get_git_dirty()

        # Build ID from environment (CI systems set this)
        prov.build_id = (
            os.environ.get('GITHUB_RUN_ID') or
            os.environ.get('CI_BUILD_ID') or
            os.environ.get('BUILD_ID') or
            os.environ.get('BUILD_NUMBER')
        )

        # Config hash
        if config_file and Path(config_file).exists():
            prov.config_hash = cls._hash_file(config_file)
            prov.config_summary = cls._parse_config_summary(config_file)

        # Stimulus hash
        if stimulus_file and Path(stimulus_file).exists():
            prov.stimulus_hash = cls._hash_file(stimulus_file)
            prov.stimulus_description = f"File: {Path(stimulus_file).name}"

        # Environment
        prov.clock_mhz = clock_mhz
        prov.trace_format = trace_format
        prov.timestamp = datetime.utcnow().isoformat() + "Z"
        prov.hostname = socket.gethostname()

        # Custom
        prov.tags = tags or []
        prov.extra = extra or {}

        return prov

    @staticmethod
    def _get_git_sha() -> Optional[str]:
        try:
            result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()[:40]
        except Exception:
            pass
        return None

    @staticmethod
    def _get_git_branch() -> Optional[str]:
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    @staticmethod
    def _get_git_dirty() -> bool:
        try:
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                capture_output=True, text=True, timeout=5
            )
            return bool(result.stdout.strip())
        except Exception:
            return False

    @staticmethod
    def _hash_file(path: Path) -> str:
        """SHA256 hash of file contents."""
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _parse_config_summary(path: Path) -> Optional[Dict[str, Any]]:
        """Extract key config values for display."""
        try:
            with open(path) as f:
                if path.suffix in ('.json',):
                    return json.load(f)
                elif path.suffix in ('.yaml', '.yml'):
                    import yaml
                    return yaml.safe_load(f)
        except Exception:
            pass
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Provenance":
        """Create from dictionary."""
        # Handle missing fields gracefully
        valid_fields = {
            'git_sha', 'git_branch', 'git_dirty', 'build_id',
            'config_hash', 'config_summary', 'stimulus_hash',
            'stimulus_description', 'clock_mhz', 'trace_format',
            'timestamp', 'hostname', 'tags', 'extra'
        }
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def to_bytes(self) -> bytes:
        """Serialize to bytes for embedding in trace file."""
        json_bytes = json.dumps(self.to_dict()).encode('utf-8')
        # Length prefix (4 bytes) + JSON
        return struct.pack('<I', len(json_bytes)) + json_bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> "Provenance":
        """Deserialize from bytes."""
        length = struct.unpack('<I', data[:4])[0]
        json_bytes = data[4:4+length]
        return cls.from_dict(json.loads(json_bytes.decode('utf-8')))

    def matches(self, other: "Provenance",
                require_same_stimulus: bool = True,
                require_same_config: bool = True,
                require_same_clock: bool = True) -> "ProvenanceMatch":
        """
        Check if two provenance records are comparable.
        Returns detailed match result.
        """
        issues = []
        warnings = []

        # Critical: stimulus must match for valid comparison
        if require_same_stimulus:
            if self.stimulus_hash and other.stimulus_hash:
                if self.stimulus_hash != other.stimulus_hash:
                    issues.append(
                        f"Stimulus mismatch: {self.stimulus_hash[:8]}... vs {other.stimulus_hash[:8]}..."
                    )
            elif self.stimulus_hash or other.stimulus_hash:
                warnings.append("One trace has stimulus hash, other doesn't")

        # Critical: config should match
        if require_same_config:
            if self.config_hash and other.config_hash:
                if self.config_hash != other.config_hash:
                    issues.append(
                        f"Config mismatch: {self.config_hash[:8]}... vs {other.config_hash[:8]}..."
                    )
            elif self.config_hash or other.config_hash:
                warnings.append("One trace has config hash, other doesn't")

        # Critical: clock must match
        if require_same_clock:
            if abs(self.clock_mhz - other.clock_mhz) > 0.01:
                issues.append(
                    f"Clock mismatch: {self.clock_mhz}MHz vs {other.clock_mhz}MHz"
                )

        # Warning: format should match
        if self.trace_format != other.trace_format:
            warnings.append(
                f"Format mismatch: {self.trace_format} vs {other.trace_format}"
            )

        # Warning: dirty git state
        if self.git_dirty or other.git_dirty:
            warnings.append("One or both traces from dirty git state")

        return ProvenanceMatch(
            comparable=len(issues) == 0,
            issues=issues,
            warnings=warnings,
            baseline_sha=self.git_sha,
            current_sha=other.git_sha,
        )


@dataclass
class ProvenanceMatch:
    """Result of comparing two provenance records."""
    comparable: bool
    issues: list
    warnings: list
    baseline_sha: Optional[str]
    current_sha: Optional[str]

    def print_report(self, verbose: bool = False):
        """Print human-readable comparison report."""
        try:
            import click

            if self.comparable:
                click.secho("Traces are comparable", fg='green')
            else:
                click.secho("Traces NOT comparable", fg='red')

            if self.issues:
                click.echo("\nIssues (comparison invalid):")
                for issue in self.issues:
                    click.secho(f"  {issue}", fg='red')

            if self.warnings:
                click.echo("\nWarnings:")
                for warning in self.warnings:
                    click.secho(f"  {warning}", fg='yellow')

            if verbose and self.baseline_sha and self.current_sha:
                click.echo(f"\nCommits: {self.baseline_sha[:8]} -> {self.current_sha[:8]}")
        except ImportError:
            # Fallback without click
            print("Comparable:" if self.comparable else "NOT Comparable")
            for issue in self.issues:
                print(f"  Issue: {issue}")
            for warning in self.warnings:
                print(f"  Warning: {warning}")
