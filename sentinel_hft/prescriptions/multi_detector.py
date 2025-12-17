"""
Multi-pattern detection with confidence scoring and counter-evidence.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Protocol
from enum import Enum


class ConfidenceLevel(Enum):
    HIGH = "high"          # > 0.80
    MEDIUM = "medium"      # 0.65 - 0.80
    LOW = "low"            # 0.50 - 0.65
    UNCERTAIN = "uncertain"  # < 0.50


@dataclass
class EvidenceItem:
    """A piece of evidence for or against a pattern."""
    description: str
    value: Any
    expected: Any
    supports: bool  # True = supports pattern, False = counter-evidence
    weight: float   # How much this affects confidence


@dataclass
class PatternMatch:
    """A potential pattern match with full evidence."""
    pattern_id: str
    pattern_name: str
    confidence: float
    confidence_level: ConfidenceLevel

    # What supports this hypothesis
    supporting_evidence: List[EvidenceItem]

    # What argues against it
    counter_evidence: List[EvidenceItem]

    # Where to look
    primary_stage: str
    affected_metrics: List[str]

    # What's missing that would increase confidence
    missing_data: List[str]

    # Summary for humans
    summary: str

    def explain(self) -> str:
        """Generate human-readable explanation."""
        lines = []
        lines.append(f"Pattern: {self.pattern_name}")
        lines.append(f"Confidence: {self.confidence:.0%} ({self.confidence_level.value})")
        lines.append(f"Primary stage: {self.primary_stage}")
        lines.append("")

        if self.supporting_evidence:
            lines.append("Why we think this:")
            for ev in self.supporting_evidence[:3]:
                lines.append(f"  + {ev.description}")

        if self.counter_evidence:
            lines.append("")
            lines.append("However:")
            for ev in self.counter_evidence[:2]:
                lines.append(f"  - {ev.description}")

        if self.missing_data:
            lines.append("")
            lines.append("Would increase confidence:")
            for item in self.missing_data[:2]:
                lines.append(f"  ? {item}")

        return "\n".join(lines)


@dataclass
class DetectionResult:
    """Result of pattern detection with multiple candidates."""
    top_matches: List[PatternMatch]
    is_uncertain: bool
    uncertainty_reason: Optional[str]

    # Overall assessment
    most_likely: Optional[PatternMatch]
    recommendation: str

    def print_report(self, verbose: bool = False):
        """Print formatted detection report."""
        try:
            import click

            click.echo()
            click.secho("Pattern Analysis", bold=True)
            click.echo("=" * 50)

            if self.is_uncertain:
                click.secho(f"\n! UNCERTAIN: {self.uncertainty_reason}", fg='yellow')
                click.echo("\nClosest matches (interpret with caution):")
            else:
                click.echo(f"\nTop {len(self.top_matches)} candidates:")

            for i, match in enumerate(self.top_matches, 1):
                conf_colors = {
                    ConfidenceLevel.HIGH: 'green',
                    ConfidenceLevel.MEDIUM: 'yellow',
                    ConfidenceLevel.LOW: 'yellow',
                    ConfidenceLevel.UNCERTAIN: 'red',
                }
                color = conf_colors[match.confidence_level]

                click.echo()
                click.secho(
                    f"#{i} {match.pattern_name}",
                    fg='cyan', bold=True
                )
                click.secho(
                    f"   Confidence: {match.confidence:.0%} ({match.confidence_level.value})",
                    fg=color
                )
                click.echo(f"   Stage: {match.primary_stage}")

                if verbose or i == 1:
                    click.echo()
                    if match.supporting_evidence:
                        click.echo("   Evidence:")
                        for ev in match.supporting_evidence[:3]:
                            click.secho(f"     + {ev.description}", fg='green')

                    if match.counter_evidence:
                        click.echo("   Counter-evidence:")
                        for ev in match.counter_evidence[:2]:
                            click.secho(f"     - {ev.description}", fg='red')

            click.echo()
            click.secho("Recommendation:", bold=True)
            click.echo(f"  {self.recommendation}")

        except ImportError:
            # Fallback without click
            print("\nPattern Analysis")
            print("=" * 50)
            for i, match in enumerate(self.top_matches, 1):
                print(f"\n#{i} {match.pattern_name}")
                print(f"   Confidence: {match.confidence:.0%}")
                print(f"   Stage: {match.primary_stage}")
            print(f"\nRecommendation: {self.recommendation}")


class PatternCriterion(Protocol):
    """Protocol for pattern matching criteria."""
    feature: str
    expected: Any
    weight: float

    def evaluate(self, value: Any) -> bool:
        """Evaluate if value matches this criterion."""
        ...

    def describe(self, value: Any) -> str:
        """Describe the evaluation result."""
        ...


class PatternSignature(Protocol):
    """Protocol for pattern signatures."""
    criteria: List[PatternCriterion]


class Pattern(Protocol):
    """Protocol for patterns that can be detected."""
    id: str
    name: str
    description: str
    signature: PatternSignature
    primary_stage: str
    affected_metrics: List[str]


@dataclass
class SimpleCriterion:
    """Simple criterion implementation for pattern matching."""
    feature: str
    expected: Any
    weight: float = 1.0
    operator: str = "eq"  # eq, gt, lt, gte, lte, range, contains

    def evaluate(self, value: Any) -> bool:
        """Evaluate if value matches this criterion."""
        if value is None:
            return False

        if self.operator == "eq":
            return value == self.expected
        elif self.operator == "gt":
            return value > self.expected
        elif self.operator == "lt":
            return value < self.expected
        elif self.operator == "gte":
            return value >= self.expected
        elif self.operator == "lte":
            return value <= self.expected
        elif self.operator == "range":
            low, high = self.expected
            return low <= value <= high
        elif self.operator == "contains":
            return self.expected in value
        return False

    def describe(self, value: Any) -> str:
        """Describe the evaluation result."""
        matches = self.evaluate(value)
        if self.operator == "eq":
            if matches:
                return f"{self.feature} = {value} (expected {self.expected})"
            return f"{self.feature} = {value} (expected {self.expected})"
        elif self.operator == "gt":
            return f"{self.feature} = {value} {'>' if matches else '<='} {self.expected}"
        elif self.operator == "range":
            low, high = self.expected
            return f"{self.feature} = {value} ({'in' if matches else 'outside'} {low}-{high})"
        return f"{self.feature} = {value}"


@dataclass
class SimpleSignature:
    """Simple signature implementation."""
    criteria: List[SimpleCriterion]


@dataclass
class SimplePattern:
    """Simple pattern implementation."""
    id: str
    name: str
    description: str
    signature: SimpleSignature
    primary_stage: str
    affected_metrics: List[str] = field(default_factory=list)


class MultiPatternDetector:
    """
    Detect multiple potential patterns with confidence scoring.
    """

    def __init__(self, patterns: List[Any] = None):
        self.patterns = patterns or self._get_default_patterns()

    def _get_default_patterns(self) -> List[SimplePattern]:
        """Get built-in patterns for HFT latency issues."""
        return [
            SimplePattern(
                id="fifo_backpressure",
                name="FIFO Backpressure Stall",
                description="FIFO full condition causing upstream stalls",
                signature=SimpleSignature(criteria=[
                    SimpleCriterion("risk_delta_pct", 20.0, weight=2.0, operator="gt"),
                    SimpleCriterion("p999_p99_ratio", 2.0, weight=1.5, operator="gt"),
                    SimpleCriterion("drop_rate", 0.001, weight=1.0, operator="gt"),
                ]),
                primary_stage="risk",
                affected_metrics=["p99", "p999", "drops"],
            ),
            SimplePattern(
                id="arbiter_contention",
                name="Arbiter Contention",
                description="Multiple requestors competing for shared resource",
                signature=SimpleSignature(criteria=[
                    SimpleCriterion("core_delta_pct", 15.0, weight=2.0, operator="gt"),
                    SimpleCriterion("variance_increase", 1.5, weight=1.5, operator="gt"),
                    SimpleCriterion("burst_correlation", 0.7, weight=1.0, operator="gt"),
                ]),
                primary_stage="core",
                affected_metrics=["p90", "p99", "variance"],
            ),
            SimplePattern(
                id="pipeline_bubble",
                name="Pipeline Bubble",
                description="Stall cycles inserted in pipeline",
                signature=SimpleSignature(criteria=[
                    SimpleCriterion("mean_delta_pct", 10.0, weight=2.0, operator="gt"),
                    SimpleCriterion("p50_delta_pct", 10.0, weight=1.5, operator="gt"),
                    SimpleCriterion("tail_ratio_stable", True, weight=1.0, operator="eq"),
                ]),
                primary_stage="core",
                affected_metrics=["mean", "p50"],
            ),
            SimplePattern(
                id="memory_bandwidth",
                name="Memory Bandwidth Saturation",
                description="External memory access latency increased",
                signature=SimpleSignature(criteria=[
                    SimpleCriterion("ingress_delta_pct", 20.0, weight=2.0, operator="gt"),
                    SimpleCriterion("throughput_decrease", 0.1, weight=1.5, operator="gt"),
                    SimpleCriterion("burst_size_increase", 1.2, weight=1.0, operator="gt"),
                ]),
                primary_stage="ingress",
                affected_metrics=["p99", "throughput"],
            ),
            SimplePattern(
                id="clock_domain_crossing",
                name="Clock Domain Crossing Issue",
                description="Synchronizer adding latency at domain boundary",
                signature=SimpleSignature(criteria=[
                    SimpleCriterion("egress_delta_pct", 25.0, weight=2.0, operator="gt"),
                    SimpleCriterion("jitter_increase", 2.0, weight=1.5, operator="gt"),
                    SimpleCriterion("periodic_spikes", True, weight=1.0, operator="eq"),
                ]),
                primary_stage="egress",
                affected_metrics=["p99", "p999", "jitter"],
            ),
        ]

    def detect(self, features: Dict[str, Any], top_n: int = 3) -> DetectionResult:
        """
        Detect top N pattern matches with full evidence.
        """
        matches = []

        for pattern in self.patterns:
            match = self._evaluate_pattern(pattern, features)
            if match.confidence > 0.30:  # Minimum threshold
                matches.append(match)

        # Sort by confidence
        matches.sort(key=lambda m: m.confidence, reverse=True)
        top_matches = matches[:top_n]

        # Determine if uncertain
        is_uncertain = False
        uncertainty_reason = None

        if not top_matches:
            is_uncertain = True
            uncertainty_reason = "No patterns matched above 30% confidence"
        elif top_matches[0].confidence < 0.65:
            is_uncertain = True
            uncertainty_reason = f"Best match only {top_matches[0].confidence:.0%} confident"
        elif len(top_matches) > 1 and top_matches[0].confidence - top_matches[1].confidence < 0.15:
            is_uncertain = True
            uncertainty_reason = "Multiple patterns with similar confidence"

        # Generate recommendation
        if is_uncertain:
            recommendation = self._uncertain_recommendation(top_matches, features)
        else:
            recommendation = self._confident_recommendation(top_matches[0])

        return DetectionResult(
            top_matches=top_matches,
            is_uncertain=is_uncertain,
            uncertainty_reason=uncertainty_reason,
            most_likely=top_matches[0] if top_matches and not is_uncertain else None,
            recommendation=recommendation,
        )

    def _evaluate_pattern(self, pattern: Any, features: Dict[str, Any]) -> PatternMatch:
        """
        Evaluate a single pattern against features.
        Returns PatternMatch with full evidence.
        """
        supporting = []
        counter = []
        missing = []

        # Evaluate each signature criterion
        for criterion in pattern.signature.criteria:
            feature_value = features.get(criterion.feature)

            if feature_value is None:
                missing.append(f"Missing data: {criterion.feature}")
                continue

            matches = criterion.evaluate(feature_value)

            ev = EvidenceItem(
                description=criterion.describe(feature_value),
                value=feature_value,
                expected=criterion.expected,
                supports=matches,
                weight=criterion.weight,
            )

            if matches:
                supporting.append(ev)
            else:
                counter.append(ev)

        # Calculate confidence
        if not supporting and not counter:
            confidence = 0.0
        else:
            total_weight = sum(e.weight for e in supporting + counter)
            supporting_weight = sum(e.weight for e in supporting)
            confidence = supporting_weight / total_weight if total_weight > 0 else 0.0

        # Adjust for missing data
        if missing:
            confidence *= (1 - len(missing) * 0.1)

        # Determine confidence level
        if confidence >= 0.80:
            level = ConfidenceLevel.HIGH
        elif confidence >= 0.65:
            level = ConfidenceLevel.MEDIUM
        elif confidence >= 0.50:
            level = ConfidenceLevel.LOW
        else:
            level = ConfidenceLevel.UNCERTAIN

        return PatternMatch(
            pattern_id=pattern.id,
            pattern_name=pattern.name,
            confidence=confidence,
            confidence_level=level,
            supporting_evidence=supporting,
            counter_evidence=counter,
            primary_stage=pattern.primary_stage,
            affected_metrics=pattern.affected_metrics,
            missing_data=missing,
            summary=pattern.description,
        )

    def _uncertain_recommendation(
        self,
        matches: List[PatternMatch],
        features: Dict[str, Any]
    ) -> str:
        """Generate recommendation when uncertain."""
        if not matches:
            return (
                "No known patterns match this regression profile. "
                "Consider manual investigation starting with the stage "
                "that contributed most to the latency increase."
            )

        # Suggest what would help
        all_missing = []
        for m in matches[:2]:
            all_missing.extend(m.missing_data)

        if all_missing:
            return (
                f"Top candidate is {matches[0].pattern_name} ({matches[0].confidence:.0%}), "
                f"but confidence is low. Collect more data: {', '.join(set(all_missing)[:3])}"
            )

        return (
            f"Possibly {matches[0].pattern_name}, but consider also "
            f"{matches[1].pattern_name if len(matches) > 1 else 'manual investigation'}. "
            f"Review counter-evidence before proceeding."
        )

    def _confident_recommendation(self, match: PatternMatch) -> str:
        """Generate recommendation when confident."""
        return (
            f"Strong match for {match.pattern_name}. "
            f"Run 'sentinel-hft prescribe' to generate fix. "
            f"Focus investigation on {match.primary_stage} stage."
        )
