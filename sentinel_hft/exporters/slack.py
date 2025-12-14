"""
Slack alerter for Sentinel-HFT.

Sends alerts to Slack via webhook when thresholds are exceeded.

Example:
    alerter = SlackAlerter(
        webhook_url='https://hooks.slack.com/services/...',
        channel='#alerts',
    )

    # Send alert based on report
    alerter.alert_on_status(report)
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from ..core.report import AnalysisReport, ReportStatus

logger = logging.getLogger(__name__)


@dataclass
class SlackMessage:
    """Slack message structure."""
    channel: str
    text: str
    attachments: list = field(default_factory=list)
    username: str = 'Sentinel-HFT'
    icon_emoji: str = ':warning:'

    def to_dict(self) -> dict:
        return {
            'channel': self.channel,
            'text': self.text,
            'attachments': self.attachments,
            'username': self.username,
            'icon_emoji': self.icon_emoji,
        }


class SlackAlerter:
    """
    Send alerts to Slack.

    Features:
    - Alert on status changes
    - Cooldown period to avoid spam
    - Mention on critical alerts
    - Rich message formatting
    """

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        channel: str = '#alerts',
        mention_on_critical: Optional[str] = None,
        cooldown_seconds: float = 300.0,
    ):
        self.webhook_url = webhook_url
        self.channel = channel
        self.mention_on_critical = mention_on_critical
        self.cooldown_seconds = cooldown_seconds

        # Track last alert time per status to avoid spam
        self._last_alert_time: Dict[str, float] = {}
        self._last_status: Optional[ReportStatus] = None

    def _can_send(self, alert_type: str) -> bool:
        """Check if we can send an alert (cooldown expired)."""
        last_time = self._last_alert_time.get(alert_type, 0)
        return (time.time() - last_time) >= self.cooldown_seconds

    def _record_send(self, alert_type: str) -> None:
        """Record that we sent an alert."""
        self._last_alert_time[alert_type] = time.time()

    def send_message(self, message: SlackMessage) -> bool:
        """
        Send a message to Slack.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self.webhook_url:
            logger.warning("Slack webhook URL not configured")
            return False

        payload = json.dumps(message.to_dict()).encode('utf-8')

        try:
            request = Request(
                self.webhook_url,
                data=payload,
                headers={'Content-Type': 'application/json'},
            )
            with urlopen(request, timeout=10) as response:
                return response.status == 200

        except HTTPError as e:
            logger.error(f"Slack HTTP error: {e.code} {e.reason}")
            return False
        except URLError as e:
            logger.error(f"Slack URL error: {e.reason}")
            return False
        except Exception as e:
            logger.error(f"Slack send error: {e}")
            return False

    def _format_report_attachment(self, report: AnalysisReport) -> dict:
        """Format report as Slack attachment."""
        # Color based on status
        color_map = {
            ReportStatus.OK: 'good',
            ReportStatus.WARNING: 'warning',
            ReportStatus.ERROR: 'danger',
            ReportStatus.CRITICAL: 'danger',
        }

        fields = [
            {
                'title': 'P99 Latency',
                'value': f"{report.latency.p99_cycles} cycles ({report.latency.p99_ns or 0:.1f} ns)",
                'short': True,
            },
            {
                'title': 'P99.9 Latency',
                'value': f"{report.latency.p999_cycles} cycles",
                'short': True,
            },
            {
                'title': 'TX Events',
                'value': f"{report.latency.count:,}",
                'short': True,
            },
            {
                'title': 'Drop Rate',
                'value': f"{report.drops.drop_rate:.4%}",
                'short': True,
            },
        ]

        if report.risk.kill_switch_triggered:
            fields.append({
                'title': 'Kill Switch',
                'value': 'TRIGGERED',
                'short': True,
            })

        if report.anomalies.total_anomalies > 0:
            fields.append({
                'title': 'Anomalies',
                'value': str(report.anomalies.total_anomalies),
                'short': True,
            })

        return {
            'color': color_map.get(report.status, 'warning'),
            'title': f'Status: {report.status.value.upper()}',
            'text': report.status_reason or 'No specific reason',
            'fields': fields,
            'footer': f'Source: {report.source_file or "unknown"}',
            'ts': int(time.time()),
        }

    def alert_on_status(self, report: AnalysisReport, force: bool = False) -> bool:
        """
        Send alert if status warrants it.

        Alerts are sent for:
        - WARNING, ERROR, CRITICAL status
        - Status transitions (e.g., OK -> WARNING)

        Args:
            report: Analysis report
            force: Send regardless of cooldown

        Returns:
            True if alert was sent
        """
        # Only alert on non-OK status
        if report.status == ReportStatus.OK:
            if self._last_status is not None and self._last_status != ReportStatus.OK:
                # Status improved - send recovery message
                return self._send_recovery(report)
            self._last_status = report.status
            return False

        alert_type = f"status_{report.status.value}"

        if not force and not self._can_send(alert_type):
            logger.debug(f"Skipping alert (cooldown): {alert_type}")
            return False

        # Build message
        text = f"Sentinel-HFT Alert: {report.status.value.upper()}"

        if report.status == ReportStatus.CRITICAL and self.mention_on_critical:
            text = f"{self.mention_on_critical} {text}"

        message = SlackMessage(
            channel=self.channel,
            text=text,
            attachments=[self._format_report_attachment(report)],
        )

        success = self.send_message(message)

        if success:
            self._record_send(alert_type)
            self._last_status = report.status

        return success

    def _send_recovery(self, report: AnalysisReport) -> bool:
        """Send recovery notification."""
        if not self._can_send('recovery'):
            return False

        message = SlackMessage(
            channel=self.channel,
            text='Sentinel-HFT: Status returned to OK',
            icon_emoji=':white_check_mark:',
            attachments=[{
                'color': 'good',
                'title': 'Status: OK',
                'text': 'All metrics within normal thresholds',
                'ts': int(time.time()),
            }],
        )

        success = self.send_message(message)

        if success:
            self._record_send('recovery')
            self._last_status = ReportStatus.OK

        return success

    def send_test_message(self) -> bool:
        """Send a test message to verify configuration."""
        message = SlackMessage(
            channel=self.channel,
            text='Sentinel-HFT: Test message',
            icon_emoji=':test_tube:',
            attachments=[{
                'color': 'good',
                'title': 'Configuration Test',
                'text': 'If you see this, Slack alerting is configured correctly.',
                'ts': int(time.time()),
            }],
        )
        return self.send_message(message)
