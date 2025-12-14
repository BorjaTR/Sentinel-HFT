#!/usr/bin/env python3
"""Sentinel-HFT Command Line Interface.

Primary entry point for running replay simulations and analyzing results.

Usage:
    sentinel-hft replay market_data.csv --output report.json
    sentinel-hft analyze traces.bin --format markdown
    sentinel-hft convert input.csv --output input.bin
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'host'))
sys.path.insert(0, str(PROJECT_ROOT / 'wind_tunnel'))

from wind_tunnel import (
    ReplayRunner,
    ReplayConfig,
    load_input,
    write_stimulus_binary,
    TracePipeline,
)
from host.metrics import MetricsEngine, FullMetrics
from host.report import ReportGenerator
from host.trace_decode import decode_trace_file


def cmd_replay(args):
    """Run replay simulation."""
    input_file = Path(args.input)
    output = Path(args.output) if args.output else Path('replay_output')

    # Determine sim directory
    if args.sim_dir:
        sim_dir = Path(args.sim_dir)
    else:
        sim_dir = PROJECT_ROOT / 'sim'

    # Create output directory
    output_dir = output.parent if output.suffix else output
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Sentinel-HFT Replay")
    print(f"=" * 50)
    print(f"Input:      {input_file}")
    print(f"Output:     {output}")
    print(f"Latency:    {args.latency} cycles")
    print(f"Clock:      {args.clock_ns} ns")
    print()

    # Configure replay
    config = ReplayConfig(
        core_latency=args.latency,
        clock_period_ns=args.clock_ns,
        anomaly_zscore=args.zscore,
        force_rebuild=args.rebuild,
    )

    # Run replay
    runner = ReplayRunner(sim_dir)

    # Determine output format
    if output.suffix == '.json':
        result = runner.run(input_file, output_dir, config)
        if result.success and result.metrics:
            gen = ReportGenerator()
            gen.to_json(result.metrics, output)
            print(f"JSON report saved to: {output}")
    elif output.suffix == '.md':
        result = runner.run(input_file, output_dir, config)
        if result.success and result.metrics:
            gen = ReportGenerator()
            gen.to_markdown(result.metrics, output)
            print(f"Markdown report saved to: {output}")
    else:
        # Output is a directory, generate all reports
        result = runner.run_with_reports(
            input_file, output_dir, config,
            json_report=not args.no_json,
            markdown_report=not args.no_markdown,
            console_report=not args.quiet,
        )

    if not result.success:
        print(f"\nError: {result.error_message}", file=sys.stderr)
        return 1

    print(f"\nCompleted: {result.input_transactions} input -> {result.output_traces} traces")
    return 0


def cmd_analyze(args):
    """Analyze existing trace file."""
    trace_file = Path(args.traces)

    if not trace_file.exists():
        print(f"Error: Trace file not found: {trace_file}", file=sys.stderr)
        return 1

    print(f"Analyzing: {trace_file}")

    # Load traces
    with open(trace_file, 'rb') as f:
        traces = list(decode_trace_file(f))

    if not traces:
        print("No traces found in file", file=sys.stderr)
        return 1

    print(f"Loaded {len(traces)} traces")

    # Compute metrics
    engine = MetricsEngine(
        clock_period_ns=args.clock_ns,
        anomaly_zscore=args.zscore,
    )

    trace_dicts = []
    for t in traces:
        trace_dicts.append({
            'tx_id': t.tx_id,
            't_ingress': t.t_ingress,
            't_egress': t.t_egress,
            'latency_cycles': t.latency_cycles,
            'flags': t.flags,
        })

    metrics = engine.compute_full(trace_dicts)
    metrics.trace_file = str(trace_file)
    metrics.trace_count = len(traces)

    # Check if AI explanation requested
    if args.explain:
        return _analyze_with_ai(args, traces, metrics, trace_file)

    # Standard output
    gen = ReportGenerator(title=f"Analysis: {trace_file.name}")

    if args.output:
        output = Path(args.output)
        if args.format == 'json' or output.suffix == '.json':
            gen.to_json(metrics, output)
            print(f"Saved: {output}")
        elif args.format == 'markdown' or output.suffix == '.md':
            gen.to_markdown(metrics, output)
            print(f"Saved: {output}")
        else:
            gen.to_json(metrics, output)
            print(f"Saved: {output}")
    else:
        if args.format == 'json':
            print(json.dumps(gen._build_report_dict(metrics), indent=2))
        else:
            gen.to_stdout(metrics)

    return 0


def _analyze_with_ai(args, traces, metrics, trace_file):
    """Generate AI-enhanced analysis report."""
    from ai import AIReportGenerator, ExplanationConfig

    # Check for API key
    api_key = os.environ.get('ANTHROPIC_API_KEY')

    if not api_key:
        print("\nWarning: ANTHROPIC_API_KEY not set. Generating report without AI explanations.")
        print("Set the API key to enable AI-powered analysis:")
        print("  export ANTHROPIC_API_KEY=your_key")
        print()

    # Configure AI report generator
    config = ExplanationConfig(
        clock_period_ns=args.clock_ns,
    )

    generator = AIReportGenerator(api_key=api_key, config=config)

    print("Detecting patterns...")

    # Load protocol context if specified
    protocol_context = None
    if getattr(args, 'protocol', None):
        from protocol import ProtocolContextProvider
        provider = ProtocolContextProvider(
            sentinel_path=getattr(args, 'sentinel_path', None)
        )
        protocol_context = provider.get_context(args.protocol)
        if protocol_context:
            print(f"Protocol context: {protocol_context.health.protocol_name} "
                  f"({protocol_context.health.health_tier}-tier)")
        else:
            print(f"Warning: Could not load protocol context for '{args.protocol}'")

    # Generate report (with or without AI)
    if protocol_context:
        print("Generating protocol-aware analysis...")
        report = generator.generate_with_protocol(
            traces, metrics, protocol_context, trace_file=str(trace_file)
        )
    elif api_key:
        print("Generating AI-powered explanation...")
        report = generator.generate(traces, metrics, trace_file=str(trace_file))
    else:
        report = generator.generate_without_ai(traces, metrics, trace_file=str(trace_file))

    # Output report
    if args.output:
        output = Path(args.output)
        fmt = 'json' if output.suffix == '.json' else 'markdown'
        generator.save_report(report, output, format=fmt)
        print(f"Saved: {output}")
    else:
        if args.format == 'json':
            print(report.to_json())
        else:
            print(report.to_markdown())

    # Print summary stats
    print(f"\n--- Analysis Complete ---")
    print(f"Patterns detected: {report.patterns.get('patterns_detected', 0)}")
    print(f"Facts extracted: {report.facts.get('total_facts', 0)}")
    if protocol_context:
        print(f"Protocol context: {protocol_context.health.protocol_name}")
        if report.correlations:
            corr_count = len(report.correlations.get('correlated_events', []))
            print(f"Correlations found: {corr_count}")
        if report.risk_assessment:
            combined = report.risk_assessment.get('combined', {})
            print(f"Combined risk: {combined.get('risk_level', 'N/A')}")
    if report.explanation:
        print(f"AI explanation: Yes")
    else:
        print(f"AI explanation: No (API key not set)")

    return 0


def cmd_convert(args):
    """Convert input file formats."""
    input_file = Path(args.input)
    output_file = Path(args.output) if args.output else input_file.with_suffix('.bin')

    if not input_file.exists():
        print(f"Error: Input file not found: {input_file}", file=sys.stderr)
        return 1

    print(f"Converting: {input_file} -> {output_file}")

    # Load input
    transactions = load_input(input_file)
    print(f"Loaded {len(transactions)} transactions")

    # Write binary
    write_stimulus_binary(transactions, output_file)
    print(f"Written: {output_file} ({output_file.stat().st_size} bytes)")

    return 0


def cmd_validate(args):
    """Validate trace file."""
    trace_file = Path(args.traces)

    if not trace_file.exists():
        print(f"Error: Trace file not found: {trace_file}", file=sys.stderr)
        return 1

    print(f"Validating: {trace_file}")

    pipeline = TracePipeline(clock_period_ns=args.clock_ns)
    result = pipeline.validate(trace_file)

    print(f"\nValidation Results:")
    print(f"-" * 40)
    print(f"Total traces:         {result.total_traces}")
    print(f"Valid traces:         {result.valid_traces}")
    print(f"Errors:               {len(result.errors)}")
    print(f"Out-of-order:         {result.out_of_order_count}")
    print(f"Duplicate TX IDs:     {result.duplicate_tx_ids}")
    print(f"TX ID gaps:           {result.tx_id_gaps}")

    if result.errors:
        print(f"\nErrors:")
        for err in result.errors[:10]:
            print(f"  - {err}")
        if len(result.errors) > 10:
            print(f"  ... and {len(result.errors) - 10} more")

    return 0 if result.is_valid else 1


def cmd_info(args):
    """Show information about input or trace file."""
    file_path = Path(args.file)

    if not file_path.exists():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        return 1

    # Try to detect file type
    suffix = file_path.suffix.lower()

    if suffix in ('.csv', '.txt'):
        transactions = load_input(file_path)
        print(f"File: {file_path}")
        print(f"Type: CSV/Text input")
        print(f"Transactions: {len(transactions)}")
        if transactions:
            print(f"First timestamp: {transactions[0].timestamp_ns} ns")
            print(f"Last timestamp: {transactions[-1].timestamp_ns} ns")
            duration_ns = transactions[-1].timestamp_ns - transactions[0].timestamp_ns
            print(f"Duration: {duration_ns / 1e6:.2f} ms")
    elif suffix == '.bin' or suffix == '.stim':
        # Could be stimulus or trace
        try:
            # Try as trace first
            with open(file_path, 'rb') as f:
                traces = list(decode_trace_file(f))
            if traces:
                print(f"File: {file_path}")
                print(f"Type: Trace binary")
                print(f"Traces: {len(traces)}")
                print(f"TX ID range: {traces[0].tx_id} - {traces[-1].tx_id}")
                latencies = [t.latency_cycles for t in traces]
                print(f"Latency range: {min(latencies)} - {max(latencies)} cycles")
                return 0
        except:
            pass

        # Try as stimulus
        try:
            transactions = load_input(file_path)
            print(f"File: {file_path}")
            print(f"Type: Stimulus binary")
            print(f"Transactions: {len(transactions)}")
            return 0
        except:
            pass

        print(f"File: {file_path}")
        print(f"Type: Unknown binary")
        print(f"Size: {file_path.stat().st_size} bytes")
    else:
        print(f"File: {file_path}")
        print(f"Type: Unknown")
        print(f"Size: {file_path.stat().st_size} bytes")

    return 0


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog='sentinel-hft',
        description='Sentinel-HFT: Low-latency trading system analysis tools',
    )
    parser.add_argument('--version', action='version', version='%(prog)s 2.0.0')

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # replay command
    replay_parser = subparsers.add_parser('replay', help='Run replay simulation')
    replay_parser.add_argument('input', help='Input transaction file (CSV or binary)')
    replay_parser.add_argument('--output', '-o', help='Output file or directory')
    replay_parser.add_argument('--latency', '-l', type=int, default=1,
                               help='Core latency in cycles (default: 1)')
    replay_parser.add_argument('--clock-ns', type=float, default=10.0,
                               help='Clock period in nanoseconds (default: 10.0)')
    replay_parser.add_argument('--zscore', '-z', type=float, default=3.0,
                               help='Z-score threshold for anomaly detection (default: 3.0)')
    replay_parser.add_argument('--sim-dir', help='Simulation directory')
    replay_parser.add_argument('--rebuild', action='store_true',
                               help='Force rebuild of simulation')
    replay_parser.add_argument('--quiet', '-q', action='store_true',
                               help='Suppress console output')
    replay_parser.add_argument('--no-json', action='store_true',
                               help='Skip JSON report generation')
    replay_parser.add_argument('--no-markdown', action='store_true',
                               help='Skip Markdown report generation')
    replay_parser.set_defaults(func=cmd_replay)

    # analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze existing trace file')
    analyze_parser.add_argument('traces', help='Trace binary file')
    analyze_parser.add_argument('--output', '-o', help='Output report file')
    analyze_parser.add_argument('--format', '-f', choices=['json', 'markdown', 'console'],
                                default='console', help='Output format (default: console)')
    analyze_parser.add_argument('--clock-ns', type=float, default=10.0,
                                help='Clock period in nanoseconds')
    analyze_parser.add_argument('--zscore', '-z', type=float, default=3.0,
                                help='Z-score threshold for anomaly detection')
    analyze_parser.add_argument('--explain', action='store_true',
                                help='Generate AI-powered explanation (requires ANTHROPIC_API_KEY)')
    analyze_parser.add_argument('--protocol', '-p',
                                help='Protocol name for context (e.g., arbitrum, optimism)')
    analyze_parser.add_argument('--sentinel-path',
                                help='Path to Sentinel installation for live protocol data')
    analyze_parser.set_defaults(func=cmd_analyze)

    # convert command
    convert_parser = subparsers.add_parser('convert', help='Convert input file formats')
    convert_parser.add_argument('input', help='Input file (CSV)')
    convert_parser.add_argument('--output', '-o', help='Output file (binary)')
    convert_parser.set_defaults(func=cmd_convert)

    # validate command
    validate_parser = subparsers.add_parser('validate', help='Validate trace file')
    validate_parser.add_argument('traces', help='Trace binary file')
    validate_parser.add_argument('--clock-ns', type=float, default=10.0,
                                 help='Clock period in nanoseconds')
    validate_parser.set_defaults(func=cmd_validate)

    # info command
    info_parser = subparsers.add_parser('info', help='Show file information')
    info_parser.add_argument('file', help='Input or trace file')
    info_parser.set_defaults(func=cmd_info)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
