# sentinel-web — Sentinel-HFT demo UI

Next.js 14 / Tailwind / uPlot / ECharts front-end for the four core Sentinel-HFT
drills. Renders a trading-floor dark shell, live WebSocket progress, and a
full audit-chain verifier view — all backed by the FastAPI router in
`sentinel_hft/server/demo_api.py`.

## Routes

| Path                          | Purpose                                                      |
| ----------------------------- | ------------------------------------------------------------ |
| `/sentinel`                   | Overview grid (4 drills + verifier + release card)           |
| `/sentinel/toxic_flow`        | Pre-gate toxic-taker rejection drill                         |
| `/sentinel/kill_drill`        | Volatility kill-switch drill                                 |
| `/sentinel/latency`           | Wire-to-wire latency attribution drill                       |
| `/sentinel/daily_evidence`    | Morning / midday / EOD evidence-pack drill                   |
| `/sentinel/audit`             | Upload any `.aud` file → walk the chain / tamper demo        |

## Dev quick-start

1. Start the backend (FastAPI + WS):

   ```bash
   # from the repo root
   pip install -e .
   python3 -m sentinel_hft.server.app
   # listening on http://127.0.0.1:8000
   ```

2. Point the UI at it:

   ```bash
   cd sentinel-web
   cp .env.local.example .env.local   # already contains NEXT_PUBLIC_SENTINEL_API_URL
   npm install
   npm run dev
   # open http://localhost:3000/sentinel
   ```

Everything is wired off `NEXT_PUBLIC_SENTINEL_API_URL` (default
`http://127.0.0.1:8000`). The WS URL is derived by swapping the scheme.

## Architecture

```
┌─────────────────────┐      REST /api/drills*           ┌───────────────────────┐
│ app/sentinel/*      │ ────────────────────────────────▶│ FastAPI demo_api.py   │
│ lib/sentinel-api.ts │ ────── POST /api/drills/{k}/run ▶│ (wraps use-cases)     │
│                     │ ◀─── WS /api/drills/{k}/stream ──│ streaming.py worker   │
│ components/sentinel │      /api/audit/verify           │  → HyperliquidRunner  │
└─────────────────────┘      /api/audit/tamper-demo      └───────────────────────┘
        │
        ├── LatencyChart.tsx  → uPlot streaming p99
        ├── StageChart.tsx    → ECharts per-stage p50/p99 bars
        └── RejectSankey.tsx  → ECharts intent-flow sankey
```

The WS client opens a socket, sends the config overrides as its first
frame, then consumes `start | progress | heartbeat | result | error`
events. Progress snapshots include the per-stage histogram the stage chart
and reject sankey render from.

## Smoke test

Backend contract is covered by `tests/test_demo_api.py` (`pytest -q`) — 9 tests
including a live WS round-trip and a byte-flip tamper demo.

A one-shot end-to-end HTTP smoke test is provided at
`scripts/smoke_demo.sh` — starts the FastAPI server, curls the catalog,
fires a 1500-tick `toxic_flow` run, and verifies the resulting `.aud` file.

## Stack

- Next.js 14 App Router + Tailwind + Radix UI + lucide-react
- uPlot / uplot-react (streaming latency line)
- ECharts / echarts-for-react (stage bars + sankey)
- react-dropzone (audit upload)
- Trading-floor dark palette: `#0a0e14 / #0f151d / #1a232e / emerald-400`
