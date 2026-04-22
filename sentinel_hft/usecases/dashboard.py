"""Top-level cover dashboard for the Hyperliquid use-case suite.

Story this page tells
---------------------

A Keyrock interviewer opens ``dashboard.html`` and immediately sees
which of the four demonstrations have been executed, their headline
numbers (toxic rejects, kill-switch SLO, p99 latency, daily evidence
chain verification), and a link to the detail page for each. Use
cases that were not executed render as greyed-out "not run" cards --
the page does not 404 on a partial run.

The page is intentionally self-contained: it reads every use case's
``*.json`` report file off disk (relative to the output root) and
renders inline SVG summary widgets. There is no server, no template
engine, and no external JS.

Discovery
---------

By default :func:`build_dashboard` probes this layout off the supplied
output root::

    <root>/
        toxic_flow/toxic_flow.json         (+.md, +.html)
        kill_drill/kill_drill.json
        latency/latency.json
        daily_evidence/daily_evidence.json

If a use case's JSON is missing the card is rendered as "not run".
If the JSON is present but malformed the card renders an error panel
so the interviewer still sees the failure explicitly.

API
---

``build_dashboard(root) -> Path``
    Renders and writes ``<root>/dashboard.html``; returns the path.

``build_dashboard(root, out_path=...)``
    Writes to an explicit path instead.
"""

from __future__ import annotations

import datetime as _dt
import html as _html
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import _html as H


# ---------------------------------------------------------------------
# Per use-case descriptors
# ---------------------------------------------------------------------


@dataclass
class _UseCase:
    """Definition of where each use case's artifacts live."""

    key: str                 # short slug ("toxic_flow")
    title: str               # human-readable card title
    blurb: str               # one-line story
    subdir: str              # default subfolder name under root
    json_name: str           # report filename inside the subfolder
    html_name: str           # detail HTML filename
    md_name: str             # markdown filename


_USE_CASES: List[_UseCase] = [
    _UseCase(
        key="toxic_flow",
        title="Toxic-flow pre-gate",
        blurb=("Learns each taker's post-trade drift; blocks quote "
               "intents exposed to concentrated toxic flow."),
        subdir="toxic_flow",
        json_name="toxic_flow.json",
        html_name="toxic_flow.html",
        md_name="toxic_flow.md",
    ),
    _UseCase(
        key="kill_drill",
        title="Vol-spike kill-switch drill",
        blurb=("Injects a synthetic volatility regime change and "
               "verifies the kill latch trips under SLO."),
        subdir="kill_drill",
        json_name="kill_drill.json",
        html_name="kill_drill.html",
        md_name="kill_drill.md",
    ),
    _UseCase(
        key="latency",
        title="Wire-to-wire latency attribution",
        blurb=("Per-stage ns attribution across ingress / core / risk"
               " / egress from v1.2 traces."),
        subdir="latency",
        json_name="latency.json",
        html_name="latency.html",
        md_name="latency.md",
    ),
    _UseCase(
        key="daily_evidence",
        title="Daily DORA evidence pack",
        blurb=("Three concatenated sessions commit to a multi-session "
               "bundle with per-session chain verification."),
        subdir="daily_evidence",
        json_name="daily_evidence.json",
        html_name="daily_evidence.html",
        md_name="daily_evidence.md",
    ),
]


# ---------------------------------------------------------------------
# Per-card datum
# ---------------------------------------------------------------------


@dataclass
class _CardData:
    """What we extract from each use case's JSON to draw its card."""

    uc: _UseCase
    state: str                # "ok" | "warn" | "err" | "missing" | "broken"
    status_text: str          # human summary
    html_href: Optional[str] = None
    md_href: Optional[str] = None
    json_href: Optional[str] = None
    subject: str = ""
    environment: str = ""
    run_id_hex: str = ""
    kv: List[Tuple[str, str, str]] = field(default_factory=list)
    json_error: str = ""


# ---------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------


def build_dashboard(
    root: Path,
    *,
    out_path: Optional[Path] = None,
    title: str = "Sentinel-HFT Hyperliquid demo",
    subtitle: str = ("Cover page aggregating the four use-case "
                     "artifacts in this run."),
) -> Path:
    """Render the cover dashboard. Returns the output HTML path."""
    root = Path(root)
    out_path = Path(out_path) if out_path else root / "dashboard.html"
    root.mkdir(parents=True, exist_ok=True)

    cards = [_collect_card(root, uc) for uc in _USE_CASES]

    # Overall status for the banner.
    overall_state = _overall_state(cards)

    body_parts: List[str] = []
    body_parts.append(H.page_start(
        title,
        subtitle=subtitle,
        env=_env_from_cards(cards),
        run_id_hex=_run_id_from_cards(cards),
    ))

    body_parts.append(_banner(cards, overall_state, root))
    body_parts.append(_grid(cards, out_path))
    body_parts.append(_footer(root, cards))

    body_parts.append(H.page_end())

    out_path.write_text("\n".join(body_parts))
    return out_path


# ---------------------------------------------------------------------
# Card collection
# ---------------------------------------------------------------------


def _collect_card(root: Path, uc: _UseCase) -> _CardData:
    """Locate the JSON for a use case and build its card data."""
    # Try the canonical subdir first, then a flat fallback.
    candidates = [
        root / uc.subdir / uc.json_name,
        root / uc.json_name,
    ]
    json_path = next((p for p in candidates if p.is_file()), None)

    if json_path is None:
        return _CardData(
            uc=uc,
            state="missing",
            status_text="not run",
        )

    try:
        doc = json.loads(json_path.read_text())
    except Exception as exc:  # pragma: no cover - defensive
        return _CardData(
            uc=uc,
            state="broken",
            status_text=f"JSON parse error: {exc}",
            json_error=str(exc),
            json_href=str(json_path.relative_to(root)),
        )

    # Build the hrefs relative to the dashboard location (which is root).
    html_path = json_path.parent / uc.html_name
    md_path = json_path.parent / uc.md_name

    card = _CardData(
        uc=uc,
        state="ok",
        status_text="",
        json_href=str(json_path.relative_to(root)),
        html_href=(str(html_path.relative_to(root))
                   if html_path.is_file() else None),
        md_href=(str(md_path.relative_to(root))
                 if md_path.is_file() else None),
        subject=str(doc.get("subject", "")),
        environment=str(doc.get("environment", "")),
        run_id_hex=str(doc.get("run_id_hex", "")),
    )

    if uc.key == "toxic_flow":
        _populate_toxic_flow(card, doc)
    elif uc.key == "kill_drill":
        _populate_kill_drill(card, doc)
    elif uc.key == "latency":
        _populate_latency(card, doc)
    elif uc.key == "daily_evidence":
        _populate_daily_evidence(card, doc)
    return card


def _populate_toxic_flow(card: _CardData, doc: dict) -> None:
    th = doc.get("throughput", {}) or {}
    lat = doc.get("latency_ns", {}) or {}
    au = doc.get("audit", {}) or {}
    sc = doc.get("scorer", {}) or {}

    intents = int(th.get("intents", 0))
    rej_toxic = int(th.get("rejected_toxic", 0))
    chain_ok = bool(au.get("chain_ok", False))
    toxic_pct = rej_toxic / intents if intents else 0.0

    card.kv = [
        ("Quote intents",     f"{intents:,}", ""),
        ("Toxic rejects",     f"{rej_toxic:,} ({toxic_pct*100:.1f}%)",
         "warn" if rej_toxic > 0 else ""),
        ("Wallets / TOXIC",
         f"{sc.get('takers', 0):,} / {sc.get('toxic', 0):,}",
         "warn" if sc.get("toxic", 0) > 0 else ""),
        ("p99 latency",       H.fmt_ns(float(lat.get("p99", 0))), ""),
        ("Audit chain",
         "PASS" if chain_ok else "FAIL",
         "ok" if chain_ok else "err"),
    ]

    # State
    if not chain_ok:
        card.state = "err"
        card.status_text = "Audit chain FAILED."
    elif rej_toxic == 0:
        card.state = "warn"
        card.status_text = ("No toxic-flow rejects fired -- check fixture "
                            "toxic share / minimum flow events.")
    else:
        card.state = "ok"
        card.status_text = (f"{rej_toxic:,} toxic rejects blocked, "
                            f"{sc.get('toxic', 0):,} wallets learned as TOXIC.")


def _populate_kill_drill(card: _CardData, doc: dict) -> None:
    kill = doc.get("kill", {}) or {}
    lat = doc.get("latency_ns", {}) or {}
    au = doc.get("audit", {}) or {}

    triggered = bool(kill.get("triggered", False))
    within = bool(kill.get("within_slo", False))
    kill_ns = int(kill.get("latency_ns") or 0)
    slo_ns = int(kill.get("within_slo_ns") or 0)
    mismatch = int(kill.get("post_trip_mismatch", 0))
    chain_ok = bool(au.get("chain_ok", False))

    card.kv = [
        ("Kill triggered",
         "yes" if triggered else "no",
         "ok" if triggered else "warn"),
        ("Kill latency",
         H.fmt_ns(kill_ns) if triggered else "n/a",
         "ok" if triggered and within else ("err" if triggered and not within
                                            else "")),
        ("SLO budget",        H.fmt_ns(slo_ns), ""),
        ("Post-trip mismatch",
         f"{mismatch:,}",
         "err" if mismatch > 0 else "ok"),
        ("p99 latency",       H.fmt_ns(float(lat.get("p99", 0))), ""),
        ("Audit chain",
         "PASS" if chain_ok else "FAIL",
         "ok" if chain_ok else "err"),
    ]

    # State resolution.
    if not chain_ok:
        card.state = "err"
        card.status_text = "Audit chain FAILED."
    elif not triggered:
        card.state = "warn"
        card.status_text = "Kill switch never tripped in the run."
    elif mismatch > 0:
        card.state = "err"
        card.status_text = (f"{mismatch:,} post-trip decisions did not "
                            f"reject with KILL_SWITCH.")
    elif not within:
        card.state = "err"
        card.status_text = (f"Kill tripped at {H.fmt_ns(kill_ns)} "
                            f"(over SLO {H.fmt_ns(slo_ns)}).")
    else:
        card.state = "ok"
        card.status_text = (f"Kill tripped at {H.fmt_ns(kill_ns)} "
                            f"under SLO {H.fmt_ns(slo_ns)}.")


def _populate_latency(card: _CardData, doc: dict) -> None:
    lat = doc.get("latency_ns", {}) or {}
    slo = doc.get("slo", {}) or {}

    p99 = float(lat.get("p99", 0))
    slo_ns = int(slo.get("p99_budget_ns") or 0)
    viol = int(slo.get("violations", 0))
    viol_rate = float(slo.get("violation_rate", 0.0))
    bn = str(doc.get("bottleneck_stage", "") or "")

    card.kv = [
        ("Samples",           f"{int(lat.get('count', 0)):,}", ""),
        ("p50",               H.fmt_ns(float(lat.get("p50", 0))), ""),
        ("p99",               H.fmt_ns(p99),
         "err" if (slo_ns and p99 > slo_ns) else "ok"),
        ("p99.9",             H.fmt_ns(float(lat.get("p999", 0))), ""),
        ("SLO budget (p99)",  H.fmt_ns(slo_ns) if slo_ns else "n/a", ""),
        ("SLO violations",
         f"{viol:,} ({viol_rate*100:.3f}%)",
         "err" if viol > 0 else "ok"),
        ("Bottleneck",        bn.upper() if bn else "n/a", ""),
    ]

    if slo_ns and p99 > slo_ns:
        card.state = "err"
        card.status_text = (f"p99 {H.fmt_ns(p99)} exceeds SLO "
                            f"{H.fmt_ns(slo_ns)}.")
    elif viol > 0:
        card.state = "warn"
        card.status_text = (f"{viol:,} SLO violations "
                            f"({viol_rate*100:.3f}%) in the tail.")
    else:
        card.state = "ok"
        card.status_text = (f"p99 {H.fmt_ns(p99)} under SLO "
                            f"{H.fmt_ns(slo_ns)}; "
                            f"bottleneck={bn or 'n/a'}.")


def _populate_daily_evidence(card: _CardData, doc: dict) -> None:
    sm = doc.get("summary", {}) or {}
    sess = doc.get("sessions", []) or []

    sessions = int(sm.get("sessions", 0))
    records = int(sm.get("records_total", 0))
    passed = int(sm.get("passed_total", 0))
    rejected = int(sm.get("rejected_total", 0))
    toxic = int(sm.get("toxic_flow_rejects_total", 0))
    kill_ev = int(sm.get("kill_switch_events_total", 0))
    all_ok = bool(sm.get("all_chains_ok", False))

    card.kv = [
        ("Sessions",          f"{sessions:,}", ""),
        ("Records",           f"{records:,}", ""),
        ("Passed / Rejected", f"{passed:,} / {rejected:,}", ""),
        ("Toxic rejects",     f"{toxic:,}",
         "warn" if toxic > 0 else ""),
        ("Kill events",       f"{kill_ev:,}",
         "warn" if kill_ev > 0 else ""),
        ("Chains verified",
         "PASS" if all_ok else "FAIL",
         "ok" if all_ok else "err"),
    ]

    if not all_ok:
        card.state = "err"
        card.status_text = "At least one session chain verification FAILED."
    else:
        card.state = "ok"
        card.status_text = (f"{sessions} sessions / {records:,} records "
                            f"committed; all chains verified.")


# ---------------------------------------------------------------------
# Banner / grid / footer
# ---------------------------------------------------------------------


def _banner(cards: List[_CardData], overall: str, root: Path) -> str:
    total = len(cards)
    ok = sum(1 for c in cards if c.state == "ok")
    warn = sum(1 for c in cards if c.state == "warn")
    err = sum(1 for c in cards if c.state == "err")
    missing = sum(1 for c in cards if c.state == "missing")
    broken = sum(1 for c in cards if c.state == "broken")

    pill_cls = {"ok": "ok", "warn": "warn", "err": "err",
                "partial": "warn", "empty": ""}[overall]
    headline_text = {
        "ok": "all use cases green",
        "warn": "some use cases warn",
        "err": "one or more use cases failed",
        "partial": "partial run -- some use cases missing",
        "empty": "no use-case artifacts found",
    }[overall]

    generated = _dt.datetime.now(tz=_dt.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC")

    kv = [
        ("Overall",   headline_text, pill_cls),
        ("OK",        f"{ok}/{total}", "ok" if ok == total else ""),
        ("WARN",      f"{warn}",       "warn" if warn else ""),
        ("FAIL",      f"{err}",        "err" if err else ""),
        ("Not run",   f"{missing}",    ""),
        ("Broken",    f"{broken}",     "err" if broken else ""),
        ("Root",      str(root),       ""),
        ("Generated", generated,       ""),
    ]

    return '<div class="row">' + H.kv_panel("Run status", kv) + "</div>"


def _grid(cards: List[_CardData], dashboard_path: Path) -> str:
    out: List[str] = ['<div class="row">']
    for card in cards:
        out.append(_card_html(card, dashboard_path))
    out.append("</div>")
    return "\n".join(out)


def _card_html(card: _CardData, dashboard_path: Path) -> str:
    uc = card.uc
    tag_cls = {
        "ok": "ok",
        "warn": "warn",
        "err": "err",
        "missing": "",
        "broken": "err",
    }[card.state]
    tag_text = {
        "ok": "OK",
        "warn": "WARN",
        "err": "FAIL",
        "missing": "not run",
        "broken": "broken",
    }[card.state]

    # Header
    parts: List[str] = [
        '<div class="panel" style="flex:1 1 480px;">',
        '<div style="display:flex;align-items:baseline;gap:10px;">',
        f'<h3 style="margin:0;">{_html.escape(uc.title)}</h3>',
        H.status_tag(tag_cls, tag_text),
        "</div>",
        f'<p class="crumbs">{_html.escape(uc.blurb)}</p>',
    ]

    if card.state == "missing":
        parts.append(
            '<p class="crumbs">Run '
            f'<code>sentinel-hft hl {uc.key.replace("_", "-")}</code> '
            'to produce this artifact.</p>'
        )
        parts.append("</div>")
        return "\n".join(parts)

    if card.state == "broken":
        parts.append(
            '<p class="crumbs" style="color:var(--err);">'
            f'Report JSON failed to parse: '
            f'<code>{_html.escape(card.json_error)}</code></p>'
        )
        parts.append("</div>")
        return "\n".join(parts)

    # Status line
    if card.status_text:
        parts.append(
            f'<p><strong>{_html.escape(card.status_text)}</strong></p>'
        )

    # KV grid
    parts.append('<div class="kv" style="margin-top:4px;">')
    for k, v, cls in card.kv:
        parts.append(f'<div class="k">{_html.escape(k)}</div>')
        cls_txt = f' {cls}' if cls else ""
        parts.append(
            f'<span class="v{cls_txt}">{_html.escape(v)}</span>'
        )
    parts.append("</div>")

    # Links row
    links: List[str] = []
    if card.html_href:
        links.append(
            f'<a href="{_html.escape(card.html_href)}">Open dashboard &rarr;</a>'
        )
    if card.md_href:
        links.append(
            f'<a href="{_html.escape(card.md_href)}">markdown</a>'
        )
    if card.json_href:
        links.append(
            f'<a href="{_html.escape(card.json_href)}">json</a>'
        )
    if links:
        parts.append(
            '<p class="crumbs" style="margin-top:10px;">'
            + " &nbsp;|&nbsp; ".join(links) + "</p>"
        )

    if card.subject or card.environment:
        meta_bits = []
        if card.subject:
            meta_bits.append(
                f'subject=<code>{_html.escape(card.subject)}</code>')
        if card.environment:
            meta_bits.append(
                f'env=<code>{_html.escape(card.environment)}</code>')
        if card.run_id_hex:
            meta_bits.append(
                f'run=<code>{_html.escape(card.run_id_hex)}</code>')
        parts.append(
            '<p class="crumbs" style="margin-top:4px;">'
            + " &nbsp;&middot;&nbsp; ".join(meta_bits) + "</p>"
        )

    parts.append("</div>")
    return "\n".join(parts)


def _footer(root: Path, cards: List[_CardData]) -> str:
    # Build a tree of all top-level artifacts surfaced across the use
    # cases so a reviewer can see the on-disk layout at a glance.
    rows: List[str] = []
    for c in cards:
        if c.state in ("missing",):
            continue
        href_html = (f'<a href="{_html.escape(c.html_href)}">'
                     f'{_html.escape(c.html_href)}</a>'
                     if c.html_href else "-")
        href_md = (f'<a href="{_html.escape(c.md_href)}">'
                   f'{_html.escape(c.md_href)}</a>' if c.md_href else "-")
        href_json = (f'<a href="{_html.escape(c.json_href)}">'
                     f'{_html.escape(c.json_href)}</a>'
                     if c.json_href else "-")
        rows.append(
            "<tr>"
            f"<td>{_html.escape(c.uc.title)}</td>"
            f"<td>{href_html}</td>"
            f"<td>{href_md}</td>"
            f"<td>{href_json}</td>"
            "</tr>"
        )

    table = (
        '<div class="panel"><h3>Artifacts on disk</h3>'
        '<table class="data">'
        '<tr><th>Use case</th><th>HTML</th><th>Markdown</th>'
        '<th>JSON</th></tr>'
        + "".join(rows)
        + "</table>"
        '<p class="crumbs" style="margin-top:8px;">'
        f'Root: <code>{_html.escape(str(root))}</code>'
        '</p></div>'
    )

    notes = (
        '<div class="panel"><h3>What this page is</h3>'
        '<p>The Sentinel-HFT Hyperliquid demo ships four self-contained '
        'use-case pages, each backed by its own JSON / Markdown / audit / '
        'trace / DORA artifacts. This dashboard is a thin cover that '
        'auto-discovers which of them have been executed against the '
        'current output directory. Every number on a card is derived '
        'from the use case\'s own JSON report, so the cover and the '
        'detail pages are guaranteed to agree.</p>'
        '<p class="crumbs">Layout: no external JS or CSS, inline SVG '
        'only, A4-printable. The page is safe to hand to a regulator '
        'offline.</p>'
        '</div>'
    )

    return table + notes


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _overall_state(cards: List[_CardData]) -> str:
    """Aggregate state for the banner pill."""
    if all(c.state == "missing" for c in cards):
        return "empty"
    if any(c.state in ("err", "broken") for c in cards):
        return "err"
    if any(c.state == "missing" for c in cards):
        # Partial run -- any missing use case is a warn, not a fail.
        return "partial"
    if any(c.state == "warn" for c in cards):
        return "warn"
    return "ok"


def _env_from_cards(cards: List[_CardData]) -> str:
    for c in cards:
        if c.environment:
            return c.environment
    return "sim"


def _run_id_from_cards(cards: List[_CardData]) -> Optional[str]:
    for c in cards:
        if c.run_id_hex:
            return c.run_id_hex
    return None


__all__ = ["build_dashboard"]
