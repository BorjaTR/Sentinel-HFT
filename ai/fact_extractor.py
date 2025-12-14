"""Extract structured facts for LLM consumption."""

from dataclasses import dataclass, field
from typing import Optional, Any, List

from .pattern_detector import Pattern, PatternDetectionResult


@dataclass
class Fact:
    """A single fact about the trace data."""
    category: str           # 'latency', 'risk', 'throughput', 'anomaly'
    key: str                # Fact identifier
    value: Any              # Fact value
    context: str            # Human-readable context
    importance: str         # 'critical', 'high', 'medium', 'low'

    def to_dict(self) -> dict:
        return {
            'category': self.category,
            'key': self.key,
            'value': self.value,
            'context': self.context,
            'importance': self.importance,
        }


@dataclass
class FactSet:
    """Collection of facts organized for LLM consumption."""
    facts: List[Fact] = field(default_factory=list)
    critical_facts: List[Fact] = field(default_factory=list)

    def add(self, fact: Fact):
        self.facts.append(fact)
        if fact.importance == 'critical':
            self.critical_facts.append(fact)

    def to_dict(self) -> dict:
        return {
            'total_facts': len(self.facts),
            'critical_count': len(self.critical_facts),
            'facts': [f.to_dict() for f in self.facts],
        }

    def to_llm_context(self) -> str:
        """Format facts for LLM prompt."""
        lines = ["FACTS:"]

        by_category: dict = {}
        for fact in self.facts:
            by_category.setdefault(fact.category, []).append(fact)

        for category, facts in by_category.items():
            lines.append(f"\n[{category.upper()}]")
            for fact in sorted(facts, key=lambda f: f.importance):
                importance_marker = "!" if fact.importance in ('critical', 'high') else "-"
                lines.append(f"  {importance_marker} {fact.context}")

        return "\n".join(lines)


class FactExtractor:
    """Extract facts from metrics and patterns."""

    def __init__(self, clock_period_ns: float = 10.0):
        self.clock_period_ns = clock_period_ns

    def extract(
        self,
        metrics: Any,  # FullMetrics
        patterns: PatternDetectionResult,
        risk_stats: Optional[dict] = None,
    ) -> FactSet:
        """Extract all facts from analysis results."""
        facts = FactSet()

        if hasattr(metrics, 'latency'):
            self._extract_latency_facts(facts, metrics.latency)
        if hasattr(metrics, 'throughput'):
            self._extract_throughput_facts(facts, metrics.throughput)
        if hasattr(metrics, 'anomalies'):
            self._extract_anomaly_facts(facts, metrics.anomalies)

        self._extract_pattern_facts(facts, patterns)

        if risk_stats:
            self._extract_risk_facts(facts, risk_stats)

        return facts

    def _extract_latency_facts(self, facts: FactSet, latency: Any):
        """Extract latency-related facts."""
        count = getattr(latency, 'count', 0)
        facts.add(Fact(
            category='latency',
            key='count',
            value=count,
            context=f"Analyzed {count:,} transactions",
            importance='low',
        ))

        p50 = getattr(latency, 'p50_cycles', 0)
        facts.add(Fact(
            category='latency',
            key='p50',
            value=p50,
            context=f"Median latency: {p50} cycles ({p50 * self.clock_period_ns:.0f}ns)",
            importance='medium',
        ))

        p99 = getattr(latency, 'p99_cycles', 0)
        facts.add(Fact(
            category='latency',
            key='p99',
            value=p99,
            context=f"P99 latency: {p99} cycles ({p99 * self.clock_period_ns:.0f}ns)",
            importance='high',
        ))

        if p50 > 0:
            tail_ratio = p99 / p50
            importance = 'high' if tail_ratio > 3 else 'medium' if tail_ratio > 2 else 'low'
            facts.add(Fact(
                category='latency',
                key='tail_ratio',
                value=round(tail_ratio, 2),
                context=f"Tail latency ratio (P99/P50): {tail_ratio:.1f}x",
                importance=importance,
            ))

    def _extract_throughput_facts(self, facts: FactSet, throughput: Any):
        """Extract throughput-related facts."""
        tps = getattr(throughput, 'transactions_per_second', 0)
        facts.add(Fact(
            category='throughput',
            key='tx_per_second',
            value=tps,
            context=f"Throughput: {tps:,.0f} tx/sec",
            importance='medium',
        ))

        max_burst = getattr(throughput, 'max_burst_size', 0)
        if max_burst > 10:
            facts.add(Fact(
                category='throughput',
                key='max_burst',
                value=max_burst,
                context=f"Maximum burst: {max_burst} consecutive transactions",
                importance='medium',
            ))

    def _extract_anomaly_facts(self, facts: FactSet, anomalies: Any):
        """Extract anomaly-related facts."""
        count = getattr(anomalies, 'count', 0)
        threshold = getattr(anomalies, 'threshold_zscore', 3.0)

        if count == 0:
            facts.add(Fact(
                category='anomaly',
                key='none_detected',
                value=0,
                context=f"No anomalies detected (threshold: {threshold}s)",
                importance='low',
            ))
            return

        importance = 'critical' if count > 10 else 'high' if count > 3 else 'medium'
        facts.add(Fact(
            category='anomaly',
            key='count',
            value=count,
            context=f"{count} latency anomalies detected (>{threshold}s)",
            importance=importance,
        ))

        anomaly_list = getattr(anomalies, 'anomalies', [])
        if anomaly_list:
            worst = max(anomaly_list, key=lambda a: a.zscore)
            facts.add(Fact(
                category='anomaly',
                key='worst',
                value={'tx_id': worst.tx_id, 'zscore': worst.zscore, 'latency': worst.latency_cycles},
                context=f"Worst anomaly: TX {worst.tx_id} at {worst.zscore:.1f}s ({worst.latency_cycles} cycles)",
                importance='high',
            ))

    def _extract_pattern_facts(self, facts: FactSet, patterns: PatternDetectionResult):
        """Extract pattern-related facts."""
        if not patterns.patterns:
            return

        for pattern in patterns.patterns:
            importance = 'critical' if pattern.severity == 'critical' else \
                        'high' if pattern.severity == 'high' else 'medium'

            facts.add(Fact(
                category='pattern',
                key=pattern.pattern_type.name.lower(),
                value=pattern.to_dict(),
                context=self._pattern_to_context(pattern),
                importance=importance,
            ))

    def _extract_risk_facts(self, facts: FactSet, risk_stats: dict):
        """Extract risk-related facts."""
        rate_rejects = risk_stats.get('rate_limit_rejects', 0)
        if isinstance(rate_rejects, list):
            rate_rejects = len(rate_rejects)

        if rate_rejects > 0:
            total = risk_stats.get('total_orders', 1)
            pct = rate_rejects / total * 100
            importance = 'high' if pct > 1 else 'medium' if pct > 0.1 else 'low'
            facts.add(Fact(
                category='risk',
                key='rate_limit_rejects',
                value=rate_rejects,
                context=f"Rate limiter rejected {rate_rejects:,} orders ({pct:.2f}%)",
                importance=importance,
            ))

        pos_rejects = risk_stats.get('position_limit_rejects', 0)
        if isinstance(pos_rejects, list):
            pos_rejects = len(pos_rejects)

        if pos_rejects > 0:
            facts.add(Fact(
                category='risk',
                key='position_limit_rejects',
                value=pos_rejects,
                context=f"Position limiter rejected {pos_rejects:,} orders",
                importance='high',
            ))

        if risk_stats.get('kill_switch_triggered', False):
            facts.add(Fact(
                category='risk',
                key='kill_switch',
                value=True,
                context="KILL SWITCH WAS TRIGGERED",
                importance='critical',
            ))

    def _pattern_to_context(self, pattern: Pattern) -> str:
        """Convert pattern to human-readable context."""
        ptype = pattern.pattern_type.name
        affected = len(pattern.affected_tx_ids)

        if ptype == 'LATENCY_SPIKE':
            return f"Latency spike: {affected} transactions at {pattern.details.get('zscore', '?')}s"
        elif ptype == 'RATE_LIMIT_BURST':
            return f"Rate limit burst: {affected} orders rejected in {pattern.details.get('burst_duration_cycles', '?')} cycles"
        elif ptype == 'KILL_SWITCH_TRIGGER':
            return f"Kill switch triggered: {pattern.details.get('orders_blocked', '?')} orders blocked"
        elif ptype == 'LATENCY_BIMODAL':
            return f"Bimodal latency: two populations at {pattern.details.get('low_population_mean', '?')} and {pattern.details.get('high_population_mean', '?')} cycles"
        else:
            return f"{ptype}: {affected} transactions affected"
