"""
Standalone MCP HTTP / JSON-RPC 2.0 Router for FastAPI.
Provides full compatibility with Claude.ai Custom Connectors on serverless platforms (Vercel).
Supports:
  - initialize
  - notifications/initialized
  - ping
  - tools/list
  - tools/call
  - GET healthcheck & SSE probe
  - CORS preflight OPTIONS
"""

import json
from typing import Any, Dict, Optional
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from mcp_tools import VOICES, _generate_audio, _save_result
import os

router = APIRouter()

TOOLS_SPEC = [
    {
        "name": "list_voices",
        "description": (
            "List all available Kokoro TTS voices with their gender, style, and "
            "recommended use cases. Call this to choose the best voice for a script "
            "before calling generate_voiceover."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "generate_voiceover",
        "description": (
            "Generate a voiceover MP3 from script text using neural AI voices (Kokoro TTS). "
            "Saves the MP3 and returns download and playback metadata.\n\n"
            "INSTRUCTIONS FOR CLAUDE:\n"
            "Analyze the script tone and choose the best voice:\n"
            "- Storytelling / narrative -> Eleanor (Female) or Oliver (Male)\n"
            "- Documentary / thriller -> Charlotte (Female) or Jasper (Male)\n"
            "- Commercial / energetic -> Ivy (Female) or Ethan (Male)\n"
            "- Meditation / calm -> Luna (Female)\n"
            "- Charismatic / travel -> Rafael (Male)\n"
            "Keep speed at 0.0 (normal) and pitch at 1.0 unless a subtle adjustment fits."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Script text to synthesize. Supports paragraph breaks and pause markers like [pause: 1.2s], [beat].",
                },
                "voice_id": {
                    "type": "string",
                    "description": "Kokoro TTS voice: Eleanor, Jasper, Ivy, Oliver, Luna, Ethan, Charlotte, Rafael.",
                    "default": "Eleanor",
                },
                "speed": {
                    "type": "number",
                    "description": "Speed pacing: -1.0 to 1.0 (0.0 is normal).",
                    "default": 0.0,
                },
                "pitch": {
                    "type": "number",
                    "description": "Pitch factor: 0.5 to 1.5 (1.0 is default).",
                    "default": 1.0,
                },
                "bitrate": {
                    "type": "string",
                    "description": "Audio bitrate: 128k, 192k, 256k, 320k.",
                    "default": "192k",
                },
                "paragraph_pause": {
                    "type": "number",
                    "description": "Silence in seconds between paragraphs (0.0 to 3.0).",
                    "default": 0.8,
                },
                "smart_pacing": {
                    "type": "boolean",
                    "description": "Enable paragraph-aware silence stitching.",
                    "default": True,
                },
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
]


def execute_tool(name: str, args: Dict[str, Any]) -> str:
    if name == "list_voices":
        return json.dumps(VOICES, indent=2)

    if name == "generate_voiceover":
        api_key = os.environ.get("UNREALSPEECH_API_KEY", "").strip()
        if not api_key:
            return json.dumps({
                "error": True,
                "message": "UNREALSPEECH_API_KEY environment variable is not configured on the server."
            })

        text = args.get("text", "")
        voice_id = args.get("voice_id", "Eleanor")
        speed = float(args.get("speed", 0.0))
        pitch = float(args.get("pitch", 1.0))
        bitrate = str(args.get("bitrate", "192k"))
        paragraph_pause = float(args.get("paragraph_pause", 0.8))
        smart_pacing = bool(args.get("smart_pacing", True))

        try:
            audio_bytes, segment_count, total_words = _generate_audio(
                text=text,
                voice_id=voice_id,
                speed=speed,
                pitch=pitch,
                bitrate=bitrate,
                paragraph_pause=paragraph_pause,
                smart_pacing=smart_pacing,
                api_key=api_key,
            )
        except Exception as e:
            return json.dumps({"error": True, "message": f"Synthesis error: {str(e)}"})

        meta = _save_result(
            audio_bytes=audio_bytes,
            voice_id=voice_id,
            speed=speed,
            pitch=pitch,
            bitrate=bitrate,
            paragraph_pause=paragraph_pause,
            smart_pacing=smart_pacing,
            original_text=text.strip(),
            segment_count=segment_count,
            total_words=total_words,
        )

        return json.dumps({
            "success": True,
            "filename": meta.get("filename"),
            "download_url": meta.get("download_url"),
            "audio_url": meta.get("audio_url"),
            "voice_id": voice_id,
            "word_count": total_words,
            "segment_count": segment_count,
            "file_size_bytes": meta.get("file_size_bytes"),
            "settings": {
                "speed": speed,
                "pitch": pitch,
                "bitrate": bitrate,
                "paragraph_pause": paragraph_pause,
                "smart_pacing": smart_pacing,
            },
            "message": f"Voiceover generated successfully! ({total_words} words, voice: {voice_id})"
        }, indent=2)

    raise ValueError(f"Unknown tool: {name}")


async def handle_mcp_request(body: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single JSON-RPC 2.0 MCP request."""
    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {
                        "listChanged": False
                    }
                },
                "serverInfo": {
                    "name": "voiceover-studio",
                    "version": "2.0.0"
                }
            }
        }

    if method in ("notifications/initialized", "initialized"):
        # Notifications don't require an id
        if req_id is not None:
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        return {"jsonrpc": "2.0", "result": {}}

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": TOOLS_SPEC
            }
        }

    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments") or {}
        try:
            output_text = execute_tool(tool_name, tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": output_text
                        }
                    ],
                    "isError": False
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Error: {str(e)}"
                        }
                    ],
                    "isError": True
                }
            }

    # Unsupported method
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32601,
            "message": f"Method '{method}' not found"
        }
    }


@router.get("/mcp")
@router.get("/api/mcp")
async def mcp_get_handler(request: Request):
    """
    Handle GET requests from Claude connector probes, health checks, or SSE requests.
    """
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        # Return initial SSE handshake
        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
        # Send endpoint event pointing to /mcp for POST requests
        body = "event: endpoint\ndata: /mcp\n\n"
        return Response(content=body, media_type="text/event-stream", headers=headers)

    # Standard JSON health check
    return JSONResponse({
        "status": "ok",
        "name": "voiceover-studio",
        "protocolVersion": "2024-11-05",
        "transport": "streamable-http",
        "tools": [t["name"] for t in TOOLS_SPEC]
    })


@router.post("/mcp")
@router.post("/api/mcp")
async def mcp_post_handler(request: Request):
    """
    Main MCP JSON-RPC 2.0 endpoint for Claude connector.
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}
        )

    # Handle batch or single request
    if isinstance(data, list):
        results = [await handle_mcp_request(item) for item in data]
        return JSONResponse(results)

    result = await handle_mcp_request(data)
    return JSONResponse(result)


@router.options("/mcp")
@router.options("/api/mcp")
async def mcp_options_handler():
    """CORS preflight handler."""
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, x-api-key",
        }
    )
