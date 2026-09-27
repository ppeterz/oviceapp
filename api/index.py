"""
Vercel Serverless Function entrypoint for O-Voice Studio.
Exports the FastAPI `app` object for Vercel's Python runtime.

Vercel's @vercel/python builder discovers the `app` variable (a FastAPI/ASGI
instance) in this module and wraps it behind its own ASGI adapter. All HTTP
methods (GET, POST, DELETE, etc.) are forwarded to FastAPI's router.
"""
import sys
import os
from pathlib import Path

# Add project root to sys.path so server.py and its dependencies can be found
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Signal Vercel serverless environment
os.environ["VERCEL"] = "1"

# Import FastAPI application from server.py
from server import app

# Vercel's Python runtime auto-discovers the `app` ASGI object.
# No additional handler wrapper is needed.
