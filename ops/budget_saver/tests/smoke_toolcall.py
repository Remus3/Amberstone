"""GATE smoke: does the local model emit a valid Anthropic tool_use through the
LiteLLM /v1/messages endpoint? If not, local is demoted to background-only and the
default profile becomes DeepSeek-primary. Requires the proxy up + LITELLM_MASTER_KEY."""
import os
import sys
import json
import urllib.request

URL = "http://127.0.0.1:4000/v1/messages"
KEY = os.environ["LITELLM_MASTER_KEY"]
MODEL = sys.argv[1] if len(sys.argv) > 1 else "rc-local"

body = {
    "model": MODEL,
    "max_tokens": 300,
    "tools": [{
        "name": "get_weather",
        "description": "Get the weather for a city",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    }],
    "messages": [{"role": "user", "content": "Use the get_weather tool for Paris."}],
}
req = urllib.request.Request(
    URL, data=json.dumps(body).encode(), method="POST",
    headers={"content-type": "application/json", "x-api-key": KEY, "anthropic-version": "2023-06-01"},
)
with urllib.request.urlopen(req, timeout=180) as r:
    out = json.loads(r.read())

print(json.dumps(out, indent=2)[:1000])
tool_uses = [b for b in out.get("content", []) if b.get("type") == "tool_use"]
if not tool_uses:
    print(f"GATE FAIL ({MODEL}): no tool_use emitted - demote local to background-only, default DeepSeek-primary")
    sys.exit(1)
print(f"GATE PASS ({MODEL}): valid tool_use ->", tool_uses[0].get("name"))
