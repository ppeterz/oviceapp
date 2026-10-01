"""Comprehensive test suite for MCP Apps integration."""
import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from mcp_http_router import router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
c = TestClient(app)

# Test 1: tools/list has _meta with resourceUri
print("=== Test 1: tools/list ===")
r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
d = r.json()
gen_tool = [t for t in d["result"]["tools"] if t["name"] == "generate_voiceover"][0]
print("_meta:", json.dumps(gen_tool.get("_meta"), indent=2))
assert gen_tool["_meta"]["ui"]["resourceUri"] == "ui://voiceover-studio/player"
assert gen_tool["_meta"]["ui/resourceUri"] == "ui://voiceover-studio/player"

# Test 2: resources/list
print("\n=== Test 2: resources/list ===")
r2 = c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "resources/list"})
res_list = r2.json()["result"]["resources"]
print(json.dumps(res_list, indent=2))
assert len(res_list) == 1
assert res_list[0]["uri"] == "ui://voiceover-studio/player"
assert res_list[0]["mimeType"] == "text/html;profile=mcp-app"

# Test 3: resources/read
print("\n=== Test 3: resources/read ===")
r3 = c.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "resources/read", "params": {"uri": "ui://voiceover-studio/player"}})
d3 = r3.json()
content = d3["result"]["contents"][0]
print("status:", r3.status_code)
print("mime:", content["mimeType"])
print("has_html:", "<!DOCTYPE html>" in content["text"])
print("prefersBorder:", content["_meta"]["ui"]["prefersBorder"])
print("csp resourceDomains:", content["_meta"]["ui"]["csp"]["resourceDomains"])
assert content["mimeType"] == "text/html;profile=mcp-app"
assert "ui/initialize" in content["text"]
assert "ui/notifications/initialized" in content["text"]
assert "ui/notifications/size-changed" in content["text"]
assert "ui/notifications/tool-result" in content["text"]

# Test 4: initialize extensions
print("\n=== Test 4: initialize (extensions) ===")
r4 = c.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "initialize", "params": {}})
init_res = r4.json()["result"]
print("capabilities extensions:", json.dumps(init_res["capabilities"].get("extensions"), indent=2))
assert "io.modelcontextprotocol/ui" in init_res["capabilities"]["extensions"]
assert "io.modelcontextprotocol/ui" in init_res["extensions"]

# Test 5: tools/call list_voices has structuredContent
print("\n=== Test 5: tools/call list_voices ===")
r5 = c.post("/mcp", json={"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "list_voices", "arguments": {}}})
res5 = r5.json()["result"]
assert "content" in res5
assert "structuredContent" in res5
assert "voices" in res5["structuredContent"]
print("voices count:", len(res5["structuredContent"]["voices"]))

# Test 6: tools/call generate_voiceover (mock synthesis)
print("\n=== Test 6: tools/call generate_voiceover ===")
fake_audio = b"FAKE_MP3_AUDIO_BYTES_FOR_TESTING"
with patch("mcp_http_router._generate_audio", return_value=(fake_audio, 2, 25)), \
     patch.dict("os.environ", {"UNREALSPEECH_API_KEY": "test-key-123", "VERCEL_URL": "voiceover-studio.vercel.app"}):
    r6 = c.post("/mcp", json={
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": "generate_voiceover",
            "arguments": {"text": "Test voiceover script.", "voice_id": "Jasper"}
        }
    })
    res6 = r6.json()["result"]
    sc = res6["structuredContent"]
    print("success:", sc.get("success"))
    print("voice_id:", sc.get("voice_id"))
    print("audio_url:", sc.get("audio_url"))
    print("download_url:", sc.get("download_url"))
    assert sc["success"] is True
    assert sc["voice_id"] == "Jasper"
    assert sc["word_count"] == 25
    assert sc["audio_url"].endswith(".mp3")
    assert "/api/outputs/" in sc["audio_url"]
    assert "/api/download/" in sc["download_url"]
    # Verify the payload size is compact (< 2 KB) to prevent context limit errors
    assert len(json.dumps(sc)) < 2048

print("\nAll 6 tests passed successfully!")
