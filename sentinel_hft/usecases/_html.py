"""Minimal HTML + inline-SVG rendering helpers for the use-case UI.

The use-case runners each emit a single self-contained HTML file.
This module centralises the CSS, chrome, and SVG chart primitives so
the four pages share a look without pulling in a templating engine
or any external JS framework.

Design goals:

* **Zero dependencies.** No Jinja, no D3, no Chart.js -- everything
  is plain strings. A Keyrock reviewer should be able to open
  ``toxic_flow.html`` on an airgapped laptop and see the story.
* **Dense but legible.** We are showing quantiles, rejection mixes,
  and audit summaries to an interviewer who knows what a p99 is.
  The grid is tight, the charts are small, the colours signal state
  (green = good, amber = SLO warn, red = breach).
* **Printable.** The pages render fine when printed to PDF at A4.
  The ``<style>`` block includes a ``@media print`` section so the
  story survives regulator hand-off.
"""

from __future__ import annotations

import html as _html
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------
# CSS / page chrome
# ---------------------------------------------------------------------


_BASE_CSS = """
:root {
  --fg: #1e2430;
  --fg-dim: #5a6170;
  --bg: #f7f9fc;
  --panel: #ffffff;
  --border: #dde3ee;
  --accent: #0b63c5;
  --ok: #1c8a4b;
  --warn: #d97706;
  --err: #c0392b;
  --toxic: #be123c;
  --neutral: #5a6170;
  --benign: #1c8a4b;
  --chart-grid: #e5eaf2;
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color: var(--fg);
  background: var(--bg);
  font-size: 14px;
  line-height: 1.45;
}
.wrap {
  max-width: 1140px;
  margin: 0 auto;
  padding: 32px 28px 64px 28px;
}
header.banner {
  border-bottom: 1px solid var(--border);
  padding: 16px 24px;
  background: var(--panel);
  display: flex;
  align-items: baseline;
  gap: 18px;
}
header.banner h1 { margin: 0; font-size: 20px; }
header.banner .crumbs { color: var(--fg-dim); font-size: 13px; }
header.banner .pill {
  border: 1px solid var(--border);
  padding: 2px 8px;
  border-radius: 99px;
  font-size: 12px;
  color: var(--fg-dim);
}
h2 { margin: 28px 0 10px 0; font-size: 17px; }
h3 { margin: 20px 0 6px 0; font-size: 15px; }
p  { margin: 6px 0 10px 0; }
.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px 18px;
  margin: 14px 0;
}
.row { display: flex; flex-wrap: wrap; gap: 14px; }
.row > .panel { flex: 1 1 320px; }
.kv {
  display: grid;
  grid-template-columns: 1fr auto;
  row-gap: 4px;
  column-gap: 14px;
  font-family: var(--mono);
  font-size: 13px;
}
.kv .k { color: var(--fg-dim); }
.kv .v { text-align: right; }
.kv .v.ok { color: var(--ok); }
.kv .v.warn { color: var(--warn); }
.kv .v.err { color: var(--err); }
table.data {
  border-collapse: collapse; width: 100%;
  font-family: var(--mono); font-size: 13px;
}
table.data th, table.data td {
  text-align: left;
  padding: 5px 10px;
  border-bottom: 1px solid var(--border);
}
table.data th { color: var(--fg-dim); font-weight: 500; }
.tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 99px;
  font-size: 12px;
  font-family: var(--mono);
}
.tag.ok { background: #e6f6ed; color: var(--ok); }
.tag.warn { background: #fff5e6; color: var(--warn); }
.tag.err { background: #fbe9e6; color: var(--err); }
.tag.toxic { background: #fde2e8; color: var(--toxic); }
.tag.neutral { background: #edf0f5; color: var(--neutral); }
.tag.benign { background: #e6f6ed; color: var(--benign); }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
pre.mono {
  background: #f1f4fa;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px;
  font-family: var(--mono);
  font-size: 12px;
  overflow-x: auto;
}
svg.chart { display: block; }
@media print {
  body { background: #fff; }
  .wrap { max-width: 100%; padding: 0 12mm; }
  .panel { page-break-inside: avoid; }
  header.banner { border-bottom: 1px solid #000; }
}
""".strip()


def page_start(title: str, subtitle: str = "", env: str = "sim",
               run_id_hex: Optional[str] = None) -> str:
    """Top of the page: ``<html>`` header + banner. Call page_end after."""
    crumbs = "Sentinel-HFT — Hyperliquid demo"
    run_pill = (f'<span class="pill">run {run_id_hex}</span>'
                if run_id_hex else "")
    env_pill = f'<span class="pill">env: {_html.escape(env)}</span>'
    sub = (f'<div class="crumbs">{_html.escape(subtitle)}</div>'
           if subtitle else "")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_html.escape(title)}</title>
<style>{_BASE_CSS}</style>
</head>
<body>
<header class="banner">
  <h1>{_html.escape(title)}</h1>
  <div class="crumbs">{crumbs}</div>
  {sub}
  {env_pill}
  {run_pill}
</header>
<div class="wrap">
"""


def page_end() -> str:
    return """</div>
</body>
</html>
"""


# ---------------------------------------------------------------------
# Generic widgets
# ---------------------------------------------------------------------


def kv_panel(title: str, rows: Iterable[Tuple[str, str, str]]) -> str:
    """Render a small key/value panel.

    Each row is ``(key, value, cls)`` where cls is ``""`` / ``"ok"`` /
    ``"warn"`` / ``"err"`` and is applied to the value cell for
    colour-coding.
    """
    body = ['<div class="kv">']
    for k, v, cls in rows:
        vv = f'<span class="v {cls}">{_html.escape(str(v))}</span>' if cls \
             else f'<span class="v">{_html.escape(str(v))}</span>'
        body.append(
            f'<div class="k">{_html.escape(str(k))}</div>{vv}'
        )
    body.append("</div>")
    inner = "\n".join(body)
    return f'<div class="panel"><h3>{_html.escape(title)}</h3>{inner}</div>'


def table_panel(
    title: str,
    headers: Sequence[str],
    rows: Iterable[Sequence[str]],
    *,
    max_rows: Optional[int] = None,
) -> str:
    """Render a simple table panel."""
    row_list = list(rows)
    truncated = False
    if max_rows is not None and len(row_list) > max_rows:
        row_list = row_list[:max_rows]
        truncated = True
    thead = "<tr>" + "".join(
        f"<th>{_html.escape(h)}</th>" for h in headers
    ) + "</tr>"
    tbody = "\n".join(
        "<tr>" + "".join(
            f"<td>{_html.escape(str(c))}</td>" for c in r
        ) + "</tr>"
        for r in row_list
    )
    tail = ""
    if truncated:
        tail = f'<p class="crumbs">Showing first {max_rows} rows.</p>'
    return (
        f'<div class="panel"><h3>{_html.escape(title)}</h3>'
        f'<table class="data">{thead}{tbody}</table>{tail}</div>'
    )


def narrative(title: str, html_body: str) -> str:
    """A markdown-ish panel: the caller already escapes where needed."""
    return (
        f'<div class="panel"><h3>{_html.escape(title)}</h3>{html_body}</div>'
    )


# ---------------------------------------------------------------------
# SVG primitives
# ---------------------------------------------------------------------


def svg_bar_chart(
    title: str,
    categories: Sequence[str],
    values: Sequence[float],
    *,
    width: int = 520,
    height: int = 240,
    colour: str = "#0b63c5",
    y_unit: str = "",
    threshold: Optional[float] = None,
    threshold_label: str = "SLO",
) -> str:
    """Horizontal bar chart, left-labelled.

    Renders small enough to sit inside a panel; tall enough to
    distinguish 6-8 categories. Use ``threshold`` to draw an amber
    reference line (e.g. an SLO).
    """
    n = max(1, len(categories))
    margin_left = 80
    margin_right = 60
    margin_top = 20
    margin_bottom = 30
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    vmax = max(values) if values else 1.0
    if threshold is not None:
        vmax = max(vmax, threshold)
    if vmax <= 0:
        vmax = 1.0
    vmax *= 1.10

    bar_h = plot_h / n * 0.7
    gap = (plot_h / n) * 0.3

    parts: List[str] = []
    parts.append(
        f'<svg class="chart" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{_html.escape(title)}">'
    )
    # Title
    parts.append(
        f'<text x="{margin_left}" y="14" font-size="12" '
        f'fill="#5a6170">{_html.escape(title)}</text>'
    )
    # X axis line
    parts.append(
        f'<line x1="{margin_left}" y1="{margin_top + plot_h}" '
        f'x2="{margin_left + plot_w}" y2="{margin_top + plot_h}" '
        f'stroke="#dde3ee" />'
    )
    # Threshold
    if threshold is not None:
        tx = margin_left + plot_w * (threshold / vmax)
        parts.append(
            f'<line x1="{tx:.1f}" y1="{margin_top}" '
            f'x2="{tx:.1f}" y2="{margin_top + plot_h}" '
            f'stroke="#d97706" stroke-width="1" stroke-dasharray="4 3" />'
        )
        parts.append(
            f'<text x="{tx:.1f}" y="{margin_top - 4}" font-size="10" '
            f'fill="#d97706" text-anchor="middle">'
            f'{_html.escape(threshold_label)} {threshold:.0f}{y_unit}</text>'
        )
    # Bars
    for i, (cat, v) in enumerate(zip(categories, values)):
        y = margin_top + i * (plot_h / n) + gap / 2
        w = max(0.0, min(plot_w, plot_w * (v / vmax)))
        colour_use = colour
        if threshold is not None and v > threshold:
            colour_use = "#c0392b"
        parts.append(
            f'<rect x="{margin_left}" y="{y:.1f}" '
            f'width="{w:.1f}" height="{bar_h:.1f}" '
            f'fill="{colour_use}" rx="2" />'
        )
        parts.append(
            f'<text x="{margin_left - 6}" y="{y + bar_h*0.72:.1f}" '
            f'font-size="11" text-anchor="end" fill="#1e2430">'
            f'{_html.escape(cat)}</text>'
        )
        parts.append(
            f'<text x="{margin_left + w + 4:.1f}" '
            f'y="{y + bar_h*0.72:.1f}" '
            f'font-size="11" fill="#5a6170">'
            f'{v:,.0f}{y_unit}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def svg_stacked_bar(
    title: str,
    labels: Sequence[str],
    stacks: Sequence[Sequence[float]],
    stack_names: Sequence[str],
    stack_colours: Sequence[str],
    *,
    width: int = 520,
    height: int = 240,
) -> str:
    """Vertical stacked bar (e.g. taker profiles per symbol)."""
    n = max(1, len(labels))
    margin_left = 50
    margin_right = 20
    margin_top = 30
    margin_bottom = 40
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    totals = [sum(col) for col in stacks]
    vmax = max(totals) if totals else 1.0
    if vmax <= 0:
        vmax = 1.0

    bar_w = plot_w / n * 0.65
    step = plot_w / n

    parts: List[str] = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{_html.escape(title)}">'
    ]
    parts.append(
        f'<text x="{margin_left}" y="14" font-size="12" '
        f'fill="#5a6170">{_html.escape(title)}</text>'
    )
    # Bars
    for i, (label, col) in enumerate(zip(labels, stacks)):
        cx = margin_left + i * step + (step - bar_w) / 2
        y = margin_top + plot_h
        for layer_idx, v in enumerate(col):
            h = plot_h * (v / vmax) if vmax > 0 else 0
            y -= h
            fill = stack_colours[layer_idx % len(stack_colours)]
            parts.append(
                f'<rect x="{cx:.1f}" y="{y:.1f}" '
                f'width="{bar_w:.1f}" height="{h:.1f}" '
                f'fill="{fill}" />'
            )
        parts.append(
            f'<text x="{cx + bar_w/2:.1f}" y="{margin_top + plot_h + 14}" '
            f'font-size="11" text-anchor="middle" fill="#1e2430">'
            f'{_html.escape(label)}</text>'
        )
        parts.append(
            f'<text x="{cx + bar_w/2:.1f}" y="{margin_top + plot_h - 2}" '
            f'font-size="10" text-anchor="middle" fill="#ffffff" '
            f'opacity="0.0">-</text>'  # spacer
        )
    # Legend
    lx = margin_left
    for idx, name in enumerate(stack_names):
        fill = stack_colours[idx % len(stack_colours)]
        parts.append(
            f'<rect x="{lx}" y="{height - 14}" width="10" height="10" '
            f'fill="{fill}" />'
        )
        parts.append(
            f'<text x="{lx + 14}" y="{height - 5}" font-size="11" '
            f'fill="#5a6170">{_html.escape(name)}</text>'
        )
        lx += 8 * (len(name) + 4)
    parts.append("</svg>")
    return "\n".join(parts)


def svg_histogram(
    title: str,
    samples: Sequence[float],
    *,
    bins: int = 40,
    width: int = 640,
    height: int = 220,
    colour: str = "#0b63c5",
    threshold: Optional[float] = None,
    threshold_label: str = "SLO",
    x_unit: str = "ns",
) -> str:
    """Histogram of a sample array."""
    if not samples:
        return (
            f'<svg class="chart" viewBox="0 0 {width} {height}" '
            f'xmlns="http://www.w3.org/2000/svg"><text x="20" y="40" '
            f'font-size="12" fill="#5a6170">{_html.escape(title)}: '
            f'no samples</text></svg>'
        )

    lo = min(samples)
    hi = max(samples)
    if hi <= lo:
        hi = lo + 1.0
    width_per_bin = (hi - lo) / bins
    counts = [0] * bins
    for s in samples:
        idx = int((s - lo) / width_per_bin)
        if idx >= bins:
            idx = bins - 1
        if idx < 0:
            idx = 0
        counts[idx] += 1

    margin_left = 48
    margin_right = 16
    margin_top = 22
    margin_bottom = 30
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    cmax = max(counts) if counts else 1

    parts: List[str] = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{_html.escape(title)}">'
    ]
    parts.append(
        f'<text x="{margin_left}" y="14" font-size="12" '
        f'fill="#5a6170">{_html.escape(title)}</text>'
    )
    parts.append(
        f'<line x1="{margin_left}" y1="{margin_top + plot_h}" '
        f'x2="{margin_left + plot_w}" y2="{margin_top + plot_h}" '
        f'stroke="#dde3ee" />'
    )

    bw = plot_w / bins
    for i, c in enumerate(counts):
        h = plot_h * (c / cmax) if cmax > 0 else 0
        x = margin_left + i * bw
        y = margin_top + plot_h - h
        parts.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" '
            f'width="{max(0.5, bw - 0.5):.2f}" height="{h:.2f}" '
            f'fill="{colour}" />'
        )

    if threshold is not None and hi > lo:
        if threshold < lo:
            tx = margin_left
        elif threshold > hi:
            tx = margin_left + plot_w
        else:
            tx = margin_left + plot_w * (threshold - lo) / (hi - lo)
        parts.append(
            f'<line x1="{tx:.1f}" y1="{margin_top}" '
            f'x2="{tx:.1f}" y2="{margin_top + plot_h}" '
            f'stroke="#d97706" stroke-width="1" stroke-dasharray="4 3" />'
        )
        parts.append(
            f'<text x="{tx:.1f}" y="{margin_top - 4}" font-size="10" '
            f'fill="#d97706" text-anchor="middle">'
            f'{_html.escape(threshold_label)} {threshold:,.0f}{x_unit}</text>'
        )

    # Axis labels (lo, hi)
    parts.append(
        f'<text x="{margin_left}" y="{margin_top + plot_h + 14}" '
        f'font-size="10" fill="#5a6170">{lo:,.0f}{x_unit}</text>'
    )
    parts.append(
        f'<text x="{margin_left + plot_w}" y="{margin_top + plot_h + 14}" '
        f'font-size="10" fill="#5a6170" text-anchor="end">'
        f'{hi:,.0f}{x_unit}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def svg_lineplot(
    title: str,
    xs: Sequence[float],
    ys: Sequence[float],
    *,
    width: int = 640,
    height: int = 220,
    colour: str = "#0b63c5",
    x_label: str = "",
    y_label: str = "",
    mark_x: Optional[float] = None,
    mark_label: str = "event",
) -> str:
    """Small line plot."""
    if not xs or not ys or len(xs) != len(ys):
        return (
            f'<svg class="chart" viewBox="0 0 {width} {height}" '
            f'xmlns="http://www.w3.org/2000/svg"><text x="20" y="40" '
            f'font-size="12" fill="#5a6170">{_html.escape(title)}: '
            f'no data</text></svg>'
        )
    margin_left = 52
    margin_right = 16
    margin_top = 22
    margin_bottom = 30
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    x_lo, x_hi = min(xs), max(xs)
    y_lo, y_hi = min(ys), max(ys)
    if x_hi <= x_lo:
        x_hi = x_lo + 1
    if y_hi <= y_lo:
        y_hi = y_lo + 1

    def sx(x: float) -> float:
        return margin_left + plot_w * (x - x_lo) / (x_hi - x_lo)

    def sy(y: float) -> float:
        return margin_top + plot_h - plot_h * (y - y_lo) / (y_hi - y_lo)

    parts: List[str] = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{_html.escape(title)}">'
    ]
    parts.append(
        f'<text x="{margin_left}" y="14" font-size="12" '
        f'fill="#5a6170">{_html.escape(title)}</text>'
    )
    parts.append(
        f'<line x1="{margin_left}" y1="{margin_top + plot_h}" '
        f'x2="{margin_left + plot_w}" y2="{margin_top + plot_h}" '
        f'stroke="#dde3ee" />'
    )
    parts.append(
        f'<line x1="{margin_left}" y1="{margin_top}" '
        f'x2="{margin_left}" y2="{margin_top + plot_h}" '
        f'stroke="#dde3ee" />'
    )
    path_d = " ".join(
        f"{'M' if i == 0 else 'L'} {sx(x):.1f} {sy(y):.1f}"
        for i, (x, y) in enumerate(zip(xs, ys))
    )
    parts.append(
        f'<path d="{path_d}" fill="none" stroke="{colour}" stroke-width="1.5" />'
    )
    if mark_x is not None and x_lo <= mark_x <= x_hi:
        mx = sx(mark_x)
        parts.append(
            f'<line x1="{mx:.1f}" y1="{margin_top}" '
            f'x2="{mx:.1f}" y2="{margin_top + plot_h}" '
            f'stroke="#c0392b" stroke-width="1" stroke-dasharray="4 3" />'
        )
        parts.append(
            f'<text x="{mx:.1f}" y="{margin_top - 4}" font-size="10" '
            f'fill="#c0392b" text-anchor="middle">'
            f'{_html.escape(mark_label)}</text>'
        )
    if x_label:
        parts.append(
            f'<text x="{margin_left + plot_w/2:.0f}" '
            f'y="{margin_top + plot_h + 20}" '
            f'font-size="10" text-anchor="middle" fill="#5a6170">'
            f'{_html.escape(x_label)}</text>'
        )
    if y_label:
        parts.append(
            f'<text x="{14}" y="{margin_top + plot_h/2:.0f}" '
            f'font-size="10" fill="#5a6170" '
            f'transform="rotate(-90 14 {margin_top + plot_h/2:.0f})">'
            f'{_html.escape(y_label)}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def status_tag(kind: str, text: str) -> str:
    """Render an inline status pill. ``kind`` in (ok, warn, err)."""
    k = kind if kind in ("ok", "warn", "err") else ""
    return f'<span class="tag {k}">{_html.escape(text)}</span>'


def profile_tag(profile: str) -> str:
    k = profile.lower()
    if k not in ("toxic", "neutral", "benign"):
        k = "neutral"
    return f'<span class="tag {k}">{_html.escape(profile)}</span>'


def fmt_ns(x: float) -> str:
    if x >= 1_000_000:
        return f"{x/1_000_000:.2f} ms"
    if x >= 1_000:
        return f"{x/1_000:.2f} μs"
    return f"{x:.0f} ns"


def fmt_pct(x: float) -> str:
    return f"{x*100:.1f}%"


__all__ = [
    "page_start",
    "page_end",
    "kv_panel",
    "table_panel",
    "narrative",
    "svg_bar_chart",
    "svg_stacked_bar",
    "svg_histogram",
    "svg_lineplot",
    "status_tag",
    "profile_tag",
    "fmt_ns",
    "fmt_pct",
]
