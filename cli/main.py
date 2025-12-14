#!/usr/bin/env python3
"""Sentinel-HFT: Hardware execution observability for crypto trading infrastructure.

Usage:
    sentinel-hft replay <input> [options]
    sentinel-hft analyze <traces> [options]
    sentinel-hft validate <traces>
    sentinel-hft convert <input> <output>
    sentinel-hft info <file>
    sentinel-hft demo

Commands:
    replay      Replay market data through RTL simulation
    analyze     Analyze existing trace file
    validate    Check trace file integrity
    convert     Convert between formats (csv, bin)
    info        Show file information
    demo        Run demo with sample data

Examples:
    sentinel-hft replay market_data.csv -o report.json
    sentinel-hft analyze traces.bin --explain --protocol arbitrum
    sentinel-hft demo
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Version
__version__ = "1.0.0"

# Add project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'host'))
sys.path.insert(0, str(PROJECT_ROOT / 'wind_tunnel'))


# === Color Output ===

class Colors:
    """ANSI color codes for terminal output."""
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

    @classmethod
    def disable(cls):
        """Disable all colors."""
        cls.RED = cls.GREEN = cls.YELLOW = cls.BLUE = cls.CYAN = cls.BOLD = cls.RESET = ''


def _supports_color():
    """Check if terminal supports color."""
    if os.environ.get('NO_COLOR'):
        return False
    if not hasattr(sys.stdout, 'isatty'):
        return False
    return sys.stdout.isatty()


def print_error(msg: str):
    """Print error message in red."""
    print(f"{Colors.RED}Error:{Colors.RESET} {msg}", file=sys.stderr)


def print_warning(msg: str):
    """Print warning message in yellow."""
    print(f"{Colors.YELLOW}Warning:{Colors.RESET} {msg}", file=sys.stderr)


def print_success(msg: str):
    """Print success message in green."""
    print(f"{Colors.GREEN}✓{Colors.RESET} {msg}")


def print_info(msg: str):
    """Print info message in blue."""
    print(f"{Colors.BLUE}ℹ{Colors.RESET} {msg}")


def print_header(msg: str):
    """Print header in bold."""
    print(f"\n{Colors.BOLD}{msg}{Colors.RESET}")


def print_progress(msg: str):
    """Print progress message in cyan."""
    print(f"{Colors.CYAN}→{Colors.RESET} {msg}")


# === Import project modules (lazy) ===

def _get_imports():
    """Lazy import of project modules."""
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
    return {
        'ReplayRunner': ReplayRunner,
        'ReplayConfig': ReplayConfig,
        'load_input': load_input,
        'write_stimulus_binary': write_stimulus_binary,
        'TracePipeline': TracePipeline,
        'MetricsEngine': MetricsEngine,
        'FullMetrics': FullMetrics,
        'ReportGenerator': ReportGenerator,
        'decode_trace_file': decode_trace_file,
    }


# === Command Handlers ===

def cmd_replay(args) -> int:
    """Run replay simulation."""
    imports = _get_imports()
    ReplayRunner = imports['ReplayRunner']
    ReplayConfig = imports['ReplayConfig']
    ReportGenerator = imports['ReportGenerator']

    input_file = Path(args.input)
    output = Path(args.output) if args.output else Path('replay_output')

    if not input_file.exists():
        print_error(f"Input file not found: {input_file}")
        return 1

    # Determine sim directory
    sim_dir = Path(args.sim_dir) if args.sim_dir else PROJECT_ROOT / 'sim'

    # Create output directory
    output_dir = output.parent if output.suffix else output
    output_dir.mkdir(parents=True, exist_ok=True)

    print_header("Sentinel-HFT Replay")
    print(f"{'Input:':<12} {input_file}")
    print(f"{'Output:':<12} {output}")
    print(f"{'Latency:':<12} {args.latency} cycles")
    print(f"{'Clock:':<12} {args.clock_ns} ns")
    print()

    # Configure replay
    config = ReplayConfig(
        core_latency=args.latency,
        clock_period_ns=args.clock_ns,
        anomaly_zscore=args.zscore,
        force_rebuild=args.rebuild,
    )

    # Run replay
    print_progress("Starting simulation...")
    runner = ReplayRunner(sim_dir)

    # Determine output format
    if output.suffix == '.json':
        result = runner.run(input_file, output_dir, config)
        if result.success and result.metrics:
            gen = ReportGenerator()
            gen.to_json(result.metrics, output)
            print_success(f"JSON report saved to: {output}")
    elif output.suffix == '.md':
        result = runner.run(input_file, output_dir, config)
        if result.success and result.metrics:
            gen = ReportGenerator()
            gen.to_markdown(result.metrics, output)
            print_success(f"Markdown report saved to: {output}")
    else:
        # Output is a directory, generate all reports
        result = runner.run_with_reports(
            input_file, output_dir, config,
            json_report=not args.no_json,
            markdown_report=not args.no_markdown,
            console_report=not args.quiet,
        )

    if not result.success:
        print_error(result.error_message)
        return 1

    print_success(f"Completed: {result.input_transactions} input → {result.output_traces} traces")
    return 0


def cmd_analyze(args) -> int:
    """Analyze existing trace file."""
    imports = _get_imports()
    MetricsEngine = imports['MetricsEngine']
    ReportGenerator = imports['ReportGenerator']
    decode_trace_file = imports['decode_trace_file']

    trace_file = Path(args.traces)

    if not trace_file.exists():
        print_error(f"Trace file not found: {trace_file}")
        return 1

    print_header("Sentinel-HFT Analysis")
    print_progress(f"Loading traces from {trace_file}")

    # Load traces
    with open(trace_file, 'rb') as f:
        traces = list(decode_trace_file(f))

    if not traces:
        print_error("No traces found in file")
        return 1

    print_info(f"Loaded {len(traces)} traces")

    # Compute metrics
    print_progress("Computing metrics...")
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
            print_success(f"Saved: {output}")
        elif args.format == 'markdown' or output.suffix == '.md':
            gen.to_markdown(metrics, output)
            print_success(f"Saved: {output}")
        else:
            gen.to_json(metrics, output)
            print_success(f"Saved: {output}")
    else:
        if args.format == 'json':
            print(json.dumps(gen._build_report_dict(metrics), indent=2))
        else:
            gen.to_stdout(metrics)

    return 0


def _analyze_with_ai(args, traces, metrics, trace_file) -> int:
    """Generate AI-enhanced analysis report."""
    from ai import AIReportGenerator, ExplanationConfig

    # Check for API key
    api_key = os.environ.get('ANTHROPIC_API_KEY')

    if not api_key:
        print_warning("ANTHROPIC_API_KEY not set. Generating report without AI explanations.")
        print_info("Set the API key to enable AI-powered analysis:")
        print(f"  export ANTHROPIC_API_KEY=your_key")
        print()

    # Configure AI report generator
    config = ExplanationConfig(
        clock_period_ns=args.clock_ns,
    )

    generator = AIReportGenerator(api_key=api_key, config=config)

    print_progress("Detecting patterns...")

    # Load protocol context if specified
    protocol_context = None
    if getattr(args, 'protocol', None):
        from protocol import ProtocolContextProvider
        provider = ProtocolContextProvider(
            sentinel_path=getattr(args, 'sentinel_path', None)
        )
        protocol_context = provider.get_context(args.protocol)
        if protocol_context:
            print_info(f"Protocol context: {protocol_context.health.protocol_name} "
                       f"({protocol_context.health.health_tier}-tier)")
        else:
            print_warning(f"Could not load protocol context for '{args.protocol}'")

    # Generate report (with or without AI)
    if protocol_context:
        print_progress("Generating protocol-aware analysis...")
        report = generator.generate_with_protocol(
            traces, metrics, protocol_context, trace_file=str(trace_file)
        )
    elif api_key:
        print_progress("Generating AI-powered explanation...")
        report = generator.generate(traces, metrics, trace_file=str(trace_file))
    else:
        report = generator.generate_without_ai(traces, metrics, trace_file=str(trace_file))

    # Output report
    if args.output:
        output = Path(args.output)
        fmt = 'json' if output.suffix == '.json' else 'markdown'
        generator.save_report(report, output, format=fmt)
        print_success(f"Saved: {output}")
    else:
        if args.format == 'json':
            print(report.to_json())
        else:
            print(report.to_markdown())

    # Print summary stats
    print_header("Analysis Complete")
    print(f"{'Patterns detected:':<20} {report.patterns.get('patterns_detected', 0)}")
    print(f"{'Facts extracted:':<20} {report.facts.get('total_facts', 0)}")
    if protocol_context:
        print(f"{'Protocol:':<20} {protocol_context.health.protocol_name}")
        if report.correlations:
            corr_count = len(report.correlations.get('correlated_events', []))
            print(f"{'Correlations:':<20} {corr_count}")
        if report.risk_assessment:
            combined = report.risk_assessment.get('combined', {})
            print(f"{'Combined risk:':<20} {combined.get('risk_level', 'N/A')}")
    if report.explanation:
        print(f"{'AI explanation:':<20} Yes")
    else:
        print(f"{'AI explanation:':<20} No (API key not set)")

    return 0


def cmd_convert(args) -> int:
    """Convert input file formats."""
    imports = _get_imports()
    load_input = imports['load_input']
    write_stimulus_binary = imports['write_stimulus_binary']

    input_file = Path(args.input)
    output_file = Path(args.output) if args.output else input_file.with_suffix('.bin')

    if not input_file.exists():
        print_error(f"Input file not found: {input_file}")
        return 1

    print_progress(f"Converting: {input_file} → {output_file}")

    # Load input
    transactions = load_input(input_file)
    print_info(f"Loaded {len(transactions)} transactions")

    # Write binary
    write_stimulus_binary(transactions, output_file)
    print_success(f"Written: {output_file} ({output_file.stat().st_size} bytes)")

    return 0


def cmd_validate(args) -> int:
    """Validate trace file."""
    imports = _get_imports()
    TracePipeline = imports['TracePipeline']

    trace_file = Path(args.traces)

    if not trace_file.exists():
        print_error(f"Trace file not found: {trace_file}")
        return 1

    print_progress(f"Validating: {trace_file}")

    pipeline = TracePipeline(clock_period_ns=args.clock_ns)
    result = pipeline.validate(trace_file)

    print_header("Validation Results")
    print(f"{'Total traces:':<20} {result.total_traces}")
    print(f"{'Valid traces:':<20} {result.valid_traces}")
    print(f"{'Errors:':<20} {len(result.errors)}")
    print(f"{'Out-of-order:':<20} {result.out_of_order_count}")
    print(f"{'Duplicate TX IDs:':<20} {result.duplicate_tx_ids}")
    print(f"{'TX ID gaps:':<20} {result.tx_id_gaps}")

    if result.errors:
        print_header("Errors")
        for err in result.errors[:10]:
            print_error(err)
        if len(result.errors) > 10:
            print(f"  ... and {len(result.errors) - 10} more")

    if result.is_valid:
        print_success("Trace file is valid")
        return 0
    else:
        print_error("Trace file has errors")
        return 1 if not args.strict else 2


def cmd_info(args) -> int:
    """Show information about input or trace file."""
    imports = _get_imports()
    load_input = imports['load_input']
    decode_trace_file = imports['decode_trace_file']

    file_path = Path(args.file)

    if not file_path.exists():
        print_error(f"File not found: {file_path}")
        return 1

    print_header(f"File Information: {file_path.name}")

    # Try to detect file type
    suffix = file_path.suffix.lower()

    if suffix in ('.csv', '.txt'):
        transactions = load_input(file_path)
        print(f"{'Type:':<15} CSV/Text input")
        print(f"{'Transactions:':<15} {len(transactions)}")
        if transactions:
            print(f"{'First timestamp:':<15} {transactions[0].timestamp_ns} ns")
            print(f"{'Last timestamp:':<15} {transactions[-1].timestamp_ns} ns")
            duration_ns = transactions[-1].timestamp_ns - transactions[0].timestamp_ns
            print(f"{'Duration:':<15} {duration_ns / 1e6:.2f} ms")
    elif suffix == '.bin' or suffix == '.stim':
        # Could be stimulus or trace
        try:
            # Try as trace first
            with open(file_path, 'rb') as f:
                traces = list(decode_trace_file(f))
            if traces:
                print(f"{'Type:':<15} Trace binary")
                print(f"{'Traces:':<15} {len(traces)}")
                print(f"{'TX ID range:':<15} {traces[0].tx_id} - {traces[-1].tx_id}")
                latencies = [t.latency_cycles for t in traces]
                print(f"{'Latency range:':<15} {min(latencies)} - {max(latencies)} cycles")
                return 0
        except Exception:
            pass

        # Try as stimulus
        try:
            transactions = load_input(file_path)
            print(f"{'Type:':<15} Stimulus binary")
            print(f"{'Transactions:':<15} {len(transactions)}")
            return 0
        except Exception:
            pass

        print(f"{'Type:':<15} Unknown binary")
        print(f"{'Size:':<15} {file_path.stat().st_size} bytes")
    else:
        print(f"{'Type:':<15} Unknown")
        print(f"{'Size:':<15} {file_path.stat().st_size} bytes")

    return 0


def cmd_demo(args) -> int:
    """Run demo with sample data."""
    print_header("Sentinel-HFT Demo")

    # Find demo data
    demo_dir = PROJECT_ROOT / 'demo'
    if not demo_dir.exists():
        print_error("Demo data not found. Creating demo data...")
        demo_dir.mkdir(parents=True, exist_ok=True)

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Check for or generate demo data
    input_file = demo_dir / 'market_data.csv'
    if not input_file.exists():
        print_progress("Generating demo dataset...")
        _generate_demo_data(input_file)

    print_info(f"Input: {input_file}")
    print_info(f"Output: {output_dir}")

    # Check if simulation exists
    sim_dir = PROJECT_ROOT / 'sim'
    sim_binary = sim_dir / 'obj_dir' / 'Vtop_wrapper'
    if not sim_binary.exists():
        print_warning("Simulation not built. Run 'make -C sim all' first.")
        print_info("Running analysis-only demo...")

        # Generate synthetic traces for demo
        print_progress("Generating synthetic traces...")
        traces_file = output_dir / 'traces.bin'
        _generate_demo_traces(traces_file)

        # Analyze the traces
        print_progress("Analyzing traces...")

        class AnalyzeArgs:
            traces = traces_file
            output = output_dir / 'report.json'
            format = 'json'
            clock_ns = 10.0
            zscore = 3.0
            explain = False
            protocol = None
            sentinel_path = None

        result = cmd_analyze(AnalyzeArgs())
        if result != 0:
            return result

        # Also generate markdown report
        AnalyzeArgs.output = output_dir / 'report.md'
        AnalyzeArgs.format = 'markdown'
        cmd_analyze(AnalyzeArgs())

    else:
        # Run full replay
        print_progress("Running replay simulation...")

        class ReplayArgs:
            input = input_file
            output = output_dir / 'report.json'
            latency = 2
            clock_ns = 10.0
            zscore = 3.0
            sim_dir = str(sim_dir)
            rebuild = False
            quiet = False
            no_json = False
            no_markdown = False

        result = cmd_replay(ReplayArgs())
        if result != 0:
            return result

    print_success("Demo completed successfully!")
    print()
    print_header("Output Files")
    for f in sorted(output_dir.iterdir()):
        print(f"  {f.name}")

    print()
    print_info("Next steps:")
    print("  1. View report: cat demo_output/report.md")
    print("  2. Try with AI: sentinel-hft analyze demo_output/traces.bin --explain")
    print("  3. Add protocol: sentinel-hft analyze demo_output/traces.bin --explain --protocol arbitrum")

    return 0


def _generate_demo_data(output_path: Path):
    """Generate demo market data with realistic patterns."""
    import csv
    import random

    random.seed(42)  # Reproducible

    transactions = []
    timestamp_ns = 0
    order_id = 1

    for i in range(1000):
        # Normal inter-arrival: 10-50us (10000-50000 ns)
        if i < 450 or i > 550:
            timestamp_ns += random.randint(10000, 50000)
        else:
            # Burst period: rapid fire (100-500 ns)
            timestamp_ns += random.randint(100, 500)

        # Order type distribution
        r = random.random()
        if r < 0.7:
            opcode = 1  # New order (70%)
        elif r < 0.9:
            opcode = 2  # Cancel (20%)
        else:
            opcode = 3  # Modify (10%)

        # Order size
        if i == 800:
            # Large order to approach position limit
            data = 0x0000000100000000 | order_id
            meta = 5000
        else:
            data = 0x0000000100000000 | order_id
            meta = random.randint(10, 200)

        transactions.append({
            'timestamp_ns': timestamp_ns,
            'data': f'0x{data:016x}',
            'opcode': opcode,
            'meta': meta,
        })

        order_id += 1

    # Write CSV
    with open(output_path, 'w', newline='') as f:
        f.write("# Sentinel-HFT Demo Dataset\n")
        f.write("# 1000 transactions with burst at 450-550\n")
        writer = csv.DictWriter(f, fieldnames=['timestamp_ns', 'data', 'opcode', 'meta'])
        writer.writeheader()
        writer.writerows(transactions)

    print_success(f"Generated {len(transactions)} transactions")


def _generate_demo_traces(output_path: Path):
    """Generate synthetic trace data for demo."""
    import struct
    import random

    random.seed(42)

    with open(output_path, 'wb') as f:
        for tx_id in range(1, 1001):
            t_ingress = tx_id * 100
            # Most latencies are 2-3 cycles, some spikes
            if 450 <= tx_id <= 550:
                latency = random.randint(3, 8)  # Burst period - higher latency
            else:
                latency = random.choice([2, 2, 2, 2, 3, 3, 3])
            t_egress = t_ingress + latency
            flags = 0
            opcode = 1  # New order
            meta = random.randint(10, 200)

            # Pack as trace record (matching trace_decode format)
            # Format: tx_id (8), t_ingress (8), t_egress (8), flags (2), opcode (2), meta (4) = 32 bytes
            # Struct format: '<QQQHHI'
            record = struct.pack('<QQQHHI', tx_id, t_ingress, t_egress, flags, opcode, meta)
            f.write(record)

    print_success(f"Generated 1000 synthetic traces")


# === Main Entry Point ===

def main() -> int:
    """Main CLI entry point."""
    # Check color support
    if not _supports_color():
        Colors.disable()

    parser = argparse.ArgumentParser(
        prog='sentinel-hft',
        description='Hardware execution observability for crypto trading infrastructure',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s replay market_data.csv -o report.json
  %(prog)s analyze traces.bin --explain --protocol arbitrum
  %(prog)s demo

Documentation: https://github.com/BorjaTR/Sentinel-HFT
        """,
    )

    parser.add_argument(
        '--version', '-V',
        action='version',
        version=f'%(prog)s {__version__}'
    )

    parser.add_argument(
        '--no-color',
        action='store_true',
        help='Disable colored output'
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # === replay command ===
    replay = subparsers.add_parser(
        'replay',
        help='Replay market data through RTL simulation',
        description='Feed recorded transactions through Verilator simulation and generate analysis report.',
    )
    replay.add_argument('input', help='Input data file (CSV or binary)')
    replay.add_argument('-o', '--output', help='Output report file or directory')
    replay.add_argument('-l', '--latency', type=int, default=1,
                        help='Core latency in cycles (default: 1)')
    replay.add_argument('--clock-ns', type=float, default=10.0,
                        help='Clock period in nanoseconds (default: 10.0)')
    replay.add_argument('-z', '--zscore', type=float, default=3.0,
                        help='Z-score threshold for anomaly detection (default: 3.0)')
    replay.add_argument('--sim-dir', help='Simulation directory')
    replay.add_argument('--rebuild', action='store_true',
                        help='Force rebuild of simulation')
    replay.add_argument('-q', '--quiet', action='store_true',
                        help='Suppress console output')
    replay.add_argument('--no-json', action='store_true',
                        help='Skip JSON report generation')
    replay.add_argument('--no-markdown', action='store_true',
                        help='Skip Markdown report generation')
    replay.set_defaults(func=cmd_replay)

    # === analyze command ===
    analyze = subparsers.add_parser(
        'analyze',
        help='Analyze existing trace file',
        description='Compute metrics and generate report from binary trace file.',
    )
    analyze.add_argument('traces', help='Binary trace file')
    analyze.add_argument('-o', '--output', help='Output report file')
    analyze.add_argument('-f', '--format', choices=['json', 'markdown', 'console'],
                         default='console', help='Output format (default: console)')
    analyze.add_argument('--clock-ns', type=float, default=10.0,
                         help='Clock period in nanoseconds (default: 10.0)')
    analyze.add_argument('-z', '--zscore', type=float, default=3.0,
                         help='Z-score threshold for anomaly detection (default: 3.0)')
    analyze.add_argument('--explain', action='store_true',
                         help='Generate AI explanation (requires ANTHROPIC_API_KEY)')
    analyze.add_argument('-p', '--protocol',
                         help='Protocol for context (e.g., arbitrum, optimism)')
    analyze.add_argument('--sentinel-path',
                         help='Path to Sentinel installation for live protocol data')
    analyze.set_defaults(func=cmd_analyze)

    # === validate command ===
    validate = subparsers.add_parser(
        'validate',
        help='Check trace file integrity',
        description='Validate binary trace file for errors, ordering issues, and gaps.',
    )
    validate.add_argument('traces', help='Trace file to validate')
    validate.add_argument('--clock-ns', type=float, default=10.0,
                          help='Clock period in nanoseconds')
    validate.add_argument('--strict', action='store_true',
                          help='Exit with code 2 on warnings')
    validate.set_defaults(func=cmd_validate)

    # === convert command ===
    convert = subparsers.add_parser(
        'convert',
        help='Convert between formats',
        description='Convert input files between CSV and binary formats.',
    )
    convert.add_argument('input', help='Input file')
    convert.add_argument('-o', '--output', help='Output file')
    convert.set_defaults(func=cmd_convert)

    # === info command ===
    info = subparsers.add_parser(
        'info',
        help='Show file information',
        description='Display information about input or trace files.',
    )
    info.add_argument('file', help='File to inspect')
    info.set_defaults(func=cmd_info)

    # === demo command ===
    demo = subparsers.add_parser(
        'demo',
        help='Run demo with sample data',
        description='Run complete pipeline with sample data to verify installation.',
    )
    demo.add_argument('--output-dir', default='demo_output',
                      help='Output directory (default: demo_output)')
    demo.set_defaults(func=cmd_demo)

    args = parser.parse_args()

    if args.no_color:
        Colors.disable()

    if not args.command:
        parser.print_help()
        return 0

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print_warning("Interrupted")
        return 130
    except Exception as e:
        print_error(str(e))
        if os.environ.get('SENTINEL_DEBUG'):
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
