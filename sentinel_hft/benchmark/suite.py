"""
HFT Benchmark Suite.

Provides realistic workloads for testing latency analysis tools:
- Market open scenarios (high message rate)
- Steady state trading
- News events / volatility spikes
- End of day
"""

import json
import random
import struct
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, Any, List, Optional, Generator, Callable
import hashlib


class WorkloadType(Enum):
    """Types of HFT workloads."""
    MARKET_OPEN = "market_open"
    STEADY_STATE = "steady_state"
    NEWS_SPIKE = "news_spike"
    END_OF_DAY = "end_of_day"
    LATENCY_STRESS = "latency_stress"
    THROUGHPUT_STRESS = "throughput_stress"


class MessagePattern(Enum):
    """Message arrival patterns."""
    POISSON = "poisson"
    BURSTY = "bursty"
    UNIFORM = "uniform"
    REALISTIC = "realistic"  # Mix of patterns


@dataclass
class WorkloadConfig:
    """Configuration for a benchmark workload."""
    workload_type: WorkloadType
    duration_seconds: float = 10.0
    target_rate_msg_sec: int = 100000
    message_pattern: MessagePattern = MessagePattern.REALISTIC

    # Latency injection
    base_latency_ns: int = 100
    latency_jitter_ns: int = 50
    spike_probability: float = 0.001
    spike_latency_ns: int = 10000

    # Message mix
    order_percentage: float = 30.0
    trade_percentage: float = 20.0
    cancel_percentage: float = 25.0
    market_data_percentage: float = 25.0

    # Symbols
    num_symbols: int = 100
    active_symbol_percentage: float = 20.0

    # Seed for reproducibility
    seed: Optional[int] = None


@dataclass
class BenchmarkEvent:
    """A single benchmark event."""
    timestamp_ns: int
    event_type: str
    symbol: str
    latency_ns: int
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkResult:
    """Result from running a benchmark."""
    workload_type: str
    duration_seconds: float
    total_events: int
    events_per_second: float

    # Latency stats
    latency_p50_ns: float
    latency_p90_ns: float
    latency_p99_ns: float
    latency_p999_ns: float
    latency_max_ns: float
    latency_mean_ns: float

    # Throughput
    peak_rate_msg_sec: float
    sustained_rate_msg_sec: float

    # Anomalies
    spike_count: int
    drop_count: int

    # Metadata
    config_hash: str
    timestamp: str


class HFTBenchmarkSuite:
    """
    Generate and run HFT benchmark workloads.

    Usage:
        suite = HFTBenchmarkSuite()

        # Generate a market open workload
        for event in suite.generate_workload(WorkloadConfig(
            workload_type=WorkloadType.MARKET_OPEN,
            duration_seconds=60,
            target_rate_msg_sec=500000
        )):
            analyzer.process_event(event)

        # Or run a full benchmark
        result = suite.run_benchmark(config, analyzer)
    """

    # Realistic symbol list (top traded)
    DEFAULT_SYMBOLS = [
        "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "BRK.B",
        "JPM", "JNJ", "V", "PG", "UNH", "HD", "MA", "DIS", "PYPL", "BAC",
        "ADBE", "CMCSA", "NFLX", "XOM", "VZ", "INTC", "T", "PFE", "ABT",
        "CRM", "CSCO", "PEP", "AVGO", "TMO", "COST", "ACN", "NKE", "MRK",
        "WMT", "CVX", "LLY", "DHR", "MDT", "NEE", "TXN", "QCOM", "HON",
        "UNP", "LOW", "PM", "ORCL", "BMY", "RTX", "AMGN", "IBM", "SBUX",
    ]

    # Message type weights by workload
    WORKLOAD_PROFILES = {
        WorkloadType.MARKET_OPEN: {
            'order': 40,
            'trade': 15,
            'cancel': 20,
            'market_data': 25,
            'rate_multiplier': 3.0,
            'latency_multiplier': 1.5,
        },
        WorkloadType.STEADY_STATE: {
            'order': 25,
            'trade': 25,
            'cancel': 20,
            'market_data': 30,
            'rate_multiplier': 1.0,
            'latency_multiplier': 1.0,
        },
        WorkloadType.NEWS_SPIKE: {
            'order': 35,
            'trade': 30,
            'cancel': 25,
            'market_data': 10,
            'rate_multiplier': 5.0,
            'latency_multiplier': 2.0,
        },
        WorkloadType.END_OF_DAY: {
            'order': 20,
            'trade': 35,
            'cancel': 35,
            'market_data': 10,
            'rate_multiplier': 2.0,
            'latency_multiplier': 1.2,
        },
        WorkloadType.LATENCY_STRESS: {
            'order': 25,
            'trade': 25,
            'cancel': 25,
            'market_data': 25,
            'rate_multiplier': 0.5,
            'latency_multiplier': 3.0,  # Inject more latency variance
        },
        WorkloadType.THROUGHPUT_STRESS: {
            'order': 25,
            'trade': 25,
            'cancel': 25,
            'market_data': 25,
            'rate_multiplier': 10.0,  # Maximum throughput
            'latency_multiplier': 0.8,
        },
    }

    def __init__(self, symbols: List[str] = None):
        """
        Initialize benchmark suite.

        Args:
            symbols: List of symbols to use (default: top 50 stocks)
        """
        self.symbols = symbols or self.DEFAULT_SYMBOLS

    def generate_workload(
        self,
        config: WorkloadConfig
    ) -> Generator[BenchmarkEvent, None, None]:
        """
        Generate a stream of benchmark events.

        Args:
            config: Workload configuration

        Yields:
            BenchmarkEvent objects
        """
        # Set up RNG
        rng = random.Random(config.seed)

        profile = self.WORKLOAD_PROFILES[config.workload_type]

        # Adjust rate based on profile
        effective_rate = config.target_rate_msg_sec * profile['rate_multiplier']

        # Calculate inter-arrival time
        mean_interval_ns = int(1e9 / effective_rate)

        # Active symbols (hot symbols get more traffic)
        num_active = int(len(self.symbols) * config.active_symbol_percentage / 100)
        active_symbols = rng.sample(self.symbols, num_active)

        # Message type weights
        weights = [
            profile['order'],
            profile['trade'],
            profile['cancel'],
            profile['market_data'],
        ]
        msg_types = ['order', 'trade', 'cancel', 'market_data']

        # Generate events
        start_time_ns = 0
        current_time_ns = 0
        event_count = 0
        duration_ns = int(config.duration_seconds * 1e9)

        while current_time_ns < duration_ns:
            # Determine inter-arrival time based on pattern
            if config.message_pattern == MessagePattern.POISSON:
                interval = int(rng.expovariate(1.0 / mean_interval_ns))
            elif config.message_pattern == MessagePattern.BURSTY:
                # Bursts of 10-50 messages, then gaps
                if rng.random() < 0.1:
                    interval = mean_interval_ns * rng.randint(5, 20)
                else:
                    interval = mean_interval_ns // rng.randint(2, 5)
            elif config.message_pattern == MessagePattern.UNIFORM:
                interval = mean_interval_ns
            else:  # REALISTIC
                # Mix of patterns based on time of day simulation
                progress = current_time_ns / duration_ns
                if progress < 0.1:  # Opening burst
                    interval = mean_interval_ns // 3
                elif progress > 0.9:  # Closing activity
                    interval = mean_interval_ns // 2
                else:  # Normal
                    interval = int(mean_interval_ns * (0.8 + rng.random() * 0.4))

            current_time_ns += max(1, interval)

            # Select message type
            msg_type = rng.choices(msg_types, weights=weights)[0]

            # Select symbol (hot symbols more likely)
            if rng.random() < 0.7:  # 70% to hot symbols
                symbol = rng.choice(active_symbols)
            else:
                symbol = rng.choice(self.symbols)

            # Generate latency
            base_latency = config.base_latency_ns * profile['latency_multiplier']
            jitter = rng.gauss(0, config.latency_jitter_ns)
            latency_ns = int(base_latency + jitter)

            # Occasional spike
            if rng.random() < config.spike_probability:
                latency_ns = config.spike_latency_ns + rng.randint(0, 5000)

            latency_ns = max(1, latency_ns)  # Ensure positive

            # Create event
            event = BenchmarkEvent(
                timestamp_ns=current_time_ns,
                event_type=msg_type,
                symbol=symbol,
                latency_ns=latency_ns,
                data=self._generate_event_data(msg_type, symbol, rng),
            )

            yield event
            event_count += 1

    def _generate_event_data(
        self,
        msg_type: str,
        symbol: str,
        rng: random.Random
    ) -> Dict[str, Any]:
        """Generate realistic event data."""
        base_price = rng.uniform(10, 500)

        if msg_type == 'order':
            return {
                'order_id': rng.randint(1, 2**63),
                'side': rng.choice(['B', 'S']),
                'quantity': rng.choice([100, 200, 500, 1000, 5000]),
                'price': round(base_price * (1 + rng.gauss(0, 0.001)), 2),
                'order_type': rng.choice(['LMT', 'MKT', 'IOC']),
            }
        elif msg_type == 'trade':
            return {
                'trade_id': rng.randint(1, 2**63),
                'quantity': rng.choice([100, 200, 500]),
                'price': round(base_price, 2),
                'aggressor': rng.choice(['B', 'S']),
            }
        elif msg_type == 'cancel':
            return {
                'order_id': rng.randint(1, 2**63),
                'cancel_qty': rng.choice([100, 200, 500]),
            }
        else:  # market_data
            return {
                'bid': round(base_price * 0.999, 2),
                'ask': round(base_price * 1.001, 2),
                'bid_size': rng.choice([100, 500, 1000, 5000]),
                'ask_size': rng.choice([100, 500, 1000, 5000]),
            }

    def run_benchmark(
        self,
        config: WorkloadConfig,
        processor: Callable[[Dict[str, Any]], None]
    ) -> BenchmarkResult:
        """
        Run a complete benchmark.

        Args:
            config: Workload configuration
            processor: Function to process each event

        Returns:
            BenchmarkResult with statistics
        """
        latencies = []
        event_count = 0
        spike_count = 0
        drop_count = 0

        start_real = time.perf_counter()

        for event in self.generate_workload(config):
            event_dict = asdict(event)
            try:
                processor(event_dict)
                latencies.append(event.latency_ns)
            except Exception:
                drop_count += 1

            if event.latency_ns > config.spike_latency_ns * 0.5:
                spike_count += 1

            event_count += 1

        end_real = time.perf_counter()
        duration = end_real - start_real

        # Calculate stats
        latencies.sort()
        n = len(latencies)

        def percentile(p):
            if n == 0:
                return 0
            idx = int(n * p / 100)
            return latencies[min(idx, n - 1)]

        # Config hash for reproducibility
        config_str = json.dumps(asdict(config), sort_keys=True, default=str)
        config_hash = hashlib.sha256(config_str.encode()).hexdigest()[:12]

        return BenchmarkResult(
            workload_type=config.workload_type.value,
            duration_seconds=duration,
            total_events=event_count,
            events_per_second=event_count / duration if duration > 0 else 0,
            latency_p50_ns=percentile(50),
            latency_p90_ns=percentile(90),
            latency_p99_ns=percentile(99),
            latency_p999_ns=percentile(99.9),
            latency_max_ns=max(latencies) if latencies else 0,
            latency_mean_ns=sum(latencies) / n if n > 0 else 0,
            peak_rate_msg_sec=event_count / duration if duration > 0 else 0,
            sustained_rate_msg_sec=event_count / config.duration_seconds,
            spike_count=spike_count,
            drop_count=drop_count,
            config_hash=config_hash,
            timestamp=datetime.utcnow().isoformat() + "Z",
        )

    def write_trace_file(
        self,
        config: WorkloadConfig,
        output_path: str,
        format: str = "jsonl"
    ) -> int:
        """
        Write a benchmark workload to a trace file.

        Args:
            config: Workload configuration
            output_path: Path to write trace file
            format: Output format ("jsonl" or "binary")

        Returns:
            Number of events written
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        event_count = 0

        if format == "jsonl":
            with open(path, 'w') as f:
                for event in self.generate_workload(config):
                    f.write(json.dumps(asdict(event)) + '\n')
                    event_count += 1
        elif format == "binary":
            with open(path, 'wb') as f:
                # Write header
                f.write(b'SHFT')  # Magic
                f.write(struct.pack('<I', 1))  # Version
                f.write(struct.pack('<Q', int(config.duration_seconds * 1e9)))

                for event in self.generate_workload(config):
                    # Binary format: timestamp(8) + latency(4) + type(1) + symbol(8)
                    f.write(struct.pack('<Q', event.timestamp_ns))
                    f.write(struct.pack('<I', event.latency_ns))
                    f.write(event.event_type[0].encode())
                    f.write(event.symbol[:8].ljust(8).encode())
                    event_count += 1

        return event_count

    @staticmethod
    def get_preset(name: str) -> WorkloadConfig:
        """
        Get a preset workload configuration.

        Args:
            name: Preset name ("quick", "standard", "stress", "comprehensive")

        Returns:
            WorkloadConfig for the preset
        """
        presets = {
            'quick': WorkloadConfig(
                workload_type=WorkloadType.STEADY_STATE,
                duration_seconds=5.0,
                target_rate_msg_sec=10000,
            ),
            'standard': WorkloadConfig(
                workload_type=WorkloadType.STEADY_STATE,
                duration_seconds=30.0,
                target_rate_msg_sec=100000,
            ),
            'stress': WorkloadConfig(
                workload_type=WorkloadType.THROUGHPUT_STRESS,
                duration_seconds=60.0,
                target_rate_msg_sec=500000,
            ),
            'market_open': WorkloadConfig(
                workload_type=WorkloadType.MARKET_OPEN,
                duration_seconds=60.0,
                target_rate_msg_sec=200000,
            ),
            'comprehensive': WorkloadConfig(
                workload_type=WorkloadType.STEADY_STATE,
                duration_seconds=300.0,
                target_rate_msg_sec=100000,
                spike_probability=0.0001,
            ),
        }
        return presets.get(name, presets['standard'])
