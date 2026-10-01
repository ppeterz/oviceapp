import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from unittest.mock import patch
from server import app
import json

client = TestClient(app)

print("=== Testing /api/unrealspeech/generate with Pitch Tags ===")

fake_audio = b"FAKE_AUDIO_OUTPUT_PER_SEGMENT"

with patch("server.synthesize_single_segment", return_value=fake_audio) as mock_synth:
    payload = {
        "text": "He promised [pitch: 1.18]paradise[/pitch]. Nine hundred people followed him.\n\nDid they really know the truth?",
        "voice_id": "Jasper",
        "speed": 0.0,
        "pitch": 1.0,
        "api_key": "test-key-abc",
        "smart_pacing": True,
        "smart_intonation": True
    }
    
    resp = client.post("/api/unrealspeech/generate", json=payload)
    print("Status:", resp.status_code)
    data = resp.json()
    print("Response keys:", list(data.keys()))
    print("Segment count:", data.get("segment_count"))
    print("Smart intonation in meta:", data.get("smart_intonation"))
    print("Calls made to synthesize_single_segment:", mock_synth.call_count)
    for i, c in enumerate(mock_synth.call_args_list):
        kwargs = c.kwargs
        print(f"  Call {i+1}: text={kwargs.get('text')!r:30} speed={kwargs.get('speed')} pitch={kwargs.get('pitch')}")

    assert resp.status_code == 200
    assert data["segment_count"] >= 3
    assert mock_synth.call_count >= 3
    
    # Check that paradise had pitch 1.18
    paradise_call = [c.kwargs for c in mock_synth.call_args_list if "paradise" in c.kwargs.get("text", "")]
    assert len(paradise_call) == 1
    assert paradise_call[0]["pitch"] == 1.18
    
    # Check that question had question rise intonation (pitch 1.07)
    question_call = [c.kwargs for c in mock_synth.call_args_list if "?" in c.kwargs.get("text", "")]
    assert len(question_call) == 1
    assert question_call[0]["pitch"] == 1.07

print("\nAll API pitch control tests passed successfully!")
