"""
Sentinel-HFT policy plane.

Phase-4 deliverable. A policy is a YAML document describing the firm's
risk caps. The compiler turns it into a register blob the FPGA can load.
Blobs are ed25519-signed; the gate refuses to load any blob whose
signature does not verify against the configured pubkey.

Deployment workflow:

    1.  Author edits /policies/<name>.yaml
    2.  CLI compiles → register blob (.bin) + manifest (.json).
    3.  Two-of-N signers approve (`sentinel-policy sign`).
    4.  Canary deploy: applied to N% of order flow first.
    5.  Auto-rollback on threshold breach.
    6.  Promote to full traffic.

For Phase 4 the canary/rollback hooks target the Python golden gate.
The same blob format will be loaded by the FPGA in Phase 1's hardware
close.
"""

from .schema import (
    PolicySchema,
    PolicySchemaError,
    Policy,
    load_policy,
    validate_policy,
)
from .compiler import (
    compile_policy,
    decompile_blob,
    PolicyBlob,
)
from .signer import (
    sign_blob,
    verify_blob,
    SigError,
    KeyPair,
    generate_keypair,
)
from .canary import (
    CanaryDeployment,
    CanaryResult,
)

__all__ = [
    "PolicySchema",
    "PolicySchemaError",
    "Policy",
    "load_policy",
    "validate_policy",
    "compile_policy",
    "decompile_blob",
    "PolicyBlob",
    "sign_blob",
    "verify_blob",
    "SigError",
    "KeyPair",
    "generate_keypair",
    "CanaryDeployment",
    "CanaryResult",
]
