"""Synthetic fixture generators for on-chain latency traces.

These fixtures produce deterministic, seeded record streams that
approximate the latency distribution of real venues in 2026. They are
*not* market simulations -- they generate per-stage latencies grounded
in public data (venue docs, published research, public post-mortems)
so that downstream analysis (quantile estimation, AI RCA) has
something realistic to chew on.

References for the baselines below
----------------------------------

Hyperliquid 2026:
  - L1 validator set produces ~200ms block times under normal load.
  - Sequencer ingest -> order book match typically <20ms at p50.
  - Client-side signing (Ed25519 wrapped for EVM compat) ~40-80us.
  - Publicly documented: https://hyperliquid-co.gitbook.io/hyperliquid-docs

Solana Jito 2026:
  - Slot time 400ms nominal, Jito bundle path adds ~50ms auction latency.
  - Ed25519 sign ~15-30us on modern x86.
  - RPC submit (sendBundle) ~5-12ms, leader-dependent.

dYdX v4 (Cosmos L1):
  - ~1.3s block time, ~100ms p50 ack-to-include for valid tx.

Lighter (zk-rollup):
  - Sequencer ack <5ms; L1 finality 10-20min.
  - We model ``d_inclusion`` as *sequencer ack*, not L1 finality, to
    match what a maker cares about.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Iterator, Optional

from .record import (
    OnchainRecord,
    OnchainVenue,
    OnchainAction,
    FLAG_REJECTED,
    FLAG_TIMEOUT,
    FLAG_REORG,
    FLAG_LANDED,
    ONCHAIN_FORMAT_VERSION,
    symbol_hash,
)


# Jitter helpers --------------------------------------------------------


def _lognormal(rng: random.Random, median_ns: int, sigma: float = 0.35) -> int:
    """Sample a log-normal latency with given median. Positive-only."""
    import math
    mu = math.log(max(1, median_ns))
    v = rng.lognormvariate(mu, sigma)
    return max(1, int(v))


def _spike(rng: random.Random, baseline_ns: int, factor_mean: float = 2.0) -> int:
    """Occasional heavy-tail spike. Used to inject realistic tail events.

    ``factor_mean`` of 2.0 means the *additional* multiplier is expo-
    distributed with mean 2 -- so most spikes are 2-4x baseline and
    the p999 sits around 6-8x, which tracks the shape of observed
    venue tail distributions rather than blowing up into 100x outliers.
    """
    factor = rng.expovariate(1.0 / factor_mean)
    return int(baseline_ns * (1.0 + factor))


# Base class ------------------------------------------------------------


@dataclass
class FixtureProfile:
    """Per-venue latency profile. All values in nanoseconds."""

    venue: OnchainVenue
    name: str

    # Median per-stage latencies (log-normal centers).
    d_rpc_ns: int
    d_quote_ns: int
    d_sign_ns: int
    d_submit_ns: int
    d_inclusion_ns: int

    # Jitter sigma for log-normal; larger = fatter tail.
    sigma: float = 0.35

    # Probability of a heavy-tail spike on any single stage per record.
    spike_prob: float = 0.02

    # Probability of a non-ack outcome.
    reject_rate: float = 0.005
    timeout_rate: float = 0.002
    reorg_rate: float = 0.0


# Realistic 2026 profiles -----------------------------------------------

HYPERLIQUID_PROFILE = FixtureProfile(
    venue=OnchainVenue.HYPERLIQUID,
    name="hyperliquid-mainnet",
    # RPC is colocated WebSocket delta; very fast.
    d_rpc_ns=120_000,                # 120us
    d_quote_ns=25_000,                # 25us strategy decision
    d_sign_ns=60_000,                 # 60us Ed25519 wrapped
    d_submit_ns=8_000_000,            # 8ms to sequencer
    d_inclusion_ns=200_000_000,       # 200ms block time
    sigma=0.30,
    spike_prob=0.03,
    reject_rate=0.003,
    timeout_rate=0.0005,
    reorg_rate=0.0,
)

SOLANA_JITO_PROFILE = FixtureProfile(
    venue=OnchainVenue.SOLANA_JITO,
    name="solana-jito",
    d_rpc_ns=800_000,                 # 800us geyser
    d_quote_ns=40_000,                 # 40us
    d_sign_ns=20_000,                  # 20us Ed25519 native
    d_submit_ns=12_000_000,            # 12ms sendBundle
    d_inclusion_ns=400_000_000,        # 400ms slot
    sigma=0.45,                        # Solana has wider variance
    spike_prob=0.06,
    reject_rate=0.008,                 # higher due to bundle auction
    timeout_rate=0.002,
    reorg_rate=0.001,
)

DYDX_V4_PROFILE = FixtureProfile(
    venue=OnchainVenue.DYDX_V4,
    name="dydx-v4",
    d_rpc_ns=300_000,
    d_quote_ns=30_000,
    d_sign_ns=80_000,                 # secp256k1 Cosmos
    d_submit_ns=15_000_000,
    d_inclusion_ns=1_300_000_000,     # 1.3s
    sigma=0.35,
    spike_prob=0.02,
    reject_rate=0.002,
    timeout_rate=0.001,
    reorg_rate=0.0,
)

LIGHTER_PROFILE = FixtureProfile(
    venue=OnchainVenue.LIGHTER,
    name="lighter",
    d_rpc_ns=200_000,
    d_quote_ns=25_000,
    d_sign_ns=30_000,
    d_submit_ns=2_000_000,             # 2ms to sequencer
    d_inclusion_ns=4_000_000,          # 4ms sequencer ack
    sigma=0.25,
    spike_prob=0.01,
    reject_rate=0.001,
    timeout_rate=0.0,
    reorg_rate=0.0,
)


# Generators ------------------------------------------------------------


class _BaseFixture:
    """Common fixture scaffolding: seeded RNG, record builder."""

    def __init__(self, profile: FixtureProfile, symbol: str = "BTC-USD",
                 seed: int = 0, base_ts_ns: Optional[int] = None):
        self.profile = profile
        self.symbol = symbol
        self.rng = random.Random(seed)
        # Fixed base timestamp so fixtures are deterministic across runs.
        self.base_ts_ns = (
            base_ts_ns if base_ts_ns is not None else 1_713_600_000_000_000_000
        )
        self._seq = 0
        self._symbol_hash = symbol_hash(symbol)

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _sample_record(self, action: OnchainAction = OnchainAction.QUOTE,
                       inter_arrival_ns: int = 1_000_000) -> OnchainRecord:
        """Produce one synthetic record, advancing the timestamp cursor."""
        p = self.profile

        d_rpc = _lognormal(self.rng, p.d_rpc_ns, p.sigma)
        d_quote = _lognormal(self.rng, p.d_quote_ns, p.sigma)
        d_sign = _lognormal(self.rng, p.d_sign_ns, p.sigma)
        d_submit = _lognormal(self.rng, p.d_submit_ns, p.sigma)
        d_inclusion = _lognormal(self.rng, p.d_inclusion_ns, p.sigma)

        # Occasional heavy-tail spikes. Each stage is rolled independently.
        if self.rng.random() < p.spike_prob:
            d_sign = _spike(self.rng, d_sign)
        if self.rng.random() < p.spike_prob:
            d_submit = _spike(self.rng, d_submit)
        if self.rng.random() < p.spike_prob * 0.5:
            d_inclusion = _spike(self.rng, d_inclusion)

        # Wall-clock timestamps. ``client_ts`` anchors the chain; each
        # subsequent ts is the previous + current stage delta. This
        # models ideal ordering without scheduler preemption.
        client_ts = self.base_ts_ns + inter_arrival_ns * self._next_seq()
        signed_ts = client_ts + d_rpc + d_quote + d_sign
        submitted_ts = signed_ts + d_submit
        included_ts = submitted_ts + d_inclusion

        # Scheduler jitter: with small probability add a gap that bloats
        # the overhead bucket without being captured in stage deltas.
        # This is the whole point of keeping an "overhead" quantile --
        # scheduler preemption, GC pause, NUMA miss, VM pause, etc.
        if self.rng.random() < 0.05:
            jitter = self.rng.randint(500_000, 5_000_000)  # 0.5-5ms
            included_ts += jitter

        # Outcome flags.
        flags = 0
        if self.rng.random() < p.reject_rate:
            flags |= FLAG_REJECTED
        elif self.rng.random() < p.timeout_rate:
            flags |= FLAG_TIMEOUT
        else:
            flags |= FLAG_LANDED
            if self.rng.random() < p.reorg_rate:
                flags |= FLAG_REORG

        # Synthetic sizing.
        notional_usd = self.rng.uniform(1_000, 50_000)
        slippage = int(self.rng.gauss(0, 1.5))

        return OnchainRecord(
            version=ONCHAIN_FORMAT_VERSION,
            venue=int(p.venue),
            action=int(action),
            flags=flags,
            seq_no=self._seq,
            client_ts_ns=client_ts,
            signed_ts_ns=signed_ts,
            submitted_ts_ns=submitted_ts,
            included_ts_ns=included_ts,
            symbol_hash=self._symbol_hash,
            d_rpc_ns=d_rpc,
            d_quote_ns=d_quote,
            d_sign_ns=d_sign,
            d_submit_ns=d_submit,
            d_inclusion_ns=d_inclusion,
            notional_usd_e4=int(notional_usd * 10000),
            slippage_bps=slippage,
            reserved=0,
        )

    def generate(self, n: int, action: OnchainAction = OnchainAction.QUOTE,
                 inter_arrival_ns: int = 1_000_000) -> Iterator[OnchainRecord]:
        for _ in range(n):
            yield self._sample_record(action=action,
                                       inter_arrival_ns=inter_arrival_ns)


class HyperliquidFixture(_BaseFixture):
    """Realistic Hyperliquid-like latency distribution (2026 baseline)."""

    def __init__(self, symbol: str = "BTC", seed: int = 0,
                 base_ts_ns: Optional[int] = None):
        super().__init__(HYPERLIQUID_PROFILE, symbol=symbol, seed=seed,
                         base_ts_ns=base_ts_ns)


class SolanaFixture(_BaseFixture):
    """Realistic Solana Jito bundle-path latency distribution."""

    def __init__(self, symbol: str = "SOL-USDC", seed: int = 0,
                 base_ts_ns: Optional[int] = None):
        super().__init__(SOLANA_JITO_PROFILE, symbol=symbol, seed=seed,
                         base_ts_ns=base_ts_ns)


class DydxV4Fixture(_BaseFixture):
    """dYdX v4 Cosmos-chain latency distribution."""

    def __init__(self, symbol: str = "BTC-USD", seed: int = 0,
                 base_ts_ns: Optional[int] = None):
        super().__init__(DYDX_V4_PROFILE, symbol=symbol, seed=seed,
                         base_ts_ns=base_ts_ns)


class LighterFixture(_BaseFixture):
    """Lighter zk-rollup sequencer-ack latency distribution."""

    def __init__(self, symbol: str = "ETH-USD", seed: int = 0,
                 base_ts_ns: Optional[int] = None):
        super().__init__(LIGHTER_PROFILE, symbol=symbol, seed=seed,
                         base_ts_ns=base_ts_ns)


def generate_fixture(venue: str = "hyperliquid", n: int = 10_000,
                     seed: int = 0, symbol: Optional[str] = None
                     ) -> Iterator[OnchainRecord]:
    """Venue-by-name convenience dispatcher.

    ``venue`` is one of ``hyperliquid``, ``solana``, ``solana_jito``,
    ``dydx_v4``, ``dydx``, ``lighter``. Unknown venues raise ValueError.
    """
    key = venue.lower().replace("-", "_")
    if key in ("hyperliquid", "hl"):
        gen = HyperliquidFixture(symbol=symbol or "BTC", seed=seed)
    elif key in ("solana", "solana_jito", "sol_jito", "jito"):
        gen = SolanaFixture(symbol=symbol or "SOL-USDC", seed=seed)
    elif key in ("dydx_v4", "dydx", "dydx4"):
        gen = DydxV4Fixture(symbol=symbol or "BTC-USD", seed=seed)
    elif key in ("lighter",):
        gen = LighterFixture(symbol=symbol or "ETH-USD", seed=seed)
    else:
        raise ValueError(
            f"unknown venue {venue!r}; choose hyperliquid, solana, "
            f"dydx_v4, or lighter"
        )
    yield from gen.generate(n)


__all__ = [
    "FixtureProfile",
    "HYPERLIQUID_PROFILE",
    "SOLANA_JITO_PROFILE",
    "DYDX_V4_PROFILE",
    "LIGHTER_PROFILE",
    "HyperliquidFixture",
    "SolanaFixture",
    "DydxV4Fixture",
    "LighterFixture",
    "generate_fixture",
]
