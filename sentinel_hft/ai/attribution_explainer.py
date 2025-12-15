"""
attribution_explainer.py - AI-powered explanation of latency attribution

Uses Claude to generate natural language explanations of where
latency is spent in the pipeline.
"""

from dataclasses import dataclass
from typing import Optional, List
import os

from ..streaming.attribution import LatencyAttribution, StageMetrics


@dataclass
class AttributionExplanation:
    """AI-generated explanation of latency attribution."""
    summary: str
    bottleneck_analysis: str
    recommendations: List[str]
    confidence: str  # 'high', 'medium', 'low'

    def to_dict(self) -> dict:
        return {
            'summary': self.summary,
            'bottleneck_analysis': self.bottleneck_analysis,
            'recommendations': self.recommendations,
            'confidence': self.confidence,
        }


# Prompt template for attribution explanation
ATTRIBUTION_PROMPT = """You are analyzing latency attribution data from a hardware trading system.

The pipeline has these stages:
- ingress: Initial packet handling and validation
- core: Main trading logic execution
- risk: Risk gate evaluation (position limits, rate limits)
- egress: Output serialization and transmission
- overhead: Queueing delays between stages

Here is the attribution data (all times in nanoseconds):

{attribution_data}

Total p99 latency: {total_p99}ns
Identified bottleneck: {bottleneck} ({bottleneck_pct:.1%} of total)

Provide a concise analysis with:
1. A 2-sentence summary of where time is being spent
2. Analysis of the bottleneck stage and likely causes
3. 2-3 specific recommendations for optimization

Be specific and technical. Assume the reader understands FPGA trading systems."""


class AttributionExplainer:
    """Generate AI explanations for latency attribution."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY')
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if not self.api_key:
                raise ValueError("ANTHROPIC_API_KEY not set")

            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError("anthropic package required: pip install anthropic")

        return self._client

    def explain(self, attribution: LatencyAttribution) -> AttributionExplanation:
        """Generate explanation for attribution data."""

        # Format attribution data
        attr_lines = []
        for stage in attribution.stages:
            attr_lines.append(
                f"  {stage.stage}: p50={stage.p50:.1f}ns, "
                f"p99={stage.p99:.1f}ns, {stage.pct_of_total:.1%} of total"
            )

        prompt = ATTRIBUTION_PROMPT.format(
            attribution_data="\n".join(attr_lines),
            total_p99=attribution.total_p99,
            bottleneck=attribution.bottleneck,
            bottleneck_pct=attribution.bottleneck_pct,
        )

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )

            text = response.content[0].text
            return self._parse_response(text, attribution)

        except Exception as e:
            # Fallback to deterministic explanation
            return self._fallback_explanation(attribution)

    def _parse_response(
        self,
        text: str,
        attribution: LatencyAttribution
    ) -> AttributionExplanation:
        """Parse AI response into structured explanation."""
        # Simple parsing - split into sections
        lines = text.strip().split('\n')

        summary_lines = []
        analysis_lines = []
        recommendations = []

        section = 'summary'
        for line in lines:
            line = line.strip()
            if not line:
                continue

            lower = line.lower()
            if 'bottleneck' in lower or 'analysis' in lower:
                section = 'analysis'
            elif 'recommend' in lower:
                section = 'recommendations'

            if section == 'summary' and len(summary_lines) < 3:
                summary_lines.append(line)
            elif section == 'analysis':
                analysis_lines.append(line)
            elif section == 'recommendations':
                if line.startswith(('-', '*', '1', '2', '3')):
                    recommendations.append(line.lstrip('-* 0123456789.'))

        return AttributionExplanation(
            summary=' '.join(summary_lines[:2]) if summary_lines else self._default_summary(attribution),
            bottleneck_analysis=' '.join(analysis_lines) if analysis_lines else '',
            recommendations=recommendations[:3] if recommendations else self._default_recommendations(attribution),
            confidence='high' if summary_lines and recommendations else 'medium',
        )

    def _fallback_explanation(
        self,
        attribution: LatencyAttribution
    ) -> AttributionExplanation:
        """Generate deterministic explanation without AI."""
        return AttributionExplanation(
            summary=self._default_summary(attribution),
            bottleneck_analysis=self._default_analysis(attribution),
            recommendations=self._default_recommendations(attribution),
            confidence='low',
        )

    def _default_summary(self, attr: LatencyAttribution) -> str:
        return (
            f"The {attr.bottleneck} stage dominates latency at "
            f"{attr.bottleneck_pct:.0%} of total time. "
            f"Overall p99 latency is {attr.total_p99:.0f}ns."
        )

    def _default_analysis(self, attr: LatencyAttribution) -> str:
        stage = next((s for s in attr.stages if s.stage == attr.bottleneck), None)
        if stage:
            return (
                f"The {attr.bottleneck} stage shows p99={stage.p99:.0f}ns "
                f"with mean={stage.mean:.0f}ns, indicating consistent behavior."
            )
        return ""

    def _default_recommendations(self, attr: LatencyAttribution) -> List[str]:
        recs = []

        if attr.bottleneck == 'core':
            recs.append("Review core trading logic for optimization opportunities")
            recs.append("Consider pipelining core computation stages")
        elif attr.bottleneck == 'risk':
            recs.append("Evaluate risk gate lookup table size and access patterns")
            recs.append("Consider caching frequently-accessed position data")
        elif attr.bottleneck == 'ingress':
            recs.append("Review packet parsing logic for unnecessary operations")
        elif attr.bottleneck == 'egress':
            recs.append("Check output serialization for buffering issues")

        # Check overhead
        overhead = next((s for s in attr.stages if s.stage == 'overhead'), None)
        if overhead and overhead.pct_of_total > 0.1:
            recs.append(f"High overhead ({overhead.pct_of_total:.0%}) suggests queueing delays between stages")

        return recs[:3]
