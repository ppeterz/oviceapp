"""
Vercel Serverless Function — catch-all handler for O-Voice Studio.

Vercel's @vercel/python builder discovers the `app` variable (a FastAPI/ASGI
instance) in this module and wraps it with its ASGI adapter.  All HTTP methods
(GET, POST, DELETE, …) are forwarded to FastAPI's router.

This file deliberately lives at  api/[...path].py  so Vercel treats every
/api/* sub-path (regardless of HTTP method) as belonging to this single
function — avoiding the "index.py only handles GET" limitation.
"""
import sys
import os
from pathlib import Path

# Add project root to sys.path so server.py can be imported
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Signal Vercel serverless environment
os.environ["VERCEL"] = "1"

# Import FastAPI application from server.py
from server import app
