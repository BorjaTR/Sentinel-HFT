"""HTTP server for Sentinel-HFT.

Install with: pip install sentinel-hft[server]
"""

try:
    from .app import app, main
    __all__ = ['app', 'main']
except ImportError:
    # FastAPI not installed
    app = None
    main = None
    __all__ = []
