"""
Self-benchmark history and trends.
"""

import json
from pathlib import Path

import click

from ..benchmark.history import BenchmarkHistory


@click.group()
def benchmark():
    """Manage benchmark history and baselines."""
    pass


@benchmark.command()
@click.argument('trace_file', type=click.Path(exists=True))
@click.option('--tag', '-t', multiple=True, help='Add tags')
@click.option('--name', help='Baseline name (implies --baseline)')
@click.option('--baseline', is_flag=True, help='Mark as baseline')
def record(trace_file, tag, name, baseline):
    """
    Record a benchmark snapshot.

    Examples:

    \b
      sentinel-hft benchmark record traces.bin
      sentinel-hft benchmark record traces.bin --tag release --tag v2.3.0
      sentinel-hft benchmark record traces.bin --name pre-refactor
    """
    from ..streaming import StreamingAnalyzer, TraceFormat

    # Analyze trace
    analyzer = StreamingAnalyzer()
    format_detector = TraceFormat()

    path = Path(trace_file)
    if path.suffix == '.jsonl':
        with open(path) as f:
            for line in f:
                event = json.loads(line)
                analyzer.process_event(event)
    else:
        fmt = format_detector.detect(path)
        with open(path, 'rb') as f:
            if fmt.has_header:
                f.seek(fmt.header_size)
            while True:
                data = f.read(fmt.record_size)
                if not data or len(data) < fmt.record_size:
                    break
                event = fmt.parse_record(data)
                analyzer.process_event(event)

    analysis = analyzer.get_summary()

    # Build tags
    tags = list(tag)
    if name or baseline:
        tags.append('baseline')
    if name:
        tags.append(name)

    # Record
    history = BenchmarkHistory()
    snapshot = history.record(
        analysis,
        tags=tags,
        trace_file=trace_file,
    )

    click.echo(f"+ Recorded benchmark snapshot")
    click.echo(f"  P99: {snapshot.p99:.0f}ns")
    click.echo(f"  Timestamp: {snapshot.timestamp}")
    if tags:
        click.echo(f"  Tags: {', '.join(tags)}")


@benchmark.command()
@click.option('--days', default=90, help='Days of history')
@click.option('--metric', default='p99', help='Metric to show')
def history(days, metric):
    """
    Show benchmark history with trend.

    Examples:

    \b
      sentinel-hft benchmark history
      sentinel-hft benchmark history --days 30 --metric p50
    """
    hist = BenchmarkHistory()
    snapshots = hist.get_range(days)

    if not snapshots:
        click.echo("No benchmark history found.")
        click.echo("Record with: sentinel-hft benchmark record traces.bin")
        return

    click.echo()
    click.secho(f"Benchmark History (last {days} days)", bold=True)
    click.echo("=" * 55)

    # Current stats
    latest = snapshots[-1]
    values = [getattr(s, metric) for s in snapshots]

    click.echo()
    click.echo(f"  Current {metric.upper()}: {getattr(latest, metric):.0f}ns")
    click.echo(f"  {days}-day average: {sum(values)/len(values):.0f}ns")
    click.echo(f"  Best: {min(values):.0f}ns")
    click.echo(f"  Worst: {max(values):.0f}ns")

    # Stability score
    stability = hist.calculate_stability_score(min(days, 30))

    click.echo()
    click.secho(f"  Stability Score: {stability.score}/100",
                fg='green' if stability.score >= 70 else 'yellow' if stability.score >= 50 else 'red',
                bold=True)
    click.echo(f"  Trend: {stability.trend}")
    click.echo(f"  {stability.summary}")

    # ASCII chart
    click.echo()
    click.echo(_ascii_chart(snapshots, metric))

    # Recent snapshots
    click.echo()
    click.echo("Recent snapshots:")
    for snap in snapshots[-5:]:
        date = snap.timestamp[:10]
        commit = snap.commit[:8] if snap.commit else "unknown"
        tags = ", ".join(snap.tags) if snap.tags else ""
        click.echo(f"  {date}  {commit}  {getattr(snap, metric):.0f}ns  {tags}")


@benchmark.command()
@click.argument('baseline_name')
@click.argument('trace_file', type=click.Path(exists=True))
def compare(baseline_name, trace_file):
    """
    Compare trace against a named baseline.

    Examples:

    \b
      sentinel-hft benchmark compare v2.3.0 current.bin
      sentinel-hft benchmark compare pre-refactor traces.bin
    """
    from ..streaming import StreamingAnalyzer, TraceFormat

    hist = BenchmarkHistory()
    baseline = hist.get_baseline(baseline_name)

    if not baseline:
        click.secho(f"Baseline '{baseline_name}' not found", fg='red')
        click.echo("\nAvailable baselines:")
        for snap in hist.get_all_baselines():
            names = [t for t in snap.tags if t != 'baseline']
            click.echo(f"  {', '.join(names)} ({snap.timestamp[:10]})")
        return

    # Analyze current
    analyzer = StreamingAnalyzer()
    format_detector = TraceFormat()

    path = Path(trace_file)
    if path.suffix == '.jsonl':
        with open(path) as f:
            for line in f:
                event = json.loads(line)
                analyzer.process_event(event)
    else:
        fmt = format_detector.detect(path)
        with open(path, 'rb') as f:
            if fmt.has_header:
                f.seek(fmt.header_size)
            while True:
                data = f.read(fmt.record_size)
                if not data or len(data) < fmt.record_size:
                    break
                event = fmt.parse_record(data)
                analyzer.process_event(event)

    current = analyzer.get_summary()

    # Compare
    click.echo()
    click.secho(f"Comparing against baseline: {baseline_name}", bold=True)
    click.echo(f"Baseline date: {baseline.timestamp[:10]}")
    click.echo()

    latency = current.get('latency', {})
    metrics = [
        ('P50', baseline.p50, latency.get('p50', 0)),
        ('P90', baseline.p90, latency.get('p90', 0)),
        ('P99', baseline.p99, latency.get('p99', 0)),
        ('P99.9', baseline.p999, latency.get('p999', 0)),
    ]

    for name, base_val, curr_val in metrics:
        delta = (curr_val - base_val) / base_val * 100 if base_val > 0 else 0

        if delta < -5:
            indicator = click.style(f"{delta:+.1f}% +", fg='green')
        elif delta > 10:
            indicator = click.style(f"{delta:+.1f}% x", fg='red')
        else:
            indicator = f"{delta:+.1f}%"

        click.echo(f"  {name:<6} {base_val:>6.0f}ns -> {curr_val:>6.0f}ns  {indicator}")


@benchmark.command()
def baselines():
    """List all named baselines."""
    hist = BenchmarkHistory()
    all_baselines = hist.get_all_baselines()

    if not all_baselines:
        click.echo("No baselines recorded.")
        click.echo("Create one with: sentinel-hft benchmark record traces.bin --name my-baseline")
        return

    click.echo()
    click.secho("Named Baselines", bold=True)
    click.echo("=" * 55)
    click.echo()

    for snap in all_baselines:
        names = [t for t in snap.tags if t != 'baseline']
        name = ', '.join(names) if names else 'unnamed'
        click.echo(f"  {name:<20} {snap.timestamp[:10]}  P99: {snap.p99:.0f}ns")


@benchmark.command()
@click.option('--confirm', is_flag=True, help='Confirm deletion')
def clear(confirm):
    """Clear all benchmark history."""
    if not confirm:
        click.echo("This will delete all benchmark history.")
        click.echo("Run with --confirm to proceed.")
        return

    hist = BenchmarkHistory()
    hist.clear_history()
    click.echo("Benchmark history cleared.")


def _ascii_chart(snapshots, metric, width=50, height=8):
    """Generate ASCII chart of metric over time."""
    values = [getattr(s, metric) for s in snapshots]

    if not values:
        return ""

    min_val = min(values)
    max_val = max(values)
    range_val = max_val - min_val or 1

    lines = []
    lines.append(f"  {max_val:.0f} |")

    # Normalize and plot
    for row in range(height - 1, -1, -1):
        threshold = min_val + (range_val * row / height)
        line = "       |"

        step = max(1, len(values) // width)
        for i in range(0, len(values), step):
            val = values[i]
            if val >= threshold:
                line += "#"
            else:
                line += " "

        lines.append(line)

    lines.append(f"  {min_val:.0f} +" + "-" * min(width, len(values) // max(1, len(values) // width)))

    if len(snapshots) >= 2:
        lines.append(f"       {snapshots[0].timestamp[:10]}{' ' * 20}{snapshots[-1].timestamp[:10]}")

    return "\n".join(lines)
