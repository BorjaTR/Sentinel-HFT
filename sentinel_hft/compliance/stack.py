"""
ComplianceStack - aggregate observer.

One instance of :class:`ComplianceStack` is attached to the HL runner
via an optional ``runner._compliance`` attribute.  On every intent
(NEW or CANCEL) the runner calls :meth:`ComplianceStack.observe` with
the intent, the current risk-gate decision (if known), a trader id
and the wire timestamp in ns.  The stack forwards to:

* :class:`OTRCounter`        (MiFID II RTS 6 order-to-trade ratio)
* :class:`SelfTradeGuard`    (CFTC Reg AT self-trade prevention)
* :class:`FatFingerGuard`    (FINRA 15c3-5 erroneous-order check)
* :class:`SpoofLayerDetector`(MAR Art. 12 spoofing / layering)
* :class:`CATExporter`       (SEC Rule 613 Phase 2e feed)

The stack is strictly **observational**: it never flips the
``decision.passed`` bit the real RTL gate has already spoken for.
Counters / exporters are inspected from the /sentinel/regulations
dashboard; audit-chain integrity remains the RTL gate's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .cat_export import CATExporter
from .market_abuse import SpoofLayerDetector
from .mifid_otr import OTRCounter
from .price_sanity import FatFingerGuard
from .self_trade_guard import SelfTradeGuard


# Local side / action aliases so we stay decoupled from ``deribit.strategy``
# (importing that here would create a runtime cycle through the HL runner).
_SIDE_BUY = 1
_SIDE_SELL = 2
_ACTION_NEW = 1
_ACTION_CANCEL = 2


@dataclass
class ComplianceSnapshot:
    """One polling snapshot of the live compliance counters.

    Shape is stable - the UI binds to this exact JSON layout.  Any
    key-name change must be reflected in both
    ``sentinel-web/lib/sentinel-types.ts`` and the
    ``/sentinel/regulations`` page.
    """

    mifid_otr: Dict[str, Any] = field(default_factory=dict)
    cftc_self_trade: Dict[str, Any] = field(default_factory=dict)
    finra_fat_finger: Dict[str, Any] = field(default_factory=dict)
    sec_cat: Dict[str, Any] = field(default_factory=dict)
    mar_abuse: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mifid_otr": dict(self.mifid_otr),
            "cftc_self_trade": dict(self.cftc_self_trade),
            "finra_fat_finger": dict(self.finra_fat_finger),
            "sec_cat": dict(self.sec_cat),
            "mar_abuse": dict(self.mar_abuse),
        }


@dataclass
class ComplianceStack:
    """Aggregate observer + counters for the 5 live-counter regulations."""

    #: Default trader id used when the upstream hasn't broken the
    #: strategy into multiple accounts. The demo uses one trader.
    default_trader_id: int = 1
    #: Open an NDJSON CAT feed at this path if set. ``None`` keeps the
    #: feed in-memory only (counters still tick).
    cat_output_path: Optional[str] = None

    otr: OTRCounter = field(default_factory=OTRCounter)
    self_trade: SelfTradeGuard = field(default_factory=SelfTradeGuard)
    fat_finger: FatFingerGuard = field(default_factory=FatFingerGuard)
    mar: SpoofLayerDetector = field(default_factory=SpoofLayerDetector)

    # CATExporter cannot have a default_factory with a filename; build
    # it in __post_init__ so the caller can inject a run-specific path.
    cat: Optional[CATExporter] = None

    def __post_init__(self) -> None:
        if self.cat is None:
            self.cat = CATExporter(output_path=self.cat_output_path)

    # ---- context manager for the NDJSON fd --------------------------

    def close(self) -> None:
        if self.cat is not None:
            self.cat.close()

    def __enter__(self) -> "ComplianceStack":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # ---- market-data hooks ------------------------------------------

    def on_trade(self, symbol_id: int, price: float, ts_ns: int) -> None:
        """Feed public-trade price to the reference-price store."""
        self.fat_finger.on_trade(symbol_id, price)
        self.otr.on_trade(symbol_id)

    # ---- intent hook ------------------------------------------------

    def observe(
        self,
        *,
        intent: Any,
        decision: Any,
        ts_ns: int,
        trader_id: Optional[int] = None,
    ) -> Dict[str, bool]:
        """Record one intent + gate decision.

        Returns a dict of ``{"would_reject_otr": bool,
        "would_reject_self_trade": bool, "would_reject_fat_finger": bool,
        "mar_alert": bool}`` so the runner can (optionally) surface
        compliance warnings in the trace.  Host implementation never
        flips ``decision.passed`` - that bit is owned by the RTL gate.
        """
        tid = trader_id if trader_id is not None else self.default_trader_id

        side_int = int(getattr(intent, "side", 0))
        action_int = int(getattr(intent, "action", 1))
        symbol_id = int(getattr(intent, "symbol_id", 0))
        price = float(getattr(intent, "price", 0.0))
        quantity = float(getattr(intent, "quantity", 0.0))
        order_id = int(getattr(intent, "order_id", 0))

        would_otr = False
        would_self = False
        would_fat = False
        mar_alerted = False

        is_new = (action_int == _ACTION_NEW)
        is_cancel = (action_int == _ACTION_CANCEL)

        # Only NEWs feed the OTR numerator; gate.passed decides whether
        # we also record a fill proxy.  We treat a passed NEW on the
        # book as "might fill soon" and leave true on_trade() hook to
        # flip it on a real execution.  Observation only.
        if is_new:
            filled_flag = False  # conservative; gated by on_trade()
            would_otr = self.otr.observe(symbol_id, filled=filled_flag)

            if price > 0:
                would_fat = self.fat_finger.check(symbol_id, price)
                would_self = self.self_trade.check(
                    trader_id=tid,
                    symbol_id=symbol_id,
                    side=side_int,
                    price=price,
                    quantity=quantity,
                )
                # If the decision passed and it's a NEW, it now rests
                # on the book for the self-trade check next time.
                if decision is not None and bool(getattr(
                        decision, "passed", False)):
                    self.self_trade.add_resting(
                        trader_id=tid,
                        order_id=order_id,
                        symbol_id=symbol_id,
                        side=side_int,
                        price=price,
                        quantity=quantity,
                    )
            self.mar.on_new(
                trader_id=tid,
                symbol_id=symbol_id,
                side=side_int,
                order_id=order_id,
                ts_ns=ts_ns,
            )
            # CAT: MENO (new order) always; MEOR if the gate rejected.
            passed = bool(getattr(decision, "passed", True))
            if self.cat is not None:
                if passed:
                    self.cat.new_order(
                        order_id=order_id,
                        symbol=_symbol_name(symbol_id),
                        side=_side_name(side_int),
                        price=price,
                        quantity=quantity,
                        ts_ns=ts_ns,
                    )
                else:
                    self.cat.reject(
                        order_id=order_id,
                        symbol=_symbol_name(symbol_id),
                        side=_side_name(side_int),
                        price=price,
                        quantity=quantity,
                        ts_ns=ts_ns,
                        reason=_reject_name(decision),
                    )

        elif is_cancel:
            self.self_trade.cancel(trader_id=tid, order_id=order_id)
            alert = self.mar.on_cancel(
                trader_id=tid,
                symbol_id=symbol_id,
                side=side_int,
                order_id=order_id,
                ts_ns=ts_ns,
            )
            mar_alerted = alert is not None
            if self.cat is not None:
                self.cat.cancel(
                    order_id=order_id,
                    symbol=_symbol_name(symbol_id),
                    side=_side_name(side_int),
                    price=price,
                    quantity=quantity,
                    ts_ns=ts_ns,
                )

        return {
            "would_reject_otr": would_otr,
            "would_reject_self_trade": would_self,
            "would_reject_fat_finger": would_fat,
            "mar_alert": mar_alerted,
        }

    # ---- snapshots --------------------------------------------------

    def snapshot(self) -> ComplianceSnapshot:
        return ComplianceSnapshot(
            mifid_otr=self.otr.snapshot(),
            cftc_self_trade=self.self_trade.snapshot(),
            finra_fat_finger=self.fat_finger.snapshot(),
            sec_cat=(self.cat.snapshot() if self.cat is not None else {}),
            mar_abuse=self.mar.snapshot(),
        )

    def as_dict(self) -> Dict[str, Any]:
        return self.snapshot().as_dict()


# ---- helpers -------------------------------------------------------


def _side_name(side: int) -> str:
    if side == _SIDE_BUY:
        return "B"
    if side == _SIDE_SELL:
        return "S"
    return "?"


def _symbol_name(symbol_id: int) -> str:
    """Best-effort translation from symbol id -> ticker.

    Importing the actual instrument registry would introduce a runtime
    cycle (``hyperliquid.runner`` -> ``compliance.stack`` -> ``hyperliquid``).
    The CAT record tolerates a stringified id; real deployments map
    this to their own security-master on ingest.
    """
    return f"HL-{symbol_id}"


def _reject_name(decision: Any) -> str:
    if decision is None:
        return "OK"
    reason = getattr(decision, "reject_reason", 0)
    # Keep the reject-reason enum loose - the runner's RejectReason
    # is an IntEnum; we surface the raw int if name lookup fails.
    try:
        from ..audit import RejectReason  # local import to avoid cycle
        return RejectReason(int(reason)).name
    except Exception:  # noqa: BLE001
        return f"REJ_{int(reason)}"


__all__ = [
    "ComplianceStack",
    "ComplianceSnapshot",
]
