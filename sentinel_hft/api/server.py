"""
REST API server for Sentinel-HFT.

Endpoints:
    POST /analyze - Analyze uploaded trace file
    POST /analyze/stream - Streaming analysis
    GET /health - Health check
    GET /metrics - Prometheus metrics

Example:
    curl -X POST -F "file=@traces.bin" http://localhost:8080/analyze
"""

import io
import json
import logging
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field

from ..config import SentinelConfig, load_config
from ..formats.reader import TraceReader
from ..streaming.analyzer import StreamingMetrics, StreamingConfig
from ..core.report import AnalysisReport, ReportStatus
from ..core.evidence import EvidenceBundle, TraceEvidence
from ..core.errors import ErrorCode, SentinelError

logger = logging.getLogger(__name__)


@dataclass
class AnalysisRequest:
    """Request for analysis."""
    filename: Optional[str] = None
    include_evidence: bool = False
    clock_frequency_mhz: Optional[float] = None


@dataclass
class AnalysisAPI:
    """
    Core API logic, separate from HTTP framework.

    This allows testing without Flask and reuse in other contexts.
    """
    config: SentinelConfig = field(default_factory=SentinelConfig)

    def analyze_file(
        self,
        file_path: Path,
        request: Optional[AnalysisRequest] = None,
    ) -> AnalysisReport:
        """Analyze a trace file."""
        request = request or AnalysisRequest()

        report = AnalysisReport(
            source_file=str(file_path),
            clock_frequency_mhz=request.clock_frequency_mhz or self.config.clock.frequency_mhz,
        )

        if request.include_evidence:
            report.evidence = EvidenceBundle(source_file=str(file_path))
            report.include_evidence = True

        try:
            trace_file = TraceReader.open(file_path)
            report.source_format = 'sentinel' if trace_file.has_header else 'legacy'
            report.source_format_version = trace_file.header.version if trace_file.header else None

            if report.evidence:
                report.evidence.source_format = report.source_format
                report.evidence.source_version = report.source_format_version

            # Create streaming metrics
            streaming_config = StreamingConfig(
                anomaly_zscore=self.config.analysis.anomaly_zscore,
            )
            metrics = StreamingMetrics(streaming_config)

            # Process all traces
            trace_count = 0
            for trace in TraceReader.read(trace_file):
                metrics.add(trace)
                trace_count += 1

                # Sample evidence
                if report.evidence and trace_count <= 10:
                    report.evidence.add_trace_sample(
                        TraceEvidence(
                            timestamp=trace.t_egress,
                            seq_no=trace.seq_no,
                            core_id=trace.core_id,
                            latency_cycles=trace.t_egress - trace.t_ingress,
                            record_type=trace.record_type,
                            flags=trace.flags,
                            data=trace.data,
                        ),
                        'head',
                    )

            # Get snapshot from metrics
            snapshot = metrics.snapshot()

            # Populate report from snapshot
            self._populate_report_from_snapshot(report, snapshot)

            # Compute status
            report.compute_status(
                p99_warning=self.config.thresholds.p99_warning,
                p99_error=self.config.thresholds.p99_error,
                p99_critical=self.config.thresholds.p99_critical,
                drop_rate_warning=self.config.thresholds.drop_rate_warning,
                drop_rate_error=self.config.thresholds.drop_rate_error,
                anomaly_rate_warning=self.config.thresholds.anomaly_rate_warning,
                anomaly_rate_error=self.config.thresholds.anomaly_rate_error,
            )

            # Populate nanosecond values
            report.populate_ns_values()

        except FileNotFoundError:
            report.add_error(SentinelError(
                code=ErrorCode.E1005_EMPTY_FILE,
                context={'file': str(file_path)},
            ))
            report.status = ReportStatus.ERROR
        except Exception as e:
            logger.exception(f"Analysis failed: {e}")
            report.add_error(SentinelError(
                code=ErrorCode.E1006_HEADER_DECODE_FAILED,
                context={'error': str(e)},
            ))
            report.status = ReportStatus.ERROR

        return report

    def analyze_bytes(
        self,
        data: bytes,
        request: Optional[AnalysisRequest] = None,
    ) -> AnalysisReport:
        """Analyze trace data from bytes."""
        # Write to temp file and analyze
        with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
            f.write(data)
            temp_path = Path(f.name)

        try:
            report = self.analyze_file(temp_path, request)
            if request and request.filename:
                report.source_file = request.filename
        finally:
            temp_path.unlink()

        return report

    def _populate_report_from_snapshot(
        self,
        report: AnalysisReport,
        snapshot: dict,
    ) -> None:
        """Populate report from analyzer snapshot."""
        lat = snapshot.get('latency', {})
        report.latency.count = lat.get('count', 0)
        report.latency.mean_cycles = lat.get('mean_cycles', 0.0)
        report.latency.stddev_cycles = lat.get('stddev_cycles', 0.0)
        report.latency.min_cycles = lat.get('min_cycles', 0)
        report.latency.max_cycles = lat.get('max_cycles', 0)

        # Percentiles are directly in latency dict
        report.latency.p50_cycles = lat.get('p50_cycles', 0.0)
        report.latency.p75_cycles = lat.get('p75_cycles', 0.0)
        report.latency.p90_cycles = lat.get('p90_cycles', 0.0)
        report.latency.p95_cycles = lat.get('p95_cycles', 0.0)
        report.latency.p99_cycles = lat.get('p99_cycles', 0.0)
        report.latency.p999_cycles = lat.get('p999_cycles', 0.0)

        drops = snapshot.get('drops', {})
        report.drops.total_drops = drops.get('total_dropped', 0)
        report.drops.drop_events = drops.get('drop_events', 0)
        report.drops.drop_rate = drops.get('drop_rate', 0.0)
        report.drops.reorders = drops.get('reorder_count', 0)
        report.drops.resets = drops.get('reset_count', 0)

        throughput = snapshot.get('throughput', {})
        report.throughput.total_traces = throughput.get('total_count', 0)
        report.throughput.tx_events = lat.get('count', 0)

        risk = snapshot.get('risk', {})
        report.risk.rate_limit_rejects = risk.get('rate_limit_rejects', 0)
        report.risk.position_limit_rejects = risk.get('position_limit_rejects', 0)
        report.risk.kill_switch_triggered = risk.get('kill_switch_triggered', False)

        record_types = snapshot.get('record_types', {})
        report.record_types.tx_events = record_types.get('tx_events', 0)
        report.record_types.overflows = record_types.get('overflow', 0)
        report.record_types.heartbeats = record_types.get('heartbeat', 0)
        report.record_types.clock_syncs = record_types.get('clock_sync', 0)
        report.record_types.resets = record_types.get('reset', 0)
        # overflow_traces_lost is in the overflow section
        overflow = snapshot.get('overflow', {})
        report.record_types.overflow_traces_lost = overflow.get('traces_lost', 0)

        anomalies = snapshot.get('anomalies', {})
        report.anomalies.total_anomalies = anomalies.get('count', 0)
        report.anomalies.anomaly_rate = anomalies.get('rate', 0.0)

    def health_check(self) -> dict:
        """Health check endpoint data."""
        return {
            'status': 'healthy',
            'version': '2.2.0',
            'config_valid': len(self.config.validate()) == 0,
        }


def create_app(config: Optional[SentinelConfig] = None) -> 'FlaskApp':
    """
    Create Flask application.

    Example:
        app = create_app()
        app.run(host='0.0.0.0', port=8080)

    Returns stub if Flask not available (for testing without Flask).
    """
    try:
        from flask import Flask, request, jsonify
    except ImportError:
        # Return stub for environments without Flask
        return _create_stub_app(config)

    config = config or load_config()
    api = AnalysisAPI(config=config)

    app = Flask(__name__)

    @app.route('/health', methods=['GET'])
    def health():
        return jsonify(api.health_check())

    @app.route('/analyze', methods=['POST'])
    def analyze():
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'Empty filename'}), 400

        data = file.read()

        req = AnalysisRequest(
            filename=file.filename,
            include_evidence=request.form.get('include_evidence', 'false').lower() == 'true',
        )

        if 'clock_frequency_mhz' in request.form:
            try:
                req.clock_frequency_mhz = float(request.form['clock_frequency_mhz'])
            except ValueError:
                pass

        report = api.analyze_bytes(data, req)

        status_code = 200
        if report.status == ReportStatus.ERROR:
            status_code = 500
        elif report.status == ReportStatus.CRITICAL:
            status_code = 500

        return jsonify(report.to_dict()), status_code

    @app.route('/analyze/stream', methods=['POST'])
    def analyze_stream():
        """Streaming analysis - processes chunks as they arrive."""
        # For now, collect all chunks and analyze
        # True streaming would use chunked encoding
        data = request.get_data()

        req = AnalysisRequest(
            filename=request.headers.get('X-Filename'),
            include_evidence=request.headers.get('X-Include-Evidence', 'false').lower() == 'true',
        )

        report = api.analyze_bytes(data, req)
        return jsonify(report.to_dict())

    @app.route('/config', methods=['GET'])
    def get_config():
        """Get current configuration (redacted)."""
        return jsonify(config.redacted().to_dict())

    @app.errorhandler(Exception)
    def handle_error(e):
        logger.exception(f"Unhandled error: {e}")
        return jsonify({
            'error': str(e),
            'status': 'error',
        }), 500

    return app


class _StubApp:
    """Stub application for testing without Flask."""

    def __init__(self, api: AnalysisAPI):
        self.api = api

    def run(self, host: str = '0.0.0.0', port: int = 8080, **kwargs):
        logger.warning("Flask not installed, cannot run HTTP server")
        logger.info(f"Would listen on {host}:{port}")


def _create_stub_app(config: Optional[SentinelConfig] = None) -> _StubApp:
    """Create stub app when Flask is not available."""
    config = config or load_config()
    api = AnalysisAPI(config=config)
    return _StubApp(api)
