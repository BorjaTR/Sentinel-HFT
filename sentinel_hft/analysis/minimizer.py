"""
Auto-minimize reproducer: find smallest subset that reproduces regression.

Uses delta debugging algorithm to reduce trace size while preserving behavior.
"""

from dataclasses import dataclass
from typing import List, Callable, Dict, Any


@dataclass
class MinimizedResult:
    """Result of trace minimization."""
    original_count: int
    minimized_count: int
    reduction_pct: float
    minimized_traces: List[Dict[str, Any]]
    iterations: int
    preserved_behavior: str  # What behavior was preserved


def minimize_reproducer(
    traces: List[Dict[str, Any]],
    regression_check: Callable[[List[Dict[str, Any]]], bool],
    min_size: int = 10,
    max_iterations: int = 100,
) -> MinimizedResult:
    """
    Find minimal subset of traces that still exhibits regression.

    Uses ddmin (delta debugging minimization) algorithm.

    Args:
        traces: Full list of trace records
        regression_check: Function that returns True if traces show regression
        min_size: Minimum result size
        max_iterations: Maximum iterations

    Returns:
        MinimizedResult with smallest reproducing subset
    """
    # Verify original exhibits regression
    if not regression_check(traces):
        raise ValueError("Original traces don't exhibit regression")

    current = traces
    n = 2  # Start with 2 partitions
    iterations = 0

    while len(current) > min_size and iterations < max_iterations:
        iterations += 1

        # Partition into n chunks
        chunk_size = max(1, len(current) // n)
        chunks = [
            current[i:i + chunk_size]
            for i in range(0, len(current), chunk_size)
        ]

        reduced = False

        # Try each chunk alone (reduce to 1/n)
        for chunk in chunks:
            if len(chunk) >= min_size and regression_check(chunk):
                current = chunk
                n = 2
                reduced = True
                break

        if not reduced:
            # Try complement of each chunk (reduce to (n-1)/n)
            for i in range(len(chunks)):
                complement = []
                for j, chunk in enumerate(chunks):
                    if i != j:
                        complement.extend(chunk)

                if len(complement) >= min_size and regression_check(complement):
                    current = complement
                    n = max(2, n - 1)
                    reduced = True
                    break

        if not reduced:
            # Increase granularity
            if n < len(current):
                n = min(n * 2, len(current))
            else:
                break

    return MinimizedResult(
        original_count=len(traces),
        minimized_count=len(current),
        reduction_pct=(1 - len(current) / len(traces)) * 100 if traces else 0,
        minimized_traces=current,
        iterations=iterations,
        preserved_behavior="P99 regression",
    )


def create_regression_checker(
    baseline_traces: List[Dict[str, Any]],
    threshold: float = 0.10,
    metric: str = 'p99'
) -> Callable[[List[Dict[str, Any]]], bool]:
    """
    Create a regression check function for minimizer.

    Returns function that checks if given traces show regression
    compared to baseline.
    """
    from ..streaming import StreamingAnalyzer

    # Analyze baseline
    baseline_analyzer = StreamingAnalyzer()
    for trace in baseline_traces:
        baseline_analyzer.process_event(trace)

    baseline_analysis = baseline_analyzer.get_summary()
    baseline_value = baseline_analysis.get('latency', {}).get(metric, 0)

    def check(traces: List[Dict[str, Any]]) -> bool:
        if len(traces) < 10:
            return False  # Too few traces to be meaningful

        try:
            analyzer = StreamingAnalyzer()
            for trace in traces:
                analyzer.process_event(trace)

            analysis = analyzer.get_summary()
            current_value = analysis.get('latency', {}).get(metric, 0)

            if baseline_value == 0:
                return False

            delta = (current_value - baseline_value) / baseline_value
            return delta > threshold
        except Exception:
            return False

    return check


def minimize_from_files(
    baseline_file: str,
    regression_file: str,
    threshold: float = 0.10,
    metric: str = 'p99',
    min_size: int = 10,
    max_iterations: int = 100,
) -> MinimizedResult:
    """
    Minimize reproducer from trace files.

    Args:
        baseline_file: Path to baseline trace file
        regression_file: Path to regression trace file
        threshold: Regression threshold percentage
        metric: Metric to check (p50, p99, etc.)
        min_size: Minimum traces in result
        max_iterations: Maximum ddmin iterations

    Returns:
        MinimizedResult with smallest reproducing subset
    """
    import json
    from pathlib import Path
    from ..streaming import TraceFormat

    def load_traces(file_path: str) -> List[Dict[str, Any]]:
        """Load traces from file."""
        path = Path(file_path)
        traces = []

        if path.suffix == '.jsonl':
            with open(path) as f:
                for line in f:
                    traces.append(json.loads(line))
        else:
            format_detector = TraceFormat()
            fmt = format_detector.detect(path)
            with open(path, 'rb') as f:
                if fmt.has_header:
                    f.seek(fmt.header_size)
                while True:
                    data = f.read(fmt.record_size)
                    if not data or len(data) < fmt.record_size:
                        break
                    traces.append(fmt.parse_record(data))

        return traces

    baseline_traces = load_traces(baseline_file)
    regression_traces = load_traces(regression_file)

    checker = create_regression_checker(
        baseline_traces,
        threshold=threshold,
        metric=metric
    )

    return minimize_reproducer(
        regression_traces,
        checker,
        min_size=min_size,
        max_iterations=max_iterations
    )


def save_minimized(result: MinimizedResult, output_path: str):
    """Save minimized traces to file."""
    import json
    from pathlib import Path

    path = Path(output_path)

    if path.suffix == '.jsonl':
        with open(path, 'w') as f:
            for trace in result.minimized_traces:
                f.write(json.dumps(trace) + '\n')
    elif path.suffix == '.json':
        with open(path, 'w') as f:
            json.dump({
                'metadata': {
                    'original_count': result.original_count,
                    'minimized_count': result.minimized_count,
                    'reduction_pct': result.reduction_pct,
                    'iterations': result.iterations,
                    'preserved_behavior': result.preserved_behavior,
                },
                'traces': result.minimized_traces,
            }, f, indent=2)
    else:
        raise ValueError(f"Unsupported output format: {path.suffix}")
