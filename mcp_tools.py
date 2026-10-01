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
from typing import Dict, Any, List, Optional, Tuple, NamedTuple
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
# SCRIPT PACING & PROSODY ENGINE (PER-SENTENCE & PER-WORD PITCH CONTROL)
# ============================================================================

class Segment(NamedTuple):
    text: str
    pause_after: float
    speed: float
    pitch: float
    is_sentence_end: bool = True


SEMANTIC_PITCH_MAP = {
    "high": 1.12,
    "up": 1.12,
    "elevate": 1.12,
    "higher": 1.20,
    "excited": 1.20,
    "peak": 1.22,
    "low": 0.88,
    "down": 0.88,
    "deep": 0.84,
    "lower": 0.82,
    "somber": 0.82,
    "whisper": 0.78,
    "hush": 0.78,
    "aside": 0.85,
    "rise": 1.10,
    "question": 1.10,
    "drop": 0.90,
    "fall": 0.90,
    "normal": 1.0,
    "neutral": 1.0,
    "reset": 1.0,
}

SEMANTIC_SPEED_MAP = {
    "fast": 0.25,
    "faster": 0.40,
    "slow": -0.20,
    "slower": -0.35,
    "normal": 0.0,
    "rush": 0.35,
    "deliberate": -0.15,
}


def resolve_pitch_value(raw: str, base_pitch: float = 1.0) -> float:
    """Resolves raw pitch strings (e.g. '+10%', 'high', '1.15', '-0.08') into a float between 0.5 and 1.5."""
    raw_str = raw.strip().lower()
    if raw_str in SEMANTIC_PITCH_MAP:
        return round(max(0.5, min(1.5, base_pitch * SEMANTIC_PITCH_MAP[raw_str])), 3)
    if raw_str.endswith('%'):
        try:
            pct_val = float(raw_str[:-1])
            return round(max(0.5, min(1.5, base_pitch * (1.0 + pct_val / 100.0))), 3)
        except ValueError:
            pass
    if raw_str.startswith('+') or raw_str.startswith('-'):
        try:
            delta = float(raw_str)
            return round(max(0.5, min(1.5, base_pitch + delta)), 3)
        except ValueError:
            pass
    try:
        val = float(raw_str)
        return round(max(0.5, min(1.5, val)), 3)
    except ValueError:
        return round(base_pitch, 3)


def resolve_speed_value(raw: str, base_speed: float = 0.0) -> float:
    """Resolves raw speed strings (e.g. '+15%', 'fast', '0.2') into a float between -1.0 and 1.0."""
    raw_str = raw.strip().lower()
    if raw_str in SEMANTIC_SPEED_MAP:
        return round(max(-1.0, min(1.0, base_speed + SEMANTIC_SPEED_MAP[raw_str])), 3)
    if raw_str.endswith('%'):
        try:
            pct_val = float(raw_str[:-1])
            return round(max(-1.0, min(1.0, base_speed + (pct_val / 100.0))), 3)
        except ValueError:
            pass
    try:
        val = float(raw_str)
        return round(max(-1.0, min(1.0, val)), 3)
    except ValueError:
        return round(base_speed, 3)


def clean_text_segment(text: str, is_sentence_end: bool = True) -> str:
    """Normalizes prosody, em dashes, and punctuation. Only forces trailing period if is_sentence_end=True."""
    t = text.strip()
    if not t:
        return ""
    t = re.sub(r'\s*—\s*', ' — ', t)
    t = re.sub(r'\s*--\s*', ' — ', t)
    t = re.sub(r'\.{2,}', '...', t)
    if is_sentence_end:
        if not re.search(r'[.!?…][)"]?$', t):
            t += '.'
    return t


# Master pattern for prosody tags & pause tags using named groups throughout
PROSODY_TAG_REGEX = re.compile(
    r'(?P<pause>\[(?:pause|break)[:\s]*(?P<pause_num>[\d.]*)s?\]|\((?:pause|break)[:\s]*(?P<pause_num_paren>[\d.]*)s?\)|\[beat\]|<break\s+time=["\']?(?P<pause_num_xml>[\d.]+)(?P<pause_unit>m?s)["\']?\s*/?>)'
    r'|'
    r'(?P<pitch_tag>\[pitch(?::|\s*=)\s*(?P<pitch_arg>[^\]]+)\](?P<pitch_content>.*?)\[/pitch\])'
    r'|'
    r'(?P<speed_tag>\[speed(?::|\s*=)\s*(?P<speed_arg>[^\]]+)\](?P<speed_content>.*?)\[/speed\])'
    r'|'
    r'(?P<named_pitch_tag>\[(?P<named_tag>high|higher|excited|low|lower|deep|whisper|rise|drop)\](?P<named_content>.*?)\[/(?P=named_tag)\])'
    r'|'
    r'(?P<ssml_prosody><prosody(?:\s+pitch=["\']?(?P<ssml_pitch_val>[^"\'>]+)["\']?)?(?:\s+rate=["\']?(?P<ssml_rate_val>[^"\'>]+)["\']?)?\s*>(?P<prosody_content>.*?)</prosody>)'
    r'|'
    r'(?P<ssml_pitch><pitch(?:\s+val(?:ue)?=["\']?(?P<xml_pitch_val>[^"\'>]+)["\']?)?\s*>(?P<xml_pitch_content>.*?)</pitch>)',
    re.IGNORECASE | re.DOTALL
)


def parse_paragraph_intonation(
    para: str,
    default_pause: float,
    base_speed: float = 0.0,
    base_pitch: float = 1.0,
    smart_intonation: bool = True,
    is_last_paragraph: bool = False
) -> List[Segment]:
    """
    Parses a single paragraph into segments with per-word or per-sentence pitch & speed.
    """
    segments: List[Segment] = []
    matches = list(PROSODY_TAG_REGEX.finditer(para))

    if not matches:
        # No explicit tags in paragraph.
        # Check if smart_intonation should split on sentence punctuation (? / ! / ...)
        if smart_intonation and re.search(r'[?!]', para):
            sentence_parts = re.split(r'([.!?…]+(?:\s+|$))', para)
            i = 0
            while i < len(sentence_parts):
                sent_text = sentence_parts[i]
                punct = sentence_parts[i+1] if i + 1 < len(sentence_parts) else ""
                i += 2

                combined = (sent_text + punct).strip()
                if not combined:
                    continue

                seg_pitch = base_pitch
                if combined.endswith('?'):
                    seg_pitch = round(min(1.5, base_pitch * 1.07), 3)  # Inquiry / question rise
                elif combined.endswith('!'):
                    seg_pitch = round(min(1.5, base_pitch * 1.08), 3)  # Exclamation / excitement
                elif combined.startswith('(') and combined.endswith(')'):
                    seg_pitch = round(max(0.5, base_pitch * 0.92), 3)  # Parenthetical / aside

                is_para_end = (i >= len(sentence_parts))
                pause_after = (0.0 if is_last_paragraph else default_pause) if is_para_end else 0.30

                clean_s = clean_text_segment(combined, is_sentence_end=True)
                if clean_s:
                    segments.append(Segment(clean_s, pause_after, base_speed, seg_pitch, is_sentence_end=True))
            return segments

        # Plain paragraph without tags or ?/!
        clean_p = clean_text_segment(para, is_sentence_end=True)
        if clean_p:
            pause_after = 0.0 if is_last_paragraph else default_pause
            segments.append(Segment(clean_p, pause_after, base_speed, base_pitch, is_sentence_end=True))
        return segments

    # Paragraph has tags -> tokenize sequentially
    raw_tokens: List[Tuple[str, str, float, float, float]] = []

    def add_plain_block(raw_text: str):
        if not raw_text.strip():
            return
        parts = re.split(r'([.!?…]+(?:\s+|$))', raw_text)
        i = 0
        while i < len(parts):
            txt = parts[i]
            punct = parts[i+1] if i + 1 < len(parts) else ""
            i += 2
            combined = (txt + punct).strip()
            if not combined:
                continue

            p = base_pitch
            if smart_intonation:
                if combined.endswith('?'):
                    p = round(min(1.5, base_pitch * 1.07), 3)
                elif combined.endswith('!'):
                    p = round(min(1.5, base_pitch * 1.08), 3)
                elif combined.startswith('(') and combined.endswith(')'):
                    p = round(max(0.5, base_pitch * 0.92), 3)

            raw_tokens.append(("plain", combined, base_speed, p, 0.0))

    last_end = 0
    for match in matches:
        start, end = match.span()
        if start > last_end:
            interim = para[last_end:start]
            add_plain_block(interim)

        m_dict = match.groupdict()

        # Check if immediate next character is trailing punctuation (e.g. [/pitch]. or [/pitch],)
        trailing_punct_match = re.match(r'^([.!?…]+|[,;:])(?:\s+|$)', para[end:])
        trailing_punct = ""
        if trailing_punct_match and not m_dict.get("pause"):
            trailing_punct = trailing_punct_match.group(1)
            end += trailing_punct_match.end()

        if m_dict.get("pause"):
            full_tag = match.group(0).lower()
            dur_val = m_dict.get("pause_num") or m_dict.get("pause_num_paren") or m_dict.get("pause_num_xml")
            unit = m_dict.get("pause_unit") or 's'
            if dur_val:
                try:
                    p_sec = float(dur_val)
                    if unit == 'ms':
                        p_sec /= 1000.0
                except ValueError:
                    p_sec = 0.6
            elif 'beat' in full_tag:
                p_sec = 0.5
            else:
                p_sec = 0.8
            raw_tokens.append(("pause", "", base_speed, base_pitch, p_sec))

        elif m_dict.get("pitch_tag"):
            pitch_arg = m_dict.get("pitch_arg") or "1.0"
            content = (m_dict.get("pitch_content") or "") + trailing_punct
            target_pitch = resolve_pitch_value(pitch_arg, base_pitch)
            raw_tokens.append(("tagged", content, base_speed, target_pitch, 0.0))

        elif m_dict.get("speed_tag"):
            speed_arg = m_dict.get("speed_arg") or "0.0"
            content = (m_dict.get("speed_content") or "") + trailing_punct
            target_speed = resolve_speed_value(speed_arg, base_speed)
            raw_tokens.append(("tagged", content, target_speed, base_pitch, 0.0))

        elif m_dict.get("named_pitch_tag"):
            tag_name = m_dict.get("named_tag") or "normal"
            content = (m_dict.get("named_content") or "") + trailing_punct
            target_pitch = resolve_pitch_value(tag_name, base_pitch)
            raw_tokens.append(("tagged", content, base_speed, target_pitch, 0.0))

        elif m_dict.get("ssml_prosody"):
            p_arg = m_dict.get("ssml_pitch_val")
            r_arg = m_dict.get("ssml_rate_val")
            content = (m_dict.get("prosody_content") or "") + trailing_punct
            seg_p = resolve_pitch_value(p_arg, base_pitch) if p_arg else base_pitch
            seg_s = resolve_speed_value(r_arg, base_speed) if r_arg else base_speed
            raw_tokens.append(("tagged", content, seg_s, seg_p, 0.0))

        elif m_dict.get("ssml_pitch"):
            val_arg = m_dict.get("xml_pitch_val")
            content = (m_dict.get("xml_pitch_content") or "") + trailing_punct
            target_pitch = resolve_pitch_value(val_arg, base_pitch) if val_arg else base_pitch
            raw_tokens.append(("tagged", content, base_speed, target_pitch, 0.0))

        last_end = end

    if last_end < len(para):
        rem = para[last_end:]
        add_plain_block(rem)

    active_tokens: List[Tuple[str, float, float, float]] = []

    for t_type, t_text, t_speed, t_pitch, t_pause in raw_tokens:
        if t_type == "pause":
            if active_tokens:
                txt, spd, pit, p_pause = active_tokens[-1]
                active_tokens[-1] = (txt, spd, pit, p_pause + t_pause)
        else:
            txt = t_text.strip()
            if txt:
                active_tokens.append((txt, t_speed, t_pitch, 0.0))

    for idx, (txt, spd, pit, explicit_pause) in enumerate(active_tokens):
        is_last_token = (idx == len(active_tokens) - 1)
        ends_sentence = bool(re.search(r'[.!?…]$', txt))

        if explicit_pause > 0:
            pause_after = explicit_pause
        elif is_last_token:
            pause_after = 0.0 if is_last_paragraph else default_pause
        elif ends_sentence:
            pause_after = 0.30
        else:
            # Mid-sentence word or clause: zero pause so speech flows seamlessly
            pause_after = 0.0

        clean_text = clean_text_segment(txt, is_sentence_end=ends_sentence)
        if clean_text:
            segments.append(Segment(clean_text, pause_after, spd, pit, is_sentence_end=ends_sentence))

    return segments


def parse_script_into_segments(
    text: str,
    default_paragraph_pause: float = 0.8,
    base_speed: float = 0.0,
    base_pitch: float = 1.0,
    smart_intonation: bool = True
) -> List[Segment]:
    """
    Parses a script into a list of Segment(text, pause_after, speed, pitch, is_sentence_end).
    Supports:
    - Per-word and per-sentence pitch tags ([pitch: 1.15], [pitch: +10%], [pitch: high], [whisper], [rise])
    - Per-word speed tags ([speed: fast], [speed: 0.2])
    - Smart human intonation on punctuation (? -> rising pitch, ! -> exclamation energy)
    - Zero pause on mid-sentence words for smooth, natural delivery
    - Paragraph pause stitching and explicit pause tags ([pause: 1s], [beat])
    """
    if not text or not text.strip():
        return []

    norm_text = text.replace('\r\n', '\n').strip()
    raw_paragraphs = [p.strip() for p in re.split(r'\n\s*\n', norm_text) if p.strip()]

    all_segments: List[Segment] = []
    for p_idx, para in enumerate(raw_paragraphs):
        is_last = (p_idx == len(raw_paragraphs) - 1)
        p_segs = parse_paragraph_intonation(
            para=para,
            default_pause=default_paragraph_pause,
            base_speed=base_speed,
            base_pitch=base_pitch,
            smart_intonation=smart_intonation,
            is_last_paragraph=is_last
        )
        all_segments.extend(p_segs)

    return all_segments


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
    smart_intonation: bool = True,
) -> tuple:
    """
    Core generation logic with per-sentence and per-word pitch control.
    Returns (audio_bytes, segments_count, total_words) or raises.
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
        segments = parse_script_into_segments(
            clean_text,
            default_paragraph_pause=paragraph_pause,
            base_speed=speed,
            base_pitch=pitch,
            smart_intonation=smart_intonation
        )
    else:
        segments = [Segment(clean_text_segment(clean_text, is_sentence_end=True), 0.0, speed, pitch, is_sentence_end=True)]

    for i, seg in enumerate(segments):
        if len(seg.text) > 3000:
            raise ValueError(
                f"Segment {i+1} is {len(seg.text)} chars (max 3000). "
                "Break it into shorter paragraphs."
            )

    if not segments:
        raise ValueError("Script produced no valid segments after parsing.")

    total_words = sum(len(seg.text.split()) for seg in segments)

    # Single segment fast path
    if len(segments) == 1:
        seg = segments[0]
        audio_bytes = synthesize_segment(seg.text, voice_id, bitrate, seg.speed, seg.pitch, api_key)
        return audio_bytes, 1, total_words

    # Multi-segment: parallel synthesis + silence stitching
    segment_audio = {}
    errors = []

    with ThreadPoolExecutor(max_workers=min(4, len(segments))) as executor:
        future_to_idx = {}
        for idx, seg in enumerate(segments):
            future = executor.submit(
                synthesize_segment, seg.text, voice_id, bitrate, seg.speed, seg.pitch, api_key
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
        seg = segments[idx]
        master.write(segment_audio[idx])
        if seg.pause_after > 0 and idx < len(segments) - 1:
            silence = generate_silence_bytes(seg.pause_after)
            if silence:
                master.write(silence)

    return master.getvalue(), len(segments), total_words


# In-memory audio cache for rapid playback without disk latency
AUDIO_CACHE: Dict[str, bytes] = {}


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

    # Cache in memory for instant delivery
    AUDIO_CACHE[filename] = audio_bytes
    if len(AUDIO_CACHE) > 50:
        oldest = next(iter(AUDIO_CACHE))
        AUDIO_CACHE.pop(oldest, None)

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


@mcp.resource(
    "ui://voiceover-studio/player",
    name="Voiceover Audio Player",
    description="Interactive audio player widget that renders inline after voiceover generation.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": False}}
)
def get_player_widget() -> str:
    """Return the HTML/JS interactive audio player widget for MCP Apps."""
    from mcp_http_router import PLAYER_HTML
    return PLAYER_HTML


@mcp.tool(
    meta={
        "ui": {
            "resourceUri": "ui://voiceover-studio/player"
        },
        "ui/resourceUri": "ui://voiceover-studio/player"
    }
)
def generate_voiceover(
    text: str,
    voice_id: str = "Eleanor",
    speed: float = 0.0,
    pitch: float = 1.0,
    bitrate: str = "192k",
    paragraph_pause: float = 0.8,
    smart_pacing: bool = True,
    smart_intonation: bool = True,
) -> str:
    """
    Generate a voiceover MP3 from script text using neural AI voices (Kokoro TTS).

    The generated MP3 is saved to the server's outputs/ folder and metadata is
    returned including the file path and download URL.

    NATURAL HUMAN SPEECH & PITCH CONTROL:
    To make voiceovers feel alive and natural like human speech:
    - Per-word / per-sentence pitch markup:
        * Numeric: [pitch: 1.15]emphasized word[/pitch] or [pitch: 0.85]somber note[/pitch]
        * Relative: [pitch: +10%]word[/pitch] or [pitch: -8%]whisper[/pitch]
        * Semantic: [pitch: high], [pitch: low], [pitch: whisper], [pitch: rise], [pitch: drop], [pitch: excited]
        * Shorthand tags: [high]word[/high], [low]word[/low], [whisper]phrase[/whisper], [rise]word[/rise]
        * Speed markup: [speed: 0.15]rapid[/speed] or [speed: fast]urgent[/speed]
    - Smart Human Intonation (smart_intonation=True):
        * Automatically adds rising pitch inflection (+7%) on questions (?)
        * Adds energetic projection (+8%) on exclamations (!)
        * Subdues pitch (-8%) on parenthetical asides (...)

    INSTRUCTIONS FOR CLAUDE -- CHOOSING SETTINGS:
    Before calling this tool, call list_voices to see all voices.
    Then analyze the script content and pick the best voice:
    - Match voice gender to user preference if stated
    - Match voice style to script tone (warm narrative -> Eleanor, thriller -> Jasper, etc.)
    - Use smart_pacing=True and smart_intonation=True for natural human-like cadence.

    Args:
        text: The script text to synthesize. Supports prosody tags ([pitch: high], [whisper])
              and pause markers like [pause: 1.2s], [beat].
        voice_id: Kokoro TTS voice. One of: Eleanor, Jasper, Ivy, Oliver,
                  Luna, Ethan, Charlotte, Rafael. Default: Eleanor.
        speed: Base pacing from -1.0 (slow) to 1.0 (fast). 0.0 is normal.
        pitch: Base pitch from 0.5 to 1.5. Default 1.0.
        bitrate: Audio quality. 192k (default), 128k, 256k, or 320k.
        paragraph_pause: Seconds of silence between paragraphs (0.0-3.0). Default 0.8.
        smart_pacing: If True (default), parses paragraph breaks and pause markers.
        smart_intonation: If True (default), automatically applies human inflection
                          to questions, exclamations, and parentheticals.

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
            text, voice_id, speed, pitch, bitrate, paragraph_pause, smart_pacing, api_key,
            smart_intonation=smart_intonation
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
