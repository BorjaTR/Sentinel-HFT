"""
Prescribe command - Pattern detection and fix generation.
"""

import json
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

try:
    import typer
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    typer = None

from ..demo.trace_generator import TraceGenerator, TraceRecord


if HAS_RICH:
    console = Console()


def analyze_trace_for_patterns(traces: List[TraceRecord]) -> List[Dict[str, Any]]:
    """
    Analyze traces to detect performance patterns.

    Returns list of detected patterns with confidence scores.
    """
    patterns = []
    n = len(traces)
    if n == 0:
        return patterns

    # Calculate statistics
    latencies = [t.total_latency for t in traces]
    risk_lats = [t.risk_latency for t in traces]
    core_lats = [t.core_latency for t in traces]

    avg_total = sum(latencies) / n
    avg_risk = sum(risk_lats) / n
    avg_core = sum(core_lats) / n

    # Check for backpressure events (flags == 1)
    backpressure_count = sum(1 for t in traces if t.flags == 1)
    backpressure_rate = backpressure_count / n

    # Calculate variance
    risk_variance = sum((r - avg_risk) ** 2 for r in risk_lats) / n

    # Pattern 1: FIFO Backpressure
    # High confidence if: high risk latency, backpressure events, high variance
    fifo_confidence = 0.0
    fifo_evidence = []
    fifo_counter = []

    if avg_risk > avg_total * 0.4:  # Risk > 40% of total
        fifo_confidence += 0.3
        fifo_evidence.append(f"Risk stage latency high ({avg_risk:.0f}ns, {avg_risk/avg_total*100:.0f}% of total)")

    if backpressure_rate > 0.01:  # > 1% backpressure events
        fifo_confidence += 0.35
        fifo_evidence.append(f"Backpressure events detected ({backpressure_rate*100:.1f}% of traces)")

    if risk_variance > avg_risk * 2:  # High variance
        fifo_confidence += 0.22
        fifo_evidence.append(f"High risk stage variance (indicates saturation)")

    if fifo_confidence < 0.5:
        fifo_counter.append("No clock domain issues detected")

    patterns.append({
        'pattern_id': 'FIFO_BACKPRESSURE',
        'confidence': min(fifo_confidence, 0.95),
        'stage': 'risk',
        'evidence': fifo_evidence,
        'counter_evidence': fifo_counter,
    })

    # Pattern 2: Arbiter Contention
    arbiter_confidence = 0.0
    arbiter_evidence = []

    if avg_core > avg_total * 0.35:
        arbiter_confidence += 0.25
        arbiter_evidence.append(f"Core stage latency elevated ({avg_core:.0f}ns)")

    core_variance = sum((c - avg_core) ** 2 for c in core_lats) / n
    if core_variance > avg_core:
        arbiter_confidence += 0.15
        arbiter_evidence.append("Variable core latency suggests contention")

    patterns.append({
        'pattern_id': 'ARBITER_CONTENTION',
        'confidence': arbiter_confidence,
        'stage': 'core',
        'evidence': arbiter_evidence,
        'counter_evidence': [],
    })

    # Pattern 3: Memory Bandwidth
    mem_confidence = 0.0
    mem_evidence = []

    # Check for periodic spikes (memory access patterns)
    max_lat = max(latencies)
    spike_count = sum(1 for l in latencies if l > avg_total * 2)
    if spike_count > n * 0.05:
        mem_confidence += 0.2
        mem_evidence.append(f"Periodic latency spikes detected ({spike_count} > 2x avg)")

    patterns.append({
        'pattern_id': 'MEMORY_BANDWIDTH',
        'confidence': mem_confidence,
        'stage': 'risk',
        'evidence': mem_evidence,
        'counter_evidence': [],
    })

    # Sort by confidence
    patterns.sort(key=lambda p: p['confidence'], reverse=True)

    return patterns


def generate_fix_pack(
    pattern: Dict[str, Any],
    output_dir: Path,
    params: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Generate a fix pack for a detected pattern.

    Returns summary of generated files.
    """
    from ..prescriptions.templates import FixPackGenerator

    generator = FixPackGenerator()

    # Map pattern to template
    pattern_id = pattern['pattern_id']

    if pattern_id not in generator.get_available_patterns():
        return {'error': f"No template available for {pattern_id}"}

    # Use provided params or defaults
    final_params = generator.get_default_params(pattern_id)
    if params:
        final_params.update(params)

    # Generate
    result = generator.generate(
        pattern_id=pattern_id,
        output_dir=str(output_dir),
        params=final_params,
    )

    return {
        'pattern_id': pattern_id,
        'template_id': result.template_id,
        'files': {
            'rtl': result.rtl_file,
            'testbench': result.testbench_file,
            'guide': result.integration_guide_file,
        },
        'parameters': result.parameters,
        'expected_improvement_pct': result.metadata.get('expected_latency_reduction_pct', 0),
        'warnings': result.warnings,
    }


if HAS_RICH:
    app = typer.Typer()

    @app.command("prescribe")
    def prescribe_cmd(
        trace_file: Path = typer.Argument(..., help="Trace file to analyze", exists=True),
        export: Optional[Path] = typer.Option(None, "--export", "-e", help="Export fix to directory"),
        top_n: int = typer.Option(3, "--top", "-n", help="Show top N patterns"),
        min_confidence: float = typer.Option(0.3, "--min-confidence", help="Minimum confidence threshold"),
        quiet: bool = typer.Option(False, "-q", "--quiet", help="Quiet output"),
    ):
        """
        Analyze trace file and prescribe fixes for detected patterns.

        Detects performance patterns like FIFO backpressure, arbiter contention,
        and memory bandwidth issues. Optionally generates RTL fix templates.

        Example:

        \b
          sentinel-hft prescribe traces/incident.bin
          sentinel-hft prescribe traces/incident.bin --export ./fix
        """
        if not quiet:
            console.print(f"[bold blue]Analyzing:[/] {trace_file}")

        # Load trace file
        try:
            generator = TraceGenerator()
            traces = generator.read_trace_file(trace_file)
        except Exception as e:
            console.print(f"[red]Error reading trace file:[/] {e}")
            raise typer.Exit(1)

        if not quiet:
            console.print(f"Loaded {len(traces):,} traces")
            console.print()

        # Analyze for patterns
        patterns = analyze_trace_for_patterns(traces)

        # Filter by confidence
        patterns = [p for p in patterns if p['confidence'] >= min_confidence][:top_n]

        if not patterns:
            console.print("[yellow]No patterns detected above confidence threshold[/]")
            raise typer.Exit(0)

        # Display results
        console.print("[bold]Pattern Analysis[/]")
        console.print("=" * 50)
        console.print()

        for i, pattern in enumerate(patterns, 1):
            conf = pattern['confidence']
            conf_label = "high" if conf >= 0.7 else "medium" if conf >= 0.4 else "low"
            conf_color = "green" if conf >= 0.7 else "yellow" if conf >= 0.4 else "red"

            console.print(f"[bold cyan]#{i} {pattern['pattern_id']}[/]")
            console.print(f"   Confidence: [{conf_color}]{conf*100:.0f}% ({conf_label})[/]")
            console.print(f"   Stage: {pattern['stage']}")
            console.print()

            if pattern['evidence']:
                console.print("   Evidence:")
                for ev in pattern['evidence']:
                    console.print(f"     [green]+[/] {ev}")
                console.print()

            if pattern['counter_evidence']:
                console.print("   Counter-evidence:")
                for ce in pattern['counter_evidence']:
                    console.print(f"     [dim]-[/] {ce}")
                console.print()

        # Generate fix if requested
        if export and patterns:
            top_pattern = patterns[0]
            if top_pattern['confidence'] < 0.5:
                console.print(f"[yellow]Warning: Top pattern confidence is low ({top_pattern['confidence']*100:.0f}%)[/]")

            console.print()
            console.print("Generating FixPack...")

            try:
                result = generate_fix_pack(top_pattern, export)

                if 'error' in result:
                    console.print(f"[red]Error:[/] {result['error']}")
                    raise typer.Exit(1)

                console.print()
                console.print(Panel.fit(
                    f"[bold]CANDIDATE FIX PACK[/]\n\n"
                    f"Pattern: {result['pattern_id']}\n"
                    f"Expected Improvement: ~{result['expected_improvement_pct']:.0f}%\n\n"
                    f"[yellow]Human review required before deployment.[/]",
                    border_style="cyan"
                ))
                console.print()
                console.print(f"Output: {export}")
                console.print()
                console.print("Files generated:")
                for name, path in result['files'].items():
                    console.print(f"  - {Path(path).name}")

            except Exception as e:
                console.print(f"[red]Error generating fix:[/] {e}")
                raise typer.Exit(1)
