"""WebSocket collector for real Hyperliquid market data.

Reads the public wire feed at ``wss://api.hyperliquid.xyz/ws`` and
dumps the tick stream into the binary capture format defined in
:mod:`sentinel_hft.hyperliquid.reader`. The collector is intentionally
narrow: it captures exactly the fields the demo pipeline needs (BBO +
public trades with the taker ``user`` hash), not the full L2 book.

The collector is optional. The synthetic fixture is the only thing
CI depends on -- collector import lazy-loads ``websockets`` so the
package works without that library installed.

Usage
-----

::

    from sentinel_hft.hyperliquid.collector import HLCollector
    coll = HLCollector(symbols=["BTC", "ETH", "SOL"], out_path="capture.hltk")
    await coll.run_for(duration_s=30)

Or via the CLI::

    sentinel-hft hl collect --symbols BTC,ETH,SOL --duration 30 \\
        -o out/hl/captures/live.hltk

Hyperliquid wire specifics
--------------------------

* ``bbo`` channel emits top-of-book on every change. Payload:
  ``{"coin": "BTC", "time": <ms>, "bbo": [{"px": "...", "sz": "..."},
  {"px": "...", "sz": "..."}]}`` (bid, then ask).
* ``trades`` channel emits public prints. Payload:
  ``{"coin": "BTC", "px": "...", "sz": "...", "side": "A"|"B",
    "time": <ms>, "hash": "0x...", "tid": <int>, "users": ["0x...", ...]}``.
  ``users[0]`` is the taker; we hash the 20-byte address down to a
  u48 for the HLTickEvent taker_id.
* HL publishes an ``allMids`` heartbeat every ~100 ms on the pair;
  we subscribe to it only to keep our bid/ask fresh between bbo
  events on low-liquidity pairs, and we do not emit a record for it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ..deribit.fixture import TickKind
from .fixture import HLTickEvent
from .instruments import (
    HL_DEFAULT_UNIVERSE,
    HyperliquidInstrument,
    hl_by_symbol,
)
from .reader import (
    HL_TICK_HEADER_SIZE,
    HL_TICK_RECORD_SIZE,
    HLTickFileHeader,
    HL_TICK_MAGIC,
    HL_TICK_VERSION,
    pack_event,
)


log = logging.getLogger(__name__)


HL_WS_URL = "wss://api.hyperliquid.xyz/ws"


def _taker_hash(user_addr: str) -> int:
    """Collapse a 0x-prefixed 20-byte wallet into a 48-bit integer.

    48 bits gives 2^48 ~= 2.8e14 distinct wallets which is far
    beyond HL's realised distinct-taker count and fits the capture
    record without widening it.
    """
    if not user_addr:
        return 0
    h = hashlib.blake2b(user_addr.encode("ascii"), digest_size=8).digest()
    return int.from_bytes(h, "little") & 0x0000_FFFF_FFFF_FFFF


@dataclass
class _Bookside:
    px: float = 0.0
    sz: float = 0.0


@dataclass
class _SymbolBook:
    """Last-seen BBO for one symbol -- used to attach bid/ask to trades."""

    bid: _Bookside = field(default_factory=_Bookside)
    ask: _Bookside = field(default_factory=_Bookside)


# ---------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------


class HLCollector:
    """Async collector for HL BBO + public trades.

    Parameters
    ----------
    symbols
        Underlying symbols to subscribe to (e.g. ``["BTC", "ETH"]``).
    out_path
        Destination capture file (binary format -- see
        :mod:`sentinel_hft.hyperliquid.reader`).
    max_events
        Hard cap on records written. ``None`` means unbounded.
    url
        Overrideable for integration testing against a local mock.
    include_l2
        If True, subscribe to the ``l2Book`` channel as a liveness
        signal (we still do not emit records for it -- BBO is what
        we capture).
    """

    def __init__(
        self,
        symbols: Iterable[str] = ("BTC", "ETH", "SOL"),
        out_path: Optional[Path] = None,
        *,
        max_events: Optional[int] = None,
        url: str = HL_WS_URL,
        include_l2: bool = False,
    ):
        self._symbols: List[str] = [s.upper() for s in symbols]
        self._out_path = Path(out_path) if out_path else None
        self._max_events = max_events
        self._url = url
        self._include_l2 = include_l2

        # Resolve symbols against the HL universe so each capture
        # record can carry the full Instrument dataclass.
        sym_to_ins = hl_by_symbol()
        self._ins_by_coin: Dict[str, HyperliquidInstrument] = {}
        for sym in self._symbols:
            # HL uses bare coin names (BTC, ETH, SOL); our universe
            # symbols are BTC-USD-PERP etc. Match by underlying.
            matched = [ins for ins in sym_to_ins.values()
                       if ins.underlying == sym]
            if not matched:
                raise ValueError(f"symbol {sym!r} not in HL universe")
            self._ins_by_coin[sym] = matched[0]

        self._books: Dict[str, _SymbolBook] = {
            s: _SymbolBook() for s in self._symbols
        }

        # Output state.
        self._out_fh = None
        self._events_written = 0
        self._seq = 0
        self._base_ts_ns: int = 0

    # ------------------------------------------------------------------
    # Async entrypoints
    # ------------------------------------------------------------------

    async def run(self) -> int:
        """Connect and stream until EOF or cancellation."""
        try:
            import websockets   # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Install the optional dependency `websockets` "
                "(`pip install websockets`) to use the live HL "
                "collector. The synthetic fixture does not require it."
            ) from exc

        self._open_output()
        try:
            async with websockets.connect(
                self._url, ping_interval=20, ping_timeout=20,
                max_size=4 * 1024 * 1024,
            ) as ws:
                await self._subscribe(ws)
                async for raw in ws:
                    if self._max_events is not None \
                            and self._events_written >= self._max_events:
                        break
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        log.warning("non-json HL frame: %r", raw[:80])
                        continue
                    self._handle(msg)
        finally:
            self._close_output()
        return self._events_written

    async def run_for(self, duration_s: float) -> int:
        """Run with a wall-clock cap. Returns events written."""
        try:
            await asyncio.wait_for(self.run(), timeout=duration_s)
        except asyncio.TimeoutError:
            pass
        return self._events_written

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _subscribe(self, ws) -> None:
        for sym in self._symbols:
            await ws.send(json.dumps({
                "method": "subscribe",
                "subscription": {"type": "bbo", "coin": sym},
            }))
            await ws.send(json.dumps({
                "method": "subscribe",
                "subscription": {"type": "trades", "coin": sym},
            }))
            if self._include_l2:
                await ws.send(json.dumps({
                    "method": "subscribe",
                    "subscription": {"type": "l2Book", "coin": sym},
                }))

    def _handle(self, msg: dict) -> None:
        channel = msg.get("channel")
        data = msg.get("data")
        if not channel or data is None:
            return
        if channel == "bbo":
            self._handle_bbo(data)
        elif channel == "trades":
            if isinstance(data, list):
                for t in data:
                    self._handle_trade(t)
            elif isinstance(data, dict):
                self._handle_trade(data)
        # Otherwise ignore (subscription acks, l2Book liveness).

    def _handle_bbo(self, data: dict) -> None:
        coin = data.get("coin")
        bbo = data.get("bbo") or []
        if coin not in self._books or len(bbo) != 2:
            return
        try:
            bid_px = float(bbo[0].get("px", 0))
            bid_sz = float(bbo[0].get("sz", 0))
            ask_px = float(bbo[1].get("px", 0))
            ask_sz = float(bbo[1].get("sz", 0))
        except (TypeError, ValueError):
            return
        book = self._books[coin]
        book.bid.px = bid_px
        book.bid.sz = bid_sz
        book.ask.px = ask_px
        book.ask.sz = ask_sz

        now_ns = self._now_ns(data.get("time"))
        self._emit_event(
            coin=coin,
            kind=TickKind.QUOTE,
            wire_ts_ns=now_ns,
            trade_price=0.0,
            trade_size=0.0,
            taker_id=0,
        )

    def _handle_trade(self, data: dict) -> None:
        coin = data.get("coin")
        if coin not in self._books:
            return
        try:
            px = float(data.get("px", 0))
            sz = float(data.get("sz", 0))
        except (TypeError, ValueError):
            return
        users = data.get("users") or []
        taker = users[0] if users else data.get("user") or ""
        taker_id = _taker_hash(str(taker))
        now_ns = self._now_ns(data.get("time"))
        self._emit_event(
            coin=coin,
            kind=TickKind.TRADE,
            wire_ts_ns=now_ns,
            trade_price=px,
            trade_size=sz,
            taker_id=taker_id,
        )

    def _emit_event(
        self, *, coin: str, kind: TickKind, wire_ts_ns: int,
        trade_price: float, trade_size: float, taker_id: int,
    ) -> None:
        book = self._books[coin]
        if book.bid.px <= 0 or book.ask.px <= 0:
            return  # haven't seen a BBO yet

        ins = self._ins_by_coin[coin]
        self._seq += 1
        host_ts = self._now_ns(None)
        ev = HLTickEvent(
            wire_ts_ns=wire_ts_ns,
            host_ts_ns=host_ts,
            seq_no=self._seq,
            instrument=ins,
            kind=kind,
            bid_price=book.bid.px,
            ask_price=book.ask.px,
            bid_size=book.bid.sz,
            ask_size=book.ask.sz,
            trade_price=trade_price,
            trade_size=trade_size,
            taker_id=taker_id,
            profile=0,
        )
        if self._out_fh is not None:
            self._out_fh.write(pack_event(ev))
            self._events_written += 1

    # ------------------------------------------------------------------
    # Output plumbing
    # ------------------------------------------------------------------

    def _open_output(self) -> None:
        if self._out_path is None:
            return
        self._out_path.parent.mkdir(parents=True, exist_ok=True)
        self._base_ts_ns = time.time_ns()
        self._out_fh = self._out_path.open("wb")
        header = HLTickFileHeader(
            magic=HL_TICK_MAGIC,
            version=HL_TICK_VERSION,
            record_size=HL_TICK_RECORD_SIZE,
            base_ts_ns=self._base_ts_ns,
        )
        self._out_fh.write(header.encode())

    def _close_output(self) -> None:
        if self._out_fh is not None:
            try:
                self._out_fh.flush()
            finally:
                self._out_fh.close()
                self._out_fh = None

    def _now_ns(self, wire_ms: Optional[int]) -> int:
        """Convert HL's ms-resolution time to ns, falling back to host."""
        if wire_ms is None:
            return time.time_ns()
        try:
            return int(wire_ms) * 1_000_000
        except (TypeError, ValueError):
            return time.time_ns()


# ---------------------------------------------------------------------
# Blocking convenience
# ---------------------------------------------------------------------


def collect_to_file(
    out_path: Path,
    *,
    symbols: Iterable[str] = ("BTC", "ETH", "SOL"),
    duration_s: float = 30.0,
    max_events: Optional[int] = None,
    url: str = HL_WS_URL,
) -> int:
    """Blocking wrapper: collect from HL for ``duration_s`` seconds."""
    coll = HLCollector(
        symbols=symbols, out_path=out_path,
        max_events=max_events, url=url,
    )
    return asyncio.run(coll.run_for(duration_s=duration_s))


__all__ = [
    "HL_WS_URL",
    "HLCollector",
    "collect_to_file",
]
