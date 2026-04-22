"""Workstream 4 -- nightly RCA digest generator.

Entry point for the scheduled job that produces the daily
Markdown digest the ops team reads with their morning coffee.

Flow::

    drill artifacts (out/hl/**)
        -> rca_features.build_features_from_root()
        -> LLM prompt (deterministic, temp=0)
            -> Markdown digest
        -> writes ``out/digests/YYYY-MM-DD.md`` + JSON sidecar

LLM backends (in priority order)
--------------------------------

1.  Anthropic API (``ANTHROPIC_API_KEY`` env var set).
    Model is ``claude-haiku-4-5``, temperature 0. This is the
    production path.
2.  Deterministic template (always available). Used when the API key
    isn't set, the network is unavailable, or the caller explicitly
    passes ``backend="template"``. This keeps the nightly job
    useful in air-gapped deployments and the test suite reproducible.

Output invariants
-----------------

* The digest Markdown contains only facts derivable from the feature
  dict. The LLM is prompted to cite each anomaly's ``kind`` and
  ``detail`` string verbatim so we can cross-check later.
* The JSON sidecar contains the feature dict, the digest text, the
  backend used, and the prompt hash. Archived alongside the Markdown
  for back-testing.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .rca_features import (
    FEATURE_SCHEMA_VERSION,
    Anomaly,
    RcaFeatures,
    build_features_from_root,
)


DIGEST_SCHEMA_VERSION = "sentinel-hft/rca-digest/1"
DEFAULT_MODEL = "claude-haiku-4-5"

# The nightly prompt template. Intentionally terse, anomaly-driven,
# and forbids speculation outside the feature dict.
NIGHTLY_PROMPT = """You are the on-call SRE for a hardware-assisted trading system.
Produce a Markdown operational digest for the trading day described below.

Rules:
- Cite each anomaly by its ``kind`` and the exact ``detail`` text.
- If there are no anomalies, say so in one sentence.
- Candidate root causes must be grounded in the feature dict only.
- Do not invent metrics that aren't in the input.
- Section headers: ``## Headline``, ``## Anomalies``, ``## Candidate
  root causes``, ``## Recommended actions``, ``## Chain integrity``.
- Keep each section <= 120 words.
- Use bullet points only inside Anomalies and Recommended actions.

Feature bundle (JSON):

```json
{features_json}
```
"""


# ---------------------------------------------------------------------
# Digest result container
# ---------------------------------------------------------------------


@dataclass
class DigestResult:
    schema: str
    date: str
    markdown: str
    backend: str
    model: Optional[str]
    prompt_sha256: str
    features: Dict[str, Any]
    generated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------


def _format_prompt(features: RcaFeatures) -> str:
    return NIGHTLY_PROMPT.format(
        features_json=json.dumps(features.to_dict(), indent=2, sort_keys=True)
    )


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _try_anthropic(prompt: str, model: str) -> Optional[str]:
    """Call Claude once at temperature 0. Returns the response text,
    or ``None`` if the client cannot be constructed or the call fails."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic  # type: ignore
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        # messages API: content is a list of blocks, text is on the
        # first text block.
        for block in resp.content:
            if getattr(block, "type", "") == "text":
                return block.text
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------
# Deterministic template fallback
# ---------------------------------------------------------------------


def _template_digest(features: RcaFeatures) -> str:
    """A deterministic Markdown digest built purely from features.

    Identical inputs always produce identical output. This is what the
    test suite validates against and what ships when the nightly job
    can't reach an LLM backend."""
    agg = features.aggregate
    anomalies = features.anomalies
    date_str = features.window_end or features.window_start or "n/a"

    # Headline
    if not anomalies:
        headline = (
            f"{date_str}: nominal day. {agg.get('drills', 0)} drills replayed, "
            f"{agg.get('intents_total', 0)} intents, "
            f"{agg.get('rejected_total', 0)} rejects, "
            f"all chains verified."
        )
    else:
        kinds = sorted({a.kind for a in anomalies})
        headline = (
            f"{date_str}: {len(anomalies)} anomaly hit(s) across "
            f"{agg.get('drills', 0)} drills: {', '.join(kinds)}."
        )

    # Anomalies
    if anomalies:
        bullet_lines = []
        for a in anomalies:
            parts = [f"**{a.kind}**", f"drill=`{a.drill}`"]
            if a.stage:
                parts.append(f"stage=`{a.stage}`")
            if a.detail:
                parts.append(a.detail)
            bullet_lines.append("- " + " \u2014 ".join(parts))
        anomalies_md = "\n".join(bullet_lines)
    else:
        anomalies_md = "_No anomalies fired this window._"

    # Candidate root causes
    causes = _template_causes(anomalies)

    # Recommended actions
    actions = _template_actions(anomalies)

    # Chain integrity
    chain_ok = bool(agg.get("audit_chains_ok", True))
    integrity = (
        "All drill audit chains verified. "
        f"{agg.get('drills', 0)} chains walked, "
        f"{agg.get('intents_total', 0)} records total."
    ) if chain_ok else (
        "**Audit chain break detected.** Downstream regulator bundle "
        "MUST be regenerated from the last verified seq_no. Investigate "
        "immediately."
    )

    md = (
        f"## Headline\n{headline}\n\n"
        f"## Anomalies\n{anomalies_md}\n\n"
        f"## Candidate root causes\n{causes}\n\n"
        f"## Recommended actions\n{actions}\n\n"
        f"## Chain integrity\n{integrity}\n"
    )
    return md


def _template_causes(anomalies: List[Anomaly]) -> str:
    if not anomalies:
        return (
            "No anomaly triggered -- no candidate causes surfaced. "
            "Operational posture remains **green**."
        )
    bullets: List[str] = []
    seen: set = set()
    for a in anomalies:
        if a.kind in seen:
            continue
        seen.add(a.kind)
        if a.kind == "stage_latency_p99":
            bullets.append(
                f"Stage `{a.stage}` p99 drifted above warn threshold -- "
                "candidates: pipeline contention, XDMA back-pressure, "
                "or a traffic burst that outran the credit window."
            )
        elif a.kind == "reject_rate_high":
            bullets.append(
                "Reject rate elevated -- candidates: position limit "
                "too tight for the day's flow, or a strategy emitting "
                "stale quotes."
            )
        elif a.kind == "toxic_dominant":
            bullets.append(
                "TOXIC_FLOW dominates the reject mix -- candidates: "
                "adversary probing, stale quote exposure, or "
                "ToxicFlowScorer threshold slippage."
            )
        elif a.kind == "audit_chain_break":
            bullets.append(
                "Audit chain broken -- candidates: logger crash "
                "mid-record, disk truncation, or concurrent writer. "
                "Immediate forensic."
            )
        elif a.kind == "mifid_otr_would_trip":
            bullets.append(
                "MiFID RTS 6 OTR would have tripped -- candidates: "
                "quote-storm after a vol spike, or cancel-chatter "
                "without corresponding fills."
            )
        elif a.kind == "fat_finger_excursion":
            bullets.append(
                "FINRA 15c3-5 fat-finger excursion -- candidates: "
                "strategy mis-quoting after a feed gap, or a "
                "mid-reference drift during a halt."
            )
        elif a.kind == "mar_spoofing_alerts":
            bullets.append(
                "MAR Art. 12 spoofing detector fired -- candidates: "
                "taker probing the book, or our own strategy "
                "posting/cancelling in a window tighter than policy."
            )
        else:
            bullets.append(f"`{a.kind}` -- see anomaly detail for context.")
    return "\n".join(f"- {b}" for b in bullets)


def _template_actions(anomalies: List[Anomaly]) -> str:
    if not anomalies:
        return "- Hold the line. Continue monitoring."
    bullets: List[str] = []
    seen: set = set()
    for a in anomalies:
        if a.kind in seen:
            continue
        seen.add(a.kind)
        if a.kind == "stage_latency_p99":
            bullets.append(
                "Pull the trace fragment for the worst-bar window and "
                "confirm the stage is saturating, not flapping."
            )
        elif a.kind == "reject_rate_high":
            bullets.append(
                "Review the per-reason histogram and validate the "
                "limit configuration against expected day-flow."
            )
        elif a.kind == "toxic_dominant":
            bullets.append(
                "Escalate to alpha desk: review top takers by "
                "ewma_drift_ticks, consider quote-size reduction."
            )
        elif a.kind == "audit_chain_break":
            bullets.append(
                "Freeze the affected session, open an incident, "
                "regenerate DORA bundle from last verified seq."
            )
        elif a.kind == "mifid_otr_would_trip":
            bullets.append(
                "Send the OTR counter snapshot to compliance and "
                "confirm whether a live enforcement cutover is due."
            )
        elif a.kind == "fat_finger_excursion":
            bullets.append(
                "Validate mid-reference drift against primary-venue "
                "quote feed; widen/tighten the FatFingerGuard band "
                "only after feed root-cause."
            )
        elif a.kind == "mar_spoofing_alerts":
            bullets.append(
                "Export the ``last_alerts`` block to the market-abuse "
                "desk; confirm whether alerts originate from our book."
            )
        else:
            bullets.append(f"Investigate `{a.kind}`.")
    return "\n".join(f"- {b}" for b in bullets)


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------


def generate_digest(
    features: RcaFeatures,
    *,
    backend: str = "auto",
    model: str = DEFAULT_MODEL,
) -> DigestResult:
    """Produce a ``DigestResult`` from a feature bundle.

    ``backend`` is one of:
      * ``"auto"``     -- try Anthropic, fall back to template.
      * ``"anthropic"`` -- only try Anthropic, template on failure.
      * ``"template"`` -- deterministic template only.
    """
    prompt = _format_prompt(features)
    phash = _prompt_hash(prompt)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    md: Optional[str] = None
    used_backend = "template"
    used_model: Optional[str] = None

    if backend in ("auto", "anthropic"):
        md = _try_anthropic(prompt, model=model)
        if md is not None:
            used_backend = "anthropic"
            used_model = model

    if md is None:
        md = _template_digest(features)
        used_backend = "template"

    return DigestResult(
        schema=DIGEST_SCHEMA_VERSION,
        date=features.window_end or features.window_start or date.today().isoformat(),
        markdown=md,
        backend=used_backend,
        model=used_model,
        prompt_sha256=phash,
        features=features.to_dict(),
        generated_at=now,
    )


def run_nightly(
    *,
    artifacts_root: Path,
    digest_dir: Path,
    run_date: Optional[str] = None,
    backend: str = "auto",
    model: str = DEFAULT_MODEL,
) -> DigestResult:
    """Full nightly run: discover drills, build features, generate
    digest, archive to ``digest_dir/<date>.md`` + ``<date>.json``.

    Returns the ``DigestResult``. Raises if the features are empty
    (meaning the scheduled job should surface a "no data" alert
    separately -- we don't want to silently archive empty digests).
    """
    artifacts_root = Path(artifacts_root)
    digest_dir = Path(digest_dir)
    digest_dir.mkdir(parents=True, exist_ok=True)

    iso_date = run_date or date.today().isoformat()
    feats = build_features_from_root(
        artifacts_root,
        window_start=iso_date,
        window_end=iso_date,
    )
    if not feats.drills and not feats.provenance:
        raise RuntimeError(
            f"no drill artifacts discovered under {artifacts_root}"
        )

    digest = generate_digest(feats, backend=backend, model=model)

    md_path = digest_dir / f"{iso_date}.md"
    json_path = digest_dir / f"{iso_date}.json"
    md_path.write_text(digest.markdown, encoding="utf-8")
    json_path.write_text(
        json.dumps(digest.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return digest


def list_digests(digest_dir: Path) -> List[Dict[str, Any]]:
    """List archived digests (newest first)."""
    digest_dir = Path(digest_dir)
    if not digest_dir.exists():
        return []
    out: List[Dict[str, Any]] = []
    for p in sorted(digest_dir.glob("*.json"), reverse=True):
        try:
            with p.open("r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        out.append({
            "date": d.get("date"),
            "backend": d.get("backend"),
            "model": d.get("model"),
            "prompt_sha256": d.get("prompt_sha256"),
            "path_md": str(p.with_suffix(".md")),
            "path_json": str(p),
            "anomaly_count": len(d.get("features", {}).get("anomalies", [])),
        })
    return out


def load_digest(digest_dir: Path, iso_date: str) -> Optional[Dict[str, Any]]:
    digest_dir = Path(digest_dir)
    json_path = digest_dir / f"{iso_date}.json"
    if not json_path.exists():
        return None
    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)


__all__ = [
    "DIGEST_SCHEMA_VERSION",
    "DEFAULT_MODEL",
    "DigestResult",
    "generate_digest",
    "list_digests",
    "load_digest",
    "run_nightly",
]
