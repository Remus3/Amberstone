"""Probe whether an Ollama model returns STRUCTURED tool_calls (required to drive an
agentic loop) vs emitting the call as plain text. Usage: probe_ollama_tools.py <model>."""
import sys
import json
import urllib.request

model = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5-coder:14b-instruct"
body = {
    "model": model,
    "messages": [{"role": "user", "content": "Use the get_weather tool for Paris."}],
    "tools": [{"type": "function", "function": {
        "name": "get_weather",
        "description": "Get the weather for a city",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    }}],
    "stream": False,
}
req = urllib.request.Request(
    "http://127.0.0.1:11434/api/chat", data=json.dumps(body).encode(),
    method="POST", headers={"content-type": "application/json"},
)
out = json.loads(urllib.request.urlopen(req, timeout=180).read())
msg = out.get("message", {})
tc = msg.get("tool_calls")
print(f"MODEL={model} HAS_TOOL_CALLS={bool(tc)}")
if tc:
    print("OK:", json.dumps(tc)[:200])
else:
    print("TEXT:", repr(msg.get("content"))[:200])
