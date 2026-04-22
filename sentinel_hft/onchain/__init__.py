"""On-chain / off-exchange latency attribution.

This package extends Sentinel-HFT's per-stage attribution beyond the
FPGA pipeline to the software pipeline used for venues like Hyperliquid,
Lighter, dYdX-v4, and Jupiter/Solana DEXs. The FPGA pipeline measures
wire->FPGA->wire; the on-chain pipeline measures market-event -> signed-tx
-> inclusion-block.

The five stages modelled:

- ``d_rpc``       -- market-data RPC/WS arrival -> user-space handoff
- ``d_quote``     -- quote evaluation / strategy decision
- ``d_sign``      -- signing (Ed25519 for Solana, secp256k1 for EVM)
- ``d_submit``    -- submission to sequencer / RPC / leader
- ``d_inclusion`` -- submission -> block / sequencer ack

Stages are defined in nanoseconds (not FPGA clock cycles) because the
relevant latencies span 5 orders of magnitude (10us signing to 400ms
block times). The format is deliberately a separate record shape
rather than an extension of v1.2 because the semantics and units differ.
"""

from .record import (
    OnchainStage,
    OnchainRecord,
    ONCHAIN_STRUCT,
    ONCHAIN_RECORD_SIZE,
    ONCHAIN_MAGIC,
)
from .analyzer import (
    OnchainMetrics,
    OnchainSnapshot,
    StageSummary,
)
from .fixtures import (
    HyperliquidFixture,
    SolanaFixture,
    generate_fixture,
)

__all__ = [
    "OnchainStage",
    "OnchainRecord",
    "ONCHAIN_STRUCT",
    "ONCHAIN_RECORD_SIZE",
    "ONCHAIN_MAGIC",
    "OnchainMetrics",
    "OnchainSnapshot",
    "StageSummary",
    "HyperliquidFixture",
    "SolanaFixture",
    "generate_fixture",
]
