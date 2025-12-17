"""
Generate realistic synthetic traces for demo scenarios.

Traces are synthetic but model real FPGA behavior:
- Deterministic base latency per stage
- Variance from input-dependent paths
- Backpressure effects when FIFOs fill
- Correlated anomalies during stress
"""

import struct
import random
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional

import yaml


@dataclass
class LatencyProfile:
    """Statistical profile for latency generation."""
    mean: float
    std: float

    def sample(self, rng: random.Random = None) -> float:
        """Sample a latency value (always positive)."""
        r = rng if rng else random
        return max(1, r.gauss(self.mean, self.std))


@dataclass
class TraceConfig:
    """Configuration for trace generation."""
    trace_count: int
    message_rate: int
    duration_ms: int

    ingress: LatencyProfile
    core: LatencyProfile
    risk: LatencyProfile
    egress: LatencyProfile

    fifo_utilization: float = 0.35
    backpressure_events: int = 0

    anomalies: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class TraceRecord:
    """A single trace record matching v1.2 format."""
    seq_id: int
    timestamp_ns: int

    # Per-stage timestamps
    t_ingress: int
    t_core: int
    t_risk: int
    t_egress: int

    # Metadata
    message_type: int = 32  # Default: MDIncrementalRefreshBook
    flags: int = 0

    @property
    def total_latency(self) -> int:
        return self.t_egress - self.t_ingress

    @property
    def ingress_latency(self) -> int:
        return self.t_core - self.t_ingress

    @property
    def core_latency(self) -> int:
        return self.t_risk - self.t_core

    @property
    def risk_latency(self) -> int:
        return self.t_egress - self.t_risk

    def to_bytes(self) -> bytes:
        """Serialize to binary format (64 bytes)."""
        # Format matches v1.2: stage timestamps + metadata
        return struct.pack(
            '<QQ QQQQ II 16x',
            self.seq_id,
            self.timestamp_ns,
            self.t_ingress,
            self.t_core,
            self.t_risk,
            self.t_egress,
            self.message_type,
            self.flags,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> 'TraceRecord':
        """Deserialize from binary format."""
        unpacked = struct.unpack('<QQ QQQQ II', data[:48])
        return cls(
            seq_id=unpacked[0],
            timestamp_ns=unpacked[1],
            t_ingress=unpacked[2],
            t_core=unpacked[3],
            t_risk=unpacked[4],
            t_egress=unpacked[5],
            message_type=unpacked[6],
            flags=unpacked[7],
        )

    @classmethod
    def record_size(cls) -> int:
        return 64  # bytes


class TraceGenerator:
    """
    Generate realistic synthetic traces.

    Models:
    - Base deterministic latency per stage
    - Input-dependent variance
    - Backpressure effects
    - Correlated stress anomalies
    """

    # Trace file header
    MAGIC = b'SNTL'
    VERSION = 0x0102  # v1.2

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)

    def generate(self, config: TraceConfig) -> List[TraceRecord]:
        """Generate traces according to config."""
        traces = []

        # Calculate inter-arrival time in ns
        ns_per_msg = 1_000_000_000 / config.message_rate

        # Precompute backpressure event indices if any
        backpressure_indices = set()
        if config.backpressure_events > 0:
            bp_count = min(config.backpressure_events, config.trace_count)
            backpressure_indices = set(
                self.rng.sample(range(config.trace_count), bp_count)
            )

        current_time_ns = 0

        for i in range(config.trace_count):
            # Base timestamp with jitter
            timestamp = int(current_time_ns + self.rng.gauss(0, ns_per_msg * 0.1))
            timestamp = max(0, timestamp)

            # Stage latencies
            t_ingress = timestamp

            ingress_lat = config.ingress.sample(self.rng)
            t_core = t_ingress + int(ingress_lat)

            core_lat = config.core.sample(self.rng)
            t_risk = t_core + int(core_lat)

            risk_lat = config.risk.sample(self.rng)

            # Add backpressure effect
            if i in backpressure_indices:
                risk_lat += self.rng.gauss(45, 15)

            # Add anomaly effects
            for anomaly in config.anomalies:
                if self.rng.random() < anomaly.get('frequency', 0):
                    added = anomaly.get('added_latency_ns', {})
                    risk_lat += self.rng.gauss(
                        added.get('mean', 0),
                        added.get('std', 0)
                    )

            t_egress = t_risk + int(max(1, risk_lat))

            egress_lat = config.egress.sample(self.rng)
            t_egress += int(egress_lat)

            # Create record
            record = TraceRecord(
                seq_id=i,
                timestamp_ns=timestamp,
                t_ingress=t_ingress,
                t_core=t_core,
                t_risk=t_risk,
                t_egress=t_egress,
                message_type=self._random_message_type(),
                flags=1 if i in backpressure_indices else 0,
            )

            traces.append(record)
            current_time_ns += int(ns_per_msg)

        return traces

    def _random_message_type(self) -> int:
        """Generate realistic message type distribution."""
        # CME MDP3 message type distribution
        types = [
            (32, 0.60),  # MDIncrementalRefreshBook (60%)
            (36, 0.25),  # MDIncrementalRefreshTrade (25%)
            (48, 0.10),  # SecurityStatus (10%)
            (38, 0.05),  # SnapshotFullRefresh (5%)
        ]

        r = self.rng.random()
        cumulative = 0
        for msg_type, prob in types:
            cumulative += prob
            if r < cumulative:
                return msg_type
        return 32

    def write_trace_file(
        self,
        traces: List[TraceRecord],
        path: Path,
        provenance: Dict[str, Any] = None
    ):
        """Write traces to binary file with header."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'wb') as f:
            # Write header
            f.write(self.MAGIC)
            f.write(struct.pack('<H', self.VERSION))
            f.write(struct.pack('<I', len(traces)))
            f.write(struct.pack('<I', 100))  # clock_mhz

            # Write provenance if provided
            if provenance:
                prov_bytes = json.dumps(provenance).encode('utf-8')
                f.write(struct.pack('<I', len(prov_bytes)))
                f.write(prov_bytes)
            else:
                f.write(struct.pack('<I', 0))

            # Padding to align to 64 bytes
            current_pos = f.tell()
            padding = (64 - (current_pos % 64)) % 64
            f.write(b'\x00' * padding)

            # Write records
            for trace in traces:
                f.write(trace.to_bytes())

    def read_trace_file(self, path: Path) -> List[TraceRecord]:
        """Read traces from binary file."""
        traces = []

        with open(path, 'rb') as f:
            # Read header
            magic = f.read(4)
            if magic != self.MAGIC:
                raise ValueError(f"Invalid trace file: {path}")

            version = struct.unpack('<H', f.read(2))[0]
            count = struct.unpack('<I', f.read(4))[0]
            clock_mhz = struct.unpack('<I', f.read(4))[0]

            # Skip provenance
            prov_len = struct.unpack('<I', f.read(4))[0]
            if prov_len > 0:
                f.read(prov_len)

            # Skip to aligned position
            pos = f.tell()
            aligned = ((pos + 63) // 64) * 64
            f.seek(aligned)

            # Read records
            record_size = TraceRecord.record_size()
            for _ in range(count):
                data = f.read(record_size)
                if len(data) < record_size:
                    break
                traces.append(TraceRecord.from_bytes(data))

        return traces


def load_scenario(scenario_path: Path) -> Dict[str, Any]:
    """Load scenario from YAML file."""
    with open(scenario_path) as f:
        return yaml.safe_load(f)


def config_from_profile(profile: Dict[str, Any]) -> TraceConfig:
    """Create TraceConfig from scenario profile."""
    lat = profile['latency_profile']

    return TraceConfig(
        trace_count=profile.get('trace_count', 50000),
        message_rate=profile.get('message_rate', 2_000_000),
        duration_ms=profile.get('duration_ms', 1000),
        ingress=LatencyProfile(**lat['ingress_ns']),
        core=LatencyProfile(**lat['core_ns']),
        risk=LatencyProfile(**lat['risk_ns']),
        egress=LatencyProfile(**lat['egress_ns']),
        fifo_utilization=profile.get('fifo_utilization', 0.35),
        backpressure_events=profile.get('backpressure_events', 0),
        anomalies=profile.get('anomalies', []),
    )


def _interpolate_config(
    baseline: TraceConfig,
    incident: TraceConfig,
    pct: float
) -> TraceConfig:
    """Interpolate between two configs."""
    def lerp(a: float, b: float) -> float:
        return a + (b - a) * pct

    def lerp_profile(a: LatencyProfile, b: LatencyProfile) -> LatencyProfile:
        return LatencyProfile(
            mean=lerp(a.mean, b.mean),
            std=lerp(a.std, b.std),
        )

    return TraceConfig(
        trace_count=baseline.trace_count,
        message_rate=int(lerp(baseline.message_rate, incident.message_rate)),
        duration_ms=baseline.duration_ms,
        ingress=lerp_profile(baseline.ingress, incident.ingress),
        core=lerp_profile(baseline.core, incident.core),
        risk=lerp_profile(baseline.risk, incident.risk),
        egress=lerp_profile(baseline.egress, incident.egress),
        fifo_utilization=lerp(baseline.fifo_utilization, incident.fifo_utilization),
        backpressure_events=int(lerp(baseline.backpressure_events, incident.backpressure_events)),
        anomalies=incident.anomalies if pct > 0.5 else [],
    )


def generate_scenario_traces(
    scenario: Dict[str, Any],
    output_dir: Path,
    seed: int = 42
) -> Dict[str, Path]:
    """
    Generate all trace files for a scenario.

    Returns dict mapping trace_id -> file_path
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    generator = TraceGenerator(seed=seed)
    trace_files = {}

    # Generate baseline
    baseline_config = config_from_profile(scenario['baseline'])
    baseline_traces = generator.generate(baseline_config)
    baseline_path = output_dir / 'baseline.bin'
    generator.write_trace_file(
        baseline_traces,
        baseline_path,
        provenance={
            'scenario': scenario['scenario']['id'],
            'profile': 'baseline',
            'description': scenario['baseline']['name'],
        }
    )
    trace_files['baseline'] = baseline_path

    # Generate incident
    incident_config = config_from_profile(scenario['incident'])
    incident_traces = generator.generate(incident_config)
    incident_path = output_dir / 'incident.bin'
    generator.write_trace_file(
        incident_traces,
        incident_path,
        provenance={
            'scenario': scenario['scenario']['id'],
            'profile': 'incident',
            'description': scenario['incident']['name'],
        }
    )
    trace_files['incident'] = incident_path

    # Generate timeline traces for bisect
    for point in scenario['timeline']:
        if point['profile'] == 'baseline':
            config = baseline_config
        elif point['profile'] == 'incident':
            config = incident_config
        elif point['profile'] == 'transition':
            config = _interpolate_config(
                baseline_config,
                incident_config,
                point.get('transition_pct', 0.5)
            )
        else:
            continue

        traces = generator.generate(config)
        path = output_dir / f"{point['id']}.bin"
        generator.write_trace_file(
            traces,
            path,
            provenance={
                'scenario': scenario['scenario']['id'],
                'profile': point['profile'],
                'timestamp': point['timestamp'],
                'description': point['description'],
            }
        )
        trace_files[point['id']] = path

    return trace_files
