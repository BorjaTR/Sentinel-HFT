"""
SEC Rule 613 (Consolidated Audit Trail) Phase 2e formatter.

Transforms every order event produced by the drill into the 23-field
CAT Industry Member Specification record (JSON flavour).  The spec is
a public PDF; we model the subset Sentinel-HFT can legitimately fill
in from a simulated HL session.

We emit one record per event to an NDJSON feed (default
``{output_dir}/cat_feed.ndjson``) so the resulting file is ingestible
by the real CAT Central Repository reporter.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, TextIO


CAT_EVENT_TYPES = {
    "MENO": "new_order",           # New order event
    "MECR": "cancel_route",        # Cancel or route
    "MEOM": "modify_order",        # Modification / replace
    "METR": "trade_event",         # Trade execution
    "MEOR": "order_reject",        # Order rejection
}


@dataclass
class CATRecord:
    """One CAT-2e envelope."""

    event_type: str                 # MENO | MECR | MEOM | METR | MEOR
    event_timestamp_ns: int
    order_id: int
    symbol: str
    side: str                       # B / S / SS / SX
    price: float
    quantity: float
    order_type: str                 # LMT / MKT / ...
    time_in_force: str              # DAY / IOC / ...
    account_type: str = "PROP"      # CUS | PROP | COMB
    firm_designated_id: str = "KEYROCK"
    venue_mic: str = "XHYP"         # HL placeholder MIC
    reject_reason: Optional[str] = None
    parent_order_id: Optional[int] = None

    def as_dict(self) -> Dict[str, object]:
        ts = datetime.fromtimestamp(
            self.event_timestamp_ns / 1e9, tz=timezone.utc
        ).isoformat()
        d: Dict[str, object] = {
            "eventType": self.event_type,
            "eventTypeName": CAT_EVENT_TYPES.get(self.event_type, "unknown"),
            "eventTimestamp": ts,
            "eventTimestampNs": self.event_timestamp_ns,
            "orderID": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "price": round(self.price, 8),
            "quantity": round(self.quantity, 8),
            "orderType": self.order_type,
            "timeInForce": self.time_in_force,
            "accountType": self.account_type,
            "firmDesignatedID": self.firm_designated_id,
            "venueMIC": self.venue_mic,
        }
        if self.reject_reason:
            d["rejectReason"] = self.reject_reason
        if self.parent_order_id is not None:
            d["parentOrderID"] = self.parent_order_id
        return d


@dataclass
class CATExporter:
    """Buffered NDJSON writer + counter."""

    output_path: Optional[str] = None
    _fh: Optional[TextIO] = None
    _count: int = 0
    _by_type: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.output_path:
            os.makedirs(
                os.path.dirname(self.output_path) or ".", exist_ok=True
            )
            self._fh = open(self.output_path, "w", encoding="utf-8")

    # ---- core emit --------------------------------------------------

    def emit(self, record: CATRecord) -> None:
        self._count += 1
        self._by_type[record.event_type] = (
            self._by_type.get(record.event_type, 0) + 1
        )
        if self._fh is not None:
            self._fh.write(json.dumps(record.as_dict(), separators=(",", ":")) + "\n")

    def emit_many(self, records: Iterable[CATRecord]) -> None:
        for r in records:
            self.emit(r)

    def close(self) -> None:
        if self._fh is not None:
            self._fh.flush()
            self._fh.close()
            self._fh = None

    # ---- convenience -----------------------------------------------

    def new_order(
        self,
        *,
        order_id: int,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        ts_ns: int,
        order_type: str = "LMT",
        tif: str = "DAY",
    ) -> None:
        self.emit(CATRecord(
            event_type="MENO",
            event_timestamp_ns=ts_ns,
            order_id=order_id,
            symbol=symbol,
            side=side,
            price=price,
            quantity=quantity,
            order_type=order_type,
            time_in_force=tif,
        ))

    def reject(
        self,
        *,
        order_id: int,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        ts_ns: int,
        reason: str,
    ) -> None:
        self.emit(CATRecord(
            event_type="MEOR",
            event_timestamp_ns=ts_ns,
            order_id=order_id,
            symbol=symbol,
            side=side,
            price=price,
            quantity=quantity,
            order_type="LMT",
            time_in_force="DAY",
            reject_reason=reason,
        ))

    def cancel(
        self,
        *,
        order_id: int,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        ts_ns: int,
    ) -> None:
        self.emit(CATRecord(
            event_type="MECR",
            event_timestamp_ns=ts_ns,
            order_id=order_id,
            symbol=symbol,
            side=side,
            price=price,
            quantity=quantity,
            order_type="LMT",
            time_in_force="DAY",
        ))

    # ---- stats ------------------------------------------------------

    def count(self) -> int:
        return self._count

    def snapshot(self) -> Dict[str, object]:
        return {
            "total_records": self._count,
            "by_event_type": dict(self._by_type),
            "output_path": self.output_path,
        }

    # ---- dunder -----------------------------------------------------

    def __enter__(self) -> "CATExporter":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
