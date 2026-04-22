"""
Regulation compliance layer (Workstream 3).

This package implements the 9 regulation primitives crosswalked in
``docs/COMPLIANCE.md``:

    MiFID II RTS 6  -> order-to-trade ratio counter           (mifid_otr.py + rtl/otr_counter.sv)
    MiFID II RTS 6  -> max message rate per venue             (rtl/rate_limiter.sv - already shipped)
    CFTC Reg AT     -> self-trade prevention                  (self_trade_guard.py + rtl/self_trade_guard.sv)
    FINRA 15c3-5    -> fat-finger price check                 (price_sanity.py + rtl/price_sanity.sv)
    FINRA 15c3-5    -> credit / capital check                 (rtl/position_limiter.sv - already shipped)
    SEC Rule 613    -> order-event formatter (CAT)            (cat_export.py)
    MAR             -> spoofing / layering detector           (market_abuse.py)
    Swiss FINMA     -> operational resilience log export      (resilience_log.py)
    MAS Singapore   -> same shape as FINMA                    (resilience_log.py)

Every primitive is expressed as a small, pure-Python object with a
``.observe(intent, decision)`` or ``.format(...)`` surface.  The
``ComplianceStack`` aggregates them so the HL runner only has to call
one observer per intent.

The layer is strictly **observational**: it never modifies a drill's
outcome.  RTL stubs under ``rtl/`` are synthesizable reference
implementations of the same logic for the U55C target.
"""

from .crosswalk import (
    ComplianceEntry,
    CROSSWALK,
    get_crosswalk,
    crosswalk_as_dict,
)
from .stack import ComplianceStack, ComplianceSnapshot

__all__ = [
    "ComplianceEntry",
    "CROSSWALK",
    "get_crosswalk",
    "crosswalk_as_dict",
    "ComplianceStack",
    "ComplianceSnapshot",
]
