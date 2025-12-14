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
    ):
        """
        Compare current metrics against baseline.

        Exit codes: 0=pass, 1=fail
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

        diff = {
            'p99': {
                'baseline': baseline_p99,
                'current': current_p99,
                'change_percent': round(regression_pct, 2),
            },
            'drops': {
                'baseline': baseline_data.get('drops', {}).get('total_drops', 0),
                'current': current_drops,
            },
        }

        # Print report
        console.print()
        console.print(Panel.fit("[bold]REGRESSION REPORT[/]", border_style="blue"))
        console.print()

        table = Table(show_header=True)
        table.add_column("Metric")
        table.add_column("Baseline", justify="right")
        table.add_column("Current", justify="right")
        table.add_column("Change", justify="right")

        style = "red" if regression_pct > max_p99_regression else "green"
        table.add_row("P99", f"{baseline_p99}", f"{current_p99}", f"[{style}]{regression_pct:+.1f}%[/]")
        table.add_row("Drops", str(diff['drops']['baseline']), str(current_drops), "")

        console.print(table)
        console.print()

        # Check pass/fail
        failed = False
        reasons = []

        if regression_pct > max_p99_regression:
            failed = True
            reasons.append(f"P99 regression {regression_pct:.1f}% > {max_p99_regression}%")

        if fail_on_drops and current_drops > 0:
            failed = True
            reasons.append(f"{current_drops} traces dropped")

        if output:
            output.write_text(json.dumps(diff, indent=2))

        if failed:
            console.print("[bold red]FAILED[/]")
            for r in reasons:
                console.print(f"  - {r}")
            raise typer.Exit(1)
        else:
            console.print("[bold green]PASSED[/]")
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


    # === VERSION COMMAND ===

    @app.command()
    def version():
        """Show version information."""
        console.print(f"Sentinel-HFT v{__version__}")


    # === DEMO COMMAND ===

    @app.command()
    def demo(
        output_dir: Path = typer.Option(Path("./demo_output"), "-o", "--output-dir"),
    ):
        """Run demo with sample data."""
        import random
        import struct

        console.print("[bold blue]Sentinel-HFT Demo[/]")

        output_dir.mkdir(parents=True, exist_ok=True)

        # Generate sample traces
        console.print("Generating sample traces...")

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

        trace_file = output_dir / "demo_traces.bin"
        header = FileHeader(version=1, record_size=48, record_count=num_traces, clock_mhz=100)

        with open(trace_file, 'wb') as f:
            f.write(header.encode())
            for t in traces_data:
                f.write(t)

        console.print(f"  Created: {trace_file} ({num_traces:,} traces)")

        # Analyze
        console.print("Analyzing...")

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

        report_file = output_dir / "demo_report.json"
        report_file.write_text(report.to_json(indent=2))
        console.print(f"  Created: {report_file}")

        _print_summary(snapshot, 0, num_traces)
        console.print(f"\n[green]Demo complete![/] Output: {output_dir}")


def main():
    """Main entry point."""
    if not HAS_RICH:
        print("Error: typer and rich are required for CLI")
        print("Install with: pip install typer rich")
        sys.exit(1)
    app()


if __name__ == "__main__":
    main()
