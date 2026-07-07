"""Probe a model through the LiteLLM proxy /v1/messages endpoint - a plain text
round-trip to confirm the backend + key work. Usage: probe_model.py <model_name>.
Never prints keys. Exit 0 = PASS, 1 = FAIL (auth/backend error)."""
import os
import sys
import json
import urllib.request

model = sys.argv[1] if len(sys.argv) > 1 else "rc-local"
KEY = os.environ["LITELLM_MASTER_KEY"]
body = {"model": model, "max_tokens": 30,
        "messages": [{"role": "user", "content": "Reply with just: OK"}]}
req = urllib.request.Request(
    "http://127.0.0.1:4000/v1/messages", data=json.dumps(body).encode(), method="POST",
    headers={"content-type": "application/json", "x-api-key": KEY, "anthropic-version": "2023-06-01"})
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read())
    txt = "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")
    print(f"PASS {model}: {txt[:60]!r}")
except urllib.error.HTTPError as e:
    detail = e.read().decode(errors="replace")[:200]
    print(f"FAIL {model}: HTTP {e.code} {detail}")
    sys.exit(1)
except (OSError, ValueError) as e:
    print(f"FAIL {model}: {e}")
    sys.exit(1)
