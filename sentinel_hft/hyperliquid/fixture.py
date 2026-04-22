"""Seeded Hyperliquid-shaped tick fixture.

The fixture replays the structure of Hyperliquid's public perp feed:
per-instrument quote (BBO) snapshots and public trade prints, both
produced deterministically from a seeded RNG so CI can regression-
diff two runs.

Key differences from the Deribit fixture
----------------------------------------

1. **Taker identity.** Each trade carries a ``taker_id`` (an integer
   hash of the original wallet address -- Hyperliquid exposes a
   ``user`` field on every public trade). The risk pipeline uses this
   to score adverse selection per counterparty.

2. **Taker profiles.** The fixture models a small population of
   traders with distinct post-trade alpha profiles: ``TOXIC`` takers
   pick off stale quotes and the price drifts against the maker
   after their trade; ``NEUTRAL`` takers trade flat; ``BENIGN`` takers
   bleed alpha to the maker. The proportion of each controls the
   severity of the toxic flow scenario.

3. **Volatility-regime injection.** The fixture accepts an optional
   ``vol_spike`` spec: at a configured tick index the mid-price is
   jumped by N% (sign random-per-seed), quote rates jump 3-5x, and
   trade_prob doubles. This is what the kill-drill use case uses to
   exercise the kill switch without waiting for a real vol event.

The fixture emits :class:`HLTickEvent` rather than the Deribit
``TickEvent`` so the extra ``taker_id`` field is typed rather than
stuffed into a side channel. :class:`HLTickEvent` is drop-in
compatible with the Deribit ``TickEvent`` for any consumer that does
not read ``taker_id``.
"""

from __future__ import annotations

import enum
import math
import random
from dataclasses import dataclass, field
from typing import Iterable, Iterator, List, Optional, Tuple

from ..deribit.fixture import TickEvent, TickKind
from .instruments import HL_DEFAULT_UNIVERSE, HyperliquidInstrument


# ---------------------------------------------------------------------
# Taker profile
# ---------------------------------------------------------------------


class TakerProfile(enum.IntEnum):
    """Adverse-selection archetype for a counterparty.

    The numerical value is used by :class:`ToxicFlowScorer` as the
    expected post-trade mid drift (in units of instrument tick_size,
    signed to the trade direction).
    """

    TOXIC = 1
    NEUTRAL = 2
    BENIGN = 3


# Drift coefficients (signed, in ticks, applied over a small post-trade
# horizon ~5ms). Tuned so the scorer sees TOXIC takers as clearly
# negative-alpha at small N, and NEUTRAL / BENIGN as positive for the
# maker.
_PROFILE_DRIFT_TICKS = {
    TakerProfile.TOXIC: 3.5,     # price drifts 3.5 ticks with taker
    TakerProfile.NEUTRAL: 0.0,
    TakerProfile.BENIGN: -1.2,   # price reverts against taker
}


# ---------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------


@dataclass
class HLTickEvent:
    """Hyperliquid tick: same shape as ``deribit.TickEvent`` + taker id.

    Attributes mirror the Deribit event so consumers that only care
    about price/size can treat HL ticks interchangeably. The extra
    ``taker_id`` (populated on TRADE events) is the anonymised user
    identifier Hyperliquid emits on the public trade channel; the
    toxic-flow scorer groups by it.

    ``profile`` is only populated in the fixture, never on a real wire,
    so downstream consumers that compare HL vs live data should not
    rely on it. It is available so the kill-drill runner can verify it
    is scoring the right taker cohort.
    """

    wire_ts_ns: int
    host_ts_ns: int
    seq_no: int
    instrument: HyperliquidInstrument
    kind: TickKind
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float
    trade_price: float = 0.0
    trade_size: float = 0.0
    taker_id: int = 0
    profile: int = 0  # TakerProfile value for introspection only

    @property
    def mid(self) -> float:
        return 0.5 * (self.bid_price + self.ask_price)

    @property
    def spread(self) -> float:
        return self.ask_price - self.bid_price

    def as_deribit_event(self) -> TickEvent:
        """Return a Deribit-compatible :class:`TickEvent` view.

        Useful for feeding HL ticks to modules typed on the Deribit
        event (``BookState``, ``SpreadMMStrategy``) without changing
        their signatures.
        """
        return TickEvent(
            wire_ts_ns=self.wire_ts_ns,
            host_ts_ns=self.host_ts_ns,
            seq_no=self.seq_no,
            instrument=self.instrument,
            kind=self.kind,
            bid_price=self.bid_price,
            ask_price=self.ask_price,
            bid_size=self.bid_size,
            ask_size=self.ask_size,
            trade_price=self.trade_price,
            trade_size=self.trade_size,
        )


# ---------------------------------------------------------------------
# Volatility-spike injection
# ---------------------------------------------------------------------


@dataclass
class VolSpike:
    """Synthetic vol event specification.

    Parameters
    ----------
    at_tick
        1-based tick index at which the spike fires.
    magnitude
        Fractional jump applied to mid (e.g. 0.02 == 2% jump).
    direction
        +1 for up-jump, -1 for down-jump, 0 for seeded random sign.
    burst_quote_mult
        Multiply per-instrument quote_rate while the spike is active.
    burst_trade_prob
        Replace ``trade_prob`` during the spike.
    decay_ticks
        Ticks over which the burst parameters linearly decay back to
        baseline. Zero means the jump fires and the market returns to
        its baseline quote pace on the next tick (a "flash crash" that
        settles immediately).
    """

    at_tick: int
    magnitude: float = 0.02
    direction: int = 0
    burst_quote_mult: float = 4.0
    burst_trade_prob: float = 0.18
    decay_ticks: int = 250


# ---------------------------------------------------------------------
# Internal per-instrument state
# ---------------------------------------------------------------------


@dataclass
class _InstState:
    inst: HyperliquidInstrument
    mid: float
    next_event_ns: int
    vol_per_s: float


# ---------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------


class HyperliquidFixture:
    """Deterministic Hyperliquid tick stream.

    Parameters are documented on :class:`VolSpike`, :class:`TakerProfile`
    and the ``__init__`` signature below.
    """

    def __init__(
        self,
        universe: Iterable[HyperliquidInstrument] = HL_DEFAULT_UNIVERSE,
        seed: int = 0,
        base_ts_ns: int = 1_713_600_000_000_000_000,
        duration_ns: Optional[int] = None,
        trade_prob: float = 0.09,
        mean_revert: float = 0.05,
        taker_population: int = 12,
        toxic_share: float = 0.25,
        benign_share: float = 0.35,
        vol_spike: Optional[VolSpike] = None,
    ):
        if not 0 <= toxic_share <= 1 or not 0 <= benign_share <= 1:
            raise ValueError("shares must be in [0, 1]")
        if toxic_share + benign_share > 1:
            raise ValueError("toxic_share + benign_share cannot exceed 1")

        self._universe: Tuple[HyperliquidInstrument, ...] = tuple(universe)
        if not self._universe:
            raise ValueError("HyperliquidFixture: empty universe")

        self._rng = random.Random(seed)
        self._base_ts_ns = base_ts_ns
        self._duration_ns = duration_ns
        self._trade_prob = trade_prob
        self._mean_revert = mean_revert
        self._vol_spike = vol_spike
        self._seq = 0
        self._tick_index = 0

        # Build a deterministic taker population.
        self._takers: List[Tuple[int, TakerProfile]] = self._build_takers(
            taker_population, toxic_share, benign_share
        )

        # Seed per-instrument state.
        self._state: List[_InstState] = []
        for ins in self._universe:
            self._state.append(_InstState(
                inst=ins,
                mid=ins.base_price,
                next_event_ns=base_ts_ns + self._next_gap_ns(ins, 1.0),
                vol_per_s=0.0006,
            ))

        # Resolve vol-spike direction once, so replays are stable.
        if self._vol_spike is not None and self._vol_spike.direction == 0:
            # seeded coin flip, burned so the main stream RNG isn't perturbed
            sign_rng = random.Random(seed ^ 0xC0FFEE)
            self._vol_spike = VolSpike(
                at_tick=self._vol_spike.at_tick,
                magnitude=self._vol_spike.magnitude,
                direction=1 if sign_rng.random() >= 0.5 else -1,
                burst_quote_mult=self._vol_spike.burst_quote_mult,
                burst_trade_prob=self._vol_spike.burst_trade_prob,
                decay_ticks=self._vol_spike.decay_ticks,
            )

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def generate(self, n: Optional[int] = None) -> Iterator[HLTickEvent]:
        """Yield HL ticks in wall-clock order."""
        emitted = 0
        while True:
            if n is not None and emitted >= n:
                return

            idx = min(range(len(self._state)),
                      key=lambda i: self._state[i].next_event_ns)
            st = self._state[idx]

            if (self._duration_ns is not None
                    and st.next_event_ns - self._base_ts_ns > self._duration_ns):
                return

            self._tick_index += 1
            ev = self._step(st)
            yield ev
            emitted += 1

    @property
    def taker_profiles(self) -> List[Tuple[int, TakerProfile]]:
        """The frozen taker population for this fixture run.

        Intended for tests and the toxic-flow use case to verify it is
        scoring the cohorts the fixture produced.
        """
        return list(self._takers)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_takers(
        self, n: int, toxic_share: float, benign_share: float,
    ) -> List[Tuple[int, TakerProfile]]:
        toxic_n = int(round(n * toxic_share))
        benign_n = int(round(n * benign_share))
        neutral_n = max(0, n - toxic_n - benign_n)
        takers: List[Tuple[int, TakerProfile]] = []
        base_id = 0xA000_0000
        for i in range(toxic_n):
            takers.append((base_id + i, TakerProfile.TOXIC))
        for i in range(neutral_n):
            takers.append((base_id + 0x100 + i, TakerProfile.NEUTRAL))
        for i in range(benign_n):
            takers.append((base_id + 0x200 + i, TakerProfile.BENIGN))
        return takers

    def _next_gap_ns(self, ins: HyperliquidInstrument, rate_mult: float) -> int:
        rate_per_ns = (ins.quote_rate * rate_mult) / 1_000_000_000.0
        if rate_per_ns <= 0:
            return 10_000_000_000
        u = max(self._rng.random(), 1e-12)
        return max(1, int(-math.log(u) / rate_per_ns))

    def _current_spike_state(self) -> Tuple[float, float, Optional[int]]:
        """Return (quote_rate_mult, trade_prob, jump_sign_or_None)."""
        spike = self._vol_spike
        if spike is None:
            return 1.0, self._trade_prob, None

        delta = self._tick_index - spike.at_tick
        if delta < 0:
            return 1.0, self._trade_prob, None
        if delta == 0:
            return spike.burst_quote_mult, spike.burst_trade_prob, spike.direction

        # Linearly decay back to baseline over decay_ticks.
        if spike.decay_ticks <= 0 or delta >= spike.decay_ticks:
            return 1.0, self._trade_prob, None
        frac = 1.0 - (delta / spike.decay_ticks)
        mult = 1.0 + (spike.burst_quote_mult - 1.0) * frac
        tprob = self._trade_prob + (spike.burst_trade_prob - self._trade_prob) * frac
        return mult, tprob, None  # only the firing tick carries the jump

    def _step(self, st: _InstState) -> HLTickEvent:
        ins = st.inst
        mult, trade_prob, jump_sign = self._current_spike_state()

        # Mean-reverting GBM step.
        dt_s = (st.next_event_ns - self._base_ts_ns) / 1_000_000_000.0
        drift = -self._mean_revert * math.log(
            max(1e-9, st.mid / ins.base_price)
        ) * max(1e-6, dt_s / 1e6)
        shock = self._rng.gauss(0.0, st.vol_per_s)
        st.mid = max(ins.tick_size, st.mid * math.exp(drift + shock))

        # Apply spike jump on the firing tick.
        if jump_sign is not None:
            spike = self._vol_spike
            assert spike is not None
            st.mid = max(ins.tick_size,
                         st.mid * (1.0 + spike.magnitude * jump_sign))

        # Tight spread for perps; spreads widen during vol bursts.
        half_spread = ins.tick_size * (1.0 + 2.0 * (mult - 1.0))
        bid = self._round_tick(st.mid - half_spread, ins.tick_size)
        ask = self._round_tick(st.mid + half_spread, ins.tick_size)
        if ask <= bid:
            ask = bid + ins.tick_size

        bid_size = self._rng.uniform(0.5, 5.0) * ins.lot_size
        ask_size = self._rng.uniform(0.5, 5.0) * ins.lot_size

        wire_ts = st.next_event_ns
        host_ts = wire_ts + self._rng.randint(40, 480)

        self._seq += 1
        kind = TickKind.QUOTE
        trade_price = 0.0
        trade_size = 0.0
        taker_id = 0
        profile_val = 0

        if self._rng.random() < trade_prob:
            kind = TickKind.TRADE
            tk = self._rng.choice(self._takers)
            taker_id = tk[0]
            profile_val = int(tk[1])
            # Direction: toxic takers disproportionately lift the ask
            # (buy against a stale maker bid) and hit the bid when
            # price is about to fall. Model that with a light directional
            # bias for the TOXIC profile; NEUTRAL / BENIGN trade
            # uniformly.
            if tk[1] == TakerProfile.TOXIC:
                lift_ask = self._rng.random() < 0.65
            else:
                lift_ask = self._rng.random() < 0.5
            if lift_ask:
                trade_price = ask
            else:
                trade_price = bid
            trade_size = self._rng.uniform(0.1, 1.8) * ins.lot_size

            # Nudge the mid post-trade by the profile's expected drift.
            # This is what a post-trade alpha scorer will measure.
            drift_ticks = _PROFILE_DRIFT_TICKS[tk[1]]
            # Sign by trade direction: a toxic buy should push mid up.
            sign = 1.0 if lift_ask else -1.0
            st.mid = max(ins.tick_size,
                         st.mid + sign * drift_ticks * ins.tick_size * 0.25)

        ev = HLTickEvent(
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
            taker_id=taker_id,
            profile=profile_val,
        )

        st.next_event_ns += self._next_gap_ns(ins, mult)
        return ev

    @staticmethod
    def _round_tick(x: float, tick: float) -> float:
        return round(round(x / tick) * tick, 10)


def generate_hl_ticks(
    n: int = 10_000,
    seed: int = 0,
    universe: Iterable[HyperliquidInstrument] = HL_DEFAULT_UNIVERSE,
    **kwargs,
) -> Iterator[HLTickEvent]:
    """Convenience: build a fixture and yield ``n`` events."""
    return HyperliquidFixture(
        universe=universe, seed=seed, **kwargs,
    ).generate(n=n)


__all__ = [
    "TakerProfile",
    "VolSpike",
    "HLTickEvent",
    "HyperliquidFixture",
    "generate_hl_ticks",
]
