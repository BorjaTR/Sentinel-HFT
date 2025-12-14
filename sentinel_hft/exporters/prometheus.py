"""
Prometheus exporter for Sentinel-HFT metrics.

Exposes metrics in Prometheus format on a configurable port.

Example:
    exporter = PrometheusExporter(port=9090, prefix='sentinel_hft')
    exporter.start()

    # Update metrics from analysis
    exporter.update_from_report(report)
    exporter.update_from_snapshot(snapshot)
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional, Any
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

logger = logging.getLogger(__name__)


@dataclass
class MetricDefinition:
    """Definition of a Prometheus metric."""
    name: str
    help_text: str
    metric_type: str  # 'gauge', 'counter', 'histogram'
    labels: Dict[str, str] = field(default_factory=dict)


class PrometheusExporter:
    """
    Export metrics in Prometheus format.

    Metrics are exposed at http://host:port/metrics

    Standard metrics:
        sentinel_hft_latency_p99_cycles - P99 latency in cycles
        sentinel_hft_latency_mean_cycles - Mean latency in cycles
        sentinel_hft_drop_rate - Rate of dropped traces
        sentinel_hft_tx_count_total - Total TX events processed
        sentinel_hft_overflow_count_total - Total overflow events
        sentinel_hft_kill_switch - Kill switch status (0/1)
    """

    def __init__(
        self,
        host: str = '0.0.0.0',
        port: int = 9090,
        prefix: str = 'sentinel_hft',
    ):
        self.host = host
        self.port = port
        self.prefix = prefix

        # Metric values (thread-safe via lock)
        self._lock = threading.Lock()
        self._metrics: Dict[str, float] = {}
        self._labels: Dict[str, Dict[str, str]] = {}

        # HTTP server
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

        # Define standard metrics
        self._definitions: Dict[str, MetricDefinition] = {
            'latency_p99_cycles': MetricDefinition(
                name=f'{prefix}_latency_p99_cycles',
                help_text='P99 latency in clock cycles',
                metric_type='gauge',
            ),
            'latency_p999_cycles': MetricDefinition(
                name=f'{prefix}_latency_p999_cycles',
                help_text='P99.9 latency in clock cycles',
                metric_type='gauge',
            ),
            'latency_mean_cycles': MetricDefinition(
                name=f'{prefix}_latency_mean_cycles',
                help_text='Mean latency in clock cycles',
                metric_type='gauge',
            ),
            'latency_min_cycles': MetricDefinition(
                name=f'{prefix}_latency_min_cycles',
                help_text='Minimum latency in clock cycles',
                metric_type='gauge',
            ),
            'latency_max_cycles': MetricDefinition(
                name=f'{prefix}_latency_max_cycles',
                help_text='Maximum latency in clock cycles',
                metric_type='gauge',
            ),
            'drop_rate': MetricDefinition(
                name=f'{prefix}_drop_rate',
                help_text='Rate of dropped traces (0-1)',
                metric_type='gauge',
            ),
            'drop_count': MetricDefinition(
                name=f'{prefix}_drop_count_total',
                help_text='Total number of dropped traces',
                metric_type='counter',
            ),
            'tx_count': MetricDefinition(
                name=f'{prefix}_tx_count_total',
                help_text='Total TX events processed',
                metric_type='counter',
            ),
            'overflow_count': MetricDefinition(
                name=f'{prefix}_overflow_count_total',
                help_text='Total overflow events',
                metric_type='counter',
            ),
            'overflow_traces_lost': MetricDefinition(
                name=f'{prefix}_overflow_traces_lost_total',
                help_text='Total traces lost to overflow',
                metric_type='counter',
            ),
            'rate_limit_rejects': MetricDefinition(
                name=f'{prefix}_rate_limit_rejects_total',
                help_text='Total rate limit rejections',
                metric_type='counter',
            ),
            'kill_switch': MetricDefinition(
                name=f'{prefix}_kill_switch',
                help_text='Kill switch status (0=off, 1=triggered)',
                metric_type='gauge',
            ),
            'anomaly_count': MetricDefinition(
                name=f'{prefix}_anomaly_count_total',
                help_text='Total anomalies detected',
                metric_type='counter',
            ),
            'status': MetricDefinition(
                name=f'{prefix}_status',
                help_text='Overall status (0=ok, 1=warning, 2=error, 3=critical)',
                metric_type='gauge',
            ),
        }

    def set_metric(self, key: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Set a metric value."""
        with self._lock:
            self._metrics[key] = value
            if labels:
                self._labels[key] = labels

    def get_metric(self, key: str) -> Optional[float]:
        """Get a metric value."""
        with self._lock:
            return self._metrics.get(key)

    def update_from_snapshot(self, snapshot: dict) -> None:
        """Update metrics from analyzer snapshot."""
        lat = snapshot.get('latency', {})
        self.set_metric('latency_p99_cycles', lat.get('p99_cycles', 0))
        self.set_metric('latency_p999_cycles', lat.get('p999_cycles', 0))
        self.set_metric('latency_mean_cycles', lat.get('mean_cycles', 0))
        self.set_metric('latency_min_cycles', lat.get('min_cycles', 0))
        self.set_metric('latency_max_cycles', lat.get('max_cycles', 0))

        drops = snapshot.get('drops', {})
        self.set_metric('drop_rate', drops.get('drop_rate', 0))
        self.set_metric('drop_count', drops.get('total_dropped', 0))

        self.set_metric('tx_count', lat.get('count', 0))

        overflow = snapshot.get('overflow', {})
        self.set_metric('overflow_count', overflow.get('overflow_records', 0))
        self.set_metric('overflow_traces_lost', overflow.get('traces_lost', 0))

        risk = snapshot.get('risk', {})
        self.set_metric('rate_limit_rejects', risk.get('rate_limit_rejects', 0))
        self.set_metric('kill_switch', 1 if risk.get('kill_switch_triggered') else 0)

        anomalies = snapshot.get('anomalies', {})
        self.set_metric('anomaly_count', anomalies.get('count', 0))

    def update_from_report(self, report: 'AnalysisReport') -> None:
        """Update metrics from analysis report."""
        self.set_metric('latency_p99_cycles', report.latency.p99_cycles)
        self.set_metric('latency_p999_cycles', report.latency.p999_cycles)
        self.set_metric('latency_mean_cycles', report.latency.mean_cycles)
        self.set_metric('latency_min_cycles', report.latency.min_cycles)
        self.set_metric('latency_max_cycles', report.latency.max_cycles)

        self.set_metric('drop_rate', report.drops.drop_rate)
        self.set_metric('drop_count', report.drops.total_drops)

        self.set_metric('tx_count', report.latency.count)

        self.set_metric('overflow_count', report.record_types.overflows)
        self.set_metric('overflow_traces_lost', report.record_types.overflow_traces_lost)

        self.set_metric('rate_limit_rejects', report.risk.rate_limit_rejects)
        self.set_metric('kill_switch', 1 if report.risk.kill_switch_triggered else 0)

        self.set_metric('anomaly_count', report.anomalies.total_anomalies)

        # Status: ok=0, warning=1, error=2, critical=3
        status_map = {'ok': 0, 'warning': 1, 'error': 2, 'critical': 3}
        self.set_metric('status', status_map.get(report.status.value, 0))

    def format_metrics(self) -> str:
        """Format metrics in Prometheus text format."""
        lines = []

        with self._lock:
            for key, definition in self._definitions.items():
                value = self._metrics.get(key)
                if value is None:
                    continue

                # Add HELP line
                lines.append(f"# HELP {definition.name} {definition.help_text}")
                # Add TYPE line
                lines.append(f"# TYPE {definition.name} {definition.metric_type}")

                # Add metric line with optional labels
                labels = self._labels.get(key, {})
                if labels:
                    label_str = ','.join(f'{k}="{v}"' for k, v in labels.items())
                    lines.append(f"{definition.name}{{{label_str}}} {value}")
                else:
                    lines.append(f"{definition.name} {value}")

                lines.append("")

        return '\n'.join(lines)

    def start(self) -> None:
        """Start the HTTP server."""
        exporter = self

        class MetricsHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/metrics':
                    content = exporter.format_metrics()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/plain; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(content.encode('utf-8'))
                elif self.path == '/health':
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'{"status": "healthy"}')
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                # Suppress access logs
                pass

        self._server = HTTPServer((self.host, self.port), MetricsHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(f"Prometheus exporter listening on {self.host}:{self.port}")

    def stop(self) -> None:
        """Stop the HTTP server."""
        if self._server:
            self._server.shutdown()
            self._server = None
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("Prometheus exporter stopped")
