"""
cocotb driver for V-Parity: feed corpus orders into risk_gate_v2 and dump
RTL decisions to JSON.

Run via:
    cd verification/v_parity
    PARITY_CORPUS=../../verification/reports/v_floor/golden_seed42_n50000.json \
        make sim

Outputs:
    verification/reports/v_parity/rtl_<seed>_<n>.json

The JSON schema matches what golden writes (see verification/v_floor/random_corpus.py)
so verification/v_parity/compare.py can do a cell-by-cell comparison.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

# cocotb is imported lazily so this file can be inspected without it.
try:
    import cocotb  # type: ignore
    from cocotb.clock import Clock  # type: ignore
    from cocotb.triggers import RisingEdge, ReadOnly, Timer  # type: ignore
except ImportError:  # pragma: no cover
    cocotb = None  # type: ignore


CORPUS_PATH = Path(os.environ.get(
    "PARITY_CORPUS",
    "../../verification/reports/v_floor/golden_seed42_n50000.json",
))
OUT_PATH = Path(os.environ.get(
    "PARITY_RTL_OUT",
    "../../verification/reports/v_parity/rtl_seed42_n50000.json",
))


async def _reset(dut):
    dut.rst_n.value = 0
    for _ in range(8):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    for _ in range(2):
        await RisingEdge(dut.clk)


def _write_cfg(dut, cfg):
    dut.cfg_rate_max_tokens.value     = cfg["rate_max_tokens"]
    dut.cfg_rate_refill_rate.value    = cfg["rate_refill_rate"]
    dut.cfg_rate_refill_period.value  = cfg["rate_refill_period"]
    dut.cfg_rate_enabled.value        = 1 if cfg["rate_enabled"] else 0

    dut.cfg_pos_max_long.value        = cfg["pos_max_long"]
    dut.cfg_pos_max_short.value       = cfg["pos_max_short"]
    dut.cfg_pos_max_notional.value    = cfg["pos_max_notional"]
    dut.cfg_pos_max_order_qty.value   = cfg["pos_max_order_qty"]
    dut.cfg_pos_enabled.value         = 1 if cfg["pos_enabled"] else 0

    dut.cfg_kill_armed.value          = 1 if cfg["kill_armed"] else 0
    dut.cfg_kill_auto_enabled.value   = 1 if cfg["kill_auto_enabled"] else 0
    dut.cfg_kill_loss_threshold.value = cfg["kill_loss_threshold"] & ((1 << 64) - 1)

    dut.cfg_ff_enabled.value          = 1 if cfg["ff_enabled"] else 0
    dut.cfg_ff_band_bps.value         = cfg["ff_band_bps"]
    dut.cfg_ff_ref_price.value        = cfg["ff_ref_price"]

    dut.cfg_allowlist_enabled.value   = 1 if cfg["allowlist_enabled"] else 0


async def _program_allowlist(dut, slots):
    """Walk the allowlist tuple and write each entry into a slot."""
    for idx in range(64):
        dut.slot_we.value   = 1
        dut.slot_idx.value  = idx
        dut.slot_data.value = slots[idx] if idx < len(slots) else 0
        await RisingEdge(dut.clk)
    dut.slot_we.value = 0


def _set_zero_order(dut):
    dut.in_valid.value          = 0
    dut.in_order_id.value       = 0
    dut.in_order_symbol.value   = 0
    dut.in_order_side.value     = 0
    dut.in_order_type.value     = 0
    dut.in_order_qty.value      = 0
    dut.in_order_price.value    = 0
    dut.in_order_notional.value = 0


async def _drive_one_order(dut, o):
    dut.in_valid.value          = 1
    dut.in_order_id.value       = o["order_id"]
    dut.in_order_symbol.value   = o["symbol_id"]
    dut.in_order_side.value     = o["side"]
    dut.in_order_type.value     = o["order_type"]
    dut.in_order_qty.value      = o["qty"]
    dut.in_order_price.value    = o["price"]
    dut.in_order_notional.value = o["notional"]
    # Wait one cycle for skid-buffer capture.
    await RisingEdge(dut.clk)
    _set_zero_order(dut)


async def _drive_fill(dut, f):
    dut.fill_valid.value    = 1
    dut.fill_side.value     = f["side"]
    dut.fill_qty.value      = f["qty"]
    dut.fill_notional.value = f["notional"]
    await RisingEdge(dut.clk)
    dut.fill_valid.value    = 0


async def _drive_pnl(dut, pnl):
    # Two's complement encode signed int64 into unsigned register input.
    enc = pnl & ((1 << 64) - 1)
    dut.current_pnl.value = enc
    await RisingEdge(dut.clk)


if cocotb is not None:
    @cocotb.test()
    async def parity_drive(dut):
        cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

        corpus = json.loads(CORPUS_PATH.read_text())

        await _reset(dut)
        _set_zero_order(dut)
        dut.fill_valid.value     = 0
        dut.cmd_kill_trigger.value = 0
        dut.cmd_kill_reset.value   = 0
        dut.out_ready.value      = 1
        dut.current_pnl.value    = 0
        dut.slot_we.value        = 0
        dut.slot_idx.value       = 0
        dut.slot_data.value      = 0

        _write_cfg(dut, corpus["config"])
        await _program_allowlist(dut, corpus["config"]["allowlist"])

        # Drive orders, capture decisions
        decisions: List[dict] = []
        fills_by_idx = {f["after_idx"]: f for f in corpus["fills"]}
        pnls_by_idx  = {p["after_idx"]: p for p in corpus["pnl_updates"]}

        for idx, o in enumerate(corpus["orders"]):
            await _drive_one_order(dut, o)
            # One more cycle for the inner skid buffer to present output.
            await RisingEdge(dut.clk)
            await ReadOnly()
            decisions.append({
                "passed": int(not int(dut.out_rejected.value)) == 1,
                "reason": int(dut.out_reject_reason.value),
                "tokens_remaining": 0,        # not exposed by tb wrapper
                "current_position": 0,         # ditto
                "current_notional": 0,         # ditto
            })

            if idx in fills_by_idx:
                await _drive_fill(dut, fills_by_idx[idx])
            if idx in pnls_by_idx:
                await _drive_pnl(dut, pnls_by_idx[idx]["pnl_signed"])

        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps({
            "schema_version": 1,
            "seed": corpus["seed"],
            "n_orders": len(decisions),
            "decisions": decisions,
        }, indent=None))
