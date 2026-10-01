#!/usr/bin/env python3
"""
Voiceover Studio MCP Server — Local (stdio transport)
======================================================
Run this directly for Claude Desktop or Antigravity IDE via stdio transport.

Setup:
  1. pip install mcp requests
  2. Set UNREALSPEECH_API_KEY in your environment
  3. Add to claude_desktop_config.json or .gemini/config/mcp_config.json
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path for the shared module
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_tools import mcp  # noqa: E402 — shared MCPServer with tools registered

if __name__ == "__main__":
    mcp.run()
