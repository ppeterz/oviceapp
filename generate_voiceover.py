#!/usr/bin/env python3
"""
Generate a voiceover MP3 from a script using the Unreal Speech API (/speech endpoint).

Usage:
    export UNREALSPEECH_API_KEY=...
    python3 generate_voiceover.py --text-file script.txt --voice-id Eleanor --out voiceover.mp3

Smart Pacing:
    Scripts with multiple paragraphs are automatically segmented and synthesized
    in parallel with calibrated silence stitched between each segment.

    python3 generate_voiceover.py --text-file script.txt --paragraph-pause 1.2 --out voiceover.mp3

Request/response contract below is taken directly from Unreal Speech's own
published Python SDK (PyPI: unrealspeech), not a scraped code sample:
POST {base_url}/speech with a Bearer-token Authorization header and
PascalCase JSON fields. With OutputFormat "uri" the API returns a JSON body
containing a downloadable OutputUri rather than raw audio bytes -- this
script fetches that URI afterward and writes the MP3 to disk.

The API host has advanced its version segment over time (v6 seen in the
published SDK, v7 seen in live examples, v8 is what the current docs site
uses) while the endpoint paths stay stable. If the default host stops
working, override --base-url -- check https://docs.v8.unrealspeech.com/
for whatever host is current.
"""
import argparse
import io
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("This script needs the 'requests' package: pip install requests --break-system-packages")

from mcp_tools import Segment, parse_script_into_segments, clean_text_segment

DEFAULT_BASE_URL = "https://api.v8.unrealspeech.com"


# Prosody & pacing engine is imported from mcp_tools (Segment, parse_script_into_segments, clean_text_segment)


def synthesize_segment(text, voice_id, bitrate, speed, pitch, api_key, base_url, timestamp_type="sentence"):
    """Synthesize a single segment. Returns MP3 bytes."""
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

    resp = requests.post(f"{base_url}/speech", json=payload, headers=headers, timeout=120)
    if resp.status_code != 200:
        raise Exception(f"Unreal Speech API error {resp.status_code}: {resp.text}")

    data = resp.json()
    audio_uri = data.get("OutputUri")
    if isinstance(audio_uri, list):
        audio_uri = audio_uri[0]
    if not audio_uri:
        raise Exception(f"No OutputUri in response: {data}")

    audio_resp = requests.get(audio_uri, timeout=120)
    audio_resp.raise_for_status()
    return audio_resp.content


def load_silence_frames():
    """Load silence_frames.bin from the static/assets directory."""
    silence_path = Path(__file__).resolve().parent / "static" / "assets" / "silence_frames.bin"
    if silence_path.exists():
        with open(silence_path, "rb") as f:
            return f.read()
    return b""


def generate_silence_bytes(silence_frames: bytes, duration_sec: float) -> bytes:
    """Generate silence MP3 bytes for the given duration."""
    if not silence_frames or duration_sec <= 0:
        return b""
    base_duration = 0.8
    repeats = max(1, round(duration_sec / base_duration))
    return silence_frames * repeats


def main():
    parser = argparse.ArgumentParser(description="Generate a voiceover via the Unreal Speech API")
    parser.add_argument("--text-file", required=True, help="Path to a text file containing the script")
    parser.add_argument("--voice-id", default="Eleanor", help="Kokoro TTS voice ID, e.g. Eleanor, Jasper, Ivy, Oliver, Luna, Ethan, Charlotte, Rafael")
    parser.add_argument("--out", default="voiceover.mp3", help="Output MP3 path")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API host, in case the version segment has moved on")
    parser.add_argument("--bitrate", default="192k", help="32k-320k, e.g. 320k, 256k, 192k, 128k")
    parser.add_argument("--speed", type=float, default=0.0, help="-1.0 to 1.0. 0 is normal pace; -0.5 is roughly 50%% slower; keep small (+/-0.1 to 0.3) for natural pacing")
    parser.add_argument("--pitch", type=float, default=1.0, help="0.5-1.5. Defaults to 1.0; Unreal Speech itself defaults male voices to ~0.92 since lower reads more natural")
    parser.add_argument("--timestamp-type", default="sentence", choices=["sentence", "word"], help="Granularity of the timestamp data returned alongside the audio")
    parser.add_argument("--paragraph-pause", type=float, default=0.8, help="Silence duration between paragraphs in seconds (0.0 to 3.0). Default: 0.8")
    parser.add_argument("--no-smart-pacing", action="store_true", help="Disable smart pacing (send entire script as single API call)")
    parser.add_argument("--no-smart-intonation", action="store_true", help="Disable smart intonation heuristics for questions and exclamations")
    args = parser.parse_args()

    api_key = os.environ.get("UNREALSPEECH_API_KEY")
    if not api_key:
        sys.exit("Set the UNREALSPEECH_API_KEY environment variable first.")

    if not os.path.exists(args.text_file):
        sys.exit(f"Text file not found: {args.text_file}")

    with open(args.text_file, "r", encoding="utf-8") as f:
        text = f.read().strip()

    if not text:
        sys.exit("Text file is empty.")

    # ── Smart Pacing & Prosody: Parse & Segment ──
    if not args.no_smart_pacing:
        segments = parse_script_into_segments(
            text,
            default_paragraph_pause=args.paragraph_pause,
            base_speed=args.speed,
            base_pitch=args.pitch,
            smart_intonation=not args.no_smart_intonation
        )
        print(f"[PACING] Script parsed into {len(segments)} segment(s) (paragraph pause: {args.paragraph_pause}s, smart intonation: {not args.no_smart_intonation})")
    else:
        if len(text) > 3000:
            sys.exit(f"Script is {len(text)} characters; /speech caps at 3000. Use smart pacing or split manually.")
        segments = [Segment(clean_text_segment(text, is_sentence_end=True), 0.0, args.speed, args.pitch, is_sentence_end=True)]
        print(f"[SINGLE-PASS] Sending entire script as one API call ({len(text)} chars)")

    # Validate segment lengths
    for i, seg in enumerate(segments):
        if len(seg.text) > 3000:
            sys.exit(f"Segment {i+1} is {len(seg.text)} characters (max 3000). Break it into shorter paragraphs.")

    if not segments:
        sys.exit("Script produced no valid segments after parsing.")

    # ── Single segment: fast path ──
    if len(segments) == 1:
        seg = segments[0]
        print(f"Requesting voiceover for {len(seg.text.split())} words from voice {args.voice_id} (speed={seg.speed}, pitch={seg.pitch})...")
        audio_bytes = synthesize_segment(
            seg.text, args.voice_id, args.bitrate, seg.speed, seg.pitch,
            api_key, args.base_url, args.timestamp_type
        )
        with open(args.out, "wb") as f:
            f.write(audio_bytes)
        print(f"Saved voiceover to {args.out} ({len(audio_bytes)} bytes)")
        return

    # ── Multi-segment: Parallel synthesis + silence stitching ──
    total_words = sum(len(seg.text.split()) for seg in segments)
    print(f"Synthesizing {len(segments)} segments ({total_words} total words) in parallel with per-word/per-sentence pitch...")

    silence_frames = load_silence_frames()
    segment_audio = {}
    errors = []

    with ThreadPoolExecutor(max_workers=min(4, len(segments))) as executor:
        future_to_idx = {}
        for idx, seg in enumerate(segments):
            future = executor.submit(
                synthesize_segment,
                seg.text, args.voice_id, args.bitrate, seg.speed, seg.pitch,
                api_key, args.base_url, args.timestamp_type
            )
            future_to_idx[future] = idx

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                segment_audio[idx] = future.result()
                seg = segments[idx]
                print(f"  ✓ Segment {idx+1}/{len(segments)} synthesized ({len(segment_audio[idx])} bytes, speed={seg.speed}, pitch={seg.pitch})")
            except Exception as e:
                errors.append(f"Segment {idx+1}: {str(e)}")
                print(f"  ✗ Segment {idx+1} FAILED: {str(e)}")

    if errors:
        sys.exit(f"Failed to synthesize {len(errors)} segment(s):\n" + "\n".join(errors))

    # ── Stitch segments ──
    print(f"Stitching {len(segments)} segments with calibrated silence...")
    master = io.BytesIO()

    for idx in range(len(segments)):
        seg = segments[idx]
        master.write(segment_audio[idx])

        if seg.pause_after > 0 and idx < len(segments) - 1:
            silence = generate_silence_bytes(silence_frames, seg.pause_after)
            if silence:
                master.write(silence)
                print(f"  + {seg.pause_after:.2f}s silence after segment {idx+1}")

    final_audio = master.getvalue()

    with open(args.out, "wb") as f:
        f.write(final_audio)

    print(f"\nSaved studio-paced voiceover to {args.out}")
    print(f"  Total: {len(final_audio)} bytes | {len(segments)} segments | {total_words} words")


if __name__ == "__main__":
    main()
