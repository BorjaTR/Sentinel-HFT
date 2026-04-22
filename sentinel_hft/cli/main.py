"""
Sentinel-HFT CLI.

Three modes:
- analyze: Batch analysis of trace files
- regression: CI mode for pass/fail testing
- live: Continuous monitoring
"""

import json
import sys
import time
from pathlib import Path
from typing import Optional
from enum import Enum

try:
    import typer
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    typer = None

from ..config import SentinelConfig, load_config, generate_default_config
from ..formats.reader import TraceReader
from ..streaming.analyzer import StreamingMetrics, StreamingConfig
from ..core.report import AnalysisReport, ReportStatus
from ..core.evidence import EvidenceBundle, TraceEvidence


__version__ = "2.2.0"


if HAS_RICH:
    app = typer.Typer(
        name="sentinel-hft",
        help="Latency verification for FPGA trading",
        add_completion=False,
    )
    console = Console()
else:
    app = None
    console = None


class OutputFormat(str, Enum):
    json = "json"
    table = "table"


def _print_summary(metrics: dict, duration: float, count: int):
    """Print summary table."""
    if not HAS_RICH:
        print(f"Records: {count}")
        lat = metrics.get('latency', {})
        print(f"P99: {lat.get('p99_cycles', 0)} cycles")
        return

    console.print()
    table = Table(title="Summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")

    lat = metrics.get('latency', {})
    table.add_row("Records", f"{count:,}")
    table.add_row("P50", f"{lat.get('p50_cycles', 0)} cycles")
    table.add_row("P99", f"{lat.get('p99_cycles', 0)} cycles")
    table.add_row("P99.9", f"{lat.get('p999_cycles', 0)} cycles")
    table.add_row("Mean", f"{lat.get('mean_cycles', 0):.2f} cycles")
    table.add_row("Min", f"{lat.get('min_cycles', 0)} cycles")
    table.add_row("Max", f"{lat.get('max_cycles', 0)} cycles")

    drops = metrics.get('drops', {})
    table.add_row("Drops", str(drops.get('total_dropped', 0)))
    table.add_row("Drop Rate", f"{drops.get('drop_rate', 0):.4%}")

    if duration > 0:
        table.add_row("Duration", f"{duration:.2f}s")
        table.add_row("Throughput", f"{count/duration:,.0f}/s")

    console.print(table)


def _format_table(report: AnalysisReport) -> str:
    """Format report as table."""
    lat = report.latency
    lines = [
        "METRIC          VALUE",
        "------          -----",
        f"P50             {lat.p50_cycles} cycles",
        f"P99             {lat.p99_cycles} cycles",
        f"P99.9           {lat.p999_cycles} cycles",
        f"Mean            {lat.mean_cycles:.2f} cycles",
        f"Count           {lat.count}",
        f"Status          {report.status.value.upper()}",
    ]
    return '\n'.join(lines)


if HAS_RICH:
    # === ANALYZE COMMAND ===

    @app.command()
    def analyze(
        trace_file: Path = typer.Argument(..., help="Trace file path", exists=True),
        output: Optional[Path] = typer.Option(None, "-o", "--output", help="Output file"),
        format: OutputFormat = typer.Option(OutputFormat.json, "-f", "--format"),
        config_path: Optional[Path] = typer.Option(None, "-c", "--config"),
        include_evidence: bool = typer.Option(False, "--evidence", help="Include evidence bundle"),
        quiet: bool = typer.Option(False, "-q", "--quiet"),
    ):
        """Analyze a trace file and generate a report."""
        cfg = load_config(config_path)

        if not quiet:
            console.print(f"[bold blue]Sentinel-HFT v{__version__}[/]")
            console.print(f"Analyzing: {trace_file}")

        start = time.time()

        try:
            trace_info = TraceReader.open(trace_file)
        except Exception as e:
            console.print(f"[red]Error:[/] {e}")
            raise typer.Exit(1)

        if trace_info.header:
            cfg.clock.frequency_mhz = trace_info.header.clock_mhz
            if not quiet:
                console.print(f"Clock: {cfg.clock.frequency_mhz} MHz")
                console.print(f"Format: v{trace_info.header.version}")

        streaming_config = StreamingConfig(clock_hz=cfg.clock.frequency_hz)
        metrics = StreamingMetrics(streaming_config)

        count = 0
        if not quiet:
            with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
                task = progress.add_task("Processing...", total=None)
                for trace in TraceReader.read(trace_info):
                    metrics.add(trace)
                    count += 1
                    if count % 100000 == 0:
                        progress.update(task, description=f"Processed {count:,}...")
        else:
            for trace in TraceReader.read(trace_info):
                metrics.add(trace)
                count += 1

        duration = time.time() - start

        # Build report
        snapshot = metrics.snapshot()

        report = AnalysisReport(
            source_file=str(trace_file),
            source_format='sentinel' if trace_info.has_header else 'legacy',
            source_format_version=trace_info.header.version if trace_info.header else None,
            clock_frequency_mhz=cfg.clock.frequency_mhz,
        )

        # Populate from snapshot
        lat = snapshot.get('latency', {})
        report.latency.count = lat.get('count', 0)
        report.latency.mean_cycles = lat.get('mean_cycles', 0.0)
        report.latency.stddev_cycles = lat.get('stddev_cycles', 0.0)
        report.latency.min_cycles = lat.get('min_cycles', 0)
        report.latency.max_cycles = lat.get('max_cycles', 0)
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

        report.compute_status(
            p99_warning=cfg.thresholds.p99_warning,
            p99_error=cfg.thresholds.p99_error,
            p99_critical=cfg.thresholds.p99_critical,
        )
        report.populate_ns_values()

        if format == OutputFormat.json:
            output_text = report.to_json(indent=2)
        else:
            output_text = _format_table(report)

        if output:
            output.write_text(output_text)
            if not quiet:
                console.print(f"[green]Written to:[/] {output}")
        else:
            console.print(output_text)

        if not quiet:
            _print_summary(snapshot, duration, count)

        # Exit with error if critical
        if report.status == ReportStatus.CRITICAL:
            raise typer.Exit(2)
        elif report.status == ReportStatus.ERROR:
            raise typer.Exit(1)


    # === REGRESSION COMMAND ===

    @app.command()
    def regression(
        current: Path = typer.Argument(..., help="Current metrics JSON", exists=True),
        baseline: Path = typer.Argument(..., help="Baseline metrics JSON", exists=True),
        max_p99_regression: float = typer.Option(10.0, "--max-p99-regression", help="Max allowed P99 regression %"),
        fail_on_drops: bool = typer.Option(False, "--fail-on-drops", help="Fail if drops detected"),
        output: Optional[Path] = typer.Option(None, "-o", "--output", help="Output diff file"),
        slack_webhook: Optional[str] = typer.Option(None, "--slack-webhook", envvar="SENTINEL_SLACK_WEBHOOK", help="Slack webhook URL (Pro)"),
        slack_channel: Optional[str] = typer.Option("#alerts", "--slack-channel", help="Slack channel for alerts"),
    ):
        """
        Compare current metrics against baseline.

        Exit codes: 0=pass, 1=fail

        Pro Feature: Add --slack-webhook to get alerts on regressions.
        """
        try:
            current_data = json.loads(current.read_text())
            baseline_data = json.loads(baseline.read_text())
        except Exception as e:
            console.print(f"[red]Error loading metrics:[/] {e}")
            raise typer.Exit(1)

        # Handle nested structure
        if 'latency' not in current_data and 'metrics' in current_data:
            current_data = current_data['metrics']
        if 'latency' not in baseline_data and 'metrics' in baseline_data:
            baseline_data = baseline_data['metrics']

        current_p99 = current_data.get('latency', {}).get('p99_cycles', 0)
        baseline_p99 = baseline_data.get('latency', {}).get('p99_cycles', 0)
        current_drops = current_data.get('drops', {}).get('total_drops', 0)

        if baseline_p99 > 0:
            regression_pct = (current_p99 - baseline_p99) / baseline_p99 * 100
        else:
            regression_pct = 0 if current_p99 == 0 else 100

        # Get additional metrics
        current_p50 = current_data.get('latency', {}).get('p50_cycles', 0)
        baseline_p50 = baseline_data.get('latency', {}).get('p50_cycles', 0)
        current_p999 = current_data.get('latency', {}).get('p999_cycles', 0)
        baseline_p999 = baseline_data.get('latency', {}).get('p999_cycles', 0)
        baseline_drops = baseline_data.get('drops', {}).get('total_drops', 0)

        # Calculate all deltas
        def calc_delta(curr, base):
            if base > 0:
                return (curr - base) / base * 100
            return 0 if curr == 0 else 100

        p50_delta = calc_delta(current_p50, baseline_p50)
        p999_delta = calc_delta(current_p999, baseline_p999)

        diff = {
            'p50': {'baseline': baseline_p50, 'current': current_p50, 'change_percent': round(p50_delta, 2)},
            'p99': {'baseline': baseline_p99, 'current': current_p99, 'change_percent': round(regression_pct, 2)},
            'p999': {'baseline': baseline_p999, 'current': current_p999, 'change_percent': round(p999_delta, 2)},
            'drops': {'baseline': baseline_drops, 'current': current_drops},
        }

        # Print report header
        console.print()
        console.print(Panel.fit("[bold]REGRESSION REPORT[/]", border_style="blue"))
        console.print()

        # Helper to format metric line with arrow and emoji
        def format_metric(name: str, baseline: float, current: float, delta: float, threshold: float = None, unit: str = "ns"):
            arrow = "→"
            if threshold is not None:
                if delta > threshold:
                    status = "[red]🔴 REGRESS[/]"
                elif delta > threshold * 0.5:
                    status = "[yellow]⚠️  WARN[/]"
                else:
                    status = "[green]✅ OK[/]"
            else:
                if delta > 0:
                    status = "[yellow]↑[/]"
                elif delta < 0:
                    status = "[green]↓[/]"
                else:
                    status = "[dim]=[/]"

            delta_color = "red" if delta > 0 else "green" if delta < 0 else "dim"
            return f"  {name:<6} {baseline:>6.0f}{unit} {arrow} {current:>6.0f}{unit}  [{delta_color}]({delta:+.1f}%)[/]  {status}"

        # Print metrics with nice format
        console.print(format_metric("P50", baseline_p50, current_p50, p50_delta, threshold=max_p99_regression))
        console.print(format_metric("P99", baseline_p99, current_p99, regression_pct, threshold=max_p99_regression))
        console.print(format_metric("P99.9", baseline_p999, current_p999, p999_delta, threshold=max_p99_regression * 1.5))

        # Drops line
        if current_drops > 0 or baseline_drops > 0:
            drop_status = "[red]🔴 DROPS[/]" if current_drops > baseline_drops else "[green]✅ OK[/]"
            console.print(f"  {'Drops':<6} {baseline_drops:>6}    →  {current_drops:>6}       {drop_status}")

        console.print()

        # Check pass/fail
        failed = False
        reasons = []

        if regression_pct > max_p99_regression:
            failed = True
            reasons.append(f"P99 regression {regression_pct:.1f}% exceeds {max_p99_regression}% threshold")

        if fail_on_drops and current_drops > 0:
            failed = True
            reasons.append(f"{current_drops} traces dropped")

        if output:
            output.write_text(json.dumps(diff, indent=2))

        # Send Slack alert on regression (Pro feature)
        if failed and slack_webhook:
            try:
                from ..exporters.slack import SlackAlerter
                alerter = SlackAlerter(webhook_url=slack_webhook, channel=slack_channel)
                alerter.send_regression_alert(
                    baseline_p99=baseline_p99,
                    current_p99=current_p99,
                    delta_pct=regression_pct,
                )
                console.print(f"[green]✓[/] Slack alert sent to {slack_channel}")
            except Exception as e:
                console.print(f"[yellow]⚠[/] Slack alert failed: {e}")
        elif failed and not slack_webhook:
            # Suggest Slack for free users
            try:
                from ..licensing import check_feature
                if not check_feature("slack_alerts"):
                    console.print()
                    console.print("[dim]💡 Tip: Get Slack alerts on regressions with Pro[/]")
                    console.print("[dim]   → sentinel-hft.com/pricing[/]")
            except ImportError:
                pass

        # Final verdict
        if failed:
            console.print()
            console.print("[bold red]━━━ FAILED ━━━[/]")
            for r in reasons:
                console.print(f"  [red]✗[/] {r}")
            console.print()
            raise typer.Exit(1)
        else:
            console.print("[bold green]━━━ PASSED ━━━[/]")
            console.print()
            raise typer.Exit(0)


    # === LIVE COMMAND ===

    @app.command()
    def live(
        watch: Optional[Path] = typer.Option(None, "--watch", "-w", help="Directory to watch"),
        udp_port: Optional[int] = typer.Option(None, "--udp-port", help="UDP port for traces"),
        prometheus_port: int = typer.Option(9090, "--prometheus-port", help="Prometheus metrics port"),
        config_path: Optional[Path] = typer.Option(None, "-c", "--config"),
    ):
        """Run continuous monitoring."""
        cfg = load_config(config_path)

        console.print(f"[bold blue]Sentinel-HFT v{__version__} - Live Mode[/]")

        # Start Prometheus exporter
        prom = None
        try:
            from ..exporters.prometheus import PrometheusExporter
            prom = PrometheusExporter(port=prometheus_port)
            prom.start()
            console.print(f"[green]Prometheus:[/] http://0.0.0.0:{prometheus_port}/metrics")
        except Exception as e:
            console.print(f"[yellow]Prometheus disabled:[/] {e}")

        streaming_config = StreamingConfig(clock_hz=cfg.clock.frequency_hz)
        metrics = StreamingMetrics(streaming_config)

        def on_traces(traces):
            for trace in traces:
                metrics.add(trace)
            if prom and metrics.tx_count % 10000 == 0:
                prom.update_from_snapshot(metrics.snapshot())

        if udp_port:
            console.print(f"[blue]UDP port:[/] {udp_port}")
            try:
                from ..collectors.udp_collector import UDPCollector
                collector = UDPCollector(port=udp_port)
                collector.start()
                console.print("[green]Listening for UDP traces...[/]")
                try:
                    while True:
                        time.sleep(1)
                        if prom:
                            prom.update_from_snapshot(metrics.snapshot())
                except KeyboardInterrupt:
                    collector.stop()
                    console.print("\n[yellow]Stopped[/]")
            except ImportError as e:
                console.print(f"[red]UDP collector not available:[/] {e}")
                raise typer.Exit(1)
        elif watch:
            console.print(f"[blue]Watching:[/] {watch}")
            console.print("[yellow]File watcher not implemented yet - use --udp-port instead[/]")
            raise typer.Exit(1)
        else:
            console.print("[red]Specify --watch or --udp-port[/]")
            raise typer.Exit(1)


    # === CONFIG COMMAND ===

    @app.command("config")
    def config_cmd(
        action: str = typer.Argument(..., help="Action: init|validate|dump"),
        path: Optional[Path] = typer.Argument(None, help="Config file path"),
    ):
        """Configuration management."""
        if action == "init":
            console.print(generate_default_config())

        elif action == "validate":
            if not path:
                console.print("[red]Path required for validate[/]")
                raise typer.Exit(1)
            try:
                cfg = SentinelConfig.load(path)
                errors = cfg.validate()
                if errors:
                    console.print("[red]Invalid configuration:[/]")
                    for e in errors:
                        console.print(f"  - {e}")
                    raise typer.Exit(1)
                console.print(f"[green]Valid:[/] {path}")
            except Exception as e:
                console.print(f"[red]Error:[/] {e}")
                raise typer.Exit(1)

        elif action == "dump":
            cfg = SentinelConfig.load(path) if path else load_config()
            console.print(cfg.redacted().to_yaml())

        else:
            console.print(f"[red]Unknown action:[/] {action}")
            console.print("Valid actions: init, validate, dump")
            raise typer.Exit(1)


    # === EXPLAIN COMMAND ===

    @app.command()
    def explain(
        trace_file: Path = typer.Argument(..., help="Trace file path", exists=True),
        output: Optional[Path] = typer.Option(None, "-o", "--output", help="Write explanation to file (markdown)"),
        ai_backend: str = typer.Option("auto", "--ai-backend", help="Backend: auto|deterministic|ollama|anthropic"),
        ollama_model: str = typer.Option("llama3.1:8b", "--ollama-model", help="Ollama model name"),
        ollama_host: str = typer.Option("http://localhost:11434", "--ollama-host", help="Ollama server URL"),
        quiet: bool = typer.Option(False, "-q", "--quiet"),
    ):
        """Explain a trace file — human-readable RCA from the selected AI backend.

        Default backend is ``deterministic`` (no network, no LLM). Set
        ``--ai-backend ollama`` for a local LLM, or ``--ai-backend anthropic``
        to explicitly opt in to the Claude API.
        """
        # Imports kept local so the CLI still loads if ``ai`` extras are absent.
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

        try:
            from ai.explainer import Explainer, ExplanationConfig
            from ai.fact_extractor import FactExtractor
            from ai.pattern_detector import PatternDetector
        except ImportError as e:
            console.print(f"[red]AI module unavailable:[/] {e}")
            raise typer.Exit(1)

        cfg = load_config(None)
        trace_info = TraceReader.open(trace_file)
        if trace_info.header:
            cfg.clock.frequency_mhz = trace_info.header.clock_mhz

        streaming_config = StreamingConfig(clock_hz=cfg.clock.frequency_hz)
        metrics = StreamingMetrics(streaming_config)
        for trace in TraceReader.read(trace_info):
            metrics.add(trace)

        snapshot = metrics.snapshot()

        # Lightweight adapter: FactExtractor expects objects with .latency etc.
        class _Shim:
            def __init__(self, snap):
                lat = snap.get('latency', {})
                tp = snap.get('throughput', {})
                self.latency = type('L', (), {
                    'count': lat.get('count', 0),
                    'p50_cycles': lat.get('p50_cycles', 0),
                    'p99_cycles': lat.get('p99_cycles', 0),
                    'p999_cycles': lat.get('p999_cycles', 0),
                    'mean_cycles': lat.get('mean_cycles', 0.0),
                    'std_cycles': lat.get('stddev_cycles', 0.0),
                })()
                self.throughput = type('T', (), {
                    'transactions_per_second': tp.get('tps', 0.0),
                    'max_burst_size': tp.get('max_burst', 0),
                })()
                self.anomalies = type('A', (), {'count': 0, 'anomalies': []})()
        shim = _Shim(snapshot)

        ex_cfg = ExplanationConfig(
            backend=ai_backend,
            ollama_model=ollama_model,
            ollama_host=ollama_host,
            clock_period_ns=1e9 / cfg.clock.frequency_hz,
        )
        explainer = Explainer(config=ex_cfg)

        fe = FactExtractor(clock_period_ns=ex_cfg.clock_period_ns)
        # No raw trace list kept — we summarise from streaming snapshot. Pass an
        # empty PatternDetectionResult; the FactExtractor tolerates missing
        # patterns and the backends only depend on the fact lines they see.
        from ai.pattern_detector import PatternDetectionResult
        empty_patterns = PatternDetectionResult(
            patterns=[], analysis_window_cycles=0, total_transactions=snapshot.get('traces', 0) or 0,
        )
        facts = fe.extract(shim, empty_patterns)
        expl = explainer.explain(facts)

        if not quiet:
            console.print(Panel.fit(
                f"[bold blue]Sentinel-HFT explain[/]\n"
                f"Backend: [cyan]{expl.backend}[/]"
                + (f" (model: {expl.model})" if expl.model else "")
                + (" [green]offline[/]" if expl.offline else " [yellow]network[/]"),
                border_style="blue",
            ))
            console.print(expl.to_markdown())

        if output:
            output.write_text(expl.to_markdown())
            if not quiet:
                console.print(f"[green]✓[/] Wrote {output}")


    # === ONCHAIN COMMAND ===

    @app.command()
    def onchain(
        action: str = typer.Argument(..., help="One of: generate | analyze"),
        input_file: Optional[Path] = typer.Option(
            None, "-i", "--input", help="Input .onch file (analyze mode)"
        ),
        output_file: Optional[Path] = typer.Option(
            None, "-o", "--output",
            help="Output .onch file (generate) or JSON snapshot (analyze)",
        ),
        venue: str = typer.Option(
            "hyperliquid", "--venue",
            help="Venue: hyperliquid|solana|dydx_v4|lighter",
        ),
        count: int = typer.Option(10_000, "-n", "--count", help="Number of records"),
        seed: int = typer.Option(0, "--seed", help="Fixture seed"),
        symbol: Optional[str] = typer.Option(None, "--symbol", help="Trading symbol"),
        ai_backend: str = typer.Option(
            "auto", "--ai-backend",
            help="When analyzing, also run an RCA with this backend",
        ),
        quiet: bool = typer.Option(False, "-q", "--quiet"),
    ):
        """On-chain latency attribution (Hyperliquid/Solana/dYdX/Lighter).

        Two modes:

        * ``generate`` -- write a synthetic .onch trace with realistic 2026
          per-stage latencies for the chosen venue.
        * ``analyze``  -- read a .onch trace, compute per-stage quantiles,
          landed/rejected rates, and venue/action breakdowns. Optionally
          runs the AI explainer on top.
        """
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

        from ..onchain import OnchainMetrics, generate_fixture
        from ..onchain.analyzer import write_records

        action = action.lower()
        if action not in ("generate", "analyze"):
            console.print(f"[red]unknown action[/] {action!r}; expected generate|analyze")
            raise typer.Exit(2)

        if action == "generate":
            out = output_file or Path.cwd() / f"onchain_{venue}_n{count}.onch"
            n = write_records(out, generate_fixture(
                venue=venue, n=count, seed=seed, symbol=symbol,
            ))
            if not quiet:
                console.print(Panel.fit(
                    f"[bold blue]Generated on-chain fixture[/]\n"
                    f"venue  : [cyan]{venue}[/]\n"
                    f"records: {count}\n"
                    f"path   : {out}\n"
                    f"bytes  : {n:,}",
                    border_style="blue",
                ))
            return

        # analyze
        if not input_file:
            console.print("[red]analyze mode requires --input[/]")
            raise typer.Exit(2)

        metrics = OnchainMetrics()
        for rec in OnchainMetrics.iter_file(input_file):
            metrics.add(rec)
        snap = metrics.snapshot()

        if output_file:
            output_file.write_text(json.dumps(snap.to_dict(), indent=2))

        if quiet:
            return

        console.print(Panel.fit(
            f"[bold blue]On-chain analysis[/]  {input_file}",
            border_style="blue",
        ))
        tbl = Table(title="Per-stage latency")
        tbl.add_column("Stage")
        tbl.add_column("Count", justify="right")
        tbl.add_column("p50 (us)", justify="right")
        tbl.add_column("p99 (us)", justify="right")
        tbl.add_column("p99.9 (us)", justify="right")
        tbl.add_column("Max (us)", justify="right")
        for name in ("rpc", "quote", "sign", "submit", "inclusion"):
            s = snap.stages[name]
            tbl.add_row(
                name,
                f"{s.count:,}",
                f"{s.p50_ns/1e3:,.1f}",
                f"{s.p99_ns/1e3:,.1f}",
                f"{s.p999_ns/1e3:,.1f}",
                f"{s.max_ns/1e3:,.1f}",
            )
        tot = snap.total
        tbl.add_row(
            "[bold]TOTAL[/]",
            f"{tot.count:,}",
            f"{tot.p50_ns/1e6:,.2f}ms",
            f"{tot.p99_ns/1e6:,.2f}ms",
            f"{tot.p999_ns/1e6:,.2f}ms",
            f"{tot.max_ns/1e6:,.2f}ms",
        )
        ov = snap.overhead
        tbl.add_row(
            "[yellow]overhead[/]",
            f"{ov.count:,}",
            f"{ov.p50_ns/1e3:,.1f}",
            f"{ov.p99_ns/1e3:,.1f}",
            f"{ov.p999_ns/1e3:,.1f}",
            f"{ov.max_ns/1e3:,.1f}",
        )
        console.print(tbl)

        console.print(
            f"\nLanded: [green]{snap.total_landed:,}[/]"
            f" / Rejected: [red]{snap.total_rejected}[/]"
            f" / Timed out: [yellow]{snap.total_timed_out}[/]"
            f" / Reorged: {snap.total_reorged}"
            f" / landed rate: {snap.landed_rate():.3%}"
        )
        console.print(f"Venues: {snap.per_venue}  Actions: {snap.per_action}")

        # Optional: attach AI explanation.
        if ai_backend:
            try:
                from ai.explainer import Explainer, ExplanationConfig
                from ai.fact_extractor import Fact, FactSet
                from ai.pattern_detector import PatternDetectionResult

                # Hand-roll an on-chain FactSet: we keep the fact-shape the
                # Explainer expects but source from the on-chain snapshot.
                fs = FactSet()
                for name in ("rpc", "quote", "sign", "submit", "inclusion"):
                    s = snap.stages[name]
                    imp = "high" if s.p99_ns > 1e9 else "medium"
                    fs.add(Fact(category="latency", key=f"{name}_p99_ns",
                                value=int(s.p99_ns),
                                context=(
                                    f"{name}: p50={s.p50_ns/1e3:.1f}us "
                                    f"p99={s.p99_ns/1e3:.1f}us "
                                    f"p999={s.p999_ns/1e3:.1f}us"
                                ),
                                importance=imp))
                tot = snap.total
                fs.add(Fact(category="latency", key="total_p99_ns",
                            value=int(tot.p99_ns),
                            context=(
                                f"End-to-end p99 {tot.p99_ns/1e6:.1f}ms "
                                f"(p50 {tot.p50_ns/1e6:.1f}ms)"
                            ),
                            importance="high"))
                if snap.total_rejected:
                    fs.add(Fact(category="risk", key="rejected",
                                value=snap.total_rejected,
                                context=(
                                    f"{snap.total_rejected} rejected, "
                                    f"{snap.total_timed_out} timed out out of "
                                    f"{snap.total_records}"
                                ),
                                importance="high" if snap.total_rejected > 10 else "medium"))
                if snap.overhead.p99_ns > 1e6:  # > 1ms scheduler overhead p99
                    fs.add(Fact(category="anomaly", key="overhead",
                                value=int(snap.overhead.p99_ns),
                                context=(
                                    f"Scheduler/queue overhead p99 "
                                    f"{snap.overhead.p99_ns/1e3:.1f}us "
                                    f"(unaccounted-for time between stages)"
                                ),
                                importance="critical" if snap.overhead.p99_ns > 5e6 else "high"))

                ex_cfg = ExplanationConfig(backend=ai_backend)
                explainer = Explainer(config=ex_cfg)
                expl = explainer.explain(fs)
                console.print()
                console.print(Panel.fit(
                    f"[bold magenta]AI RCA ({expl.backend})[/]"
                    + (f" model={expl.model}" if expl.model else "")
                    + (" [green]offline[/]" if expl.offline else " [yellow]network[/]"),
                    border_style="magenta",
                ))
                console.print(expl.to_markdown())
            except Exception as e:
                console.print(f"[yellow]AI RCA skipped: {e}[/]")


    # === AUDIT COMMAND ===

    @app.command()
    def audit(
        action: str = typer.Argument(..., help="One of: generate | verify | dora"),
        positional_path: Optional[Path] = typer.Argument(
            None,
            help="Path to .aud file (verify/dora); equivalent to --input.",
            show_default=False,
        ),
        input_file: Optional[Path] = typer.Option(
            None, "-i", "--input", help="Input .aud file (verify/dora mode)"
        ),
        output_file: Optional[Path] = typer.Option(
            None, "-o", "--output",
            help="Output .aud (generate) or DORA JSON (dora)",
        ),
        count: int = typer.Option(100, "-n", "--count", help="Records to generate"),
        inject_kill_at: int = typer.Option(
            -1, "--inject-kill-at",
            help="Inject a kill-switch trip at this index (generate mode)",
        ),
        inject_reject_at: int = typer.Option(
            -1, "--inject-reject-at",
            help="Inject a hard rejection at this index (generate mode)",
        ),
        subject: str = typer.Option(
            "unspecified", "--subject",
            help="LEI / firm identifier for DORA bundle",
        ),
        environment: str = typer.Option(
            "unspecified", "--environment",
            help="Environment label for DORA bundle (prod/uat/sim)",
        ),
        quiet: bool = typer.Option(False, "-q", "--quiet"),
    ):
        """Host-hashed audit trail for the risk gate.

        The RTL is a pure *serialiser* (monotonic ``seq_no`` + in-band
        overflow marker). BLAKE2b chain construction and walk happens
        here on the host; any byte flip, dropped record, or reordered
        insertion surfaces as a chain break with the exact sequence
        number.

        Three modes:

        * ``generate`` -- produce a synthetic chained audit log
          (for demo/regression).
        * ``verify``   -- walk a .aud file and confirm the hash chain
          is intact. Exits non-zero if any break is found.
        * ``dora``     -- emit a DORA-aligned JSON evidence bundle
          from a .aud file (embeds verification result).
        """
        # A positional path is the ergonomic form; it mirrors --input.
        if positional_path is not None and input_file is None:
            input_file = positional_path
        elif positional_path is not None and input_file is not None:
            console.print("[red]pass either a positional path or --input, not both[/]")
            raise typer.Exit(2)
        from ..audit import (
            AuditLogger, RiskDecision, RejectReason,
            verify as audit_verify,
            build_bundle, dump_bundle,
            read_records, write_records,
        )

        action = action.lower()
        if action not in ("generate", "verify", "dora"):
            console.print(f"[red]unknown action[/] {action!r}; expected generate|verify|dora")
            raise typer.Exit(2)

        if action == "generate":
            log = AuditLogger()
            for i in range(count):
                d = RiskDecision(
                    timestamp_ns=1_713_600_000_000_000_000 + i * 1_000,
                    order_id=1000 + i, symbol_id=42,
                    quantity=100, price=50_000_00000000,
                    notional=5_000_000_00000000,
                    passed=True,
                    tokens_remaining=max(0, 100 - i),
                    position_after=100 * (i + 1),
                    notional_after=5_000_000 * (i + 1),
                )
                if i == inject_kill_at:
                    d.passed = False
                    d.reject_reason = int(RejectReason.KILL_SWITCH)
                    d.kill_triggered = True
                elif i == inject_reject_at:
                    d.passed = False
                    d.reject_reason = int(RejectReason.POSITION_LIMIT)
                log.log(d)

            out = output_file or Path.cwd() / f"audit_n{count}.aud"
            n = write_records(out, log.records)
            if not quiet:
                console.print(Panel.fit(
                    f"[bold blue]Generated audit log[/]\n"
                    f"records: {count}\n"
                    f"path   : {out}\n"
                    f"bytes  : {n:,}\n"
                    f"head   : {log.head_hash_lo.hex()}",
                    border_style="blue",
                ))
            return

        # verify / dora share input handling
        if not input_file:
            console.print("[red]this action requires --input[/]")
            raise typer.Exit(2)

        records = list(read_records(input_file))
        result = audit_verify(records)

        if action == "verify":
            if not quiet:
                status_colour = "green" if result.ok else "red"
                console.print(Panel.fit(
                    f"[bold {status_colour}]Chain {'OK' if result.ok else 'BROKEN'}[/]\n"
                    f"records  : {result.total_records}\n"
                    f"verified : {result.verified_records}\n"
                    f"breaks   : {len(result.breaks)}\n"
                    f"head hash: {result.head_hash_lo.hex() if result.head_hash_lo else '-'}",
                    border_style=status_colour,
                ))
                if result.breaks:
                    tbl = Table(title="Chain breaks")
                    tbl.add_column("seq_no", justify="right")
                    tbl.add_column("kind")
                    tbl.add_column("detail")
                    for b in result.breaks[:50]:
                        tbl.add_row(str(b.seq_no), b.kind.value, b.detail)
                    console.print(tbl)
            raise typer.Exit(0 if result.ok else 1)

        # dora
        out = output_file or Path.cwd() / "dora_bundle.json"
        head = dump_bundle(records, out, subject=subject, environment=environment)
        if not quiet:
            console.print(Panel.fit(
                f"[bold blue]DORA bundle written[/]\n"
                f"path     : {out}\n"
                f"records  : {len(records)}\n"
                f"head hash: {head}\n"
                f"chain ok : {'YES' if result.ok else 'NO'}",
                border_style="blue" if result.ok else "yellow",
            ))


    # === DERIBIT DEMO COMMAND ===

    @app.command()
    def deribit(
        action: str = typer.Argument("demo", help="One of: demo"),
        output_dir: Optional[Path] = typer.Option(
            None, "-o", "--output-dir",
            help="Directory for traces.sst / audit.aud / dora.json / summary.md",
        ),
        ticks: int = typer.Option(
            20_000, "-n", "--ticks",
            help="Number of synthetic Deribit ticks to consume",
        ),
        seed: int = typer.Option(1, "--seed", help="Fixture seed"),
        subject: str = typer.Option(
            "sentinel-hft-demo", "--subject",
            help="LEI / firm identifier for the DORA bundle",
        ),
        environment: str = typer.Option(
            "sim", "--environment",
            help="Environment label for the DORA bundle",
        ),
        inject_kill_at: Optional[int] = typer.Option(
            None, "--inject-kill-at",
            help="Force the kill switch to trip at this intent index",
        ),
        quiet: bool = typer.Option(False, "-q", "--quiet"),
    ):
        """Deribit LD4 tick-to-trade demo pipeline.

        Runs a seeded options/perps fixture through a full FPGA-shaped
        pipeline (parse -> book -> strategy -> risk gate -> audit) and
        writes four artifacts:

        * ``traces.sst``  -- v1.2 trace file with per-stage attribution
        * ``audit.aud``   -- tamper-evident hash-chained risk-gate log
        * ``dora.json``   -- DORA-aligned evidence bundle
        * ``summary.md``  -- human-readable run summary

        Latency numbers are cycle-accurate against a 100 MHz Alveo U55C
        target budget. The run is deterministic given the seed.
        """
        from ..deribit import run_demo

        action = action.lower()
        if action not in ("demo",):
            console.print(f"[red]unknown action[/] {action!r}; expected 'demo'")
            raise typer.Exit(2)

        out = output_dir or Path.cwd() / "out" / "deribit"

        arts = run_demo(
            ticks=ticks, seed=seed,
            output_dir=out,
            subject=subject, environment=environment,
            inject_kill_at=inject_kill_at,
        )

        if quiet:
            return

        console.print(Panel.fit(
            f"[bold blue]Deribit LD4 demo complete[/]\n"
            f"output     : {out}\n"
            f"ticks      : {arts.ticks_consumed:,}\n"
            f"intents    : {arts.intents_generated:,}\n"
            f"decisions  : {arts.decisions_logged:,}\n"
            f"passed     : {arts.passed:,}"
            f" ({arts.passed/max(1,arts.decisions_logged):.1%})\n"
            f"rejected   : {arts.rejected:,}\n"
            f"kill       : {'YES' if arts.kill_triggered else 'no'}\n"
            f"chain OK   : {'YES' if arts.chain_ok else 'NO'}\n"
            f"head hash  : {arts.head_hash_lo_hex}",
            border_style="blue" if arts.chain_ok else "red",
        ))

        tbl = Table(title="Wire-to-wire latency")
        tbl.add_column("Quantile", justify="right")
        tbl.add_column("ns", justify="right")
        tbl.add_column("us", justify="right")
        for name, v in (("p50", arts.p50_ns), ("p99", arts.p99_ns),
                        ("p99.9", arts.p999_ns), ("max", arts.max_ns)):
            tbl.add_row(name, f"{v:,.0f}", f"{v/1000:,.2f}")
        console.print(tbl)

        console.print(f"\nArtifacts: [cyan]{arts.trace_path.name}[/], "
                      f"[cyan]{arts.audit_path.name}[/], "
                      f"[cyan]{arts.dora_path.name}[/], "
                      f"[cyan]{arts.summary_path.name}[/]")


    # === HYPERLIQUID SUB-APP ===
    #
    # Five sub-commands mirroring the use-cases package:
    #
    #   sentinel-hft hl toxic-flow     adverse-selection + pre-gate block
    #   sentinel-hft hl kill-drill     vol-spike + kill-switch verify
    #   sentinel-hft hl latency        wire-to-wire attribution
    #   sentinel-hft hl daily-evidence 3-session DORA roll-up
    #   sentinel-hft hl dashboard      cover HTML linking whichever ran
    #   sentinel-hft hl collect        live HL WS capture (optional dep)
    #   sentinel-hft hl demo           run all four + dashboard

    hl_app = typer.Typer(
        name="hl",
        help="Hyperliquid use-case runners (toxic-flow / kill-drill / "
             "latency / daily-evidence / dashboard / collect).",
        add_completion=False,
    )
    app.add_typer(hl_app, name="hl")

    def _hl_summary_panel(title: str, arts, colour: str = "blue") -> None:
        border = colour if arts.chain_ok else "red"
        console.print(Panel.fit(
            f"[bold {colour}]{title}[/]\n"
            f"ticks      : {arts.ticks_consumed:,}\n"
            f"intents    : {arts.intents_generated:,}\n"
            f"decisions  : {arts.decisions_logged:,}\n"
            f"passed     : {arts.passed:,}\n"
            f"rejected   : {arts.rejected:,}\n"
            f"chain OK   : {'YES' if arts.chain_ok else 'NO'}\n"
            f"head hash  : {arts.head_hash_lo_hex}",
            border_style=border,
        ))
        tbl = Table(title="Wire-to-wire latency")
        tbl.add_column("Quantile", justify="right")
        tbl.add_column("ns", justify="right")
        tbl.add_column("us", justify="right")
        for name, v in (("p50", arts.p50_ns), ("p99", arts.p99_ns),
                        ("p99.9", arts.p999_ns), ("max", arts.max_ns)):
            tbl.add_row(name, f"{v:,.0f}", f"{v/1000:,.2f}")
        console.print(tbl)

    @hl_app.command("toxic-flow")
    def hl_toxic_flow(
        output_dir: Optional[Path] = typer.Option(
            None, "-o", "--output-dir",
            help="Directory for traces / audit / DORA / JSON / MD / HTML",
        ),
        ticks: int = typer.Option(30_000, "-n", "--ticks"),
        seed: int = typer.Option(7, "--seed"),
        taker_population: int = typer.Option(16, "--taker-population"),
        toxic_share: float = typer.Option(0.45, "--toxic-share"),
        benign_share: float = typer.Option(0.20, "--benign-share"),
        trade_prob: float = typer.Option(0.14, "--trade-prob"),
        subject: str = typer.Option(
            "sentinel-hft-hl-toxic-flow", "--subject"),
        environment: str = typer.Option("sim", "--environment"),
        quiet: bool = typer.Option(False, "-q", "--quiet"),
    ):
        """Toxic-flow adverse-selection scoring + pre-gate rejection demo."""
        from ..usecases import ToxicFlowConfig, run_toxic_flow

        out = output_dir or Path.cwd() / "out" / "hl" / "toxic_flow"
        cfg = ToxicFlowConfig(
            ticks=ticks, seed=seed, output_dir=out,
            subject=subject, environment=environment,
            taker_population=taker_population,
            toxic_share=toxic_share, benign_share=benign_share,
            trade_prob=trade_prob,
        )
        rep = run_toxic_flow(cfg)

        if quiet:
            return
        _hl_summary_panel("Hyperliquid toxic-flow demo complete",
                          rep.artifacts, colour="blue")
        console.print(
            f"\nToxic rejects    : [red]{rep.toxic_rejects:,}[/] "
            f"({rep.toxic_rejects/max(1,rep.intents)*100:.2f}% of intents)"
        )
        console.print(
            f"Wallets observed : {rep.taker_population}"
            f"   (TOXIC={rep.classified_toxic}, "
            f"NEUTRAL={rep.classified_neutral}, "
            f"BENIGN={rep.classified_benign})"
        )
        console.print(f"\nHTML : [cyan]{rep.html_path}[/]")
        console.print(f"JSON : [cyan]{rep.json_path}[/]")
        console.print(f"MD   : [cyan]{rep.md_path}[/]")

    @hl_app.command("kill-drill")
    def hl_kill_drill(
        output_dir: Optional[Path] = typer.Option(
            None, "-o", "--output-dir"),
        ticks: int = typer.Option(24_000, "-n", "--ticks"),
        seed: int = typer.Option(11, "--seed"),
        spike_at_tick: int = typer.Option(9_000, "--spike-at-tick"),
        spike_magnitude: float = typer.Option(
            0.02, "--spike-magnitude"),
        inject_kill_at_intent: int = typer.Option(
            25_500, "--inject-kill-at-intent"),
        slo_budget_ns: int = typer.Option(50_000_000, "--slo-budget-ns"),
        subject: str = typer.Option(
            "sentinel-hft-hl-kill-drill", "--subject"),
        environment: str = typer.Option("sim", "--environment"),
        quiet: bool = typer.Option(False, "-q", "--quiet"),
    ):
        """Vol-spike + kill-switch drill with tamper-evident transcript."""
        from ..usecases import KillDrillConfig, run_kill_drill

        out = output_dir or Path.cwd() / "out" / "hl" / "kill_drill"
        cfg = KillDrillConfig(
            ticks=ticks, seed=seed, output_dir=out,
            subject=subject, environment=environment,
            spike_at_tick=spike_at_tick,
            spike_magnitude=spike_magnitude,
            inject_kill_at_intent=inject_kill_at_intent,
            slo_budget_ns=slo_budget_ns,
        )
        rep = run_kill_drill(cfg)

        if quiet:
            return
        _hl_summary_panel("Hyperliquid kill-drill complete",
                          rep.artifacts, colour="blue")
        kill_line = (
            f"Kill triggered : [{'green' if rep.kill_triggered else 'yellow'}]"
            f"{'YES' if rep.kill_triggered else 'NO'}[/]"
        )
        if rep.kill_triggered and rep.kill_latency_ns is not None:
            slo_colour = "green" if rep.kill_latency_within_slo else "red"
            kill_line += (
                f"  kill latency=[{slo_colour}]{rep.kill_latency_ns:,} ns[/]"
                f" SLO={rep.config.slo_budget_ns:,} ns"
            )
        console.print("\n" + kill_line)
        console.print(
            f"Post-trip mismatch : "
            f"[{'red' if rep.rejects_after_kill_mismatch else 'green'}]"
            f"{rep.rejects_after_kill_mismatch}[/]"
        )
        console.print(f"\nHTML : [cyan]{rep.html_path}[/]")
        console.print(f"JSON : [cyan]{rep.json_path}[/]")

    @hl_app.command("latency")
    def hl_latency(
        output_dir: Optional[Path] = typer.Option(
            None, "-o", "--output-dir"),
        ticks: int = typer.Option(40_000, "-n", "--ticks"),
        seed: int = typer.Option(3, "--seed"),
        toxic_share: float = typer.Option(0.20, "--toxic-share"),
        benign_share: float = typer.Option(0.30, "--benign-share"),
        trade_prob: float = typer.Option(0.10, "--trade-prob"),
        enable_toxic_guard: bool = typer.Option(
            True, "--enable-toxic-guard/--no-toxic-guard"),
        slo_p99_ns: Optional[int] = typer.Option(
            None, "--slo-p99-ns",
            help="Override the auto-computed SLO p99 budget (ns).",
        ),
        subject: str = typer.Option(
            "sentinel-hft-hl-latency", "--subject"),
        environment: str = typer.Option("sim", "--environment"),
        quiet: bool = typer.Option(False, "-q", "--quiet"),
    ):
        """Wire-to-wire latency attribution with SLO check."""
        from ..usecases import LatencyConfig, run_latency

        out = output_dir or Path.cwd() / "out" / "hl" / "latency"
        cfg = LatencyConfig(
            ticks=ticks, seed=seed, output_dir=out,
            subject=subject, environment=environment,
            toxic_share=toxic_share, benign_share=benign_share,
            trade_prob=trade_prob,
            enable_toxic_guard=enable_toxic_guard,
            slo_p99_ns=slo_p99_ns,
        )
        rep = run_latency(cfg)

        if quiet:
            return
        _hl_summary_panel("Hyperliquid latency attribution complete",
                          rep.artifacts, colour="blue")
        slo_colour = ("red" if rep.slo_violations
                      else ("yellow" if rep.p99_ns > rep.slo_p99_ns * 0.9
                            else "green"))
        console.print(
            f"\nSLO p99 budget    : {rep.slo_p99_ns:,} ns"
            f"\nSLO violations    : [{slo_colour}]{rep.slo_violations:,}"
            f" ({rep.slo_violation_rate*100:.3f}%)[/]"
            f"\nBottleneck stage  : [yellow]{rep.bottleneck_stage}[/]"
        )

        tbl = Table(title="Per-stage latency (ns)")
        tbl.add_column("Stage")
        tbl.add_column("mean", justify="right")
        tbl.add_column("p50",  justify="right")
        tbl.add_column("p99",  justify="right")
        for stage in ("ingress", "core", "risk", "egress"):
            tbl.add_row(
                stage,
                f"{rep.stage_mean_ns.get(stage, 0):,.0f}",
                f"{rep.stage_p50_ns.get(stage, 0):,.0f}",
                f"{rep.stage_p99_ns.get(stage, 0):,.0f}",
            )
        console.print(tbl)
        console.print(f"\nHTML : [cyan]{rep.html_path}[/]")
        console.print(f"JSON : [cyan]{rep.json_path}[/]")

    @hl_app.command("daily-evidence")
    def hl_daily_evidence(
        output_dir: Optional[Path] = typer.Option(
            None, "-o", "--output-dir"),
        subject: str = typer.Option(
            "sentinel-hft-hl-daily", "--subject"),
        environment: str = typer.Option("sim", "--environment"),
        trading_date: str = typer.Option("2026-04-21", "--trading-date"),
        quiet: bool = typer.Option(False, "-q", "--quiet"),
    ):
        """Three-session DORA evidence roll-up bundle."""
        from ..usecases import DailyEvidenceConfig, run_daily_evidence

        out = output_dir or Path.cwd() / "out" / "hl" / "daily_evidence"
        cfg = DailyEvidenceConfig(
            output_dir=out,
            subject=subject,
            environment=environment,
            trading_date=trading_date,
        )
        rep = run_daily_evidence(cfg)

        if quiet:
            return

        colour = "blue" if rep.all_chains_ok else "red"
        console.print(Panel.fit(
            f"[bold {colour}]Hyperliquid daily evidence bundle[/]\n"
            f"output     : {out}\n"
            f"sessions   : {len(rep.sessions)}\n"
            f"records    : {rep.total_records:,}\n"
            f"passed     : {rep.total_passed:,}\n"
            f"rejected   : {rep.total_rejected:,}\n"
            f"toxic      : {rep.total_rejected_toxic:,}\n"
            f"kill evts  : {rep.total_kill_events:,}\n"
            f"chains OK  : {'YES' if rep.all_chains_ok else 'NO'}",
            border_style=colour,
        ))

        tbl = Table(title="Per-session breakdown")
        tbl.add_column("Label")
        tbl.add_column("Records",  justify="right")
        tbl.add_column("Passed",   justify="right")
        tbl.add_column("Rejected", justify="right")
        tbl.add_column("Toxic",    justify="right")
        tbl.add_column("Kill",     justify="right")
        tbl.add_column("Chain")
        tbl.add_column("Head lo")
        for s in rep.sessions:
            tbl.add_row(
                s.label,
                f"{s.record_count:,}",
                f"{s.passed:,}",
                f"{s.rejected:,}",
                f"{s.rejected_toxic:,}",
                f"{s.rejected_kill:,}",
                "[green]OK[/]" if s.chain_ok else "[red]FAIL[/]",
                s.head_hash_lo_hex,
            )
        console.print(tbl)

        console.print(f"\nHTML   : [cyan]{rep.html_path}[/]")
        console.print(f"Bundle : [cyan]{rep.bundle_path}[/]")
        console.print(f"JSON   : [cyan]{rep.json_path}[/]")

    @hl_app.command("dashboard")
    def hl_dashboard(
        root: Path = typer.Argument(
            ..., help="Output root directory to scan for use-case artifacts",
        ),
        out_path: Optional[Path] = typer.Option(
            None, "-o", "--output",
            help="Override dashboard.html output location",
        ),
        quiet: bool = typer.Option(False, "-q", "--quiet"),
    ):
        """Build the cover dashboard for whichever HL use-cases were run."""
        from ..usecases import build_dashboard

        written = build_dashboard(root, out_path=out_path)
        if quiet:
            return
        console.print(Panel.fit(
            f"[bold blue]Dashboard written[/]\n"
            f"path : {written}\n"
            f"root : {root}",
            border_style="blue",
        ))

    @hl_app.command("collect")
    def hl_collect(
        out_path: Path = typer.Option(
            Path("out/hl/live_capture.hltk"), "-o", "--out",
            help="Destination capture file (binary HLTK)",
        ),
        symbols: str = typer.Option(
            "BTC,ETH,SOL", "--symbols",
            help="Comma-separated HL coins (e.g. BTC,ETH,SOL)",
        ),
        duration_s: float = typer.Option(
            30.0, "--duration-s",
            help="Seconds to capture for",
        ),
        max_events: Optional[int] = typer.Option(
            None, "--max-events",
            help="Hard cap on records written",
        ),
        url: Optional[str] = typer.Option(
            None, "--url",
            help="Override WS URL (for local mock)",
        ),
        quiet: bool = typer.Option(False, "-q", "--quiet"),
    ):
        """Capture live HL BBO + trades to a binary fixture (requires websockets).

        Reads public Hyperliquid WS feeds for the configured symbols and writes
        a deterministic binary capture that can be replayed through the same
        :class:`HyperliquidRunner` as the synthetic fixture.
        """
        try:
            from ..hyperliquid.collector import collect_to_file, HL_WS_URL
        except Exception as exc:
            console.print(f"[red]HL collector unavailable:[/] {exc}")
            raise typer.Exit(1)

        sym_list = [s.strip().upper() for s in symbols.split(",")
                    if s.strip()]
        if not sym_list:
            console.print("[red]at least one symbol is required[/]")
            raise typer.Exit(2)

        out_path.parent.mkdir(parents=True, exist_ok=True)

        url_use = url or HL_WS_URL
        if not quiet:
            console.print(Panel.fit(
                f"[bold blue]HL live capture[/]\n"
                f"symbols  : {', '.join(sym_list)}\n"
                f"duration : {duration_s:.1f}s\n"
                f"url      : {url_use}\n"
                f"out      : {out_path}",
                border_style="blue",
            ))

        try:
            n = collect_to_file(
                out_path,
                symbols=sym_list,
                duration_s=duration_s,
                max_events=max_events,
                url=url_use,
            )
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1)
        except Exception as exc:
            console.print(f"[red]collector failed:[/] {exc}")
            raise typer.Exit(1)

        if not quiet:
            console.print(
                f"[green]Wrote {n:,} records to[/] [cyan]{out_path}[/]"
            )

    @hl_app.command("demo")
    def hl_demo(
        output_dir: Optional[Path] = typer.Option(
            None, "-o", "--output-dir",
            help="Root directory (creates one subfolder per use case)",
        ),
        skip_toxic: bool = typer.Option(False, "--skip-toxic"),
        skip_kill: bool = typer.Option(False, "--skip-kill"),
        skip_latency: bool = typer.Option(False, "--skip-latency"),
        skip_daily: bool = typer.Option(False, "--skip-daily"),
        quiet: bool = typer.Option(False, "-q", "--quiet"),
    ):
        """Run all four HL use cases + build the cover dashboard.

        This is the end-to-end happy-path suitable for a demo: 4 scenarios
        executed in sequence with default knobs, all artifacts written
        into per-use-case subfolders under ``output_dir``, and the
        dashboard stitched on top.
        """
        from ..usecases import (
            ToxicFlowConfig, run_toxic_flow,
            KillDrillConfig, run_kill_drill,
            LatencyConfig, run_latency,
            DailyEvidenceConfig, run_daily_evidence,
            build_dashboard,
        )

        root = output_dir or Path.cwd() / "out" / "hl"
        root.mkdir(parents=True, exist_ok=True)

        if not quiet:
            console.print(Panel.fit(
                f"[bold blue]Sentinel-HFT Hyperliquid demo[/]\n"
                f"output root : {root}",
                border_style="blue",
            ))

        # Each runner writes into <root>/<slug>/.
        if not skip_toxic:
            if not quiet:
                console.print("\n[bold cyan]1/4 toxic-flow[/]")
            run_toxic_flow(ToxicFlowConfig(
                output_dir=root / "toxic_flow",
            ))
        if not skip_kill:
            if not quiet:
                console.print("\n[bold cyan]2/4 kill-drill[/]")
            run_kill_drill(KillDrillConfig(
                output_dir=root / "kill_drill",
            ))
        if not skip_latency:
            if not quiet:
                console.print("\n[bold cyan]3/4 latency[/]")
            run_latency(LatencyConfig(
                output_dir=root / "latency",
            ))
        if not skip_daily:
            if not quiet:
                console.print("\n[bold cyan]4/4 daily-evidence[/]")
            run_daily_evidence(DailyEvidenceConfig(
                output_dir=root / "daily_evidence",
            ))

        if not quiet:
            console.print("\n[bold cyan]dashboard[/]")
        dash = build_dashboard(root)

        if quiet:
            return

        console.print(Panel.fit(
            f"[bold green]HL demo complete[/]\n"
            f"dashboard : {dash}\n"
            f"root      : {root}",
            border_style="green",
        ))


    # === VERSION COMMAND ===

    @app.command()
    def version(
        verbose: bool = typer.Option(False, "-v", "--verbose", help="Show detailed info"),
    ):
        """Show version information."""
        console.print(f"[bold blue]Sentinel-HFT v{__version__}[/]")

        if verbose:
            console.print()
            table = Table(show_header=False, box=None)
            table.add_column("Feature", style="cyan")
            table.add_column("Status", style="green")

            # Core features
            table.add_row("Trace Analysis", "✓ Streaming quantile estimation")
            table.add_row("Report Schema", "✓ JSON/YAML/Markdown export")
            table.add_row("Regression Testing", "✓ CI/CD integration")

            # Phase 1: Attribution
            table.add_row("Latency Attribution", "✓ v1.2 format (64-byte records)")
            table.add_row("Stage Breakdown", "✓ ingress/core/risk/egress/overhead")

            # Phase 2: Fault Injection
            table.add_row("Fault Injection", "✓ 8 fault types")
            table.add_row("Test Scenarios", "✓ Built-in + custom")

            # Phase 3: Server
            try:
                from ..server import app as server_app
                if server_app:
                    table.add_row("HTTP Server", "✓ FastAPI (port 8000)")
                else:
                    table.add_row("HTTP Server", "○ Not installed")
            except ImportError:
                table.add_row("HTTP Server", "○ Not installed")

            # Optional features
            try:
                import anthropic
                table.add_row("AI Explainer", "✓ Claude integration")
            except ImportError:
                table.add_row("AI Explainer", "○ Not installed")

            try:
                import prometheus_client
                table.add_row("Prometheus", "✓ Metrics export")
            except ImportError:
                table.add_row("Prometheus", "○ Not installed")

            console.print(table)

            console.print()
            console.print("[dim]Install extras: pip install sentinel-hft[all][/]")


    # === DEMO COMMAND ===

    @app.command()
    def demo(
        output_dir: Path = typer.Option(Path("./demo_output"), "-o", "--output-dir"),
        show_all: bool = typer.Option(False, "--all", help="Demo all features"),
    ):
        """Run demo with sample data showing Sentinel-HFT capabilities."""
        import random
        import struct

        console.print(Panel.fit(
            f"[bold blue]Sentinel-HFT v{__version__} Demo[/]",
            border_style="blue"
        ))

        output_dir.mkdir(parents=True, exist_ok=True)

        # ===========================================
        # DEMO 1: Basic Trace Analysis (v1.1)
        # ===========================================
        console.print("\n[bold cyan]1. Basic Trace Analysis[/]")
        console.print("   Generating v1.1 traces with realistic latency distribution...")

        from ..formats.file_header import FileHeader

        num_traces = 10000
        traces_data = []

        for i in range(num_traces):
            latency = 5 + random.randint(0, 3)
            if random.random() < 0.01:
                latency += random.randint(20, 50)

            # v1.1 format: <BBHIQQQHH
            record = struct.pack(
                '<BBHIQQQHH',
                1,  # version
                1,  # record_type (TX_EVENT)
                0,  # core_id
                i,  # seq_no
                i * 100,  # t_ingress
                i * 100 + latency,  # t_egress
                random.randint(0, 0xFFFFFFFF),  # data
                0,  # flags
                i % 65536,  # tx_id
            )
            record += b'\x00' * (48 - len(record))  # Pad to 48 bytes
            traces_data.append(record)

        trace_file = output_dir / "demo_traces_v11.bin"
        header = FileHeader(version=1, record_size=48, record_count=num_traces, clock_mhz=100)

        with open(trace_file, 'wb') as f:
            f.write(header.encode())
            for t in traces_data:
                f.write(t)

        console.print(f"   [green]✓[/] Created: {trace_file.name} ({num_traces:,} traces)")

        # Analyze
        cfg = SentinelConfig()
        streaming_config = StreamingConfig(clock_hz=cfg.clock.frequency_hz)
        metrics = StreamingMetrics(streaming_config)

        for trace in TraceReader.read_path(trace_file):
            metrics.add(trace)

        snapshot = metrics.snapshot()

        # Build report
        report = AnalysisReport(
            source_file=str(trace_file),
            source_format='sentinel',
            source_format_version=1,
            clock_frequency_mhz=100.0,
        )

        lat = snapshot.get('latency', {})
        report.latency.count = lat.get('count', 0)
        report.latency.mean_cycles = lat.get('mean_cycles', 0.0)
        report.latency.p50_cycles = lat.get('p50_cycles', 0.0)
        report.latency.p99_cycles = lat.get('p99_cycles', 0.0)
        report.latency.p999_cycles = lat.get('p999_cycles', 0.0)
        report.latency.min_cycles = lat.get('min_cycles', 0)
        report.latency.max_cycles = lat.get('max_cycles', 0)

        drops = snapshot.get('drops', {})
        report.drops.total_drops = drops.get('total_dropped', 0)
        report.drops.drop_rate = drops.get('drop_rate', 0.0)

        report.compute_status()
        report.populate_ns_values()

        report_file = output_dir / "demo_report_v11.json"
        report_file.write_text(report.to_json(indent=2))
        console.print(f"   [green]✓[/] Analysis: {report_file.name}")

        # ===========================================
        # DEMO 2: v1.2 Latency Attribution
        # ===========================================
        console.print("\n[bold cyan]2. Latency Attribution (v1.2)[/]")
        console.print("   Generating v1.2 traces with stage-level timing...")

        from ..adapters.sentinel_adapter_v12 import V12_STRUCT, V12_SIZE

        traces_v12 = []
        for i in range(num_traces):
            # Realistic stage breakdown
            d_ingress = random.randint(2, 5)
            d_core = random.randint(10, 30)
            d_risk = random.randint(3, 10)
            d_egress = random.randint(2, 5)

            # Occasional spikes
            if random.random() < 0.01:
                d_core += random.randint(20, 100)

            total = d_ingress + d_core + d_risk + d_egress + random.randint(1, 3)  # overhead

            record = V12_STRUCT.pack(
                2,          # version (v1.2)
                1,          # record_type (TX_EVENT)
                0,          # core_id
                i,          # seq_no
                i * 100,    # t_ingress
                i * 100 + total,  # t_egress
                0,          # t_host
                i % 65536,  # tx_id
                1,          # flags
                d_ingress,
                d_core,
                d_risk,
                d_egress,
            )
            traces_v12.append(record)

        trace_file_v12 = output_dir / "demo_traces_v12.bin"
        header_v12 = FileHeader(version=2, record_size=64, record_count=num_traces, clock_mhz=100)

        with open(trace_file_v12, 'wb') as f:
            f.write(header_v12.encode())
            for t in traces_v12:
                f.write(t)

        console.print(f"   [green]✓[/] Created: {trace_file_v12.name} (64-byte records)")

        # Show attribution breakdown
        from ..streaming.attribution import AttributionTracker
        from ..adapters.sentinel_adapter_v12 import SentinelV12Adapter

        attr_tracker = AttributionTracker()
        adapter = SentinelV12Adapter(clock_mhz=100.0)

        for _, attribution in adapter.iterate_with_attribution(trace_file_v12):
            attr_tracker.update(attribution)

        attr_metrics = attr_tracker.get_metrics()
        if attr_metrics:
            attr_table = Table(title="Stage Attribution", show_header=True)
            attr_table.add_column("Stage")
            attr_table.add_column("P99 (ns)", justify="right")
            attr_table.add_column("% of Total", justify="right")

            for stage in attr_metrics.stages:
                pct_style = "red" if stage.pct_of_total > 0.5 else "green"
                attr_table.add_row(
                    stage.stage.capitalize(),
                    f"{stage.p99:.0f}",
                    f"[{pct_style}]{stage.pct_of_total:.1%}[/]"
                )

            console.print(attr_table)
            console.print(f"   [yellow]Bottleneck:[/] {attr_metrics.bottleneck} ({attr_metrics.bottleneck_pct:.1%})")

        # ===========================================
        # DEMO 3: Fault Injection Scenarios
        # ===========================================
        console.print("\n[bold cyan]3. Fault Injection Testing[/]")
        console.print("   Available scenarios for resilience testing...")

        from ..testing import list_scenarios, get_scenario

        scenarios = list_scenarios()
        scenario_table = Table(show_header=True)
        scenario_table.add_column("Scenario")
        scenario_table.add_column("Description")
        scenario_table.add_column("Fault Types")

        for name in scenarios[:4]:  # Show first 4
            scenario = get_scenario(name)
            if scenario:
                fault_types = ", ".join(str(f.fault_type.name if hasattr(f.fault_type, 'name') else f.fault_type.value) for f in scenario.faults[:2])
                if len(scenario.faults) > 2:
                    fault_types += "..."
                scenario_table.add_row(name, scenario.description, fault_types)

        console.print(scenario_table)
        console.print(f"   [dim]Total scenarios: {len(scenarios)}[/]")

        # ===========================================
        # Summary
        # ===========================================
        console.print()
        console.print(Panel.fit(
            f"[green bold]Demo Complete![/]\n\n"
            f"Output directory: {output_dir}\n"
            f"Files created:\n"
            f"  • demo_traces_v11.bin (v1.1 format)\n"
            f"  • demo_traces_v12.bin (v1.2 with attribution)\n"
            f"  • demo_report_v11.json",
            title="Summary",
            border_style="green"
        ))

        console.print("\n[dim]Run 'sentinel-hft version -v' for feature status[/]")

    # ---------------------------------------------------------------
    # Workstream 4 / 5 -- AI agents: nightly RCA + online triage
    # ---------------------------------------------------------------

    ai_app = typer.Typer(
        name="ai",
        help="AI agents: nightly RCA digest + online triage",
        add_completion=False,
    )
    app.add_typer(ai_app, name="ai")

    @ai_app.command("rca-nightly")
    def ai_rca_nightly(
        artifacts_root: Path = typer.Option(
            Path("out/hl"), "--artifacts",
            help="Root directory of drill artifacts",
        ),
        digest_dir: Path = typer.Option(
            Path("out/digests"), "--digest-dir",
            help="Where to archive nightly digests",
        ),
        run_date: Optional[str] = typer.Option(
            None, "--date",
            help="ISO date for the run (default: today)",
        ),
        backend: str = typer.Option(
            "auto", "--backend",
            help="auto | anthropic | template",
        ),
        model: str = typer.Option(
            "claude-haiku-4-5", "--model",
            help="LLM model id (when backend != template)",
        ),
        print_md: bool = typer.Option(
            True, "--print/--no-print",
            help="Print the digest Markdown to stdout",
        ),
    ):
        """Build the day's RCA digest and archive it."""
        from ..ai.rca_nightly import run_nightly
        result = run_nightly(
            artifacts_root=artifacts_root,
            digest_dir=digest_dir,
            run_date=run_date,
            backend=backend,
            model=model,
        )
        if print_md:
            console.print(Panel.fit(
                result.markdown,
                title=f"[cyan]RCA digest[/] {result.date} (backend={result.backend})",
                border_style="cyan",
            ))
        console.print(
            f"[green]Archived:[/] {digest_dir}/{result.date}.md + .json"
        )

    @ai_app.command("rca-list")
    def ai_rca_list(
        digest_dir: Path = typer.Option(
            Path("out/digests"), "--digest-dir",
        ),
    ):
        """List archived digests (newest first)."""
        from ..ai.rca_nightly import list_digests
        entries = list_digests(digest_dir)
        if not entries:
            console.print("[yellow]No digests archived.[/]")
            return
        tbl = Table(title="Archived RCA digests")
        tbl.add_column("Date")
        tbl.add_column("Backend")
        tbl.add_column("Anomalies", justify="right")
        tbl.add_column("Prompt SHA256")
        for e in entries:
            tbl.add_row(
                str(e.get("date", "")),
                str(e.get("backend", "")),
                str(e.get("anomaly_count", 0)),
                str(e.get("prompt_sha256", ""))[:16],
            )
        console.print(tbl)

    @ai_app.command("triage-eval")
    def ai_triage_eval(
        out_json: Optional[Path] = typer.Option(
            None, "-o", "--out",
            help="Write evaluation report JSON to this path",
        ),
    ):
        """Replay a scripted trace stream through the online triage
        agent and score precision / recall."""
        from ..ai.triage_eval import run_evaluation
        report = run_evaluation()
        tbl = Table(title="Triage evaluation")
        tbl.add_column("Metric")
        tbl.add_column("Value", justify="right")
        for k in ("events", "labelled_anomalies", "alerts_fired",
                  "true_positives", "false_positives", "false_negatives",
                  "precision", "recall", "f1"):
            v = report.get(k)
            if isinstance(v, float):
                tbl.add_row(k, f"{v:.3f}")
            else:
                tbl.add_row(k, str(v))
        console.print(tbl)
        if out_json is not None:
            out_json.parent.mkdir(parents=True, exist_ok=True)
            out_json.write_text(
                json.dumps(report, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            console.print(f"[green]Wrote {out_json}[/]")


def main():
    """Main entry point."""
    if not HAS_RICH:
        print("Error: typer and rich are required for CLI")
        print("Install with: pip install typer rich")
        sys.exit(1)
    app()


if __name__ == "__main__":
    main()
