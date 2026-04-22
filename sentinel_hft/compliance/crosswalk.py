"""
Regulation-to-module crosswalk.

This is the single source of truth for what Sentinel-HFT implements
towards which regulation clause.  The ``/api/compliance/crosswalk``
endpoint serializes ``CROSSWALK`` directly, the ``/sentinel/regulations``
UI renders it, and ``docs/COMPLIANCE.md`` is expected to match it
verbatim.

Each ``ComplianceEntry`` ties a regulatory clause to:

* the deterrent primitive we ship (plain English),
* the concrete artefact (RTL file, Python module, or host formatter),
* the audit-log / counter signal the live dashboard watches,
* a stable ``key`` used by the counter-stats protocol on the wire.

Ordering in ``CROSSWALK`` is significant - it's the display order in
the UI.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Literal, Tuple

Jurisdiction = Literal["EU", "US", "CH", "SG", "Global"]
Layer = Literal["RTL", "Host", "Docs"]


@dataclass(frozen=True)
class ComplianceEntry:
    """One row of the compliance crosswalk."""

    key: str                 # stable id, lower_snake
    regulation: str          # e.g. "MiFID II RTS 6"
    jurisdiction: Jurisdiction
    clause: str              # "Art. 2(2)(g)" etc.
    primitive: str           # short English description
    artifact: str            # path(s) to the implementing file(s)
    layer: Layer             # RTL | Host | Docs
    audit_signal: str        # reject_reason / counter name we expose
    live_counter: bool       # whether the UI shows a live counter
    status: Literal["implemented", "partial", "reused", "stub"]


CROSSWALK: Tuple[ComplianceEntry, ...] = (
    ComplianceEntry(
        key="mifid_otr",
        regulation="MiFID II RTS 6",
        jurisdiction="EU",
        clause="Art. 2(2)(g) · Art. 15 order-to-trade ratio",
        primitive=(
            "Maintain an order-to-trade ratio per instrument + venue; "
            "block further messages once the per-second threshold trips."
        ),
        artifact="sentinel_hft/compliance/mifid_otr.py + rtl/otr_counter.sv",
        layer="Host",
        audit_signal="otr_ratio, otr_orders, otr_trades, otr_rejects",
        live_counter=True,
        status="implemented",
    ),
    ComplianceEntry(
        key="mifid_rate_limit",
        regulation="MiFID II RTS 6",
        jurisdiction="EU",
        clause="Art. 15 max message rate",
        primitive=(
            "Token-bucket rate limiter that caps new-order messages per "
            "symbol / trader to a configurable bound."
        ),
        artifact="rtl/rate_limiter.sv (v1.0.0-core-audit-closed)",
        layer="RTL",
        audit_signal="rejected_rate",
        live_counter=False,
        status="reused",
    ),
    ComplianceEntry(
        key="cftc_self_trade",
        regulation="CFTC Reg AT",
        jurisdiction="US",
        clause="17 CFR § 1.80 / § 40.22 self-trade prevention",
        primitive=(
            "Block an incoming order that would cross with the trader's "
            "own resting orders on the opposite side."
        ),
        artifact="sentinel_hft/compliance/self_trade_guard.py + rtl/self_trade_guard.sv",
        layer="Host",
        audit_signal="self_trade_rejects",
        live_counter=True,
        status="implemented",
    ),
    ComplianceEntry(
        key="finra_fat_finger",
        regulation="FINRA 15c3-5",
        jurisdiction="US",
        clause="SEA Rule 15c3-5(c)(1)(ii) erroneous-order check",
        primitive=(
            "Reject any order whose price deviates from the last trade "
            "by more than MAX_DEV_BPS (default 500 bps)."
        ),
        artifact="sentinel_hft/compliance/price_sanity.py + rtl/price_sanity.sv",
        layer="Host",
        audit_signal="fat_finger_rejects",
        live_counter=True,
        status="implemented",
    ),
    ComplianceEntry(
        key="finra_credit",
        regulation="FINRA 15c3-5",
        jurisdiction="US",
        clause="SEA Rule 15c3-5(c)(1)(i) credit / capital check",
        primitive=(
            "Per-account long/short/notional caps enforced at line rate."
        ),
        artifact="rtl/position_limiter.sv (v1.0.0-core-audit-closed)",
        layer="RTL",
        audit_signal="rejected_pos + rejected_notional",
        live_counter=False,
        status="reused",
    ),
    ComplianceEntry(
        key="sec_cat",
        regulation="SEC Rule 613 (CAT)",
        jurisdiction="US",
        clause="17 CFR § 242.613 order-event reporting",
        primitive=(
            "Emit one CAT Phase 2e record per order event (new / route / "
            "cancel / modify) into a machine-readable NDJSON feed."
        ),
        artifact="sentinel_hft/compliance/cat_export.py",
        layer="Host",
        audit_signal="cat_records_emitted",
        live_counter=True,
        status="implemented",
    ),
    ComplianceEntry(
        key="mar_abuse",
        regulation="MAR (EU Market Abuse Reg.)",
        jurisdiction="EU",
        clause="Art. 12 spoofing & layering",
        primitive=(
            "Flag patterns of N same-side orders placed and cancelled "
            "within T ms without any fill on the opposite side."
        ),
        artifact="sentinel_hft/compliance/market_abuse.py",
        layer="Host",
        audit_signal="mar_alerts",
        live_counter=False,
        status="implemented",
    ),
    ComplianceEntry(
        key="finma_resilience",
        regulation="Swiss FINMA OpResilience",
        jurisdiction="CH",
        clause="FINMA Circ. 2023/1 §49-58",
        primitive=(
            "Daily operational-resilience log: incidents, RTO/RPO, "
            "head-hash for immutability."
        ),
        artifact="sentinel_hft/compliance/resilience_log.py",
        layer="Host",
        audit_signal="resilience_log.json",
        live_counter=False,
        status="implemented",
    ),
    ComplianceEntry(
        key="mas_resilience",
        regulation="MAS Notice TRM (Singapore)",
        jurisdiction="SG",
        clause="MAS Notice 644 §6.4 operational-risk reporting",
        primitive=(
            "Same shape as FINMA; re-uses the resilience_log formatter "
            "with MAS-flavoured envelope fields."
        ),
        artifact="sentinel_hft/compliance/resilience_log.py",
        layer="Host",
        audit_signal="resilience_log.json",
        live_counter=False,
        status="implemented",
    ),
)


def get_crosswalk() -> Tuple[ComplianceEntry, ...]:
    """Return the immutable crosswalk tuple."""
    return CROSSWALK


def crosswalk_as_dict() -> List[Dict[str, object]]:
    """Return the crosswalk as a list of plain dicts (JSON-safe)."""
    return [asdict(e) for e in CROSSWALK]


def live_counter_keys() -> List[str]:
    """Return the stable keys of entries that expose a live counter."""
    return [e.key for e in CROSSWALK if e.live_counter]
