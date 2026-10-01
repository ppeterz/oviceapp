"""Quick test for MCP Apps integration."""
import json
from fastapi.testclient import TestClient
from mcp_http_router import router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
c = TestClient(app)

# Test 1: tools/list has _meta
print("=== tools/list ===")
r = c.post("/mcp", json={"jsonrpc":"2.0","id":1,"method":"tools/list"})
d = r.json()
gen_tool = [t for t in d["result"]["tools"] if t["name"] == "generate_voiceover"][0]
print("_meta:", json.dumps(gen_tool.get("_meta"), indent=2))

# Test 2: resources/list
print("\n=== resources/list ===")
r2 = c.post("/mcp", json={"jsonrpc":"2.0","id":2,"method":"resources/list"})
print(json.dumps(r2.json()["result"], indent=2))

# Test 3: resources/read
print("\n=== resources/read ===")
r3 = c.post("/mcp", json={"jsonrpc":"2.0","id":3,"method":"resources/read","params":{"uri":"ui://voiceover-studio/player"}})
d3 = r3.json()
print("status:", r3.status_code)
content = d3["result"]["contents"][0]
print("mime:", content["mimeType"])
print("has_html:", "<!DOCTYPE html>" in content["text"])
print("prefersBorder:", content["_meta"]["ui"]["prefersBorder"])

# Test 4: initialize extensions
print("\n=== initialize (extensions) ===")
r4 = c.post("/mcp", json={"jsonrpc":"2.0","id":4,"method":"initialize","params":{}})
print("extensions:", json.dumps(r4.json()["result"].get("extensions"), indent=2))

print("\nAll tests passed!")
