# Sentinel-HFT — Interactive Demo UI

The demo UI is a Next.js 14 front-end (`sentinel-web/`) backed by a thin
FastAPI layer (`sentinel_hft/server/demo_api.py` + `streaming.py`) that
runs the four core HL drills live and forwards progress over WebSocket.

It is strictly additive to the v1.0.0 core — all drill logic still lives
in `sentinel_hft/usecases/` and `HyperliquidRunner`. The web layer
observes via a monkey-patched subclass so there is zero drift risk
with the 33 audit work-packages closed in v1.0.0-core-audit-closed.

## End-to-end flow

1. User opens `/sentinel`. The page fetches `GET /api/drills`.
2. User picks a drill (e.g. `/sentinel/toxic_flow`) and presses "run drill".
3. UI opens a WebSocket to `/api/drills/toxic_flow/stream`, pushes the
   config overrides as the first frame.
4. The server spins up a worker thread running
   `run_toxic_flow(ticks=…, output_dir=/tmp/sentinel/toxic_flow, …)`
   with a capturing `HyperliquidRunner` subclass that exposes the live
   runner instance for snapshotting.
5. An asyncio loop polls the runner at 10 Hz and emits:
   - `start` — drill name, ticks_target, output_dir
   - `progress` — consumed/target ticks, rejects per category,
     per-stage p50/p99/mean, wire-to-wire p50/p99/p999/max, kill flag
   - `heartbeat` — keepalive every few seconds
   - `result` — final report dict (same shape as JSON artifact)
6. UI streams the progress events into:
   - 8 KPI tiles (intents, decisions, passed, rejected, p50, p99, p99.9, kill)
   - `LatencyChart` — uPlot streaming p99 line
   - `StageChart` — ECharts per-stage p50/p99 bars
   - `RejectSankey` — ECharts pass-vs-reject breakdown
7. On `result`, UI renders artifact links to `{kind}.html|json` and
   `audit.aud` served by `GET /api/artifacts/{kind}/{filename}`.

## Audit verifier

`/sentinel/audit` is an independent page:

1. User drops any `.aud` file (drills we just ran, or from CI).
2. "verify chain" → `POST /api/audit/verify` with the file as multipart.
   Backend runs the canonical host verifier and returns:
   - `ok`, `total_records`, `verified_records`
   - `head_hash_lo_hex` (first 80 bits of head BLAKE2b-256)
   - `first_break_seq_no` + sorted `breaks[]`
3. "run tamper demo" → `POST /api/audit/tamper-demo?record_index=N&byte_offset=80`.
   Backend copies the file, XORs one byte at
   `AUDIT_FILE_HEADER_SIZE + record_index*AUDIT_RECORD_SIZE + byte_offset`
   (default offset 80 lands inside `prev_hash_lo`), re-walks both copies
   side-by-side, and returns a diff. UI shows before/after panels
   side-by-side plus the caught seq_no.

## Configuration

| Env var                        | Default                     | Notes                                     |
| ------------------------------ | --------------------------- | ----------------------------------------- |
| `NEXT_PUBLIC_SENTINEL_API_URL` | `http://127.0.0.1:8000`     | Read by the UI; WS URL derived from it.   |
| `SENTINEL_CORS_ORIGINS`        | localhost:3000, :5173       | Comma-separated CORS allowlist on FastAPI |

## Running the full stack locally

```bash
# Terminal 1 — backend
python3 -m sentinel_hft.server.app

# Terminal 2 — UI
cd sentinel-web
cp .env.local.example .env.local
npm install
npm run dev
# open http://localhost:3000/sentinel
```

## Tests

- **Backend contract** — `pytest tests/test_demo_api.py -q`
  9 tests: catalog, defaults, toxic_flow run, latency run, audit verify,
  tamper demo, artifact serve, WS stream round-trip, unknown drill WS.
- **One-shot HTTP smoke** — `bash scripts/smoke_demo.sh`
  Boots the FastAPI server, curls the catalog, runs a tiny 1500-tick
  toxic_flow drill, verifies the resulting `.aud`, tears down.

## Files added for the demo UI

```
sentinel_hft/server/demo_api.py              # FastAPI router (REST + WS)
sentinel_hft/server/streaming.py             # Worker thread + observation layer
sentinel_hft/server/app.py                   # +CORS, +demo router
tests/test_demo_api.py                       # 9 pytest tests

sentinel-web/lib/sentinel-api.ts             # Typed REST + WS client
sentinel-web/lib/sentinel-types.ts           # Contract mirror of demo_api
sentinel-web/app/sentinel/layout.tsx         # Dark shell
sentinel-web/app/sentinel/page.tsx           # Overview
sentinel-web/app/sentinel/[drill]/page.tsx   # Per-drill runner + presets
sentinel-web/app/sentinel/audit/page.tsx     # Audit verifier
sentinel-web/components/sentinel/LatencyChart.tsx
sentinel-web/components/sentinel/StageChart.tsx
sentinel-web/components/sentinel/RejectSankey.tsx
scripts/smoke_demo.sh                        # End-to-end smoke
docs/DEMO_UI.md                              # This doc
```
