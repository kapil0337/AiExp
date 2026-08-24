"""Vercel serverless entrypoint.

Vercel maps this file to /api/index and vercel.json rewrites /api/* onto it.
FastAPI still sees the original path (e.g. /api/expenses), so the routes in
backend.main need no special casing.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.main import app  # noqa: E402

__all__ = ["app"]
