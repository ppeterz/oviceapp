#!/usr/bin/env python3
"""
Voiceover Studio Backend Server
FastAPI backend that interfaces with Unreal Speech API, manages local generation cache,
and serves the modern Tailwind CSS studio frontend.

Features:
- Smart Script Pacing: Parses paragraph breaks, explicit pause tags, and punctuation
  to synthesize segments in parallel with calibrated silence stitching.
- Neural AI Voices via Unreal Speech v8 (Kokoro TTS)
- Local audio cache with metadata + history management
"""
import os
import re
import sys
import io
import json
import time
import uuid
import glob
import base64
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import FastAPI, HTTPException, Header, Query, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, Response
from pydantic import BaseModel, Field
import requests
from mcp_tools import (
    AUDIO_CACHE,
    Segment,
    parse_script_into_segments,
    clean_text_segment,
    resolve_pitch_value,
    resolve_speed_value,
)

DEFAULT_BASE_URL = "https://api.v8.unrealspeech.com"
IS_VERCEL = bool(os.environ.get("VERCEL"))

# In Vercel serverless functions, only /tmp is writable
if IS_VERCEL:
    OUTPUTS_DIR = Path("/tmp/outputs")
else:
    OUTPUTS_DIR = Path(__file__).resolve().parent / "outputs"

# Support both public/ (Vercel standard) and static/
STATIC_DIR = Path(__file__).resolve().parent / "public"
if not STATIC_DIR.exists():
    STATIC_DIR = Path(__file__).resolve().parent / "static"

ASSETS_DIR = STATIC_DIR / "assets"

# Safe directory creation (avoids crash on read-only serverless filesystems)
try:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

try:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

try:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

# Pre-load silence frame bytes for stitching with multi-path fallback
SILENCE_FRAMES: bytes = b""
_silence_candidates = [
    ASSETS_DIR / "silence_frames.bin",
    Path(__file__).resolve().parent / "public" / "assets" / "silence_frames.bin",
    Path(__file__).resolve().parent / "static" / "assets" / "silence_frames.bin",
    Path(__file__).resolve().parent.parent / "public" / "assets" / "silence_frames.bin",
    Path(__file__).resolve().parent.parent / "static" / "assets" / "silence_frames.bin",
    Path("/var/task/public/assets/silence_frames.bin"),
    Path("/var/task/static/assets/silence_frames.bin"),
]
for _sc in _silence_candidates:
    if _sc.exists():
        try:
            with open(_sc, "rb") as _sf:
                SILENCE_FRAMES = _sf.read()
            if SILENCE_FRAMES:
                break
        except Exception:
            pass

app = FastAPI(title="Voiceover Studio API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter()


# ============================================================================
# SCRIPT PACING ENGINE
# ============================================================================

# Script pacing and intonation engine is shared via mcp_tools (Segment, parse_script_into_segments, clean_text_segment)


def generate_silence_bytes(duration_sec: float) -> bytes:
    """Generate silence MP3 bytes for the given duration using silence_frames.bin repeats."""
    if not SILENCE_FRAMES or duration_sec <= 0:
        return b""

    # silence_frames.bin is ~0.8s of silence at 192k
    # Calculate number of repeats needed
    base_duration = 0.01  # approximate duration of one silence frame
    repeats = max(1, round(duration_sec / base_duration))
    return SILENCE_FRAMES * repeats


def synthesize_single_segment(
    text: str,
    voice_id: str,
    bitrate: str,
    speed: float,
    pitch: float,
    api_key: str,
    timestamp_type: str = "sentence"
) -> bytes:
    """Synthesize a single text segment via Unreal Speech API. Returns MP3 bytes."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "Text": text,
        "VoiceId": voice_id,
        "Bitrate": bitrate,
        "Speed": speed,
        "Pitch": pitch,
        "OutputFormat": "uri",
        "TimestampType": timestamp_type,
    }

    resp = requests.post(f"{DEFAULT_BASE_URL}/speech", json=payload, headers=headers, timeout=90)

    if resp.status_code != 200:
        raise Exception(f"Unreal Speech API Error ({resp.status_code}): {resp.text}")

    data = resp.json()
    audio_uri = data.get("OutputUri")
    if isinstance(audio_uri, list):
        audio_uri = audio_uri[0] if audio_uri else None

    if not audio_uri:
        raise Exception(f"No OutputUri returned by API: {data}")

    # Download the MP3 audio bytes
    audio_resp = requests.get(audio_uri, timeout=90)
    audio_resp.raise_for_status()
    return audio_resp.content


# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class GenerateRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Script to synthesize")
    voice_id: str = Field(default="Eleanor", description="Kokoro TTS Voice ID (v8)")
    bitrate: str = Field(default="192k", description="Bitrate: 128k, 192k, 256k, 320k")
    speed: float = Field(default=0.0, ge=-1.0, le=1.0, description="Speed pacing: -1.0 to 1.0")
    pitch: float = Field(default=1.0, ge=0.5, le=1.5, description="Pitch: 0.5 to 1.5")
    timestamp_type: str = Field(default="sentence", description="sentence or word")
    api_key: Optional[str] = Field(default=None, description="Unreal Speech API key supplied from UI")
    paragraph_pause: float = Field(default=0.8, ge=0.0, le=3.0, description="Silence between paragraphs in seconds")
    smart_pacing: bool = Field(default=True, description="Enable structural pacing with silence stitching")
    smart_intonation: bool = Field(default=True, description="Enable human-like intonation on questions, exclamations, and parentheticals")


class TestKeyRequest(BaseModel):
    api_key: str = Field(..., description="Unreal Speech API key to test")


# ============================================================================
# API ROUTES
# ============================================================================

@api_router.get("/config")
def get_config():
    """Return environment status and available engine configurations."""
    env_key = os.environ.get("UNREALSPEECH_API_KEY", "").strip()
    return {
        "has_env_key": bool(env_key),
        "default_voice": "Eleanor",
        "supported_voices": [
            {
                "id": "Eleanor",
                "name": "Eleanor",
                "gender": "Female",
                "style": "Warm, Narrative & Expressive",
                "recommended_for": ["Storytelling", "Documentary", "Curious"]
            },
            {
                "id": "Jasper",
                "name": "Jasper",
                "gender": "Male",
                "style": "Deep, Resonant & Grounded",
                "recommended_for": ["Slightly Mysterious", "Thriller", "Authoritative"]
            },
            {
                "id": "Ivy",
                "name": "Ivy",
                "gender": "Female",
                "style": "Energetic, Bright & Engaging",
                "recommended_for": ["Curious", "Commercial", "Podcast"]
            },
            {
                "id": "Oliver",
                "name": "Oliver",
                "gender": "Male",
                "style": "Calm, Professional & Clear",
                "recommended_for": ["Storytelling", "Audiobook", "Explainer"]
            },
            {
                "id": "Luna",
                "name": "Luna",
                "gender": "Female",
                "style": "Gentle, Intimate & Balanced",
                "recommended_for": ["Calm", "Meditation", "Slightly Mysterious"]
            },
            {
                "id": "Ethan",
                "name": "Ethan",
                "gender": "Male",
                "style": "Energetic, Dynamic & Youthful",
                "recommended_for": ["Commercial", "Explainer", "Podcast"]
            },
            {
                "id": "Charlotte",
                "name": "Charlotte",
                "gender": "Female",
                "style": "Polished, Sophisticated & Refined",
                "recommended_for": ["Documentary", "Narrative", "Corporate"]
            },
            {
                "id": "Rafael",
                "name": "Rafael",
                "gender": "Male",
                "style": "Warm, Charismatic & Smooth",
                "recommended_for": ["Storytelling", "Curious", "Slightly Mysterious"]
            }
        ]
    }


@api_router.post("/unrealspeech/test-key")
def test_unreal_key(req: TestKeyRequest):
    """Test validity of an Unreal Speech API key by performing a 1-word trial call."""
    key = req.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key is empty.")

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "Text": "Test.",
        "VoiceId": "Eleanor",
        "Bitrate": "192k",
        "Speed": 0.0,
        "Pitch": 1.0,
        "OutputFormat": "uri",
        "TimestampType": "sentence"
    }

    try:
        resp = requests.post(f"{DEFAULT_BASE_URL}/speech", json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            return {"valid": True, "message": "API key successfully verified with Unreal Speech!"}
        else:
            return {
                "valid": False,
                "message": f"Unreal Speech API returned status {resp.status_code}: {resp.text}"
            }
    except Exception as e:
        return {"valid": False, "message": f"Connection error: {str(e)}"}


@api_router.post("/unrealspeech/generate")
def generate_unrealspeech(req: GenerateRequest, x_api_key: Optional[str] = Header(None)):
    """Generate audio via Unreal Speech API with smart pacing and silence stitching."""
    # Resolve API key
    key = (req.api_key or x_api_key or os.environ.get("UNREALSPEECH_API_KEY") or "").strip()
    if not key:
        raise HTTPException(
            status_code=400,
            detail="No Unreal Speech API Key provided. Please open Settings in the top right to save your API Key."
        )

    clean_text = req.text.strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Script text cannot be empty.")

    # ── Smart Pacing & Intonation: Parse & Segment ──
    if req.smart_pacing:
        segments = parse_script_into_segments(
            clean_text,
            default_paragraph_pause=req.paragraph_pause,
            base_speed=req.speed,
            base_pitch=req.pitch,
            smart_intonation=req.smart_intonation
        )
    else:
        segments = [Segment(clean_text_segment(clean_text, is_sentence_end=True), 0.0, req.speed, req.pitch, is_sentence_end=True)]

    # Validate total text length (each segment must be <= 3000 chars)
    for i, seg in enumerate(segments):
        if len(seg.text) > 3000:
            raise HTTPException(
                status_code=400,
                detail=f"Segment {i+1} is {len(seg.text)} characters (max 3000 per segment). Break it into shorter paragraphs."
            )

    if not segments:
        raise HTTPException(status_code=400, detail="Script text produced no valid segments after parsing.")

    # ── Single segment: fast path (no stitching needed) ──
    if len(segments) == 1:
        seg = segments[0]
        try:
            audio_bytes = synthesize_single_segment(
                text=seg.text,
                voice_id=req.voice_id,
                bitrate=req.bitrate,
                speed=seg.speed,
                pitch=seg.pitch,
                api_key=key,
                timestamp_type=req.timestamp_type,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))

        return _save_and_respond(audio_bytes, req, clean_text, segment_count=1)

    # ── Multi-segment: Parallel synthesis + silence stitching ──
    print(f"[PACING] Script parsed into {len(segments)} segments, synthesizing in parallel...")

    segment_audio: Dict[int, bytes] = {}
    errors = []

    with ThreadPoolExecutor(max_workers=min(4, len(segments))) as executor:
        future_to_idx = {}
        for idx, seg in enumerate(segments):
            future = executor.submit(
                synthesize_single_segment,
                text=seg.text,
                voice_id=req.voice_id,
                bitrate=req.bitrate,
                speed=seg.speed,
                pitch=seg.pitch,
                api_key=key,
                timestamp_type=req.timestamp_type,
            )
            future_to_idx[future] = idx

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                segment_audio[idx] = future.result()
                print(f"  [PACING] Segment {idx+1}/{len(segments)} synthesized ({len(segment_audio[idx])} bytes, speed={segments[idx].speed}, pitch={segments[idx].pitch})")
            except Exception as e:
                errors.append(f"Segment {idx+1}: {str(e)}")

    if errors:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to synthesize {len(errors)} segment(s): " + "; ".join(errors)
        )

    # ── Stitch segments with silence ──
    print(f"[PACING] Stitching {len(segments)} segments with calibrated silence...")
    master_audio = io.BytesIO()

    for idx in range(len(segments)):
        seg = segments[idx]
        audio_data = segment_audio[idx]

        master_audio.write(audio_data)

        if seg.pause_after > 0 and idx < len(segments) - 1:
            silence = generate_silence_bytes(seg.pause_after)
            if silence:
                master_audio.write(silence)
                print(f"  [PACING] Inserted {seg.pause_after:.2f}s silence after segment {idx+1}")

    final_audio = master_audio.getvalue()
    print(f"[PACING] Master audio: {len(final_audio)} bytes ({len(segments)} segments stitched)")

    return _save_and_respond(final_audio, req, clean_text, segment_count=len(segments))


def _save_and_respond(audio_bytes: bytes, req: GenerateRequest, original_text: str, segment_count: int = 1):
    """Save audio to disk, encode to base64 for instant client playback, and return metadata."""
    take_id = uuid.uuid4().hex[:10]
    filename = f"take_{int(time.time())}_{req.voice_id.lower()}_{take_id}.mp3"
    file_path = OUTPUTS_DIR / filename

    try:
        with open(file_path, "wb") as f:
            f.write(audio_bytes)
    except Exception as e:
        print(f"Warning: could not write audio to disk ({file_path}): {e}")

    # Encode audio as base64 data URI so Vercel serverless clients receive instant audio
    b64_audio = base64.b64encode(audio_bytes).decode("ascii")
    audio_data_uri = f"data:audio/mp3;base64,{b64_audio}"

    meta = {
        "id": take_id,
        "filename": filename,
        "audio_url": f"/outputs/{filename}",
        "audio_data": audio_data_uri,
        "download_url": f"/api/download/{filename}",
        "text": original_text,
        "word_count": len(original_text.split()),
        "voice_id": req.voice_id,
        "bitrate": req.bitrate,
        "speed": req.speed,
        "pitch": req.pitch,
        "paragraph_pause": req.paragraph_pause,
        "smart_pacing": req.smart_pacing,
        "smart_intonation": req.smart_intonation,
        "segment_count": segment_count,
        "timestamp_type": req.timestamp_type,
        "created_at": time.time(),
        "created_at_formatted": time.strftime("%b %d, %Y - %I:%M %p"),
        "file_size_bytes": len(audio_bytes)
    }

    # Save metadata companion
    meta_filename = filename.replace(".mp3", ".json")
    meta_path = OUTPUTS_DIR / meta_filename
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except Exception as e:
        print(f"Warning: could not write meta json ({meta_path}): {e}")

    return meta


@api_router.get("/history")
def get_history():
    """List all previous voiceover generations."""
    history = []
    seen_ids = set()
    search_dirs = [OUTPUTS_DIR]
    if Path("/tmp/outputs") != OUTPUTS_DIR and Path("/tmp/outputs").exists():
        search_dirs.append(Path("/tmp/outputs"))

    for d in search_dirs:
        for mf in glob.glob(str(d / "*.json")):
            try:
                with open(mf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    tid = data.get("id")
                    if tid and tid not in seen_ids:
                        seen_ids.add(tid)
                        mp3_path = d / data.get("filename", "")
                        if mp3_path.exists():
                            if "download_url" not in data:
                                data["download_url"] = f"/api/download/{data.get('filename')}"
                            history.append(data)
            except Exception:
                continue

    history.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return {"takes": history}


@api_router.delete("/history/{take_id}")
def delete_take(take_id: str):
    """Delete a past generation from disk."""
    search_dirs = [OUTPUTS_DIR]
    if Path("/tmp/outputs") != OUTPUTS_DIR and Path("/tmp/outputs").exists():
        search_dirs.append(Path("/tmp/outputs"))

    for d in search_dirs:
        for mf in glob.glob(str(d / "*.json")):
            try:
                with open(mf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("id") == take_id:
                    mp3_path = d / data.get("filename", "")
                    if mp3_path.exists():
                        try:
                            mp3_path.unlink()
                        except Exception:
                            pass
                    try:
                        Path(mf).unlink()
                    except Exception:
                        pass
                    return {"success": True, "deleted_id": take_id}
            except Exception:
                continue
    raise HTTPException(status_code=404, detail="Take not found.")


@api_router.get("/download/{filename}")
def download_audio_file(filename: str):
    """
    Download an MP3 take with Content-Disposition: attachment header.
    Guarantees browser triggers a native file download with .mp3 extension.
    """
    safe_filename = Path(filename).name
    out_filename = safe_filename if safe_filename.lower().endswith(".mp3") else f"{safe_filename}.mp3"

    # Fast-path: check in-memory cache
    for fname in [safe_filename, out_filename]:
        if fname in AUDIO_CACHE:
            return Response(
                content=AUDIO_CACHE[fname],
                media_type="audio/mpeg",
                headers={
                    "Content-Disposition": f'attachment; filename="{out_filename}"',
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "public, max-age=86400",
                }
            )

    search_dirs = [OUTPUTS_DIR]
    if Path("/tmp/outputs") != OUTPUTS_DIR and Path("/tmp/outputs").exists():
        search_dirs.append(Path("/tmp/outputs"))

    for d in search_dirs:
        for fname in [safe_filename, out_filename]:
            file_path = (d / fname).resolve()
            if file_path.exists() and file_path.is_file():
                return FileResponse(
                    path=str(file_path),
                    media_type="audio/mpeg",
                    filename=out_filename,
                    content_disposition_type="attachment",
                    headers={
                        "Content-Disposition": f'attachment; filename="{out_filename}"',
                        "Accept-Ranges": "bytes"
                    }
                )

    raise HTTPException(status_code=404, detail="Audio file not found on server.")


@api_router.get("/outputs/{filename}")
def stream_audio_file(filename: str):
    """Direct stream for /outputs/{filename} in serverless environments."""
    safe_filename = Path(filename).name
    out_filename = safe_filename if safe_filename.lower().endswith(".mp3") else f"{safe_filename}.mp3"

    # Fast-path: check in-memory cache
    for fname in [safe_filename, out_filename]:
        if fname in AUDIO_CACHE:
            return Response(
                content=AUDIO_CACHE[fname],
                media_type="audio/mpeg",
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Disposition": f'inline; filename="{safe_filename}"',
                    "Cache-Control": "public, max-age=86400",
                }
            )

    search_dirs = [OUTPUTS_DIR]
    if Path("/tmp/outputs") != OUTPUTS_DIR and Path("/tmp/outputs").exists():
        search_dirs.append(Path("/tmp/outputs"))

    for d in search_dirs:
        file_path = (d / safe_filename).resolve()
        if file_path.exists() and file_path.is_file():
            return FileResponse(
                path=str(file_path),
                media_type="audio/mpeg",
                headers={"Accept-Ranges": "bytes"}
            )
    raise HTTPException(status_code=404, detail="Audio file not found.")


# Mount API router both with and without /api prefix
app.include_router(api_router, prefix="/api")
app.include_router(api_router)

# Mount outputs directory for audio file streaming with Range headers
if OUTPUTS_DIR.exists():
    try:
        app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")
    except Exception:
        pass

# Mount MCP JSON-RPC endpoint for claude.ai browser integration
# Claude.ai connects to https://your-domain.vercel.app/mcp as a remote MCP connector
try:
    from mcp_http_router import router as mcp_router
    app.include_router(mcp_router)
    print("[MCP] Remote MCP endpoint mounted at /mcp and /api/mcp")
except Exception as e:
    print(f"[MCP] Could not mount MCP endpoint: {e}")

# Mount static frontend directory
if STATIC_DIR.exists():
    try:
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static_dir")
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting Voiceover Studio on http://127.0.0.1:{port}")
    uvicorn.run("server:app", host="127.0.0.1", port=port, reload=True)
