"""
Reproducibility validation for trace comparisons.
"""

from dataclasses import dataclass
from typing import Optional, List, Tuple
from enum import Enum

from ..trace.provenance import Provenance, ProvenanceMatch


class ComparisonTrust(Enum):
    """Trust level for a comparison."""
    HIGH = "high"          # All provenance matches
    MEDIUM = "medium"      # Minor warnings, still usable
    LOW = "low"            # Missing provenance, use with caution
    INVALID = "invalid"    # Critical mismatch, comparison meaningless


@dataclass
class ReproducibilityReport:
    """Report on comparison reproducibility."""
    trust_level: ComparisonTrust
    checklist: List[Tuple[str, bool, Optional[str]]]  # (item, passed, detail)
    recommendation: str
    can_proceed: bool

    def print_checklist(self):
        """Print formatted checklist."""
        try:
            import click

            trust_colors = {
                ComparisonTrust.HIGH: 'green',
                ComparisonTrust.MEDIUM: 'yellow',
                ComparisonTrust.LOW: 'yellow',
                ComparisonTrust.INVALID: 'red',
            }

            click.echo("\nReproducibility Checklist:")
            click.echo("-" * 50)

            for item, passed, detail in self.checklist:
                icon = "+" if passed else "x"
                color = 'green' if passed else 'red'
                click.secho(f"  {icon} {item}", fg=color, nl=False)
                if detail:
                    click.secho(f" ({detail})", fg='bright_black')
                else:
                    click.echo()

            click.echo()
            click.secho(
                f"Trust Level: {self.trust_level.value.upper()}",
                fg=trust_colors[self.trust_level],
                bold=True
            )

            if self.recommendation:
                click.echo(f"\n{self.recommendation}")

        except ImportError:
            # Fallback without click
            print("\nReproducibility Checklist:")
            print("-" * 50)
            for item, passed, detail in self.checklist:
                icon = "+" if passed else "x"
                print(f"  {icon} {item}" + (f" ({detail})" if detail else ""))
            print(f"\nTrust Level: {self.trust_level.value.upper()}")
            if self.recommendation:
                print(f"\n{self.recommendation}")


def check_reproducibility(
    baseline_prov: Optional[Provenance],
    current_prov: Optional[Provenance],
    strict: bool = False
) -> ReproducibilityReport:
    """
    Check if comparison between two traces is reproducible.

    Args:
        baseline_prov: Provenance of baseline trace
        current_prov: Provenance of current trace
        strict: If True, require all provenance fields

    Returns:
        ReproducibilityReport with trust level and checklist
    """
    checklist = []
    issues = 0
    warnings = 0

    # Check 1: Both have provenance
    if baseline_prov is None or current_prov is None:
        checklist.append((
            "Provenance present",
            False,
            "Missing from one or both traces"
        ))

        return ReproducibilityReport(
            trust_level=ComparisonTrust.LOW,
            checklist=checklist,
            recommendation=(
                "Traces lack provenance metadata. "
                "Results may not be reproducible. "
                "Add provenance with: sentinel-hft record --provenance"
            ),
            can_proceed=True
        )

    checklist.append(("Provenance present", True, None))

    # Check 2: Same stimulus
    if baseline_prov.stimulus_hash and current_prov.stimulus_hash:
        same_stimulus = baseline_prov.stimulus_hash == current_prov.stimulus_hash
        checklist.append((
            "Same stimulus",
            same_stimulus,
            None if same_stimulus else "Different input data"
        ))
        if not same_stimulus:
            issues += 1
    else:
        checklist.append((
            "Same stimulus",
            False,
            "Stimulus hash missing"
        ))
        warnings += 1

    # Check 3: Same config
    if baseline_prov.config_hash and current_prov.config_hash:
        same_config = baseline_prov.config_hash == current_prov.config_hash
        checklist.append((
            "Same config",
            same_config,
            None if same_config else "Config changed"
        ))
        if not same_config:
            warnings += 1  # Config changes might be intentional
    else:
        checklist.append((
            "Same config",
            False,
            "Config hash missing"
        ))
        warnings += 1

    # Check 4: Same clock
    same_clock = abs(baseline_prov.clock_mhz - current_prov.clock_mhz) < 0.01
    checklist.append((
        "Same clock frequency",
        same_clock,
        None if same_clock else f"{baseline_prov.clock_mhz} vs {current_prov.clock_mhz} MHz"
    ))
    if not same_clock:
        issues += 1

    # Check 5: Same trace format
    same_format = baseline_prov.trace_format == current_prov.trace_format
    checklist.append((
        "Same trace format",
        same_format,
        None if same_format else f"v{baseline_prov.trace_format} vs v{current_prov.trace_format}"
    ))
    if not same_format:
        warnings += 1

    # Check 6: Clean git state
    clean_git = not (baseline_prov.git_dirty or current_prov.git_dirty)
    checklist.append((
        "Clean git state",
        clean_git,
        None if clean_git else "Uncommitted changes present"
    ))
    if not clean_git:
        warnings += 1

    # Determine trust level
    if issues > 0:
        trust_level = ComparisonTrust.INVALID
        recommendation = (
            "Critical reproducibility issues detected. "
            "Comparison results are not meaningful. "
            "Ensure both traces use same stimulus and clock."
        )
        can_proceed = False
    elif warnings > 2:
        trust_level = ComparisonTrust.LOW
        recommendation = (
            "Multiple reproducibility warnings. "
            "Results should be interpreted with caution."
        )
        can_proceed = True
    elif warnings > 0:
        trust_level = ComparisonTrust.MEDIUM
        recommendation = (
            "Minor reproducibility concerns. "
            "Results are likely valid but verify if critical."
        )
        can_proceed = True
    else:
        trust_level = ComparisonTrust.HIGH
        recommendation = "Traces are fully comparable. Results are trustworthy."
        can_proceed = True

    return ReproducibilityReport(
        trust_level=trust_level,
        checklist=checklist,
        recommendation=recommendation,
        can_proceed=can_proceed
    )


def require_reproducible(
    baseline_prov: Optional[Provenance],
    current_prov: Optional[Provenance],
    min_trust: ComparisonTrust = ComparisonTrust.LOW
) -> ReproducibilityReport:
    """
    Check reproducibility and raise if below minimum trust.

    Use in CLI commands to enforce reproducibility.
    """
    report = check_reproducibility(baseline_prov, current_prov)

    trust_order = [
        ComparisonTrust.INVALID,
        ComparisonTrust.LOW,
        ComparisonTrust.MEDIUM,
        ComparisonTrust.HIGH,
    ]

    if trust_order.index(report.trust_level) < trust_order.index(min_trust):
        raise ReproducibilityError(report)

    return report


class ReproducibilityError(Exception):
    """Raised when comparison fails reproducibility check."""

    def __init__(self, report: ReproducibilityReport):
        self.report = report
        super().__init__(report.recommendation)
