"""
Tests for Phase 6: Configuration System.

CRITICAL TESTS:
1. test_env_var_substitution - ${VAR} must be replaced
2. test_validation_errors - Invalid configs must fail validation
3. test_secret_redaction - Secrets must be redacted for logging
"""

import os
import pytest
from pathlib import Path
from tempfile import NamedTemporaryFile

from sentinel_hft.config import (
    SentinelConfig,
    ClockConfig,
    AnalysisConfig,
    ThresholdsConfig,
    load_config,
    generate_default_config,
)


class TestClockConfig:
    """Test clock configuration."""

    def test_default_frequency(self):
        """Default frequency is 100 MHz."""
        clock = ClockConfig()
        assert clock.frequency_mhz == 100.0

    def test_frequency_hz_conversion(self):
        """Frequency converts to Hz correctly."""
        clock = ClockConfig(frequency_mhz=200.0)
        assert clock.frequency_hz == 200_000_000

    def test_period_ns_computation(self):
        """Period is computed correctly."""
        clock = ClockConfig(frequency_mhz=100.0)
        # 100 MHz = 10 ns period
        assert clock.period_ns == 10.0


class TestAnalysisConfig:
    """Test analysis configuration."""

    def test_default_percentiles(self):
        """Default percentiles include P50, P99, P99.9."""
        analysis = AnalysisConfig()
        assert 0.5 in analysis.percentiles
        assert 0.99 in analysis.percentiles
        assert 0.999 in analysis.percentiles


class TestThresholdsConfig:
    """Test thresholds configuration."""

    def test_default_ordering(self):
        """Warning < error < critical by default."""
        thresholds = ThresholdsConfig()
        assert thresholds.p99_warning < thresholds.p99_error
        assert thresholds.p99_error < thresholds.p99_critical


class TestSentinelConfig:
    """Test root configuration."""

    def test_default_config(self):
        """Default config is valid."""
        config = SentinelConfig()
        errors = config.validate()
        assert errors == []

    def test_from_dict(self):
        """Config can be created from dict."""
        data = {
            'version': 1,
            'clock': {'frequency_mhz': 200},
            'thresholds': {'p99_warning': 5},
        }
        config = SentinelConfig.from_dict(data)
        assert config.clock.frequency_mhz == 200
        assert config.thresholds.p99_warning == 5

    def test_to_dict_roundtrip(self):
        """Config survives dict roundtrip."""
        original = SentinelConfig()
        data = original.to_dict()
        restored = SentinelConfig.from_dict(data)
        assert restored.clock.frequency_mhz == original.clock.frequency_mhz

    def test_to_yaml(self):
        """Config can be exported to YAML."""
        config = SentinelConfig()
        yaml_str = config.to_yaml()
        assert 'clock' in yaml_str
        assert 'thresholds' in yaml_str


class TestValidation:
    """Test configuration validation."""

    def test_invalid_clock_frequency(self):
        """Zero/negative frequency fails validation."""
        config = SentinelConfig()
        config.clock.frequency_mhz = 0
        errors = config.validate()
        assert any('frequency' in e.lower() for e in errors)

    def test_invalid_window_seconds(self):
        """Zero/negative window fails validation."""
        config = SentinelConfig()
        config.analysis.window_seconds = -1
        errors = config.validate()
        assert any('window' in e.lower() for e in errors)

    def test_invalid_threshold_ordering(self):
        """Warning >= error fails validation."""
        config = SentinelConfig()
        config.thresholds.p99_warning = 100
        config.thresholds.p99_error = 50
        errors = config.validate()
        assert any('warning' in e.lower() and 'error' in e.lower() for e in errors)

    def test_slack_enabled_without_webhook(self):
        """Slack enabled without webhook fails validation."""
        config = SentinelConfig()
        config.exporters.slack.enabled = True
        config.exporters.slack.webhook = None
        errors = config.validate()
        assert any('slack' in e.lower() and 'webhook' in e.lower() for e in errors)


class TestEnvVarSubstitution:
    """Test environment variable substitution."""

    def test_env_var_substitution(self):
        """
        CRITICAL TEST: ${VAR} must be replaced with env value.
        """
        # Set env var
        os.environ['TEST_WEBHOOK_URL'] = 'https://hooks.slack.com/test123'

        try:
            yaml_content = """
version: 1
exporters:
  slack:
    enabled: true
    webhook: ${TEST_WEBHOOK_URL}
"""
            with NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
                f.write(yaml_content)
                f.flush()
                config = SentinelConfig.load(Path(f.name))

            assert config.exporters.slack.webhook == 'https://hooks.slack.com/test123'

        finally:
            os.environ.pop('TEST_WEBHOOK_URL', None)

    def test_env_var_not_found_kept(self):
        """Missing env vars are kept as-is."""
        yaml_content = """
version: 1
exporters:
  slack:
    webhook: ${NONEXISTENT_VAR_12345}
"""
        with NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = SentinelConfig.load(Path(f.name))

        # Original ${VAR} syntax is preserved
        assert '${NONEXISTENT_VAR_12345}' in config.exporters.slack.webhook


class TestSecretRedaction:
    """Test secret redaction for logging."""

    def test_secret_redaction(self):
        """
        CRITICAL TEST: Secrets must be redacted for safe logging.
        """
        config = SentinelConfig()
        config.exporters.slack.webhook = 'https://hooks.slack.com/secret123'

        redacted = config.redacted()

        # Original unchanged
        assert config.exporters.slack.webhook == 'https://hooks.slack.com/secret123'

        # Redacted version
        assert redacted.exporters.slack.webhook == '***REDACTED***'


class TestFileLoading:
    """Test YAML file loading."""

    def test_load_from_file(self):
        """Config loads from YAML file."""
        yaml_content = """
version: 1
clock:
  frequency_mhz: 250
thresholds:
  p99_warning: 8
  p99_error: 40
"""
        with NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = SentinelConfig.load(Path(f.name))

        assert config.clock.frequency_mhz == 250
        assert config.thresholds.p99_warning == 8
        assert config.thresholds.p99_error == 40

    def test_load_missing_file(self):
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            SentinelConfig.load(Path('/nonexistent/config.yml'))

    def test_load_config_returns_defaults(self):
        """load_config returns defaults when no file found."""
        config = load_config(path=None)
        assert config.version == 1


class TestDefaultConfigGeneration:
    """Test default config generation."""

    def test_generate_default_config(self):
        """Generated default config is valid YAML."""
        yaml_str = generate_default_config()
        assert 'version: 1' in yaml_str
        assert 'clock:' in yaml_str
        assert 'frequency_mhz:' in yaml_str


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
