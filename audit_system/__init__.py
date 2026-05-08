"""
Sentinel-HFT independent audit system.

Mirrors the volat-agent monthly audit pattern: pre-registration before the
data window opens, six axes of evidence, PASS/WARN/FAIL verdicts, signed
reports.

Six axes (see ROADMAP_TO_LAUNCH.md §11):

    A-Spec      shipped binary/bitstream ≡ locked spec
    A-Forward   replay last period's flow → expected decisions
    A-Coverage  policy clauses exercised by tests
    A-Drift     latency/reject distributions in band
    A-Chain     audit chain end-to-end integrity
    A-Bias      gate behaves consistently across cohorts

Pre-registration files: audit_system/pre_reg/audit_<YYYY_MM>.yml
Reports: audit_system/reports/audit_<YYYY_MM>.md (+ .json)
"""
