"""
app.py - FastAPI REST server for Sentinel-HFT

Provides HTTP API for trace analysis with streaming upload support.
"""

from fastapi import FastAPI, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from typing import Optional
import tempfile
import shutil
from pathlib import Path

from sentinel_hft import __version__
from sentinel_hft.api.server import AnalysisAPI


app = FastAPI(
    title="Sentinel-HFT",
    version=__version__,
    description="Hardware execution observability API",
    docs_url="/docs",
    redoc_url="/redoc",
)

api = AnalysisAPI()

# Global metrics storage for Prometheus
_last_metrics = {
    'latency_p50_cycles': 0,
    'latency_p99_cycles': 0,
    'latency_p999_cycles': 0,
    'drop_rate': 0.0,
    'transactions_total': 0,
    'drops_total': 0,
    'kill_switch_status': 0,
}


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": "Sentinel-HFT",
        "version": __version__,
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": __version__,
    }


@app.get("/version")
async def version():
    """Version information."""
    return {
        "version": __version__,
    }


@app.post("/analyze")
async def analyze(
    file: UploadFile,
    clock_mhz: float = Query(100.0, description="Clock frequency in MHz"),
    attribution: bool = Query(False, description="Include latency attribution"),
):
    """
    Analyze an uploaded trace file.

    Streams upload to temp file to avoid memory issues with large traces.
    """
    # Stream to temp file (preserves streaming guarantee)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        result = api.analyze_file(tmp_path)
        return JSONResponse(result.to_json())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        tmp_path.unlink()


@app.post("/analyze/bytes")
async def analyze_bytes(
    file: UploadFile,
    adapter: str = Query("v1.1", description="Adapter: v1.0, v1.1, v1.2"),
    clock_mhz: float = Query(100.0, description="Clock frequency in MHz"),
):
    """Analyze raw bytes with specified adapter."""
    content = await file.read()

    try:
        result = api.analyze_bytes(content, adapter=adapter)
        return JSONResponse(result.to_json())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint."""
    content = generate_prometheus_metrics()
    return Response(
        content=content,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


def generate_prometheus_metrics() -> str:
    """Generate Prometheus-format metrics."""
    lines = [
        "# HELP sentinel_latency_p50_cycles P50 latency in clock cycles",
        "# TYPE sentinel_latency_p50_cycles gauge",
        f"sentinel_latency_p50_cycles {_last_metrics['latency_p50_cycles']}",
        "",
        "# HELP sentinel_latency_p99_cycles P99 latency in clock cycles",
        "# TYPE sentinel_latency_p99_cycles gauge",
        f"sentinel_latency_p99_cycles {_last_metrics['latency_p99_cycles']}",
        "",
        "# HELP sentinel_latency_p999_cycles P99.9 latency in clock cycles",
        "# TYPE sentinel_latency_p999_cycles gauge",
        f"sentinel_latency_p999_cycles {_last_metrics['latency_p999_cycles']}",
        "",
        "# HELP sentinel_drop_rate Trace drop rate",
        "# TYPE sentinel_drop_rate gauge",
        f"sentinel_drop_rate {_last_metrics['drop_rate']}",
        "",
        "# HELP sentinel_transactions_total Total transactions processed",
        "# TYPE sentinel_transactions_total counter",
        f"sentinel_transactions_total {_last_metrics['transactions_total']}",
        "",
        "# HELP sentinel_drops_total Total traces dropped",
        "# TYPE sentinel_drops_total counter",
        f"sentinel_drops_total {_last_metrics['drops_total']}",
        "",
        "# HELP sentinel_kill_switch_status Kill switch status (0=clear, 1=armed, 2=triggered)",
        "# TYPE sentinel_kill_switch_status gauge",
        f"sentinel_kill_switch_status {_last_metrics['kill_switch_status']}",
        "",
    ]
    return "\n".join(lines)


def update_metrics(report) -> None:
    """Update global metrics from analysis report."""
    global _last_metrics

    if hasattr(report, 'latency'):
        _last_metrics['latency_p50_cycles'] = report.latency.p50_cycles
        _last_metrics['latency_p99_cycles'] = report.latency.p99_cycles
        _last_metrics['latency_p999_cycles'] = report.latency.p999_cycles

    if hasattr(report, 'drops'):
        _last_metrics['drops_total'] = report.drops.total_drops
        _last_metrics['drop_rate'] = report.drops.drop_rate

    if hasattr(report, 'risk'):
        _last_metrics['kill_switch_status'] = 2 if report.risk.kill_switch_triggered else 0


def main(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    """Run the server."""
    import uvicorn
    uvicorn.run(
        "sentinel_hft.server.app:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    main()
