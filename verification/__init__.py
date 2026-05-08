"""
Sentinel-HFT verification system.

The verification system proves that the deployed build matches the
behavioral specification at any given commit. It runs in CI on every
push to main and produces a per-commit report.

Six axes (see ROADMAP_TO_LAUNCH.md §10 and roadmap/pre_reg/phase_01.yml):

    V-Floor     gate decision matches behavioral golden
    V-Mut       mutation testing
    V-Meta      metamorphic relations hold
    V-Parity    RTL sim ≡ gate sim ≡ FPGA execution
    V-Contract  register-map / interface contract tests
    V-Tamper    audit-chain tamper-evidence

Reports land in verification/reports/ as JSON + markdown.
"""
