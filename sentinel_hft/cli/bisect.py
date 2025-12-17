"""
Trace bisect: find the first trace file where regression appears.
"""

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

import click


@dataclass
class BisectResult:
    """Result of trace bisection."""
    last_good: Path
    first_bad: Path
    last_good_metrics: Dict[str, Any]
    first_bad_metrics: Dict[str, Any]
    regression_delta: Dict[str, Any]
    stage_attribution: Dict[str, Any]
    regression_source: Optional[str]
    pattern_match: Optional[str]
    pattern_confidence: Optional[float]
    steps_taken: int
    total_traces: int


@click.command()
@click.argument('trace_dir', type=click.Path(exists=True))
@click.option('--metric', default='p99', help='Metric to bisect on (p50, p99, p999)')
@click.option('--threshold', default=0.10, help='Regression threshold (default 10%)')
@click.option('--baseline', type=click.Path(exists=True), help='Explicit baseline trace')
@click.option('--json', 'as_json', is_flag=True, help='Output as JSON')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed progress')
def bisect(trace_dir, metric, threshold, baseline, as_json, verbose):
    """
    Find the first trace file where regression appears.

    Expects trace files that sort chronologically:

    \b
      traces/
        001_abc123.bin
        002_def456.bin
        003_ghi789.bin

    Or with timestamps/commits in filename:

    \b
      traces/
        20240115_140000_abc123.bin
        20240115_143000_def456.bin

    Examples:

    \b
      sentinel-hft bisect traces/
      sentinel-hft bisect traces/ --metric p99 --threshold 0.05
      sentinel-hft bisect traces/ --baseline known_good.bin
    """
    trace_path = Path(trace_dir)

    # Find and sort trace files
    traces = _find_traces(trace_path)

    if len(traces) < 2:
        click.secho("Error: Need at least 2 trace files to bisect", fg='red')
        sys.exit(1)

    click.echo(f"Found {len(traces)} trace files")

    # Determine baseline
    if baseline:
        baseline_path = Path(baseline)
        baseline_idx = -1  # External baseline
    else:
        baseline_path = traces[0]
        baseline_idx = 0

    # Analyze baseline
    baseline_analysis = _analyze_trace(str(baseline_path))
    baseline_value = _get_metric(baseline_analysis, metric)

    click.echo(f"Baseline {metric.upper()}: {baseline_value:.0f}ns ({baseline_path.name})")
    click.echo()

    # Binary search for first bad trace
    if baseline_idx == 0:
        search_traces = traces[1:]
    else:
        search_traces = traces

    result = _binary_search(
        search_traces,
        baseline_analysis,
        metric,
        threshold,
        verbose
    )

    if result is None:
        click.secho("No regression found in trace files", fg='green')
        sys.exit(0)

    last_good_idx, first_bad_idx, steps = result
    last_good = search_traces[last_good_idx] if last_good_idx >= 0 else baseline_path
    first_bad = search_traces[first_bad_idx]

    # Deep analysis of regression
    bisect_result = _analyze_regression(
        last_good,
        first_bad,
        baseline_analysis,
        metric,
        steps,
        len(traces)
    )

    if as_json:
        _output_json(bisect_result)
    else:
        _output_human(bisect_result, len(traces))

    sys.exit(1)  # Regression found


def _find_traces(path: Path) -> List[Path]:
    """Find and sort trace files."""
    patterns = ['*.bin', '*.trace', '*.sentinel', '*.jsonl']

    traces = []
    for pattern in patterns:
        traces.extend(path.glob(pattern))

    # Sort by name (assumes chronological naming)
    traces.sort(key=lambda p: p.name)

    return traces


def _analyze_trace(trace_path: str) -> Dict[str, Any]:
    """Analyze a trace file and return metrics."""
    # Import here to avoid circular imports
    from ..streaming import StreamingAnalyzer, TraceFormat

    analyzer = StreamingAnalyzer()
    format_detector = TraceFormat()

    path = Path(trace_path)
    if path.suffix == '.jsonl':
        # JSON lines format
        with open(path) as f:
            for line in f:
                event = json.loads(line)
                analyzer.process_event(event)
    else:
        # Binary format
        fmt = format_detector.detect(path)
        with open(path, 'rb') as f:
            # Read header if present
            if fmt.has_header:
                f.seek(fmt.header_size)

            while True:
                data = f.read(fmt.record_size)
                if not data or len(data) < fmt.record_size:
                    break

                event = fmt.parse_record(data)
                analyzer.process_event(event)

    return analyzer.get_summary()


def _get_metric(analysis: Dict[str, Any], metric: str) -> float:
    """Extract metric value from analysis."""
    latency = analysis.get('latency', {})

    metric_map = {
        'p50': 'p50',
        'p90': 'p90',
        'p99': 'p99',
        'p999': 'p999',
        'mean': 'mean',
    }

    key = metric_map.get(metric, 'p99')
    return latency.get(key, 0.0)


def _binary_search(
    traces: List[Path],
    baseline_analysis: Dict[str, Any],
    metric: str,
    threshold: float,
    verbose: bool
) -> Optional[Tuple[int, int, int]]:
    """
    Binary search for first bad trace.
    Returns (last_good_idx, first_bad_idx, steps) or None if no regression.
    """
    baseline_value = _get_metric(baseline_analysis, metric)

    def is_regression(trace_path: Path) -> bool:
        analysis = _analyze_trace(str(trace_path))
        current_value = _get_metric(analysis, metric)
        delta = (current_value - baseline_value) / baseline_value if baseline_value > 0 else 0
        return delta > threshold

    # First check if there's any regression
    if not is_regression(traces[-1]):
        return None

    # Binary search
    good = -1  # -1 means baseline is last good
    bad = len(traces) - 1
    steps = 0

    while good < bad - 1:
        mid = (good + bad) // 2
        steps += 1

        if verbose:
            click.echo(f"  Step {steps}: Testing {traces[mid].name}...", nl=False)

        if is_regression(traces[mid]):
            bad = mid
            if verbose:
                click.secho(" regression", fg='red')
        else:
            good = mid
            if verbose:
                click.secho(" ok", fg='green')

    if verbose:
        click.echo(f"\nFound in {steps} steps")

    return (good, bad, steps)


def _analyze_regression(
    last_good: Path,
    first_bad: Path,
    baseline_analysis: Dict[str, Any],
    metric: str,
    steps: int,
    total: int
) -> BisectResult:
    """Deep analysis of the regression between two traces."""

    # Analyze both
    good_analysis = _analyze_trace(str(last_good))
    bad_analysis = _analyze_trace(str(first_bad))

    # Calculate deltas
    regression_delta = {}
    for m in ['p50', 'p90', 'p99', 'p999']:
        good_val = _get_metric(good_analysis, m)
        bad_val = _get_metric(bad_analysis, m)
        regression_delta[m] = {
            'before': good_val,
            'after': bad_val,
            'delta_ns': bad_val - good_val,
            'delta_pct': ((bad_val - good_val) / good_val * 100) if good_val > 0 else 0,
        }

    # Stage attribution
    stage_attribution = {}
    regression_source = None
    max_contribution = 0

    good_attr = good_analysis.get('attribution', {})
    bad_attr = bad_analysis.get('attribution', {})

    for stage in ['ingress', 'core', 'risk', 'egress']:
        key = f'{stage}_ns'
        good_val = good_attr.get(key, 0)
        bad_val = bad_attr.get(key, 0)
        delta = bad_val - good_val
        delta_pct = (delta / good_val * 100) if good_val > 0 else 0

        stage_attribution[stage] = {
            'before': good_val,
            'after': bad_val,
            'delta_ns': delta,
            'delta_pct': delta_pct,
        }

        if delta > max_contribution:
            max_contribution = delta
            regression_source = stage

    # Pattern detection (optional)
    pattern_match = None
    pattern_confidence = None

    try:
        from ..prescriptions import MultiPatternDetector

        detector = MultiPatternDetector()

        # Build features from analysis
        features = {}
        for stage, data in stage_attribution.items():
            features[f'{stage}_delta_pct'] = data['delta_pct']

        p99_delta = regression_delta.get('p99', {})
        p999_delta = regression_delta.get('p999', {})
        if p99_delta.get('after', 0) > 0:
            features['p999_p99_ratio'] = p999_delta.get('after', 0) / p99_delta.get('after', 1)

        features['drop_rate'] = bad_analysis.get('drops', {}).get('rate', 0)

        result = detector.detect(features)
        if result.most_likely:
            pattern_match = result.most_likely.pattern_name
            pattern_confidence = result.most_likely.confidence
    except Exception:
        pass

    return BisectResult(
        last_good=last_good,
        first_bad=first_bad,
        last_good_metrics=good_analysis.get('latency', {}),
        first_bad_metrics=bad_analysis.get('latency', {}),
        regression_delta=regression_delta,
        stage_attribution=stage_attribution,
        regression_source=regression_source,
        pattern_match=pattern_match,
        pattern_confidence=pattern_confidence,
        steps_taken=steps,
        total_traces=total,
    )


def _output_human(result: BisectResult, total_traces: int):
    """Human-readable output."""
    click.echo()
    click.secho("Regression Identified", fg='red', bold=True)
    click.echo("=" * 55)

    # Transition point
    click.echo()
    click.echo(f"  Last good:  {result.last_good.name}")
    click.echo(f"  First bad:  {result.first_bad.name}")

    # Extract commit info from filenames if present
    good_match = re.search(r'([a-f0-9]{7,40})', result.last_good.name)
    bad_match = re.search(r'([a-f0-9]{7,40})', result.first_bad.name)

    if good_match and bad_match:
        click.echo()
        click.echo(f"  Commits: {good_match.group(1)[:8]} -> {bad_match.group(1)[:8]}")

    # Impact
    click.echo()
    click.secho("Impact:", bold=True)

    p99 = result.regression_delta.get('p99', {})
    click.echo(
        f"  P99: {p99.get('before', 0):.0f}ns -> {p99.get('after', 0):.0f}ns "
        f"({p99.get('delta_pct', 0):+.1f}%)"
    )

    # Stage attribution
    if result.stage_attribution:
        click.echo()
        click.secho("Stage Attribution:", bold=True)
        click.echo("  +---------------------------------------------------------+")
        click.echo("  | Stage      Before    After     Delta    Share           |")
        click.echo("  +---------------------------------------------------------+")

        total_delta = sum(
            s.get('delta_ns', 0)
            for s in result.stage_attribution.values()
        )

        for stage, data in result.stage_attribution.items():
            share = (data['delta_ns'] / total_delta * 100) if total_delta > 0 else 0
            bar = "#" * int(share / 5) if share > 0 else ""
            marker = " <- SOURCE" if stage == result.regression_source else ""

            click.echo(
                f"  | {stage.capitalize():<10} {data['before']:>6.0f}ns  "
                f"{data['after']:>6.0f}ns  {data['delta_pct']:>+6.1f}%  "
                f"{bar:<6}{marker:<10}|"
            )

        click.echo("  +---------------------------------------------------------+")

    # Pattern match
    if result.pattern_match:
        click.echo()
        click.secho("Pattern Match:", bold=True)
        click.echo(
            f"  {result.pattern_match} "
            f"({result.pattern_confidence:.0%} confidence)"
        )

    # Suggested action
    click.echo()
    click.secho("Suggested Action:", bold=True)
    click.echo(f"  Run 'sentinel-hft prescribe {result.first_bad}' for fix options")
    click.echo()


def _output_json(result: BisectResult):
    """JSON output."""
    output = {
        "last_good": str(result.last_good),
        "first_bad": str(result.first_bad),
        "regression_delta": result.regression_delta,
        "stage_attribution": result.stage_attribution,
        "regression_source": result.regression_source,
        "pattern_match": result.pattern_match,
        "pattern_confidence": result.pattern_confidence,
        "steps_taken": result.steps_taken,
        "total_traces": result.total_traces,
    }

    print(json.dumps(output, indent=2))
