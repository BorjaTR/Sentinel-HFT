"""
Tests for Phase 9: Exporters.

CRITICAL TESTS:
1. test_prometheus_format - Metrics must be in valid Prometheus format
2. test_slack_message_format - Slack messages must have correct structure
3. test_cooldown - Alerts respect cooldown period
"""

import pytest
import time
from unittest.mock import Mock, patch

from sentinel_hft.exporters.prometheus import PrometheusExporter, MetricDefinition
from sentinel_hft.exporters.slack import SlackAlerter, SlackMessage
from sentinel_hft.core.report import (
    AnalysisReport,
    ReportStatus,
    LatencyStats,
    DropStats,
    RiskStats,
)


class TestPrometheusExporter:
    """Test Prometheus exporter."""

    def test_set_and_get_metric(self):
        """Metrics can be set and retrieved."""
        exporter = PrometheusExporter()

        exporter.set_metric('latency_p99_cycles', 42.5)

        assert exporter.get_metric('latency_p99_cycles') == 42.5

    def test_prometheus_format(self):
        """
        CRITICAL TEST: Metrics in valid Prometheus format.
        """
        exporter = PrometheusExporter(prefix='test')

        exporter.set_metric('latency_p99_cycles', 100)
        exporter.set_metric('drop_rate', 0.001)
        exporter.set_metric('kill_switch', 0)

        output = exporter.format_metrics()

        # Check format components
        assert '# HELP test_latency_p99_cycles' in output
        assert '# TYPE test_latency_p99_cycles gauge' in output
        assert 'test_latency_p99_cycles 100' in output

        assert '# HELP test_drop_rate' in output
        assert 'test_drop_rate 0.001' in output

    def test_update_from_snapshot(self):
        """Exporter updates from analyzer snapshot."""
        exporter = PrometheusExporter()

        snapshot = {
            'latency': {
                'count': 1000,
                'p99_cycles': 45,
                'p999_cycles': 80,
                'mean_cycles': 12.5,
                'min_cycles': 5,
                'max_cycles': 120,
            },
            'drops': {
                'drop_rate': 0.0001,
                'total_dropped': 10,
            },
            'overflow': {
                'overflow_records': 2,
                'traces_lost': 500,
            },
            'risk': {
                'rate_limit_rejects': 5,
                'kill_switch_triggered': False,
            },
            'anomalies': {
                'count': 3,
            },
        }

        exporter.update_from_snapshot(snapshot)

        assert exporter.get_metric('latency_p99_cycles') == 45
        assert exporter.get_metric('latency_mean_cycles') == 12.5
        assert exporter.get_metric('drop_rate') == 0.0001
        assert exporter.get_metric('kill_switch') == 0

    def test_update_from_report(self):
        """Exporter updates from analysis report."""
        exporter = PrometheusExporter()

        report = AnalysisReport()
        report.latency.p99_cycles = 55
        report.latency.p999_cycles = 90
        report.latency.mean_cycles = 15.0
        report.latency.count = 5000
        report.drops.drop_rate = 0.002
        report.drops.total_drops = 100
        report.risk.kill_switch_triggered = True
        report.status = ReportStatus.ERROR

        exporter.update_from_report(report)

        assert exporter.get_metric('latency_p99_cycles') == 55
        assert exporter.get_metric('tx_count') == 5000
        assert exporter.get_metric('kill_switch') == 1
        assert exporter.get_metric('status') == 2  # ERROR = 2

    def test_status_mapping(self):
        """Status maps to correct numeric value."""
        exporter = PrometheusExporter()

        for status, expected in [
            (ReportStatus.OK, 0),
            (ReportStatus.WARNING, 1),
            (ReportStatus.ERROR, 2),
            (ReportStatus.CRITICAL, 3),
        ]:
            report = AnalysisReport()
            report.status = status
            exporter.update_from_report(report)
            assert exporter.get_metric('status') == expected


class TestSlackMessage:
    """Test Slack message formatting."""

    def test_slack_message_format(self):
        """
        CRITICAL TEST: Slack messages have correct structure.
        """
        message = SlackMessage(
            channel='#alerts',
            text='Test alert',
            attachments=[{'color': 'danger', 'text': 'Details'}],
        )

        d = message.to_dict()

        assert d['channel'] == '#alerts'
        assert d['text'] == 'Test alert'
        assert len(d['attachments']) == 1
        assert d['username'] == 'Sentinel-HFT'


class TestSlackAlerter:
    """Test Slack alerter."""

    def test_alert_not_sent_for_ok_status(self):
        """OK status doesn't trigger alert."""
        alerter = SlackAlerter(webhook_url='https://example.com/hook')

        report = AnalysisReport()
        report.status = ReportStatus.OK

        # Mock the send to ensure it's not called
        alerter.send_message = Mock(return_value=True)

        result = alerter.alert_on_status(report)

        assert result is False
        alerter.send_message.assert_not_called()

    def test_alert_sent_for_warning_status(self):
        """WARNING status triggers alert."""
        alerter = SlackAlerter(
            webhook_url='https://example.com/hook',
            cooldown_seconds=0,  # Disable cooldown for test
        )

        report = AnalysisReport()
        report.status = ReportStatus.WARNING
        report.status_reason = 'P99 latency elevated'

        alerter.send_message = Mock(return_value=True)

        result = alerter.alert_on_status(report)

        assert result is True
        alerter.send_message.assert_called_once()

    def test_alert_sent_for_critical_status(self):
        """CRITICAL status triggers alert."""
        alerter = SlackAlerter(
            webhook_url='https://example.com/hook',
            cooldown_seconds=0,
        )

        report = AnalysisReport()
        report.status = ReportStatus.CRITICAL
        report.risk.kill_switch_triggered = True

        alerter.send_message = Mock(return_value=True)

        result = alerter.alert_on_status(report)

        assert result is True

    def test_mention_on_critical(self):
        """Critical alerts include mention."""
        alerter = SlackAlerter(
            webhook_url='https://example.com/hook',
            mention_on_critical='@oncall',
            cooldown_seconds=0,
        )

        report = AnalysisReport()
        report.status = ReportStatus.CRITICAL

        captured_message = []

        def capture_send(msg):
            captured_message.append(msg)
            return True

        alerter.send_message = capture_send

        alerter.alert_on_status(report)

        assert len(captured_message) == 1
        assert '@oncall' in captured_message[0].text

    def test_cooldown(self):
        """
        CRITICAL TEST: Alerts respect cooldown period.
        """
        alerter = SlackAlerter(
            webhook_url='https://example.com/hook',
            cooldown_seconds=60,  # 60 second cooldown
        )

        report = AnalysisReport()
        report.status = ReportStatus.WARNING

        alerter.send_message = Mock(return_value=True)

        # First alert should send
        result1 = alerter.alert_on_status(report)
        assert result1 is True
        assert alerter.send_message.call_count == 1

        # Second alert should be blocked by cooldown
        result2 = alerter.alert_on_status(report)
        assert result2 is False
        assert alerter.send_message.call_count == 1  # Still 1

        # Force should bypass cooldown
        result3 = alerter.alert_on_status(report, force=True)
        assert result3 is True
        assert alerter.send_message.call_count == 2

    def test_no_webhook_returns_false(self):
        """Missing webhook URL returns False."""
        alerter = SlackAlerter(webhook_url=None)

        message = SlackMessage(channel='#test', text='test')
        result = alerter.send_message(message)

        assert result is False

    def test_attachment_formatting(self):
        """Report attachment has correct fields."""
        alerter = SlackAlerter(webhook_url='https://example.com/hook')

        report = AnalysisReport()
        report.status = ReportStatus.ERROR
        report.latency.p99_cycles = 100
        report.latency.p999_cycles = 150
        report.latency.count = 1000
        report.drops.drop_rate = 0.01
        report.source_file = 'test.bin'

        attachment = alerter._format_report_attachment(report)

        assert attachment['color'] == 'danger'
        assert 'ERROR' in attachment['title']
        assert len(attachment['fields']) >= 4
        assert attachment['footer'] == 'Source: test.bin'


class TestPrometheusServer:
    """Test Prometheus HTTP server."""

    def test_server_start_stop(self):
        """Server starts and stops cleanly."""
        exporter = PrometheusExporter(port=0)  # Port 0 = random available port

        # This is a basic test - actual HTTP test would need the server running
        # Just verify we can create and have the right attributes
        assert exporter._server is None
        assert exporter._thread is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
