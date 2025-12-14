"""
Configuration schema for Sentinel-HFT.

Supports:
- YAML file loading
- Environment variable substitution (${VAR_NAME})
- Validation with error messages
- Secret redaction for safe logging

Example config (sentinel.yml):
    version: 1

    clock:
      frequency_mhz: 200

    thresholds:
      p99_warning: 10
      p99_error: 50

    exporters:
      slack:
        webhook: ${SLACK_WEBHOOK_URL}
"""

import os
import re
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Any

import yaml


def _substitute_env_vars(value: Any) -> Any:
    """
    Substitute ${VAR_NAME} with environment variable values.

    Example:
        ${SLACK_WEBHOOK_URL} → os.environ.get('SLACK_WEBHOOK_URL')
    """
    if isinstance(value, str):
        pattern = r'\$\{([^}]+)\}'

        def replace(match):
            var_name = match.group(1)
            env_value = os.environ.get(var_name)
            if env_value is None:
                return match.group(0)  # Keep original if not found
            return env_value

        return re.sub(pattern, replace, value)

    elif isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}

    elif isinstance(value, list):
        return [_substitute_env_vars(v) for v in value]

    return value


@dataclass
class ClockConfig:
    """Clock configuration."""
    frequency_mhz: float = 100.0

    @property
    def frequency_hz(self) -> float:
        return self.frequency_mhz * 1_000_000

    @property
    def period_ns(self) -> float:
        return 1000.0 / self.frequency_mhz


@dataclass
class AnalysisConfig:
    """Analysis settings."""
    window_seconds: float = 60.0
    anomaly_zscore: float = 3.0
    percentiles: List[float] = field(
        default_factory=lambda: [0.5, 0.75, 0.9, 0.95, 0.99, 0.999]
    )
    max_anomalies_tracked: int = 1000


@dataclass
class ThresholdsConfig:
    """Alert thresholds."""
    p99_warning: int = 10
    p99_error: int = 50
    p99_critical: int = 100
    anomaly_rate_warning: float = 0.01
    anomaly_rate_error: float = 0.05
    drop_rate_warning: float = 0.001
    drop_rate_error: float = 0.01


@dataclass
class PrometheusConfig:
    """Prometheus exporter settings."""
    enabled: bool = True
    port: int = 9090
    prefix: str = 'sentinel_hft'


@dataclass
class SlackConfig:
    """Slack alerter settings."""
    enabled: bool = False
    webhook: Optional[str] = None
    channel: str = '#alerts'
    mention_on_critical: Optional[str] = None
    cooldown_seconds: float = 300.0

    def get_webhook(self) -> Optional[str]:
        if self.webhook and self.webhook.startswith('${'):
            return _substitute_env_vars(self.webhook)
        return self.webhook


@dataclass
class ExportersConfig:
    """Exporter settings."""
    prometheus: PrometheusConfig = field(default_factory=PrometheusConfig)
    slack: SlackConfig = field(default_factory=SlackConfig)


@dataclass
class SentinelConfig:
    """Root configuration."""

    version: int = 1
    clock: ClockConfig = field(default_factory=ClockConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    thresholds: ThresholdsConfig = field(default_factory=ThresholdsConfig)
    exporters: ExportersConfig = field(default_factory=ExportersConfig)

    @classmethod
    def load(cls, path: Path) -> 'SentinelConfig':
        """Load from YAML file with env var substitution."""
        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(f"Config not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        data = _substitute_env_vars(data)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> 'SentinelConfig':
        """Create from dictionary."""
        return cls(
            version=data.get('version', 1),
            clock=ClockConfig(**data.get('clock', {})),
            analysis=AnalysisConfig(**data.get('analysis', {})),
            thresholds=ThresholdsConfig(**data.get('thresholds', {})),
            exporters=ExportersConfig(
                prometheus=PrometheusConfig(**data.get('exporters', {}).get('prometheus', {})),
                slack=SlackConfig(**data.get('exporters', {}).get('slack', {})),
            ) if 'exporters' in data else ExportersConfig(),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)

    def to_yaml(self) -> str:
        """Convert to YAML string."""
        return yaml.dump(self.to_dict(), default_flow_style=False, sort_keys=False)

    def validate(self) -> List[str]:
        """Validate config. Returns list of errors (empty if valid)."""
        errors = []

        if self.clock.frequency_mhz <= 0:
            errors.append(f"Invalid clock frequency: {self.clock.frequency_mhz}")

        if self.analysis.window_seconds <= 0:
            errors.append(f"Invalid window_seconds: {self.analysis.window_seconds}")

        if self.thresholds.p99_warning >= self.thresholds.p99_error:
            errors.append("p99_warning should be less than p99_error")

        if self.exporters.prometheus.enabled and self.exporters.prometheus.port <= 0:
            errors.append(f"Invalid Prometheus port: {self.exporters.prometheus.port}")

        if self.exporters.slack.enabled and not self.exporters.slack.get_webhook():
            errors.append("Slack enabled but webhook not configured")

        return errors

    def redacted(self) -> 'SentinelConfig':
        """Return copy with secrets redacted."""
        import copy
        redacted = copy.deepcopy(self)
        if redacted.exporters.slack.webhook:
            redacted.exporters.slack.webhook = '***REDACTED***'
        return redacted


def load_config(path: Optional[Path] = None) -> SentinelConfig:
    """Load config from file or return defaults."""
    if path and Path(path).exists():
        return SentinelConfig.load(path)

    search_paths = [
        Path('./sentinel.yml'),
        Path('./sentinel.yaml'),
        Path.home() / '.sentinel' / 'config.yml',
    ]

    for p in search_paths:
        if p.exists():
            return SentinelConfig.load(p)

    return SentinelConfig()


def generate_default_config() -> str:
    """Generate default config as YAML."""
    return """# Sentinel-HFT Configuration
version: 1

clock:
  frequency_mhz: 100

analysis:
  window_seconds: 60.0
  anomaly_zscore: 3.0

thresholds:
  p99_warning: 10
  p99_error: 50
  p99_critical: 100
  drop_rate_warning: 0.001
  drop_rate_error: 0.01

exporters:
  prometheus:
    enabled: true
    port: 9090
  slack:
    enabled: false
    webhook: ${SLACK_WEBHOOK_URL}
    channel: "#alerts"
"""
