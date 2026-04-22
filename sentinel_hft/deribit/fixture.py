"""Seeded tick fixture for the Deribit LD4 demo.

The fixture emits a stream of :class:`TickEvent` objects that mimic
what a market-data handler colocated at LD4 would receive from
Deribit's public feed: best-bid/best-offer updates and trade prints.

Key design choices:

* **Deterministic.** A seed parameterises every RNG draw, so a test
  run or demo replay produces an identical stream -- essential for
  regression diffs against an audit log.

* **Poisson arrivals.** Per-instrument quote updates arrive at a
  rate proportional to the instrument's ``quote_rate`` (ticks/sec).
  This captures the bursty, uncorrelated-between-instrument nature
  of real venue feeds without modelling the book microstructure.

* **Mean-reverting mid.** Mid-prices random-walk around the
  instrument's ``base_price`` with a mild mean-reverting drift. No
  cointegration or real options pricing -- the analysis pipeline
  only cares about *latency*, not that the volatility surface is
  arbitrage-free.

* **Co-located wall clock.** Each tick carries a ``wire_ts_ns``
  which is what the FPGA would stamp at the network interface, and
  a ``host_ts_ns`` set to ``wire_ts_ns`` + a small ingress jitter.
"""

from __future__ import annotations

import enum
import math
import random
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional, Tuple

from .instruments import (
    DEFAULT_UNIVERSE,
    Instrument,
    InstrumentKind,
)


class TickKind(enum.IntEnum):
    """Kind of market-data event emitted by the fixture."""

    QUOTE = 1   # best-bid/offer update
    TRADE = 2   # public trade print


@dataclass
class TickEvent:
    """One market-data event.

    Prices are floats for readability; the pipeline converts to
    fixed-point integers at the risk-gate boundary so nothing in
    the audit layer ever sees a float.
    """

    wire_ts_ns: int
    host_ts_ns: int
    seq_no: int
    instrument: Instrument
    kind: TickKind
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float
    trade_price: float = 0.0
    trade_size: float = 0.0

    @property
    def mid(self) -> float:
        return 0.5 * (self.bid_price + self.ask_price)

    @property
    def spread(self) -> float:
        return self.ask_price - self.bid_price


# Internal per-instrument state --------------------------------------


@dataclass
class _InstState:
    """Random-walk + Poisson clock state for one instrument."""

    inst: Instrument
    mid: float
    next_event_ns: int
    vol_per_s: float             # per-second volatility of log mid


class DeribitFixture:
    """Generate a deterministic Deribit-shaped tick stream."""

    def __init__(
        self,
        universe: Iterable[Instrument] = DEFAULT_UNIVERSE,
        seed: int = 0,
        base_ts_ns: int = 1_713_600_000_000_000_000,
        duration_ns: Optional[int] = None,
        trade_prob: float = 0.08,
        mean_revert: float = 0.05,
    ):
        """Parameters
        ----------
        universe
            Instruments to simulate.
        seed
            RNG seed.
        base_ts_ns
            Wall-clock start (ns). The default is a fixed epoch so
            that artifacts hash stably across machines.
        duration_ns
            When set, ``generate()`` stops emitting once the
            simulation clock exceeds this horizon. ``None`` means
            only the ``n`` parameter to ``generate()`` limits the
            stream.
        trade_prob
            Probability that a quote event is also accompanied by a
            trade print. Empirically ~5-10% on liquid Deribit perps.
        mean_revert
            Strength of pull toward ``base_price`` per second of
            simulated time. Prevents the random walk from drifting
            arbitrarily far.
        """
        self._universe: Tuple[Instrument, ...] = tuple(universe)
        if not self._universe:
            raise ValueError("DeribitFixture: empty universe")

        self._rng = random.Random(seed)
        self._base_ts_ns = base_ts_ns
        self._duration_ns = duration_ns
        self._trade_prob = trade_prob
        self._mean_revert = mean_revert
        self._seq = 0

        # Seed per-instrument state. Volatility scales with quote
        # rate so liquid perps move faster than thin options.
        self._state: List[_InstState] = []
        for ins in self._universe:
            # Rough annual vol mapped into a small per-step scale.
            if ins.kind == InstrumentKind.PERPETUAL:
                vol_per_s = 0.0005  # ~0.05%/s
            elif ins.kind == InstrumentKind.OPTION:
                vol_per_s = 0.001   # options premia move faster
            else:
                vol_per_s = 0.0003
            self._state.append(_InstState(
                inst=ins,
                mid=ins.base_price,
                next_event_ns=base_ts_ns + self._next_gap_ns(ins),
                vol_per_s=vol_per_s,
            ))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, n: Optional[int] = None) -> Iterator[TickEvent]:
        """Yield tick events in wall-clock order.

        Stops when:

        * ``n`` events have been emitted (if given), or
        * ``duration_ns`` is exceeded (if given), or
        * both limits fire; whichever comes first.
        """
        emitted = 0
        while True:
            if n is not None and emitted >= n:
                return

            # Pick the next-to-fire instrument (earliest next_event_ns).
            idx = min(range(len(self._state)),
                      key=lambda i: self._state[i].next_event_ns)
            st = self._state[idx]

            if (self._duration_ns is not None
                    and st.next_event_ns - self._base_ts_ns > self._duration_ns):
                return

            ev = self._step(st)
            yield ev
            emitted += 1

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_gap_ns(self, ins: Instrument) -> int:
        """Exponential inter-arrival with rate = ins.quote_rate / s."""
        rate_per_ns = ins.quote_rate / 1_000_000_000.0
        if rate_per_ns <= 0:
            return 10_000_000_000  # 10s fallback
        u = max(self._rng.random(), 1e-12)
        return max(1, int(-math.log(u) / rate_per_ns))

    def _step(self, st: _InstState) -> TickEvent:
        """Advance one instrument's state and return the event."""
        ins = st.inst
        # Time since base in seconds for the mean-revert drift.
        dt_s = (st.next_event_ns - self._base_ts_ns) / 1_000_000_000.0
        # GBM-ish step with mean reversion toward base_price.
        drift = -self._mean_revert * math.log(
            max(1e-9, st.mid / ins.base_price)
        ) * max(1e-6, dt_s / 1e6)
        shock = self._rng.gauss(0.0, st.vol_per_s)
        st.mid = max(ins.tick_size, st.mid * math.exp(drift + shock))

        # Build a synthetic book: one tick on each side, random-ish
        # size. Tight spread for perps, wider for options.
        if ins.kind == InstrumentKind.PERPETUAL:
            half_spread = ins.tick_size
        elif ins.kind == InstrumentKind.FUTURE:
            half_spread = ins.tick_size * 2
        else:
            half_spread = max(ins.tick_size, st.mid * 0.005)

        bid = self._round_tick(st.mid - half_spread, ins.tick_size)
        ask = self._round_tick(st.mid + half_spread, ins.tick_size)
        if ask <= bid:
            ask = bid + ins.tick_size

        bid_size = self._rng.uniform(0.5, 5.0) * ins.lot_size
        ask_size = self._rng.uniform(0.5, 5.0) * ins.lot_size

        # Timestamps: wire is the "arrived at FPGA MAC" time, host
        # adds a jittered delay to model software ingestion.
        wire_ts = st.next_event_ns
        host_ts = wire_ts + self._rng.randint(50, 600)

        self._seq += 1
        kind = TickKind.QUOTE
        trade_price = 0.0
        trade_size = 0.0
        if self._rng.random() < self._trade_prob:
            kind = TickKind.TRADE
            # Trade crosses into one side of the book with small size.
            if self._rng.random() < 0.5:
                trade_price = bid
                trade_size = self._rng.uniform(0.1, 1.5) * ins.lot_size
            else:
                trade_price = ask
                trade_size = self._rng.uniform(0.1, 1.5) * ins.lot_size

        ev = TickEvent(
            wire_ts_ns=wire_ts,
            host_ts_ns=host_ts,
            seq_no=self._seq,
            instrument=ins,
            kind=kind,
            bid_price=bid,
            ask_price=ask,
            bid_size=bid_size,
            ask_size=ask_size,
            trade_price=trade_price,
            trade_size=trade_size,
        )

        # Schedule next event for this instrument.
        st.next_event_ns += self._next_gap_ns(ins)
        return ev

    @staticmethod
    def _round_tick(x: float, tick: float) -> float:
        return round(round(x / tick) * tick, 10)


def generate_ticks(
    n: int = 10_000,
    seed: int = 0,
    universe: Iterable[Instrument] = DEFAULT_UNIVERSE,
    duration_ns: Optional[int] = None,
) -> Iterator[TickEvent]:
    """Convenience wrapper: build a fixture and yield ``n`` events."""
    return DeribitFixture(
        universe=universe, seed=seed, duration_ns=duration_ns
    ).generate(n=n)


__all__ = [
    "TickKind",
    "TickEvent",
    "DeribitFixture",
    "generate_ticks",
]
