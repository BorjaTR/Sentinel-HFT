"""Tests for H4 AI Explainer components.

Tests pattern detection, fact extraction, and report generation.
"""

import pytest
from dataclasses import dataclass
from typing import List, Optional
import json

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ai.pattern_detector import (
    PatternType,
    Pattern,
    PatternDetectionResult,
    PatternDetector,
)

from ai.fact_extractor import (
    Fact,
    FactSet,
    FactExtractor,
)

from ai.explainer import (
    ExplanationConfig,
    Explanation,
)

from ai.report_generator import (
    AIReport,
    AIReportGenerator,
)


# ============================================================================
# Mock Data Classes
# ============================================================================

@dataclass
class MockTrace:
    """Mock trace for testing."""
    tx_id: int
    t_ingress: int
    t_egress: int
    latency_cycles: int
    flags: int = 0


@dataclass
class MockLatencyMetrics:
    """Mock latency metrics."""
    count: int
    p50_cycles: int
    p99_cycles: int
    p999_cycles: int = 0
    mean_cycles: float = 0.0
    std_cycles: float = 0.0


@dataclass
class MockThroughputMetrics:
    """Mock throughput metrics."""
    transactions_per_second: float
    max_burst_size: int = 0


@dataclass
class MockAnomaly:
    """Mock anomaly."""
    tx_id: int
    latency_cycles: int
    zscore: float


@dataclass
class MockAnomalyReport:
    """Mock anomaly report."""
    count: int
    threshold_zscore: float
    anomalies: List[MockAnomaly]


@dataclass
class MockMetrics:
    """Mock full metrics."""
    latency: MockLatencyMetrics
    throughput: MockThroughputMetrics
    anomalies: MockAnomalyReport

    def to_dict(self) -> dict:
        return {
            'latency': {
                'count': self.latency.count,
                'p50_cycles': self.latency.p50_cycles,
                'p99_cycles': self.latency.p99_cycles,
                'p999_cycles': self.latency.p999_cycles,
            },
            'throughput': {
                'transactions_per_second': self.throughput.transactions_per_second,
            },
            'anomalies': {
                'count': self.anomalies.count,
            },
        }


def create_mock_traces(count: int, base_latency: int = 5, variance: int = 1) -> List[MockTrace]:
    """Create mock traces with specified latency characteristics."""
    import random
    traces = []
    t = 0
    for i in range(count):
        latency = base_latency + random.randint(-variance, variance)
        traces.append(MockTrace(
            tx_id=i,
            t_ingress=t,
            t_egress=t + latency,
            latency_cycles=latency,
        ))
        t += latency + 5
    return traces


def create_traces_with_spike(count: int, spike_at: int, spike_latency: int) -> List[MockTrace]:
    """Create traces with a latency spike at specified index."""
    traces = create_mock_traces(count, base_latency=5, variance=1)
    if spike_at < len(traces):
        traces[spike_at].latency_cycles = spike_latency
        traces[spike_at].t_egress = traces[spike_at].t_ingress + spike_latency
    return traces


# ============================================================================
# Pattern Detector Tests
# ============================================================================

class TestPatternDetector:
    """Tests for pattern detection."""

    def test_detector_initialization(self):
        """Test detector can be initialized with defaults."""
        detector = PatternDetector()
        assert detector.latency_zscore_threshold == 3.0
        assert detector.burst_window_cycles == 100
        assert detector.min_pattern_confidence == 0.7

    def test_detector_custom_config(self):
        """Test detector with custom configuration."""
        detector = PatternDetector(
            latency_zscore_threshold=2.0,
            burst_window_cycles=50,
            min_pattern_confidence=0.5,
        )
        assert detector.latency_zscore_threshold == 2.0
        assert detector.burst_window_cycles == 50

    def test_detect_empty_traces(self):
        """Test detection with empty trace list."""
        detector = PatternDetector()
        result = detector.detect_all([])
        assert isinstance(result, PatternDetectionResult)
        assert len(result.patterns) == 0
        assert result.total_transactions == 0

    def test_detect_normal_traces(self):
        """Test detection with normal traces (no anomalies)."""
        detector = PatternDetector()
        traces = create_mock_traces(100, base_latency=5, variance=1)
        result = detector.detect_all(traces)
        # With uniform latency, no spikes should be detected
        spike_patterns = [p for p in result.patterns if p.pattern_type == PatternType.LATENCY_SPIKE]
        assert len(spike_patterns) == 0

    def test_detect_latency_spike(self):
        """Test detection of latency spikes."""
        detector = PatternDetector(latency_zscore_threshold=3.0)
        # Create traces with a significant spike
        traces = create_mock_traces(100, base_latency=5, variance=0)
        # Add a spike at index 50
        traces[50].latency_cycles = 50  # 10x normal
        traces[50].t_egress = traces[50].t_ingress + 50

        result = detector.detect_all(traces)
        spike_patterns = [p for p in result.patterns if p.pattern_type == PatternType.LATENCY_SPIKE]
        assert len(spike_patterns) >= 1
        # The spike should include tx_id 50
        spike = spike_patterns[0]
        assert 50 in spike.affected_tx_ids

    def test_detect_rate_limit_burst(self):
        """Test detection of rate limit bursts."""
        detector = PatternDetector(burst_window_cycles=100)
        traces = create_mock_traces(50)

        risk_events = {
            'rate_limit_rejects': [
                {'cycle': 100, 'tx_id': 10, 'tokens_remaining': 0},
                {'cycle': 105, 'tx_id': 11, 'tokens_remaining': 0},
                {'cycle': 110, 'tx_id': 12, 'tokens_remaining': 0},
                {'cycle': 115, 'tx_id': 13, 'tokens_remaining': 0},
            ]
        }

        result = detector.detect_all(traces, risk_events)
        burst_patterns = [p for p in result.patterns if p.pattern_type == PatternType.RATE_LIMIT_BURST]
        assert len(burst_patterns) == 1
        assert burst_patterns[0].details['burst_size'] == 4

    def test_detect_kill_switch(self):
        """Test detection of kill switch events."""
        detector = PatternDetector()
        traces = create_mock_traces(50)

        risk_events = {
            'kill_switch_triggers': [
                {'cycle': 500, 'reason': 'pnl_threshold', 'orders_blocked': 10, 'pnl': -15000}
            ]
        }

        result = detector.detect_all(traces, risk_events)
        kill_patterns = [p for p in result.patterns if p.pattern_type == PatternType.KILL_SWITCH_TRIGGER]
        assert len(kill_patterns) == 1
        assert kill_patterns[0].severity == 'critical'
        assert kill_patterns[0].confidence == 1.0

    def test_pattern_to_dict(self):
        """Test pattern serialization."""
        pattern = Pattern(
            pattern_type=PatternType.LATENCY_SPIKE,
            confidence=0.95,
            start_cycle=100,
            end_cycle=150,
            affected_tx_ids=[1, 2, 3],
            severity='high',
            details={'zscore': 4.5}
        )
        d = pattern.to_dict()
        assert d['type'] == 'LATENCY_SPIKE'
        assert d['confidence'] == 0.95
        assert d['affected_transactions'] == 3

    def test_result_to_dict(self):
        """Test result serialization."""
        result = PatternDetectionResult(
            patterns=[],
            analysis_window_cycles=1000,
            total_transactions=100,
        )
        d = result.to_dict()
        assert d['patterns_detected'] == 0
        assert d['analysis_window_cycles'] == 1000
        assert d['total_transactions'] == 100


# ============================================================================
# Fact Extractor Tests
# ============================================================================

class TestFactExtractor:
    """Tests for fact extraction."""

    def test_extractor_initialization(self):
        """Test extractor can be initialized."""
        extractor = FactExtractor(clock_period_ns=10.0)
        assert extractor.clock_period_ns == 10.0

    def test_extract_latency_facts(self):
        """Test extraction of latency facts."""
        extractor = FactExtractor()
        metrics = MockMetrics(
            latency=MockLatencyMetrics(count=1000, p50_cycles=5, p99_cycles=10),
            throughput=MockThroughputMetrics(transactions_per_second=10000),
            anomalies=MockAnomalyReport(count=0, threshold_zscore=3.0, anomalies=[]),
        )
        patterns = PatternDetectionResult(patterns=[], analysis_window_cycles=1000, total_transactions=100)

        facts = extractor.extract(metrics, patterns)

        # Check latency facts were extracted
        latency_facts = [f for f in facts.facts if f.category == 'latency']
        assert len(latency_facts) >= 3  # count, p50, p99

        # Check p50 fact
        p50_fact = next((f for f in latency_facts if f.key == 'p50'), None)
        assert p50_fact is not None
        assert p50_fact.value == 5

    def test_extract_anomaly_facts(self):
        """Test extraction of anomaly facts."""
        extractor = FactExtractor()
        metrics = MockMetrics(
            latency=MockLatencyMetrics(count=1000, p50_cycles=5, p99_cycles=10),
            throughput=MockThroughputMetrics(transactions_per_second=10000),
            anomalies=MockAnomalyReport(
                count=5,
                threshold_zscore=3.0,
                anomalies=[
                    MockAnomaly(tx_id=100, latency_cycles=50, zscore=5.0),
                    MockAnomaly(tx_id=200, latency_cycles=40, zscore=4.0),
                ]
            ),
        )
        patterns = PatternDetectionResult(patterns=[], analysis_window_cycles=1000, total_transactions=100)

        facts = extractor.extract(metrics, patterns)

        anomaly_facts = [f for f in facts.facts if f.category == 'anomaly']
        assert len(anomaly_facts) >= 1

        count_fact = next((f for f in anomaly_facts if f.key == 'count'), None)
        assert count_fact is not None
        assert count_fact.value == 5

    def test_extract_risk_facts(self):
        """Test extraction of risk facts."""
        extractor = FactExtractor()
        metrics = MockMetrics(
            latency=MockLatencyMetrics(count=1000, p50_cycles=5, p99_cycles=10),
            throughput=MockThroughputMetrics(transactions_per_second=10000),
            anomalies=MockAnomalyReport(count=0, threshold_zscore=3.0, anomalies=[]),
        )
        patterns = PatternDetectionResult(patterns=[], analysis_window_cycles=1000, total_transactions=100)

        risk_stats = {
            'rate_limit_rejects': 50,
            'total_orders': 1000,
            'position_limit_rejects': 5,
            'kill_switch_triggered': True,
        }

        facts = extractor.extract(metrics, patterns, risk_stats)

        risk_facts = [f for f in facts.facts if f.category == 'risk']
        assert len(risk_facts) >= 2

        # Kill switch should be critical
        kill_fact = next((f for f in risk_facts if f.key == 'kill_switch'), None)
        assert kill_fact is not None
        assert kill_fact.importance == 'critical'

    def test_fact_set_to_llm_context(self):
        """Test formatting facts for LLM."""
        facts = FactSet()
        facts.add(Fact(
            category='latency',
            key='p50',
            value=5,
            context='Median latency: 5 cycles',
            importance='medium',
        ))
        facts.add(Fact(
            category='risk',
            key='kill_switch',
            value=True,
            context='KILL SWITCH TRIGGERED',
            importance='critical',
        ))

        context = facts.to_llm_context()
        assert 'LATENCY' in context
        assert 'RISK' in context
        assert 'Median latency' in context
        assert 'KILL SWITCH' in context

    def test_fact_set_to_dict(self):
        """Test fact set serialization."""
        facts = FactSet()
        facts.add(Fact(
            category='latency',
            key='count',
            value=100,
            context='100 transactions',
            importance='low',
        ))

        d = facts.to_dict()
        assert d['total_facts'] == 1
        assert d['critical_count'] == 0


# ============================================================================
# Explainer Tests
# ============================================================================

class TestExplainer:
    """Tests for the explainer (without actual LLM calls)."""

    def test_explanation_config_defaults(self):
        """Test explanation config has sensible defaults."""
        config = ExplanationConfig()
        assert config.model == "claude-sonnet-4-20250514"
        assert config.max_tokens == 1024
        assert config.temperature == 0.3
        assert config.clock_period_ns == 10.0

    def test_explanation_to_dict(self):
        """Test explanation serialization."""
        explanation = Explanation(
            summary="System healthy",
            key_findings=["Low latency", "No anomalies"],
            root_cause=None,
            recommendations=["Increase tokens"],
            raw_response="Full response",
        )
        d = explanation.to_dict()
        assert d['summary'] == "System healthy"
        assert len(d['key_findings']) == 2
        assert d['root_cause'] is None
        assert len(d['recommendations']) == 1

    def test_explanation_to_markdown(self):
        """Test explanation markdown generation."""
        explanation = Explanation(
            summary="System is operating normally.",
            key_findings=["P99 latency is 10 cycles", "No rate limit violations"],
            root_cause="Traffic spike at cycle 1000",
            recommendations=["Increase buffer size"],
            raw_response="Full response",
        )
        md = explanation.to_markdown()
        assert "## Analysis Summary" in md
        assert "## Key Findings" in md
        assert "## Root Cause Analysis" in md
        assert "## Recommendations" in md
        assert "P99 latency" in md


# ============================================================================
# Report Generator Tests
# ============================================================================

class TestReportGenerator:
    """Tests for report generation."""

    def test_generator_initialization(self):
        """Test generator can be initialized without API key."""
        generator = AIReportGenerator()
        assert generator.explainer is None

    def test_generator_with_config(self):
        """Test generator with custom config."""
        config = ExplanationConfig(clock_period_ns=5.0)
        generator = AIReportGenerator(config=config)
        assert generator.config.clock_period_ns == 5.0

    def test_generate_without_ai(self):
        """Test report generation without AI."""
        generator = AIReportGenerator()
        traces = create_mock_traces(100)
        metrics = MockMetrics(
            latency=MockLatencyMetrics(count=100, p50_cycles=5, p99_cycles=10),
            throughput=MockThroughputMetrics(transactions_per_second=10000),
            anomalies=MockAnomalyReport(count=0, threshold_zscore=3.0, anomalies=[]),
        )

        report = generator.generate_without_ai(traces, metrics, trace_file="test.bin")

        assert isinstance(report, AIReport)
        assert report.trace_file == "test.bin"
        assert report.explanation is None
        assert report.executive_summary is None
        assert 'patterns_detected' in report.patterns

    def test_report_to_dict(self):
        """Test report serialization."""
        report = AIReport(
            generated_at="2024-01-01T00:00:00",
            trace_file="test.bin",
            metrics={'latency': {'count': 100}},
            patterns={'patterns_detected': 0, 'patterns': []},
            facts={'total_facts': 5},
            explanation=None,
            executive_summary=None,
        )
        d = report.to_dict()
        assert d['metadata']['trace_file'] == "test.bin"
        assert d['metadata']['ai_enhanced'] is False
        assert d['metrics']['latency']['count'] == 100

    def test_report_to_markdown(self):
        """Test report markdown generation."""
        report = AIReport(
            generated_at="2024-01-01T00:00:00",
            trace_file="test.bin",
            metrics={'latency': {'count': 100, 'p50_cycles': 5, 'p99_cycles': 10, 'p999_cycles': 15}},
            patterns={'patterns_detected': 1, 'patterns': [{'type': 'LATENCY_SPIKE', 'severity': 'high', 'affected_transactions': 5}]},
            facts={'total_facts': 5},
            explanation={'summary': 'Test summary', 'key_findings': ['Finding 1'], 'recommendations': ['Rec 1']},
            executive_summary="System healthy.",
        )
        md = report.to_markdown()
        assert "# Sentinel-HFT Analysis Report" in md
        assert "test.bin" in md
        assert "## Executive Summary" in md
        assert "System healthy" in md
        assert "## AI Analysis" in md
        assert "## Metrics" in md
        assert "### Latency" in md

    def test_report_to_json(self):
        """Test report JSON generation."""
        report = AIReport(
            generated_at="2024-01-01T00:00:00",
            trace_file="test.bin",
            metrics={'latency': {'count': 100}},
            patterns={'patterns_detected': 0},
            facts={'total_facts': 5},
            explanation=None,
            executive_summary=None,
        )
        json_str = report.to_json()
        parsed = json.loads(json_str)
        assert parsed['metadata']['trace_file'] == "test.bin"


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Integration tests for the full AI pipeline."""

    def test_full_pipeline_without_ai(self):
        """Test the full pipeline from traces to report."""
        # Create mock data
        traces = create_mock_traces(100)
        metrics = MockMetrics(
            latency=MockLatencyMetrics(count=100, p50_cycles=5, p99_cycles=10),
            throughput=MockThroughputMetrics(transactions_per_second=10000),
            anomalies=MockAnomalyReport(count=0, threshold_zscore=3.0, anomalies=[]),
        )

        # Run pipeline
        detector = PatternDetector()
        patterns = detector.detect_all(traces)

        extractor = FactExtractor()
        facts = extractor.extract(metrics, patterns)

        generator = AIReportGenerator()
        report = generator.generate_without_ai(traces, metrics)

        # Verify outputs
        assert isinstance(patterns, PatternDetectionResult)
        assert isinstance(facts, FactSet)
        assert isinstance(report, AIReport)

    def test_pipeline_with_anomalies(self):
        """Test pipeline with anomalous data."""
        # Create traces with a spike
        traces = create_mock_traces(100, base_latency=5, variance=0)
        traces[50].latency_cycles = 100  # Large spike
        traces[50].t_egress = traces[50].t_ingress + 100

        metrics = MockMetrics(
            latency=MockLatencyMetrics(count=100, p50_cycles=5, p99_cycles=100),
            throughput=MockThroughputMetrics(transactions_per_second=10000),
            anomalies=MockAnomalyReport(
                count=1,
                threshold_zscore=3.0,
                anomalies=[MockAnomaly(tx_id=50, latency_cycles=100, zscore=10.0)],
            ),
        )

        # Run pipeline
        detector = PatternDetector()
        patterns = detector.detect_all(traces)

        # Should detect the spike
        spike_patterns = [p for p in patterns.patterns if p.pattern_type == PatternType.LATENCY_SPIKE]
        assert len(spike_patterns) >= 1

        extractor = FactExtractor()
        facts = extractor.extract(metrics, patterns)

        # Should have anomaly facts
        anomaly_facts = [f for f in facts.facts if f.category == 'anomaly']
        assert len(anomaly_facts) >= 1

    def test_pipeline_with_risk_events(self):
        """Test pipeline with risk events."""
        traces = create_mock_traces(100)
        metrics = MockMetrics(
            latency=MockLatencyMetrics(count=100, p50_cycles=5, p99_cycles=10),
            throughput=MockThroughputMetrics(transactions_per_second=10000),
            anomalies=MockAnomalyReport(count=0, threshold_zscore=3.0, anomalies=[]),
        )

        risk_events = {
            'rate_limit_rejects': [
                {'cycle': 100, 'tx_id': 10},
                {'cycle': 102, 'tx_id': 11},
                {'cycle': 104, 'tx_id': 12},
            ],
            'kill_switch_triggers': [
                {'cycle': 500, 'reason': 'manual', 'orders_blocked': 5},
            ],
        }

        risk_stats = {
            'rate_limit_rejects': 3,
            'total_orders': 100,
            'kill_switch_triggered': True,
        }

        detector = PatternDetector()
        patterns = detector.detect_all(traces, risk_events)

        # Should detect kill switch
        kill_patterns = [p for p in patterns.patterns if p.pattern_type == PatternType.KILL_SWITCH_TRIGGER]
        assert len(kill_patterns) == 1

        extractor = FactExtractor()
        facts = extractor.extract(metrics, patterns, risk_stats)

        # Should have risk facts
        risk_facts = [f for f in facts.facts if f.category == 'risk']
        assert len(risk_facts) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
