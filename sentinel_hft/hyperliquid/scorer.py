"""Post-trade adverse-selection scorer for Hyperliquid flow.

Adverse selection ("toxic flow") is the single biggest PnL leak for
a market-maker running a passive book. Every time a taker crosses
the spread and the mid-price *continues* in the taker's direction
over the next few ms, the maker's fill was priced wrong and the
counterparty walked away with a positive edge. This module measures
that edge per taker wallet and lets the risk pipeline reject new
quotes when the recent flow on a given side is dominated by
counterparties with a sustained adverse edge.

Two primitives:

* :class:`ToxicFlowScorer` consumes ticks (quotes + trades) and
  builds a running :class:`TakerScorecard` per wallet. Each trade
  gets a post-trade drift measurement once a follow-up mid is seen
  inside the configured horizon.

* :class:`ToxicFlowGuard` inspects a prospective
  :class:`~sentinel_hft.deribit.strategy.QuoteIntent` and returns a
  reject reason (``RejectReason.TOXIC_FLOW``) when the recent
  toxic-weighted flow on the intent's side exceeds a threshold.

The scorer is online and allocation-light: no dataframes, no numpy.
It carries a single list of "open" trades whose horizon has not
elapsed, plus a small per-taker dict. Complexity is O(open_trades)
per quote tick, which is bounded by the product of trade_rate *
horizon_ns and is typically < 20.

Symmetry with the synthetic fixture
-----------------------------------

In simulation, :class:`sentinel_hft.hyperliquid.fixture.HyperliquidFixture`
stamps a ``profile`` (TOXIC / NEUTRAL / BENIGN) onto each trade
event. The scorer ignores that stamp and learns the profile from
behavior alone, so the same code path runs on real Hyperliquid
WebSocket data where the profile stamp does not exist. The tests
cross-check that the *learned* classification matches the synthetic
stamp once the scorecard has enough observations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..audit import RejectReason
from ..deribit.strategy import QuoteIntent, Side
from .fixture import HLTickEvent, TakerProfile
from ..deribit.fixture import TickKind


# ---------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------


@dataclass
class TakerOutcome:
    """One post-trade observation awaiting horizon fill-in.

    ``drift_ticks`` is signed against the taker's direction: positive
    means the mid moved *with* the taker (adverse for the maker),
    negative means the mid reverted (good for the maker).
    """

    taker_id: int
    instrument_id: int
    lifted_ask: bool           # True if taker bought (lifted ask)
    trade_price: float
    trade_ts_ns: int
    horizon_ns: int
    tick_size: float
    mid_at_trade: float
    mid_after: float = 0.0
    drift_ticks: float = 0.0
    settled: bool = False

    def settle(self, mid_after: float) -> None:
        """Close out with the horizon-end mid."""
        self.mid_after = mid_after
        raw = mid_after - self.mid_at_trade
        sign = 1.0 if self.lifted_ask else -1.0
        self.drift_ticks = sign * raw / max(1e-9, self.tick_size)
        self.settled = True


@dataclass
class TakerScorecard:
    """Running stats for one counterparty wallet.

    ``ewma_drift_ticks`` is the exponentially-weighted average
    drift (with decay ``EWMA_ALPHA``) over all settled outcomes
    so far. ``profile`` is the learned classification once
    ``MIN_TRADES_FOR_CLASSIFY`` trades have settled.
    """

    taker_id: int
    trades: int = 0
    settled: int = 0
    total_drift_ticks: float = 0.0
    ewma_drift_ticks: float = 0.0
    first_seen_ns: int = 0
    last_seen_ns: int = 0
    profile: TakerProfile = TakerProfile.NEUTRAL

    def touch(self, ts_ns: int) -> None:
        if self.first_seen_ns == 0:
            self.first_seen_ns = ts_ns
        self.last_seen_ns = ts_ns

    @property
    def mean_drift_ticks(self) -> float:
        if self.settled == 0:
            return 0.0
        return self.total_drift_ticks / self.settled


# ---------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------


class ToxicFlowScorer:
    """Online post-trade adverse-selection scorer.

    Parameters
    ----------
    horizon_ns
        Time window over which post-trade drift is measured. 5 ms is
        the conventional "one round-trip on a fast CEX" horizon and
        also empirically separates stale-pickoff behavior from random
        noise on HL.
    ewma_alpha
        Smoothing factor on the per-taker drift estimate. 0.1 means
        the last ~10 observations dominate.
    min_trades_for_classify
        Number of settled trades before a taker is moved out of
        NEUTRAL and into TOXIC / BENIGN.
    toxic_ticks
        Sustained EWMA drift (in instrument ticks) above which a
        taker is tagged TOXIC.
    benign_ticks
        Sustained EWMA drift below which a taker is tagged BENIGN
        (i.e., price reverts against them post-trade).
    flow_window_ns
        Trailing window used by :meth:`toxic_flow_rate` and consumed
        by :class:`ToxicFlowGuard`. 500 ms by default.
    """

    EWMA_ALPHA = 0.10
    MIN_TRADES_FOR_CLASSIFY = 4

    def __init__(
        self,
        horizon_ns: int = 5_000_000,
        ewma_alpha: float = EWMA_ALPHA,
        min_trades_for_classify: int = MIN_TRADES_FOR_CLASSIFY,
        toxic_ticks: float = 1.2,
        benign_ticks: float = -0.4,
        flow_window_ns: int = 500_000_000,
    ):
        self._horizon_ns = horizon_ns
        self._alpha = ewma_alpha
        self._min_trades = min_trades_for_classify
        self._toxic_ticks = toxic_ticks
        self._benign_ticks = benign_ticks
        self._flow_window_ns = flow_window_ns

        # Per-instrument last-seen mid (for horizon settlement).
        self._last_mid: Dict[int, float] = {}
        self._last_mid_ns: Dict[int, int] = {}

        # Open outcomes waiting for horizon fill-in.
        self._open: List[TakerOutcome] = []

        # Per-taker running stats.
        self._scorecards: Dict[int, TakerScorecard] = {}

        # Rolling flow log (settled outcomes) for guard queries.
        # Each entry: (ts_ns, instrument_id, lifted_ask, profile).
        self._flow: List[Tuple[int, int, bool, TakerProfile]] = []

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def on_tick(self, ev: HLTickEvent) -> None:
        """Consume one tick (quote or trade) and advance the scorer."""
        ins_id = ev.instrument.symbol_id
        mid = ev.mid
        if mid > 0:
            self._last_mid[ins_id] = mid
            self._last_mid_ns[ins_id] = ev.host_ts_ns
            # Settle any open outcomes whose horizon has elapsed.
            self._settle_open(ev.host_ts_ns)

        if ev.kind != TickKind.TRADE or ev.taker_id == 0:
            return

        # Record a new open outcome.
        taker_id = ev.taker_id
        sc = self._scorecards.get(taker_id)
        if sc is None:
            sc = TakerScorecard(taker_id=taker_id)
            self._scorecards[taker_id] = sc
        sc.touch(ev.host_ts_ns)
        sc.trades += 1

        lifted_ask = ev.trade_price >= ev.ask_price - 1e-9
        self._open.append(TakerOutcome(
            taker_id=taker_id,
            instrument_id=ins_id,
            lifted_ask=lifted_ask,
            trade_price=ev.trade_price,
            trade_ts_ns=ev.host_ts_ns,
            horizon_ns=self._horizon_ns,
            tick_size=ev.instrument.tick_size,
            mid_at_trade=mid if mid > 0 else ev.trade_price,
        ))

    # ------------------------------------------------------------------
    # Settlement
    # ------------------------------------------------------------------

    def _settle_open(self, now_ns: int) -> None:
        """Close outcomes whose horizon has elapsed, using latest mid."""
        if not self._open:
            return
        keep: List[TakerOutcome] = []
        for out in self._open:
            if now_ns - out.trade_ts_ns < out.horizon_ns:
                keep.append(out)
                continue
            # Use the latest seen mid for that instrument.
            mid_after = self._last_mid.get(out.instrument_id)
            if mid_after is None:
                # No new mid in horizon: treat as zero drift and move on.
                mid_after = out.mid_at_trade
            out.settle(mid_after)
            self._update_scorecard(out)
            self._flow.append((
                out.trade_ts_ns, out.instrument_id, out.lifted_ask,
                self._scorecards[out.taker_id].profile,
            ))
        self._open = keep

        # Prune the flow log to the window.
        cutoff = now_ns - self._flow_window_ns
        if self._flow and self._flow[0][0] < cutoff:
            self._flow = [f for f in self._flow if f[0] >= cutoff]

    def _update_scorecard(self, out: TakerOutcome) -> None:
        sc = self._scorecards[out.taker_id]
        sc.settled += 1
        sc.total_drift_ticks += out.drift_ticks
        if sc.settled == 1:
            sc.ewma_drift_ticks = out.drift_ticks
        else:
            sc.ewma_drift_ticks = (
                self._alpha * out.drift_ticks
                + (1.0 - self._alpha) * sc.ewma_drift_ticks
            )
        # Update classification.
        if sc.settled >= self._min_trades:
            if sc.ewma_drift_ticks >= self._toxic_ticks:
                sc.profile = TakerProfile.TOXIC
            elif sc.ewma_drift_ticks <= self._benign_ticks:
                sc.profile = TakerProfile.BENIGN
            else:
                sc.profile = TakerProfile.NEUTRAL

    # ------------------------------------------------------------------
    # Public queries
    # ------------------------------------------------------------------

    @property
    def scorecards(self) -> Dict[int, TakerScorecard]:
        return self._scorecards

    def toxic_flow_rate(
        self, instrument_id: int, side: Side, now_ns: int,
    ) -> float:
        """Fraction of recent flow on ``side`` that was toxic.

        ``side == BUY`` queries the rate of toxic flow *lifting the
        ask* (a toxic buyer picking off a maker's sell quote). Mirror
        for ``SELL``. Window is ``flow_window_ns``.
        """
        cutoff = now_ns - self._flow_window_ns
        want_lifted = (side == Side.BUY)
        match = 0
        total = 0
        for ts, ins, lifted, prof in self._flow:
            if ts < cutoff:
                continue
            if ins != instrument_id or lifted != want_lifted:
                continue
            total += 1
            if prof == TakerProfile.TOXIC:
                match += 1
        if total == 0:
            return 0.0
        return match / total

    def summary(self) -> Dict:
        toxic = 0
        neutral = 0
        benign = 0
        for sc in self._scorecards.values():
            if sc.profile == TakerProfile.TOXIC:
                toxic += 1
            elif sc.profile == TakerProfile.BENIGN:
                benign += 1
            else:
                neutral += 1
        return {
            "takers": len(self._scorecards),
            "toxic": toxic,
            "neutral": neutral,
            "benign": benign,
            "open_outcomes": len(self._open),
            "flow_events": len(self._flow),
        }


# ---------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------


class ToxicFlowGuard:
    """Pre-gate that rejects quote intents exposed to toxic flow.

    Runs *before* the risk gate's rate / position / notional checks.
    A reject here surfaces in the audit chain as
    ``RejectReason.TOXIC_FLOW`` (0x07) rather than a standard risk
    reject -- that way the DORA bundle's highlights section shows
    adverse-selection rejections separately from rate limiting and
    position caps, which is what a compliance reader expects.
    """

    def __init__(
        self,
        scorer: ToxicFlowScorer,
        *,
        toxic_rate_threshold: float = 0.55,
        min_flow_events: int = 3,
    ):
        self._scorer = scorer
        self._threshold = toxic_rate_threshold
        self._min_events = min_flow_events
        self.rejected = 0

    def check(self, intent: QuoteIntent, now_ns: int) -> RejectReason:
        """Return OK or TOXIC_FLOW.

        The check is side-aware: a BUY intent (maker posting a bid)
        is vulnerable to toxic *sellers* hitting that bid, which is
        flow lifting the bid from the maker's perspective. But in
        the HL trade stream, a taker "hitting the bid" lifts the bid
        price in the trade record (trade_price == bid), so we query
        the opposite direction via a side flip.
        """
        # Count how many flow events we actually have on the queried side.
        # If none, abstain (OK).
        opposite = Side.SELL if intent.side == Side.BUY else Side.BUY
        # Opposite because a maker's bid is lifted by a *seller* (taker hits bid).
        rate = self._scorer.toxic_flow_rate(
            intent.symbol_id, opposite, now_ns,
        )
        # Simple heuristic: if the toxic rate exceeds the threshold
        # and we've seen enough events, reject.
        if rate >= self._threshold:
            # Also require a minimum event count so we don't reject on
            # 1/1 with no statistical weight.
            total = self._count_side_events(intent.symbol_id, opposite, now_ns)
            if total >= self._min_events:
                self.rejected += 1
                return RejectReason.TOXIC_FLOW
        return RejectReason.OK

    def _count_side_events(
        self, instrument_id: int, side: Side, now_ns: int,
    ) -> int:
        cutoff = now_ns - self._scorer._flow_window_ns  # type: ignore[attr-defined]
        want_lifted = (side == Side.BUY)
        return sum(
            1 for ts, ins, lifted, _p in self._scorer._flow  # type: ignore[attr-defined]
            if ts >= cutoff and ins == instrument_id and lifted == want_lifted
        )


__all__ = [
    "TakerOutcome",
    "TakerScorecard",
    "ToxicFlowScorer",
    "ToxicFlowGuard",
]
