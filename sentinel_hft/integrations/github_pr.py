"""
GitHub PR comment generation.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any


@dataclass
class PRCommentData:
    """Data for PR comment."""
    regression_detected: bool
    metrics: List[Dict[str, Any]]
    stage_attribution: Dict[str, Any]
    regression_source: Optional[str]
    pattern_match: Optional[str]
    pattern_confidence: Optional[float]
    baseline_sha: Optional[str]
    current_sha: Optional[str]
    reproducibility_trust: str
    fix_preview: Optional[str]

    # For TL;DR
    tldr_metric: str
    tldr_delta: float
    tldr_stage: Optional[str]
    tldr_pattern: Optional[str]


def generate_pr_comment(data: PRCommentData, is_pro: bool = False) -> str:
    """
    Generate GitHub PR comment markdown.

    Args:
        data: PRCommentData with all metrics
        is_pro: If True, show full fix. If False, show preview with upgrade link.

    Returns:
        Markdown string for PR comment
    """
    lines = []

    # Header with TL;DR
    if data.regression_detected:
        emoji = "🔴"
        status = "Latency Regression Detected"

        # TL;DR line
        tldr_parts = [f"P99 {data.tldr_delta:+.1f}%"]
        if data.tldr_stage:
            tldr_parts.append(f"{data.tldr_stage} stage")
        if data.tldr_pattern:
            tldr_parts.append(f"likely {data.tldr_pattern}")

        tldr = " | ".join(tldr_parts)
    else:
        emoji = "✅"
        status = "No Regression Detected"
        tldr = "All metrics within threshold"

    lines.append(f"## {emoji} Sentinel-HFT: {status}")
    lines.append("")
    lines.append(f"**TL;DR:** {tldr}")
    lines.append("")

    # Reproducibility badge
    trust_badges = {
        'high': '![Trust: High](https://img.shields.io/badge/reproducibility-high-green)',
        'medium': '![Trust: Medium](https://img.shields.io/badge/reproducibility-medium-yellow)',
        'low': '![Trust: Low](https://img.shields.io/badge/reproducibility-low-orange)',
        'invalid': '![Trust: Invalid](https://img.shields.io/badge/reproducibility-invalid-red)',
    }
    lines.append(trust_badges.get(data.reproducibility_trust, ''))
    lines.append("")

    # Metrics table
    lines.append("### Metrics")
    lines.append("")
    lines.append("| Metric | Baseline | Current | Delta | Status |")
    lines.append("|--------|----------|---------|-------|--------|")

    for m in data.metrics:
        if m['status'] == 'regress':
            status_cell = "🔴 Regression"
        elif m['status'] == 'warn':
            status_cell = "⚠️ Warning"
        else:
            status_cell = "✅ OK"

        lines.append(
            f"| {m['name']} | {m['baseline']:.0f}ns | {m['current']:.0f}ns | "
            f"{m['delta_pct']:+.1f}% | {status_cell} |"
        )

    lines.append("")

    # Stage attribution (collapsible)
    if data.stage_attribution and data.regression_detected:
        lines.append("<details>")
        lines.append("<summary><strong>Stage Attribution</strong></summary>")
        lines.append("")
        lines.append("```")

        for stage, values in data.stage_attribution.items():
            marker = " <- SOURCE" if stage == data.regression_source else ""
            lines.append(
                f"{stage.capitalize():<10} {values['before']:.0f}ns -> "
                f"{values['after']:.0f}ns ({values['delta_pct']:+.1f}%){marker}"
            )

        lines.append("```")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # Pattern match
    if data.pattern_match and data.regression_detected:
        lines.append("### Pattern Analysis")
        lines.append("")
        lines.append(
            f"**Detected:** `{data.pattern_match}` "
            f"({data.pattern_confidence:.0%} confidence)"
        )
        lines.append("")

    # Fix preview
    if data.regression_detected and data.fix_preview:
        lines.append("<details>")
        lines.append("<summary><strong>Suggested Fix</strong></summary>")
        lines.append("")

        if is_pro:
            lines.append("```systemverilog")
            lines.append(data.fix_preview)
            lines.append("```")
        else:
            # Show preview with upgrade prompt
            preview_lines = data.fix_preview.split('\n')[:20]
            lines.append("```systemverilog")
            lines.extend(preview_lines)
            lines.append("// ... truncated ...")
            lines.append("```")
            lines.append("")
            lines.append(
                "💡 [Upgrade to Pro](https://sentinel-hft.com/pricing) "
                "for full fix + testbench"
            )

        lines.append("")
        lines.append("</details>")
        lines.append("")

    # Footer
    lines.append("---")
    if data.baseline_sha and data.current_sha:
        lines.append(
            f"*Comparing `{data.baseline_sha[:8]}` -> `{data.current_sha[:8]}`*"
        )
    lines.append(
        "*[Docs](https://docs.sentinel-hft.com) | "
        "[Dashboard](https://sentinel-hft.com/dashboard)*"
    )

    return "\n".join(lines)


def generate_comment_identifier() -> str:
    """
    Return identifier to find/update existing comment.
    """
    return "<!-- sentinel-hft-pr-comment -->"


def wrap_with_identifier(comment: str) -> str:
    """
    Wrap comment with identifier for finding later.
    """
    identifier = generate_comment_identifier()
    return f"{identifier}\n{comment}"


def create_pr_comment_from_result(
    result: Dict[str, Any],
    baseline_prov: Optional[Dict] = None,
    current_prov: Optional[Dict] = None,
    is_pro: bool = False
) -> str:
    """
    Create PR comment from regression analysis result.

    Args:
        result: Output from regression analysis
        baseline_prov: Baseline provenance dict
        current_prov: Current provenance dict
        is_pro: Whether user has Pro license

    Returns:
        Formatted PR comment markdown
    """
    # Build metrics list
    metrics = []
    for m in result.get('metrics', []):
        metrics.append({
            'name': m.get('name', 'Unknown'),
            'baseline': m.get('baseline', 0),
            'current': m.get('current', 0),
            'delta_pct': m.get('delta_pct', 0),
            'status': m.get('status', 'ok'),
        })

    # Get P99 for TL;DR
    p99_metric = next(
        (m for m in metrics if m['name'] == 'P99'),
        {'delta_pct': 0}
    )

    # Build comment data
    data = PRCommentData(
        regression_detected=result.get('regression_detected', False),
        metrics=metrics,
        stage_attribution=result.get('stage_attribution', {}),
        regression_source=result.get('regression_source'),
        pattern_match=result.get('pattern_match'),
        pattern_confidence=result.get('pattern_confidence'),
        baseline_sha=baseline_prov.get('git_sha') if baseline_prov else None,
        current_sha=current_prov.get('git_sha') if current_prov else None,
        reproducibility_trust=result.get('reproducibility_trust', 'low'),
        fix_preview=result.get('fix_preview'),
        tldr_metric='P99',
        tldr_delta=p99_metric['delta_pct'],
        tldr_stage=result.get('regression_source'),
        tldr_pattern=result.get('pattern_match'),
    )

    comment = generate_pr_comment(data, is_pro=is_pro)
    return wrap_with_identifier(comment)
