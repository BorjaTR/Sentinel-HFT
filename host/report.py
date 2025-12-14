#!/usr/bin/env python3
"""Report generation for Sentinel-HFT metrics.

Generates JSON, Markdown, and console output reports from FullMetrics.

Usage:
    from report import ReportGenerator
    gen = ReportGenerator()
    gen.to_json(metrics, Path("report.json"))
    gen.to_markdown(metrics, Path("report.md"))
    gen.to_stdout(metrics)
"""

import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO

from metrics import FullMetrics, LatencyMetrics, ThroughputMetrics, AnomalyReport


class ReportGenerator:
    """Generate reports from metrics data."""

    def __init__(self, title: str = "Sentinel-HFT Replay Report"):
        """Initialize report generator.

        Args:
            title: Report title for headers
        """
        self.title = title

    def to_json(self, metrics: FullMetrics, path: Path) -> None:
        """Write metrics to JSON file.

        Args:
            metrics: Computed metrics to serialize
            path: Output file path
        """
        report = self._build_report_dict(metrics)

        with open(path, 'w') as f:
            json.dump(report, f, indent=2)

    def to_markdown(self, metrics: FullMetrics, path: Path) -> None:
        """Write metrics to Markdown report file.

        Args:
            metrics: Computed metrics to format
            path: Output file path
        """
        content = self._format_markdown(metrics)

        with open(path, 'w') as f:
            f.write(content)

    def to_stdout(self, metrics: FullMetrics, file: TextIO = None) -> None:
        """Print metrics summary to stdout (or specified file).

        Args:
            metrics: Computed metrics to display
            file: Output file object (defaults to sys.stdout)
        """
        if file is None:
            file = sys.stdout

        content = self._format_console(metrics)
        print(content, file=file)

    def generate_histogram_data(
        self,
        latencies: list[int],
        num_bins: int = 20,
    ) -> dict:
        """Generate histogram data for latency distribution.

        Args:
            latencies: List of latency values in cycles
            num_bins: Number of histogram bins

        Returns:
            Dictionary with bin edges, counts, and percentiles
        """
        if not latencies:
            return {
                'bins': [],
                'counts': [],
                'bin_width': 0,
                'percentiles': {},
            }

        min_lat = min(latencies)
        max_lat = max(latencies)

        # Handle edge case of all same values
        if min_lat == max_lat:
            return {
                'bins': [min_lat],
                'counts': [len(latencies)],
                'bin_width': 1,
                'percentiles': {
                    'p50': min_lat,
                    'p90': min_lat,
                    'p99': min_lat,
                },
            }

        # Calculate bin edges
        bin_width = (max_lat - min_lat) / num_bins
        bins = [min_lat + i * bin_width for i in range(num_bins + 1)]

        # Count values in each bin
        counts = [0] * num_bins
        for lat in latencies:
            bin_idx = min(int((lat - min_lat) / bin_width), num_bins - 1)
            counts[bin_idx] += 1

        # Calculate percentiles
        sorted_lat = sorted(latencies)
        n = len(sorted_lat)

        def percentile(p):
            k = int((n - 1) * p / 100)
            return sorted_lat[k]

        return {
            'bins': [round(b, 2) for b in bins[:-1]],  # Bin start edges
            'counts': counts,
            'bin_width': round(bin_width, 2),
            'percentiles': {
                'p50': percentile(50),
                'p75': percentile(75),
                'p90': percentile(90),
                'p95': percentile(95),
                'p99': percentile(99),
            },
        }

    def _build_report_dict(self, metrics: FullMetrics) -> dict:
        """Build complete report dictionary.

        Args:
            metrics: Metrics to serialize

        Returns:
            Complete report dictionary
        """
        return {
            'report': {
                'title': self.title,
                'generated_at': datetime.now().isoformat(),
                'version': '2.0',
            },
            **metrics.to_dict(),
        }

    def _format_markdown(self, metrics: FullMetrics) -> str:
        """Format metrics as Markdown.

        Args:
            metrics: Metrics to format

        Returns:
            Markdown-formatted string
        """
        lat = metrics.latency
        tp = metrics.throughput
        anom = metrics.anomalies

        lines = [
            f"# {self.title}",
            "",
            f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Traces | {metrics.trace_count} |",
            f"| Trace Drops | {metrics.trace_drops} |",
            f"| Validation Errors | {len(metrics.validation_errors)} |",
            "",
            "## Latency Distribution",
            "",
            f"| Statistic | Cycles | Time (ns) |",
            f"|-----------|--------|-----------|",
            f"| Count | {lat.count} | - |",
            f"| Minimum | {lat.min_cycles} | {lat.min_ns:.1f} |",
            f"| Maximum | {lat.max_cycles} | {lat.max_ns:.1f} |",
            f"| Mean | {lat.mean_cycles:.2f} | {lat.mean_ns:.1f} |",
            f"| Std Dev | {lat.stddev_cycles:.2f} | - |",
            "",
            "### Percentiles",
            "",
            f"| Percentile | Cycles | Time (ns) |",
            f"|------------|--------|-----------|",
            f"| P50 (Median) | {lat.p50_cycles:.1f} | {lat.p50_cycles * lat.clock_period_ns:.1f} |",
            f"| P75 | {lat.p75_cycles:.1f} | {lat.p75_cycles * lat.clock_period_ns:.1f} |",
            f"| P90 | {lat.p90_cycles:.1f} | {lat.p90_cycles * lat.clock_period_ns:.1f} |",
            f"| P95 | {lat.p95_cycles:.1f} | {lat.p95_cycles * lat.clock_period_ns:.1f} |",
            f"| P99 | {lat.p99_cycles:.1f} | {lat.p99_ns:.1f} |",
            f"| P99.9 | {lat.p999_cycles:.1f} | {lat.p999_ns:.1f} |",
            "",
            "## Throughput",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Transactions | {tp.total_transactions} |",
            f"| Total Cycles | {tp.total_cycles} |",
            f"| Transactions/Cycle | {tp.transactions_per_cycle:.4f} |",
            f"| Transactions/Second | {tp.transactions_per_second:,.0f} |",
            f"| Max Burst Size | {tp.max_burst_size} |",
            f"| Avg Inter-arrival | {tp.avg_inter_arrival_cycles:.2f} cycles |",
            "",
            "## Anomaly Detection",
            "",
            f"| Setting | Value |",
            f"|---------|-------|",
            f"| Z-Score Threshold | {anom.threshold_zscore} |",
            f"| Baseline Mean | {anom.baseline_mean:.2f} cycles |",
            f"| Baseline Std Dev | {anom.baseline_stddev:.2f} cycles |",
            f"| Anomalies Detected | {anom.count} |",
            "",
        ]

        # Add anomalies table if any
        if anom.anomalies:
            lines.extend([
                "### Detected Anomalies",
                "",
                "| TX ID | Latency | Z-Score | Description |",
                "|-------|---------|---------|-------------|",
            ])
            for a in anom.anomalies[:20]:  # Limit to 20 in markdown
                lines.append(
                    f"| {a.tx_id} | {a.latency_cycles} | {a.zscore:.2f} | {a.description} |"
                )
            if len(anom.anomalies) > 20:
                lines.append(f"| ... | ... | ... | ({len(anom.anomalies) - 20} more) |")
            lines.append("")

        # Footer
        lines.extend([
            "---",
            "",
            f"*Clock Period: {lat.clock_period_ns} ns*",
            "",
        ])

        return "\n".join(lines)

    def _format_console(self, metrics: FullMetrics) -> str:
        """Format metrics for console output.

        Args:
            metrics: Metrics to format

        Returns:
            Console-formatted string
        """
        lat = metrics.latency
        tp = metrics.throughput
        anom = metrics.anomalies

        lines = [
            "=" * 60,
            f"  {self.title}",
            "=" * 60,
            "",
            "SUMMARY",
            "-" * 40,
            f"  Traces:           {metrics.trace_count}",
            f"  Drops:            {metrics.trace_drops}",
            f"  Errors:           {len(metrics.validation_errors)}",
            "",
            "LATENCY (cycles)",
            "-" * 40,
            f"  Min:              {lat.min_cycles}",
            f"  Max:              {lat.max_cycles}",
            f"  Mean:             {lat.mean_cycles:.2f}",
            f"  Std Dev:          {lat.stddev_cycles:.2f}",
            "",
            "  P50 (Median):     {:.1f}".format(lat.p50_cycles),
            "  P90:              {:.1f}".format(lat.p90_cycles),
            "  P99:              {:.1f}".format(lat.p99_cycles),
            "  P99.9:            {:.1f}".format(lat.p999_cycles),
            "",
            "LATENCY (nanoseconds @ {}ns clock)".format(lat.clock_period_ns),
            "-" * 40,
            f"  Min:              {lat.min_ns:.1f} ns",
            f"  Max:              {lat.max_ns:.1f} ns",
            f"  Mean:             {lat.mean_ns:.1f} ns",
            f"  P99:              {lat.p99_ns:.1f} ns",
            "",
            "THROUGHPUT",
            "-" * 40,
            f"  Total TX:         {tp.total_transactions}",
            f"  Total Cycles:     {tp.total_cycles}",
            f"  TX/Cycle:         {tp.transactions_per_cycle:.4f}",
            f"  TX/Second:        {tp.transactions_per_second:,.0f}",
            f"  Max Burst:        {tp.max_burst_size}",
            "",
            "ANOMALIES",
            "-" * 40,
            f"  Threshold (Z):    {anom.threshold_zscore}",
            f"  Detected:         {anom.count}",
        ]

        if anom.anomalies:
            lines.append("")
            lines.append("  Top anomalies:")
            for a in anom.anomalies[:5]:
                lines.append(f"    TX {a.tx_id}: {a.latency_cycles} cycles (z={a.zscore:.2f})")

        lines.extend([
            "",
            "=" * 60,
        ])

        return "\n".join(lines)


def generate_json_report(metrics: FullMetrics, path: Path) -> None:
    """Convenience function to generate JSON report.

    Args:
        metrics: Metrics to serialize
        path: Output file path
    """
    gen = ReportGenerator()
    gen.to_json(metrics, path)


def generate_markdown_report(metrics: FullMetrics, path: Path) -> None:
    """Convenience function to generate Markdown report.

    Args:
        metrics: Metrics to serialize
        path: Output file path
    """
    gen = ReportGenerator()
    gen.to_markdown(metrics, path)


def print_report(metrics: FullMetrics) -> None:
    """Convenience function to print report to stdout.

    Args:
        metrics: Metrics to display
    """
    gen = ReportGenerator()
    gen.to_stdout(metrics)


if __name__ == '__main__':
    # Demo: Generate a sample report
    from metrics import MetricsEngine

    # Create sample data
    sample_latencies = [3, 3, 4, 3, 5, 4, 3, 4, 3, 3, 4, 4, 3, 5, 12]  # Note: 12 is anomaly
    sample_ingress = list(range(0, 150, 10))
    sample_egress = [i + l for i, l in zip(sample_ingress, sample_latencies)]

    # Compute metrics
    engine = MetricsEngine(clock_period_ns=10.0, anomaly_zscore=2.5)
    latency_metrics = engine.compute_latency(sample_latencies)
    throughput_metrics = engine.compute_throughput(sample_ingress, sample_egress)
    anomaly_report = engine.detect_anomalies(sample_latencies, list(range(len(sample_latencies))))

    full_metrics = FullMetrics(
        latency=latency_metrics,
        throughput=throughput_metrics,
        anomalies=anomaly_report,
        trace_file="demo_traces.bin",
        trace_count=len(sample_latencies),
        trace_drops=0,
    )

    # Generate reports
    gen = ReportGenerator(title="Demo Report")
    gen.to_stdout(full_metrics)

    print("\n\n--- JSON Output ---\n")
    print(json.dumps(gen._build_report_dict(full_metrics), indent=2))
