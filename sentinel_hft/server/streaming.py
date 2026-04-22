"""
streaming.py - background-thread drill runners that emit progress
events for the demo UI's WebSocket transport.

Each drill is already a synchronous ``run_*`` function in
``sentinel_hft.usecases`` that runs to completion and writes JSON/MD/
HTML artifacts. For the interactive UI we want the same thing, but
with tick-level progress updates streaming out while the drill runs.

The approach is strictly additive to the use-case code: we monkey-patch
``HyperliquidRunner`` in the target module for the duration of the run
so we capture a live reference to the runner instance, then poll it
from a sampler thread at ~10 Hz and push snapshots to the client.
When the worker thread completes, we push the final Report JSON and
close the stream. The use-case modules themselves remain untouched.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from sentinel_hft.hyperliquid.runner import (
    HLRunConfig,
    HyperliquidRunner,
)


# ---------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------


def _to_jsonable(obj: Any) -> Any:
    """Recursively coerce dataclasses / Paths / bytes into JSON primitives."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, Path):
        return str(obj)
    if is_dataclass(obj):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        return _to_jsonable(obj.to_dict())
    if hasattr(obj, "__dict__"):
        return {k: _to_jsonable(v) for k, v in vars(obj).items()
                if not k.startswith("_")}
    return str(obj)


def report_to_json(report: Any) -> Dict[str, Any]:
    """Flatten a use-case Report into a JSON-safe dict for the UI."""
    return _to_jsonable(report)


# ---------------------------------------------------------------------
# Percentile helper (in-process, no numpy dep on this hot path)
# ---------------------------------------------------------------------


def _pct(samples: List[int], p: float) -> float:
    if not samples:
        return 0.0
    s = sorted(samples)
    k = max(0, min(len(s) - 1, int(round((len(s) - 1) * p / 100.0))))
    return float(s[k])


# ---------------------------------------------------------------------
# Snapshot of a live HyperliquidRunner
# ---------------------------------------------------------------------


def _snapshot(runner: HyperliquidRunner, total_ticks: int,
              started_at: float) -> Dict[str, Any]:
    """Take a polling snapshot of a live runner."""
    # These private attrs are read-only from our side; we never mutate.
    lat = list(runner._latencies_ns)         # noqa: SLF001
    stg = {k: list(v) for k, v in runner._stage_ns.items()}  # noqa: SLF001
    gate = runner._gate                      # noqa: SLF001
    progress = (
        runner.ticks_consumed / total_ticks
        if total_ticks > 0 else 0.0
    )
    compliance = None
    if getattr(runner, "compliance", None) is not None:
        try:
            compliance = runner.compliance.snapshot().as_dict()
        except Exception:      # noqa: BLE001
            compliance = None
    return {
        "type": "progress",
        "elapsed_s": round(time.time() - started_at, 3),
        "progress": round(min(1.0, progress), 4),
        "ticks_consumed": runner.ticks_consumed,
        "ticks_target": total_ticks,
        "intents_generated": runner.intents_generated,
        "decisions_logged": runner.decisions_logged,
        "rejected_toxic": runner.rejected_toxic,
        "rejected_rate": gate.rejected_rate,
        "rejected_pos": gate.rejected_pos,
        "rejected_notional": gate.rejected_notional,
        "rejected_order_size": gate.rejected_order_size,
        "rejected_kill": gate.rejected_kill,
        "passed": gate.passed,
        "kill_triggered": bool(getattr(gate.kill, "triggered", False)),
        "latency_ns": {
            "count": len(lat),
            "p50": _pct(lat, 50.0),
            "p99": _pct(lat, 99.0),
            "p999": _pct(lat, 99.9),
            "max": float(max(lat)) if lat else 0.0,
        },
        "stage_ns": {
            name: {
                "count": len(v),
                "p50": _pct(v, 50.0),
                "p99": _pct(v, 99.0),
                "mean": (sum(v) / len(v)) if v else 0.0,
            } for name, v in stg.items()
        },
        "compliance": compliance,
    }


# ---------------------------------------------------------------------
# Capture helper: monkey-patch HyperliquidRunner in a target module so
# we capture a live reference the instant the use-case builds one.
# ---------------------------------------------------------------------


def _with_captured_runner(module, target_callable: Callable[[], Any]):
    """Context manager that patches ``module.HyperliquidRunner`` with a
    capturing subclass and yields a dict that ends up with ``{'runner':
    <instance>}`` once the use-case instantiates it.

    Returns (holder, wrapped_target). Call ``wrapped_target()`` from the
    worker thread; the patch is reverted inside the wrapper's ``finally``.
    """
    holder: Dict[str, HyperliquidRunner] = {}
    original = module.HyperliquidRunner

    class _Capturing(original):  # type: ignore[misc,valid-type]
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            # First construction wins. Multi-session drills (daily
            # evidence) overwrite as each session starts -- that's
            # what we want: the snapshot reflects the *current*
            # sub-runner.
            holder["runner"] = self

    module.HyperliquidRunner = _Capturing  # type: ignore[assignment]

    def _wrapped():
        try:
            return target_callable()
        finally:
            module.HyperliquidRunner = original  # type: ignore[assignment]

    return holder, _wrapped


# ---------------------------------------------------------------------
# DrillStream: the async event producer consumed by the WS handler
# ---------------------------------------------------------------------


class DrillStream:
    """Runs a drill on a worker thread; produces async JSON events.

    Typical use::

        stream = build_<drill>_stream(cfg)
        async for event in stream.events():
            await ws.send_json(event)
    """

    def __init__(self, *, target: Callable[[], Any],
                 holder: Dict[str, HyperliquidRunner],
                 fallback_runner: HyperliquidRunner,
                 total_ticks: int,
                 poll_hz: float = 10.0,
                 intro: Optional[Dict[str, Any]] = None):
        self._target = target
        self._holder = holder
        self._fallback = fallback_runner
        self._total_ticks = total_ticks
        self._poll_interval = 1.0 / max(0.1, poll_hz)
        self._thread: Optional[threading.Thread] = None
        self._done = threading.Event()
        self._err: Optional[BaseException] = None
        self._result: Any = None
        self._intro = intro or {}

    def _run(self) -> None:
        try:
            self._result = self._target()
        except BaseException as e:          # noqa: BLE001
            self._err = e
        finally:
            self._done.set()

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="drill-worker", daemon=True)
        self._thread.start()

    def _active(self) -> HyperliquidRunner:
        return self._holder.get("runner", self._fallback)

    async def events(self) -> AsyncIterator[Dict[str, Any]]:
        if self._thread is None:
            self.start()
        started = time.time()
        intro: Dict[str, Any] = {
            "type": "start",
            "ticks_target": self._total_ticks,
        }
        intro.update(self._intro)
        yield intro

        last_ticks = -1
        last_latn = -1
        while not self._done.is_set():
            await asyncio.sleep(self._poll_interval)
            snap = _snapshot(self._active(), self._total_ticks, started)
            # Don't spam: emit only on observable change.
            if (snap["ticks_consumed"] != last_ticks
                    or snap["latency_ns"]["count"] != last_latn):
                last_ticks = snap["ticks_consumed"]
                last_latn = snap["latency_ns"]["count"]
                yield snap

        # Final snapshot + result/error.
        yield _snapshot(self._active(), self._total_ticks, started)
        if self._err is not None:
            yield {
                "type": "error",
                "error": f"{type(self._err).__name__}: {self._err}",
            }
        else:
            yield {
                "type": "result",
                "report": report_to_json(self._result),
            }

    def join(self, timeout: Optional[float] = None) -> Any:
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        if self._err is not None:
            raise self._err
        return self._result


# ---------------------------------------------------------------------
# Per-drill builders -- each delegates to the canonical run_* on a
# worker thread and observes via the monkey-patch capture pattern.
# ---------------------------------------------------------------------


def build_toxic_flow_stream(cfg) -> DrillStream:
    from sentinel_hft.usecases import toxic_flow as _mod
    holder, target = _with_captured_runner(_mod, lambda: _mod.run_toxic_flow(cfg))
    fallback = HyperliquidRunner(HLRunConfig(ticks=cfg.ticks, seed=cfg.seed))
    return DrillStream(
        target=target, holder=holder,
        fallback_runner=fallback, total_ticks=cfg.ticks,
        intro={"drill": "toxic_flow", "output_dir": str(cfg.output_dir)},
    )


def build_kill_drill_stream(cfg) -> DrillStream:
    from sentinel_hft.usecases import kill_drill as _mod
    holder, target = _with_captured_runner(_mod, lambda: _mod.run_kill_drill(cfg))
    fallback = HyperliquidRunner(HLRunConfig(ticks=cfg.ticks, seed=cfg.seed))
    return DrillStream(
        target=target, holder=holder,
        fallback_runner=fallback, total_ticks=cfg.ticks,
        intro={"drill": "kill_drill", "output_dir": str(cfg.output_dir),
               "spike_at_tick": cfg.spike_at_tick,
               "inject_kill_at_intent": cfg.inject_kill_at_intent},
    )


def build_latency_stream(cfg) -> DrillStream:
    from sentinel_hft.usecases import latency as _mod
    holder, target = _with_captured_runner(_mod, lambda: _mod.run_latency(cfg))
    fallback = HyperliquidRunner(HLRunConfig(ticks=cfg.ticks, seed=cfg.seed))
    return DrillStream(
        target=target, holder=holder,
        fallback_runner=fallback, total_ticks=cfg.ticks,
        intro={"drill": "latency", "output_dir": str(cfg.output_dir)},
    )


def build_daily_evidence_stream(cfg) -> DrillStream:
    """Daily evidence chains 3 sub-sessions. The holder picks up each
    sub-runner as it's instantiated, so per-session progress bars just
    work -- ``ticks_consumed`` resets per session and we report the
    active session's tick target."""
    from sentinel_hft.usecases import daily_evidence as _mod
    holder, target = _with_captured_runner(
        _mod, lambda: _mod.run_daily_evidence(cfg))
    total_ticks = sum(s.ticks for s in cfg.sessions)
    fallback = HyperliquidRunner(HLRunConfig(ticks=total_ticks))
    return DrillStream(
        target=target, holder=holder,
        fallback_runner=fallback, total_ticks=total_ticks,
        poll_hz=4.0,  # lower cadence -- the drill is ~45s of wall-clock
        intro={"drill": "daily_evidence",
               "output_dir": str(cfg.output_dir),
               "sessions": [s.label for s in cfg.sessions],
               "trading_date": cfg.trading_date},
    )


__all__ = [
    "DrillStream",
    "report_to_json",
    "build_toxic_flow_stream",
    "build_kill_drill_stream",
    "build_latency_stream",
    "build_daily_evidence_stream",
]
