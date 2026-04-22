#!/usr/bin/env bash
#
# One-shot end-to-end smoke for the Sentinel-HFT demo stack.
#
# - boots the FastAPI server on $SMOKE_PORT (default 8765)
# - GET /api/drills (catalog must list 4 drills)
# - POST /api/drills/toxic_flow/run (ticks=1500)
# - POST /api/audit/verify on the produced audit.aud
# - tears the server down
#
# Exits 0 on pass, non-zero on any failure. Safe to run in CI.

set -euo pipefail

PORT="${SMOKE_PORT:-8765}"
HOST="127.0.0.1"
BASE="http://${HOST}:${PORT}"
OUT="$(mktemp -d -t sentinel_smoke.XXXXXX)"
PID_FILE="${OUT}/server.pid"
LOG_FILE="${OUT}/server.log"

cleanup() {
  if [[ -f "${PID_FILE}" ]]; then
    local pid
    pid="$(cat "${PID_FILE}")"
    if kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
      sleep 0.5
      kill -9 "${pid}" 2>/dev/null || true
    fi
  fi
  # keep output dir so a CI run can archive logs
  echo "[smoke] server log: ${LOG_FILE}"
  echo "[smoke] output dir: ${OUT}"
}
trap cleanup EXIT

echo "[smoke] starting FastAPI server on :${PORT} ..."
(
  cd "$(dirname "$0")/.."
  SENTINEL_CORS_ORIGINS="http://localhost:3000" \
    python3 -m uvicorn sentinel_hft.server.app:app \
    --host "${HOST}" --port "${PORT}" --log-level warning >"${LOG_FILE}" 2>&1 &
  echo $! > "${PID_FILE}"
)

# wait for /api/drills
for _ in $(seq 1 40); do
  if curl -fsS "${BASE}/api/drills" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

echo "[smoke] GET /api/drills"
CATALOG="$(curl -fsS "${BASE}/api/drills")"
echo "${CATALOG}" | python3 -c '
import json, sys
d = json.load(sys.stdin)
need = {"toxic_flow", "kill_drill", "latency", "daily_evidence"}
got = set(d.keys())
assert need.issubset(got), f"missing drills: {need - got}"
print(f"  -> catalog ok · {sorted(got)}")
'

echo "[smoke] POST /api/drills/toxic_flow/run (ticks=1500)"
RUN="$(curl -fsS -X POST "${BASE}/api/drills/toxic_flow/run" \
  -H 'Content-Type: application/json' \
  --data '{"ticks": 1500, "output_dir": "'"${OUT}"'/toxic_flow"}')"
echo "${RUN}" | python3 -c '
import json, sys
r = json.load(sys.stdin)
rep = r["report"]
assert rep["ticks"] >= 1500, rep["ticks"]
assert rep["audit_chain_ok"] is True, rep
t = rep["ticks"]; i = rep["intents"]; tr = rep["toxic_rejects"]
print("  -> drill ok · ticks={0} intents={1} toxic_rejects={2}".format(t, i, tr))
'

AUD="${OUT}/toxic_flow/audit.aud"
if [[ ! -s "${AUD}" ]]; then
  echo "[smoke] FAIL: expected audit file at ${AUD}"
  exit 1
fi

echo "[smoke] POST /api/audit/verify ${AUD}"
VER="$(curl -fsS -X POST "${BASE}/api/audit/verify" -F "file=@${AUD}")"
echo "${VER}" | python3 -c '
import json, sys
v = json.load(sys.stdin)
assert v["ok"] is True, v
assert v["verified_records"] == v["total_records"], v
rec = v["verified_records"]; head = v["head_hash_lo_hex"]
print("  -> verifier ok · {0} records · head 0x{1}".format(rec, head))
'

echo "[smoke] OK"
