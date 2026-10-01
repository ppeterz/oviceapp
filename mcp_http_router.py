"""
Standalone MCP HTTP / JSON-RPC 2.0 Router for FastAPI.
Provides full compatibility with Claude.ai Custom Connectors on serverless platforms (Vercel).
Supports:
  - initialize (with MCP Apps extension capability)
  - notifications/initialized
  - ping
  - tools/list (with _meta.ui.resourceUri for MCP Apps)
  - tools/call
  - resources/list
  - resources/read (serves ui:// HTML widget)
  - GET healthcheck & SSE probe
  - CORS preflight OPTIONS
"""

import json
import html as html_module
from typing import Any, Dict, Optional
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from mcp_tools import VOICES, _generate_audio, _save_result
import os

router = APIRouter()

# ---------------------------------------------------------------------------
# MCP Apps: UI Resource Definition
# ---------------------------------------------------------------------------

UI_RESOURCE_URI = "ui://voiceover-studio/player"
UI_RESOURCE_MIME = "text/html;profile=mcp-app"

# The audio player widget HTML. Self-contained, no external dependencies.
# Uses postMessage JSON-RPC bridge per the MCP Apps spec to receive tool results.
PLAYER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<meta name="color-scheme" content="light dark"/>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{
  background:transparent;
  font-family:var(--font-family,'Anthropic Sans','Inter',system-ui,sans-serif);
  color:var(--text-color,#1a1a2e);
  line-height:1.5;
}
@media(prefers-color-scheme:dark){
  :root{--text-color:#e0e0e0;--card-bg:rgba(255,255,255,0.06);--border-color:rgba(255,255,255,0.12);--accent:#7c6aef;--accent-light:#a496f7;--meta-color:#999}
}
@media(prefers-color-scheme:light){
  :root{--text-color:#1a1a2e;--card-bg:rgba(0,0,0,0.03);--border-color:rgba(0,0,0,0.1);--accent:#5b4dc7;--accent-light:#7c6aef;--meta-color:#666}
}
.player-card{
  padding:16px 20px;
  border-radius:12px;
  background:var(--card-bg,rgba(0,0,0,0.03));
  border:1px solid var(--border-color,rgba(0,0,0,0.1));
  max-width:100%;
}
.player-header{
  display:flex;align-items:center;gap:10px;margin-bottom:12px;
}
.voice-badge{
  display:inline-flex;align-items:center;gap:5px;
  background:var(--accent,#5b4dc7);color:#fff;
  padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600;
  letter-spacing:0.3px;
}
.voice-badge svg{width:14px;height:14px;fill:currentColor}
.player-title{font-size:14px;font-weight:600;color:var(--text-color)}
audio{
  width:100%;height:40px;border-radius:8px;outline:none;
  margin:8px 0;
}
audio::-webkit-media-controls-panel{background:var(--card-bg,#f5f5f5);border-radius:8px}
.meta-row{
  display:flex;flex-wrap:wrap;gap:16px;
  font-size:12px;color:var(--meta-color,#666);
  margin-top:8px;
}
.meta-item{display:flex;align-items:center;gap:4px}
.meta-item svg{width:13px;height:13px;fill:currentColor;opacity:0.6}
.download-link{
  display:inline-flex;align-items:center;gap:4px;
  color:var(--accent,#5b4dc7);text-decoration:none;font-size:12px;font-weight:500;
  margin-top:8px;
  transition:opacity 0.15s;
}
.download-link:hover{opacity:0.8}
.download-link svg{width:13px;height:13px;fill:currentColor}
.loading{text-align:center;padding:24px;color:var(--meta-color,#666);font-size:13px}
.error{color:#e74c3c;font-size:13px;padding:12px}
</style>
</head>
<body>
<div id="app"><div class="loading">Waiting for voiceover result...</div></div>

<script>
(function(){
  // MCP Apps postMessage bridge (no SDK needed)
  let nextId = 1;
  let toolResult = null;

  function sendRequest(method, params) {
    const id = nextId++;
    window.parent.postMessage({ jsonrpc: "2.0", id, method, params }, '*');
    return new Promise((resolve, reject) => {
      function listener(event) {
        if (event.data && event.data.id === id) {
          window.removeEventListener('message', listener);
          if (event.data.result) resolve(event.data.result);
          else if (event.data.error) reject(new Error(JSON.stringify(event.data.error)));
        }
      }
      window.addEventListener('message', listener);
    });
  }

  function sendNotification(method, params) {
    window.parent.postMessage({ jsonrpc: "2.0", method, params }, '*');
  }

  // Listen for tool-result notification from the host
  window.addEventListener('message', function(event) {
    const data = event.data;
    if (!data || !data.method) return;

    if (data.method === 'ui/notifications/tool-result') {
      const result = data.params;
      if (result && result.content) {
        // Extract text content from MCP tool result
        for (const item of result.content) {
          if (item.type === 'text') {
            try {
              toolResult = JSON.parse(item.text);
              renderPlayer(toolResult);
            } catch(e) {
              renderError('Could not parse tool result');
            }
            return;
          }
        }
      }
    }

    // Handle initialize request from host
    if (data.method === 'ui/initialize' || data.method === 'initialize') {
      const response = {
        jsonrpc: "2.0",
        id: data.id,
        result: {
          protocolVersion: "2026-01-26",
          capabilities: {},
          serverInfo: { name: "voiceover-player", version: "1.0.0" }
        }
      };
      window.parent.postMessage(response, '*');
      // Send initialized notification
      sendNotification('ui/notifications/initialized', {});
    }
  });

  // Initialize the MCP Apps bridge
  async function init() {
    try {
      await sendRequest('initialize', {
        capabilities: {},
        clientInfo: { name: "voiceover-player", version: "1.0.0" },
        protocolVersion: "2026-01-26"
      });
      sendNotification('notifications/initialized', {});
    } catch(e) {
      // Host may handle initialization differently; that's okay
    }
  }

  function renderPlayer(data) {
    if (data.error) {
      renderError(data.message || 'Generation failed');
      return;
    }
    const app = document.getElementById('app');
    const baseUrl = data._baseUrl || '';
    const audioUrl = baseUrl + (data.audio_url || '');
    const downloadUrl = baseUrl + (data.download_url || '');
    const voice = data.voice_id || 'Unknown';
    const words = data.word_count || 0;
    const segments = data.segment_count || 1;
    const filename = data.filename || '';
    const fileSize = data.file_size_bytes;
    const settings = data.settings || {};

    let sizeStr = '';
    if (fileSize) {
      sizeStr = fileSize > 1048576
        ? (fileSize / 1048576).toFixed(1) + ' MB'
        : (fileSize / 1024).toFixed(0) + ' KB';
    }

    app.innerHTML = `
      <div class="player-card">
        <div class="player-header">
          <span class="voice-badge">
            <svg viewBox="0 0 24 24"><path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/><path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/></svg>
            ${escapeHtml(voice)}
          </span>
          <span class="player-title">Voiceover Generated</span>
        </div>
        <audio controls preload="auto" src="${escapeAttr(audioUrl)}"></audio>
        <div class="meta-row">
          <span class="meta-item">
            <svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zM6 20V4h7v5h5v11H6z"/></svg>
            ${words} words
          </span>
          <span class="meta-item">
            <svg viewBox="0 0 24 24"><path d="M3 4h18v2H3V4zm0 7h12v2H3v-2zm0 7h18v2H3v-2z"/></svg>
            ${segments} segment${segments !== 1 ? 's' : ''}
          </span>
          ${sizeStr ? `<span class="meta-item">
            <svg viewBox="0 0 24 24"><path d="M20 6H4V4h16v2zm-4 5H4V9h12v2zm4 5H4v-2h16v2z"/></svg>
            ${sizeStr}
          </span>` : ''}
          ${settings.speed !== undefined ? `<span class="meta-item">Speed: ${settings.speed}</span>` : ''}
          ${settings.pitch !== undefined ? `<span class="meta-item">Pitch: ${settings.pitch}</span>` : ''}
        </div>
        ${downloadUrl ? `<a class="download-link" href="${escapeAttr(downloadUrl)}" target="_blank" rel="noopener">
          <svg viewBox="0 0 24 24"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
          Download MP3
        </a>` : ''}
      </div>
    `;
  }

  function renderError(msg) {
    document.getElementById('app').innerHTML = '<div class="error">' + escapeHtml(msg) + '</div>';
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function escapeAttr(str) {
    return str.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // Start bridge
  init();
})();
</script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# UI Resource list entry (for resources/list)
# ---------------------------------------------------------------------------
UI_RESOURCES = [
    {
        "uri": UI_RESOURCE_URI,
        "name": "Voiceover Audio Player",
        "description": "Interactive audio player widget that renders inline after voiceover generation.",
        "mimeType": UI_RESOURCE_MIME,
    }
]

# ---------------------------------------------------------------------------
# Tool Definitions (with MCP Apps metadata on generate_voiceover)
# ---------------------------------------------------------------------------

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
        # MCP Apps: link this tool to the audio player UI resource
        "_meta": {
            "ui": {
                "resourceUri": UI_RESOURCE_URI,
            }
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

        # Include _baseUrl so the widget can construct absolute audio URLs
        base_url = os.environ.get("VERCEL_URL", "")
        if base_url and not base_url.startswith("http"):
            base_url = f"https://{base_url}"

        return json.dumps({
            "success": True,
            "filename": meta.get("filename"),
            "download_url": meta.get("download_url"),
            "audio_url": meta.get("audio_url"),
            "voice_id": voice_id,
            "word_count": total_words,
            "segment_count": segment_count,
            "file_size_bytes": meta.get("file_size_bytes"),
            "_baseUrl": base_url,
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
                    },
                    "resources": {
                        "subscribe": False,
                        "listChanged": False,
                    },
                },
                "serverInfo": {
                    "name": "voiceover-studio",
                    "version": "2.0.0"
                },
                # Advertise MCP Apps extension support
                "extensions": {
                    "io.modelcontextprotocol/ui": {}
                },
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

    if method == "resources/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "resources": UI_RESOURCES
            }
        }

    if method == "resources/read":
        uri = params.get("uri", "")
        if uri == UI_RESOURCE_URI:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "contents": [{
                        "uri": UI_RESOURCE_URI,
                        "mimeType": UI_RESOURCE_MIME,
                        "text": PLAYER_HTML,
                        "_meta": {
                            "ui": {
                                "prefersBorder": False,
                                "csp": {
                                    # Player is fully self-contained; no external requests needed
                                }
                            }
                        }
                    }]
                }
            }
        # Unknown resource
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32602,
                "message": f"Resource not found: {uri}"
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
        "tools": [t["name"] for t in TOOLS_SPEC],
        "resources": [r["uri"] for r in UI_RESOURCES],
        "extensions": ["io.modelcontextprotocol/ui"],
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
