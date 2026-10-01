#!/usr/bin/env python3
"""
Voiceover Studio — Shared MCP Tool Definitions
================================================
Defines the MCPServer instance with generate_voiceover and list_voices tools.
Used by both:
  - mcp_voiceover_server.py  (local stdio transport for Claude Desktop / Antigravity IDE)
  - server.py                (remote Streamable HTTP transport for claude.ai browser)
"""

import io
import os
import re
import json
import time
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from mcp.server.mcpserver import MCPServer

# ============================================================================
# CONFIGURATION
# ============================================================================

DEFAULT_BASE_URL = "https://api.v8.unrealspeech.com"

# Resolve project root — works both when imported and when run directly
_THIS_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = _THIS_DIR / "outputs"

# In Vercel serverless, only /tmp is writable
if os.environ.get("VERCEL"):
    OUTPUTS_DIR = Path("/tmp/outputs")

try:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

# Pre-load silence frames for inter-segment stitching
SILENCE_FRAMES: bytes = b""
_silence_candidates = [
    _THIS_DIR / "static" / "assets" / "silence_frames.bin",
    _THIS_DIR / "public" / "assets" / "silence_frames.bin",
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

# ============================================================================
# VOICE CATALOG
# ============================================================================

VOICES = [
    {
        "id": "Eleanor",
        "gender": "Female",
        "style": "Warm, Narrative & Expressive",
        "best_for": ["Storytelling", "Documentary", "Curious tone", "Educational"],
        "description": "A warm, expressive female voice ideal for narrative content, documentaries, and anything that needs a curious, engaging tone.",
    },
    {
        "id": "Jasper",
        "gender": "Male",
        "style": "Deep, Resonant & Grounded",
        "best_for": ["Thriller", "Mystery", "Authoritative", "Cinematic trailers"],
        "description": "A deep, resonant male voice with gravitas. Perfect for thrillers, mystery narration, authoritative explainers, and cinematic content.",
    },
    {
        "id": "Ivy",
        "gender": "Female",
        "style": "Energetic, Bright & Engaging",
        "best_for": ["Commercials", "Podcast intros", "Upbeat explainers", "Product demos"],
        "description": "An energetic, bright female voice that grabs attention. Great for commercials, podcast intros, and upbeat content.",
    },
    {
        "id": "Oliver",
        "gender": "Male",
        "style": "Calm, Professional & Clear",
        "best_for": ["Audiobooks", "Storytelling", "Explainers", "Corporate narration"],
        "description": "A calm, professional male voice with excellent clarity. Ideal for audiobooks, long-form storytelling, and professional explainers.",
    },
    {
        "id": "Luna",
        "gender": "Female",
        "style": "Gentle, Intimate & Balanced",
        "best_for": ["Meditation", "ASMR", "Calm narration", "Slightly mysterious"],
        "description": "A gentle, intimate female voice with a balanced warmth. Perfect for meditation guides, calm narration, and atmospheric content.",
    },
    {
        "id": "Ethan",
        "gender": "Male",
        "style": "Energetic, Dynamic & Youthful",
        "best_for": ["Commercials", "Tech explainers", "Podcast", "Social media"],
        "description": "An energetic, youthful male voice with dynamic range. Great for tech content, social media ads, and fast-paced explainers.",
    },
    {
        "id": "Charlotte",
        "gender": "Female",
        "style": "Polished, Sophisticated & Refined",
        "best_for": ["Documentary", "Corporate", "Luxury branding", "Narrative journalism"],
        "description": "A polished, sophisticated female voice with refined elegance. Ideal for documentaries, corporate presentations, and premium branding.",
    },
    {
        "id": "Rafael",
        "gender": "Male",
        "style": "Warm, Charismatic & Smooth",
        "best_for": ["Storytelling", "Curious tone", "Mystery", "Travel narration"],
        "description": "A warm, charismatic male voice with smooth delivery. Perfect for storytelling, travel content, and conversational narration.",
    },
]


# ============================================================================
# SCRIPT PACING ENGINE
# ============================================================================

def clean_text_segment(text: str) -> str:
    """Normalizes prosody, em dashes, and sentence-terminating punctuation."""
    t = text.strip()
    if not t:
        return ""
    t = re.sub(r'\s*—\s*', ' — ', t)
    t = re.sub(r'\s*--\s*', ' — ', t)
    t = re.sub(r'\.{2,}', '...', t)
    if not re.search(r'[.!?…]$', t):
        t += '.'
    return t


def parse_script_into_segments(text: str, default_paragraph_pause: float = 0.8):
    """
    Parses a script into a list of (segment_text, pause_after_sec).
    Handles paragraph breaks, explicit pause markers, and punctuation normalization.
    """
    if not text or not text.strip():
        return []

    norm_text = text.replace('\r\n', '\n').strip()

    pause_tag_pattern = re.compile(
        r'(\[(?:pause|break)[:\s]*([\d.]*)s?\]|\((?:pause|break)[:\s]*([\d.]*)s?\)|\[beat\]|<break\s+time=["\']?([\d.]+)(m?s)["\']?\s*/?>)',
        re.IGNORECASE
    )

    raw_paragraphs = [p.strip() for p in re.split(r'\n\s*\n', norm_text) if p.strip()]
    segments = []

    for p_idx, para in enumerate(raw_paragraphs):
        is_last_paragraph = (p_idx == len(raw_paragraphs) - 1)

        matches = list(pause_tag_pattern.finditer(para))
        if not matches:
            clean_p = clean_text_segment(para)
            if clean_p:
                pause_after = 0.0 if is_last_paragraph else default_paragraph_pause
                segments.append((clean_p, pause_after))
        else:
            last_end = 0
            for match in matches:
                span_start, span_end = match.span()
                part_text = para[last_end:span_start].strip()

                full_tag = match.group(0).lower()
                dur_val = match.group(2) or match.group(3) or match.group(4)
                unit = match.group(5) or 's'

                if dur_val:
                    try:
                        pause_sec = float(dur_val)
                        if unit == 'ms':
                            pause_sec /= 1000.0
                    except ValueError:
                        pause_sec = 0.6
                elif 'beat' in full_tag:
                    pause_sec = 0.5
                else:
                    pause_sec = 0.8

                if part_text:
                    clean_part = clean_text_segment(part_text)
                    if clean_part:
                        segments.append((clean_part, pause_sec))
                elif segments:
                    prev_text, prev_pause = segments[-1]
                    segments[-1] = (prev_text, prev_pause + pause_sec)

                last_end = span_end

            remaining = para[last_end:].strip()
            if remaining:
                clean_rem = clean_text_segment(remaining)
                if clean_rem:
                    pause_after = 0.0 if is_last_paragraph else default_paragraph_pause
                    segments.append((clean_rem, pause_after))

    return segments


def generate_silence_bytes(duration_sec: float) -> bytes:
    """Generate silence MP3 bytes for the given duration."""
    if not SILENCE_FRAMES or duration_sec <= 0:
        return b""
    base_duration = 0.8
    repeats = max(1, round(duration_sec / base_duration))
    return SILENCE_FRAMES * repeats


def synthesize_segment(
    text: str,
    voice_id: str,
    bitrate: str,
    speed: float,
    pitch: float,
    api_key: str,
    timestamp_type: str = "sentence",
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

    resp = requests.post(f"{DEFAULT_BASE_URL}/speech", json=payload, headers=headers, timeout=120)
    if resp.status_code != 200:
        raise Exception(f"Unreal Speech API error ({resp.status_code}): {resp.text}")

    data = resp.json()
    audio_uri = data.get("OutputUri")
    if isinstance(audio_uri, list):
        audio_uri = audio_uri[0] if audio_uri else None
    if not audio_uri:
        raise Exception(f"No OutputUri in API response: {data}")

    audio_resp = requests.get(audio_uri, timeout=120)
    audio_resp.raise_for_status()
    return audio_resp.content


# ============================================================================
# CORE GENERATION LOGIC
# ============================================================================

def _generate_audio(
    text: str,
    voice_id: str,
    speed: float,
    pitch: float,
    bitrate: str,
    paragraph_pause: float,
    smart_pacing: bool,
    api_key: str,
) -> tuple:
    """
    Core generation logic. Returns (audio_bytes, segments_count, total_words) or raises.
    """
    clean_text = text.strip()
    if not clean_text:
        raise ValueError("Script text cannot be empty.")

    valid_voices = {v["id"] for v in VOICES}
    if voice_id not in valid_voices:
        raise ValueError(f"Unknown voice '{voice_id}'. Valid: {', '.join(sorted(valid_voices))}")

    speed = max(-1.0, min(1.0, speed))
    pitch = max(0.5, min(1.5, pitch))
    paragraph_pause = max(0.0, min(3.0, paragraph_pause))

    if smart_pacing:
        segments = parse_script_into_segments(clean_text, paragraph_pause)
    else:
        segments = [(clean_text_segment(clean_text), 0.0)]

    for i, (seg_text, _) in enumerate(segments):
        if len(seg_text) > 3000:
            raise ValueError(
                f"Segment {i+1} is {len(seg_text)} chars (max 3000). "
                "Break it into shorter paragraphs."
            )

    if not segments:
        raise ValueError("Script produced no valid segments after parsing.")

    total_words = sum(len(seg.split()) for seg, _ in segments)

    # Single segment fast path
    if len(segments) == 1:
        seg_text, _ = segments[0]
        audio_bytes = synthesize_segment(seg_text, voice_id, bitrate, speed, pitch, api_key)
        return audio_bytes, 1, total_words

    # Multi-segment: parallel synthesis + silence stitching
    segment_audio = {}
    errors = []

    with ThreadPoolExecutor(max_workers=min(4, len(segments))) as executor:
        future_to_idx = {}
        for idx, (seg_text, _) in enumerate(segments):
            future = executor.submit(
                synthesize_segment, seg_text, voice_id, bitrate, speed, pitch, api_key
            )
            future_to_idx[future] = idx

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                segment_audio[idx] = future.result()
            except Exception as e:
                errors.append(f"Segment {idx+1}: {str(e)}")

    if errors:
        raise RuntimeError(
            f"Failed to synthesize {len(errors)} segment(s): " + "; ".join(errors)
        )

    master = io.BytesIO()
    for idx in range(len(segments)):
        seg_text, pause_after = segments[idx]
        master.write(segment_audio[idx])
        if pause_after > 0 and idx < len(segments) - 1:
            silence = generate_silence_bytes(pause_after)
            if silence:
                master.write(silence)

    return master.getvalue(), len(segments), total_words


def _save_result(
    audio_bytes: bytes,
    voice_id: str,
    speed: float,
    pitch: float,
    bitrate: str,
    paragraph_pause: float,
    smart_pacing: bool,
    original_text: str,
    segment_count: int,
    total_words: int,
) -> dict:
    """Save MP3 + metadata JSON to outputs/. Returns result dict."""
    take_id = uuid.uuid4().hex[:10]
    timestamp = int(time.time())
    filename = f"take_{timestamp}_{voice_id.lower()}_{take_id}.mp3"
    file_path = OUTPUTS_DIR / filename

    try:
        with open(file_path, "wb") as f:
            f.write(audio_bytes)
    except Exception as e:
        print(f"Warning: could not write audio ({file_path}): {e}")

    meta = {
        "id": take_id,
        "filename": filename,
        "file_path": str(file_path),
        "audio_url": f"/outputs/{filename}",
        "download_url": f"/api/download/{filename}",
        "text": original_text,
        "word_count": total_words,
        "voice_id": voice_id,
        "bitrate": bitrate,
        "speed": speed,
        "pitch": pitch,
        "paragraph_pause": paragraph_pause,
        "smart_pacing": smart_pacing,
        "segment_count": segment_count,
        "timestamp_type": "sentence",
        "created_at": time.time(),
        "created_at_formatted": time.strftime("%b %d, %Y - %I:%M %p"),
        "file_size_bytes": len(audio_bytes),
        "generated_by": "mcp_voiceover_server",
    }

    meta_path = OUTPUTS_DIR / filename.replace(".mp3", ".json")
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except Exception as e:
        print(f"Warning: could not write metadata ({meta_path}): {e}")

    return meta


# ============================================================================
# MCP SERVER INSTANCE
# ============================================================================

mcp = MCPServer(
    "Voiceover Studio",
    description=(
        "Generate professional voiceovers from script text using neural AI voices "
        "(Kokoro TTS via Unreal Speech). Supports smart pacing with paragraph-aware "
        "silence stitching, 8 distinct voice personalities, and fine-tuned speed/pitch control."
    ),
)


@mcp.tool()
def list_voices() -> str:
    """
    List all available Kokoro TTS voices with their gender, style, and
    recommended use cases. Use this to choose the best voice for a script
    before calling generate_voiceover.

    VOICE SELECTION GUIDE FOR CLAUDE:
    - Storytelling / narrative -> Eleanor (F) or Oliver (M) or Rafael (M)
    - Documentary / cinematic -> Charlotte (F) or Jasper (M)
    - Commercial / upbeat -> Ivy (F) or Ethan (M)
    - Calm / meditation / ASMR -> Luna (F)
    - Mystery / thriller -> Jasper (M) or Luna (F)
    - Corporate / professional -> Charlotte (F) or Oliver (M)
    - Travel / conversational -> Rafael (M)
    """
    return json.dumps(VOICES, indent=2)


@mcp.tool()
def generate_voiceover(
    text: str,
    voice_id: str = "Eleanor",
    speed: float = 0.0,
    pitch: float = 1.0,
    bitrate: str = "192k",
    paragraph_pause: float = 0.8,
    smart_pacing: bool = True,
) -> str:
    """
    Generate a voiceover MP3 from script text using neural AI voices (Kokoro TTS).

    The generated MP3 is saved to the server's outputs/ folder and metadata is
    returned including the file path and download URL.

    INSTRUCTIONS FOR CLAUDE -- CHOOSING SETTINGS:
    Before calling this tool, call list_voices to see all voices.
    Then analyze the script content and pick the best voice:
    - Match voice gender to user preference if stated
    - Match voice style to script tone (warm narrative -> Eleanor, thriller -> Jasper, etc.)
    - For speed: keep at 0.0 (normal) unless the content calls for slower (-0.1 to -0.3
      for dramatic/calm) or faster (+0.1 to +0.2 for energetic)
    - For pitch: keep at 1.0 unless male voice benefits from slightly lower (0.92)
      or the content needs higher energy (1.05-1.1)
    - Use smart_pacing=True (default) for multi-paragraph scripts

    Args:
        text: The script text to synthesize. Supports paragraph breaks and
              pause markers like [pause: 1.2s], [beat], (pause).
              Max 3000 characters per paragraph segment.
        voice_id: Kokoro TTS voice. One of: Eleanor, Jasper, Ivy, Oliver,
                  Luna, Ethan, Charlotte, Rafael. Default: Eleanor.
        speed: Pacing from -1.0 (slow) to 1.0 (fast). 0.0 is normal.
        pitch: Pitch from 0.5 to 1.5. Default 1.0.
        bitrate: Audio quality. 192k (default), 128k, 256k, or 320k.
        paragraph_pause: Seconds of silence between paragraphs (0.0-3.0). Default 0.8.
        smart_pacing: If True (default), parses paragraph breaks and pause
                      markers for natural segment-by-segment synthesis.

    Returns:
        JSON with success status, file_path, filename, word_count, and settings used.
    """
    api_key = os.environ.get("UNREALSPEECH_API_KEY", "").strip()
    if not api_key:
        return json.dumps({
            "error": True,
            "message": "UNREALSPEECH_API_KEY environment variable is not set.",
        })

    try:
        audio_bytes, segment_count, total_words = _generate_audio(
            text, voice_id, speed, pitch, bitrate, paragraph_pause, smart_pacing, api_key
        )
    except (ValueError, RuntimeError) as e:
        return json.dumps({"error": True, "message": str(e)})
    except Exception as e:
        return json.dumps({"error": True, "message": f"Synthesis failed: {str(e)}"})

    meta = _save_result(
        audio_bytes, voice_id, speed, pitch, bitrate,
        paragraph_pause, smart_pacing, text.strip(),
        segment_count, total_words,
    )

    return json.dumps({
        "success": True,
        "file_path": meta["file_path"],
        "filename": meta["filename"],
        "download_url": meta["download_url"],
        "voice_id": voice_id,
        "word_count": total_words,
        "segment_count": segment_count,
        "file_size_bytes": meta["file_size_bytes"],
        "settings": {
            "speed": speed,
            "pitch": pitch,
            "bitrate": bitrate,
            "paragraph_pause": paragraph_pause,
            "smart_pacing": smart_pacing,
        },
        "created_at": meta["created_at_formatted"],
        "message": f"Voiceover generated! {total_words} words, "
                   f"{segment_count} segment(s), voice: {voice_id}. "
                   f"Saved to: {meta['file_path']}",
    })
