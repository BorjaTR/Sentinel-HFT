"""
Canary deployment + auto-rollback.

The canary applies a new policy to a fraction of traffic and watches
the gate's reject-rate distribution. If the rate breaches a configured
band, the canary rolls back automatically; otherwise it promotes to
full traffic.

For Phase-4 the canary runs against the Python golden gate using a
synthetic order stream. A real-world canary would tap mirrored
production traffic; the protocol is identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from sentinel_hft.golden import (
    Decision,
    GateConfig,
    GoldenRiskGate,
    Order,
    RejectReason,
)
from .schema import Policy


@dataclass
class CanaryResult:
    promoted: bool
    reject_rate: float
    rollback_reason: Optional[str]
    n_orders: int


@dataclass
class CanaryDeployment:
    """Stateful canary controller.

    Workflow:
        canary = CanaryDeployment(
            old_policy=p_old, new_policy=p_new,
            traffic_share=0.05,
            reject_rate_max=0.10,
            min_n_orders=1000,
        )
        for order in stream:
            decision = canary.decide(order)
            ...

        result = canary.decide_outcome()    # call after the canary window
    """
    old_policy: Policy
    new_policy: Policy
    traffic_share: float = 0.05
    reject_rate_max: float = 0.10
    min_n_orders: int = 1000

    _old_gate: GoldenRiskGate = field(init=False)
    _new_gate: GoldenRiskGate = field(init=False)
    _seen_old: int = 0
    _seen_new: int = 0
    _rejects_new: int = 0
    _step: int = 0

    def __post_init__(self) -> None:
        self._old_gate = GoldenRiskGate(_to_cfg(self.old_policy))
        self._new_gate = GoldenRiskGate(_to_cfg(self.new_policy))

    def decide(self, order: Order) -> Decision:
        # Deterministic split: every Nth order goes to the new gate.
        slot = self._step
        self._step += 1
        if slot % int(1.0 / self.traffic_share) == 0:
            self._new_gate.tick()
            d = self._new_gate.decide(order)
            self._seen_new += 1
            if not d.passed:
                self._rejects_new += 1
            return d
        else:
            self._old_gate.tick()
            self._seen_old += 1
            return self._old_gate.decide(order)

    def decide_outcome(self) -> CanaryResult:
        if self._seen_new < self.min_n_orders:
            return CanaryResult(
                promoted=False,
                reject_rate=self._reject_rate(),
                rollback_reason=f"insufficient samples ({self._seen_new} < {self.min_n_orders})",
                n_orders=self._seen_new,
            )
        rate = self._reject_rate()
        if rate > self.reject_rate_max:
            return CanaryResult(
                promoted=False,
                reject_rate=rate,
                rollback_reason=f"reject rate {rate:.2%} exceeds max {self.reject_rate_max:.2%}",
                n_orders=self._seen_new,
            )
        return CanaryResult(
            promoted=True,
            reject_rate=rate,
            rollback_reason=None,
            n_orders=self._seen_new,
        )

    def _reject_rate(self) -> float:
        return self._rejects_new / max(1, self._seen_new)


def _to_cfg(p: Policy) -> GateConfig:
    return GateConfig(
        rate_max_tokens=p.rate_max_tokens,
        rate_refill_rate=p.rate_refill_rate,
        rate_refill_period=p.rate_refill_period,
        rate_enabled=p.rate_enabled,
        pos_max_long=p.pos_max_long,
        pos_max_short=p.pos_max_short,
        pos_max_notional=p.pos_max_notional,
        pos_max_order_qty=p.pos_max_order_qty,
        pos_enabled=p.pos_enabled,
        kill_armed=p.kill_armed,
        kill_auto_enabled=p.kill_auto_enabled,
        kill_loss_threshold=p.kill_loss_threshold,
        ff_enabled=p.ff_enabled,
        ff_band_bps=p.ff_band_bps,
        ff_ref_price=p.ff_ref_price,
        allowlist_enabled=p.allowlist_enabled,
        allowlist=p.allowlist,
    )
