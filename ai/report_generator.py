"""Generate final reports with AI explanations."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any, List
import json
from datetime import datetime

from .pattern_detector import PatternDetector, PatternDetectionResult
from .fact_extractor import FactExtractor, FactSet
from .explainer import Explainer, ExplanationConfig


@dataclass
class AIReport:
    """Complete AI-enhanced analysis report."""
    generated_at: str
    trace_file: str
    metrics: dict
    patterns: dict
    facts: dict
    explanation: Optional[dict]
    executive_summary: Optional[str]
    protocol: Optional[dict] = None
    correlations: Optional[dict] = None
    risk_assessment: Optional[dict] = None

    def to_dict(self) -> dict:
        result = {
            'metadata': {
                'generated_at': self.generated_at,
                'trace_file': self.trace_file,
                'ai_enhanced': self.explanation is not None,
                'protocol_context': self.protocol is not None,
            },
            'metrics': self.metrics,
            'patterns': self.patterns,
            'facts': self.facts,
            'ai_analysis': {
                'explanation': self.explanation,
                'executive_summary': self.executive_summary,
            },
        }
        if self.protocol:
            result['protocol'] = self.protocol
        if self.correlations:
            result['correlations'] = self.correlations
        if self.risk_assessment:
            result['risk_assessment'] = self.risk_assessment
        return result

    def to_markdown(self) -> str:
        """Generate full markdown report."""
        lines = [
            "# Sentinel-HFT Analysis Report",
            "",
            f"Generated: {self.generated_at}",
            f"Trace file: {self.trace_file}",
            "",
        ]

        if self.executive_summary:
            lines.extend(["## Executive Summary", "", self.executive_summary, ""])

        # Protocol context section (H5)
        if self.protocol:
            health = self.protocol.get('health', {})
            lines.extend([
                "---",
                "",
                "## Protocol Context",
                "",
                f"**{health.get('protocol_name', 'Unknown')}**: "
                f"{health.get('health', {}).get('tier', 'N/A')}-tier health, "
                f"${health.get('financial', {}).get('treasury_usd', 0)/1e6:.1f}M treasury, "
                f"{health.get('financial', {}).get('runway_months', 0):.0f} months runway",
                "",
                "| Metric | Value |",
                "|--------|-------|",
                f"| Health Score | {health.get('health', {}).get('overall_score', 'N/A')}/100 |",
                f"| Active Proposals | {health.get('governance', {}).get('active_proposals', 0)} |",
                f"| Governance Participation | {health.get('governance', {}).get('participation_rate', 0)*100:.1f}% |",
                f"| Risk Level | {health.get('risk', {}).get('level', 'unknown')} |",
                "",
            ])

            # Risk flags
            risk_flags = health.get('risk', {}).get('flags', [])
            if risk_flags:
                lines.append("**Risk Flags**: " + ", ".join(risk_flags))
                lines.append("")

        # Correlations section
        if self.correlations and self.correlations.get('correlated_events'):
            lines.extend(["### Correlations", ""])
            for corr in self.correlations['correlated_events']:
                lines.append(f"- {corr.get('correlation', {}).get('explanation', 'Unknown correlation')}")
            lines.append("")

        # Risk assessment section
        if self.risk_assessment:
            combined = self.risk_assessment.get('combined', {})
            lines.extend([
                "### Combined Risk Assessment",
                "",
                "| Component | Status |",
                "|-----------|--------|",
                f"| HFT System | {self.risk_assessment.get('hft', {}).get('health', 'N/A')} |",
                f"| Protocol | {self.risk_assessment.get('protocol', {}).get('health', 'N/A')} |",
                f"| Combined Risk | {combined.get('risk_level', 'N/A')} |",
                "",
                f"**Recommendation**: {combined.get('recommendation', 'N/A')}",
                "",
            ])

        if self.explanation:
            lines.extend(["---", "", "## AI Analysis", "", self.explanation.get('summary', ''), ""])

            if self.explanation.get('key_findings'):
                lines.append("### Key Findings\n")
                for finding in self.explanation['key_findings']:
                    lines.append(f"- {finding}")
                lines.append("")

            if self.explanation.get('root_cause'):
                lines.extend(["### Root Cause", "", self.explanation['root_cause'], ""])

            if self.explanation.get('recommendations'):
                lines.append("### Recommendations\n")
                for rec in self.explanation['recommendations']:
                    lines.append(f"- {rec}")
                lines.append("")

        # Metrics section
        lines.extend(["---", "", "## Metrics", ""])
        latency = self.metrics.get('latency', {})
        lines.extend([
            "### Latency",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Count | {latency.get('count', 'N/A'):,} |" if isinstance(latency.get('count'), int) else f"| Count | {latency.get('count', 'N/A')} |",
            f"| P50 | {latency.get('p50_cycles', 'N/A')} cycles |",
            f"| P99 | {latency.get('p99_cycles', 'N/A')} cycles |",
            f"| P99.9 | {latency.get('p999_cycles', 'N/A')} cycles |",
            "",
        ])

        # Patterns section
        if self.patterns.get('patterns'):
            lines.extend(["### Detected Patterns", ""])
            for pattern in self.patterns['patterns']:
                severity_icon = {
                    'critical': '[CRITICAL]',
                    'high': '[HIGH]',
                    'medium': '[MEDIUM]',
                    'low': '[LOW]',
                }.get(pattern.get('severity', 'low'), '')
                lines.append(f"- {severity_icon} {pattern.get('type', 'Unknown')}: "
                           f"{pattern.get('affected_transactions', 0)} transactions affected")
            lines.append("")

        return "\n".join(lines)

    def to_json(self) -> str:
        """Generate JSON report."""
        return json.dumps(self.to_dict(), indent=2)


class AIReportGenerator:
    """Generate AI-enhanced analysis reports."""

    def __init__(self, api_key: str = None, config: ExplanationConfig = None):
        self.config = config or ExplanationConfig()
        self.api_key = api_key

        self.pattern_detector = PatternDetector()
        self.fact_extractor = FactExtractor(clock_period_ns=self.config.clock_period_ns)

        self.explainer = None
        if api_key:
            try:
                self.explainer = Explainer(config=self.config, api_key=api_key)
            except Exception:
                pass

    def generate(
        self,
        traces: list,
        metrics: Any,
        risk_stats: dict = None,
        trace_file: str = "unknown",
    ) -> AIReport:
        """Generate complete AI-enhanced report."""
        patterns = self.pattern_detector.detect_all(traces, risk_stats)
        facts = self.fact_extractor.extract(metrics, patterns, risk_stats)

        explanation = None
        executive_summary = None

        if self.explainer:
            try:
                explanation_obj = self.explainer.explain(facts, patterns)
                explanation = explanation_obj.to_dict()
                executive_summary = self.explainer.executive_summary(facts)
            except Exception as e:
                explanation = {'error': str(e)}

        # Convert metrics to dict if it has a to_dict method
        metrics_dict = metrics.to_dict() if hasattr(metrics, 'to_dict') else {}

        return AIReport(
            generated_at=datetime.now().isoformat(),
            trace_file=trace_file,
            metrics=metrics_dict,
            patterns=patterns.to_dict(),
            facts=facts.to_dict(),
            explanation=explanation,
            executive_summary=executive_summary,
        )

    def generate_without_ai(
        self,
        traces: list,
        metrics: Any,
        risk_stats: dict = None,
        trace_file: str = "unknown",
    ) -> AIReport:
        """Generate report without AI (facts and patterns only)."""
        patterns = self.pattern_detector.detect_all(traces, risk_stats)
        facts = self.fact_extractor.extract(metrics, patterns, risk_stats)

        metrics_dict = metrics.to_dict() if hasattr(metrics, 'to_dict') else {}

        return AIReport(
            generated_at=datetime.now().isoformat(),
            trace_file=trace_file,
            metrics=metrics_dict,
            patterns=patterns.to_dict(),
            facts=facts.to_dict(),
            explanation=None,
            executive_summary=None,
        )

    def generate_with_protocol(
        self,
        traces: list,
        metrics: Any,
        protocol_context: Any,
        risk_stats: dict = None,
        trace_file: str = "unknown",
    ) -> AIReport:
        """Generate report with protocol context (H5)."""
        from protocol.risk_correlation import RiskCorrelator
        from protocol.health import HealthIntegrator

        # Standard analysis
        patterns = self.pattern_detector.detect_all(traces, risk_stats)
        facts = self.fact_extractor.extract(metrics, patterns, risk_stats)

        # Add protocol facts
        self.fact_extractor.extract_protocol_facts(facts, protocol_context)

        # Correlate events
        correlator = RiskCorrelator()
        correlations = correlator.correlate(patterns.patterns, protocol_context)

        # Compute risk assessment
        metrics_dict = metrics.to_dict() if hasattr(metrics, 'to_dict') else {}
        integrator = HealthIntegrator()
        risk_assessment = integrator.assess(metrics_dict, protocol_context.health)

        # Generate AI explanation
        explanation = None
        executive_summary = None

        if self.explainer:
            try:
                explanation_obj = self.explainer.explain(facts, patterns)
                explanation = explanation_obj.to_dict()
                executive_summary = self.explainer.executive_summary(facts)
            except Exception as e:
                explanation = {'error': str(e)}

        return AIReport(
            generated_at=datetime.now().isoformat(),
            trace_file=trace_file,
            metrics=metrics_dict,
            patterns=patterns.to_dict(),
            facts=facts.to_dict(),
            explanation=explanation,
            executive_summary=executive_summary,
            protocol=protocol_context.to_dict(),
            correlations=correlations.to_dict(),
            risk_assessment=risk_assessment.to_dict(),
        )

    def save_report(self, report: AIReport, output_path: Path, format: str = 'json'):
        """Save report to file."""
        output_path = Path(output_path)

        if format == 'json':
            with open(output_path, 'w') as f:
                json.dump(report.to_dict(), f, indent=2)
        elif format in ('markdown', 'md'):
            with open(output_path, 'w') as f:
                f.write(report.to_markdown())
