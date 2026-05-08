"""
bridge_post.py - Stop hook (fires when Claude finishes responding).

Reads the Stop hook payload from stdin, extracts the assistant's last
message text, and posts a one-line summary to Legion's bridge so the
other machine's Claude sees it on its next prompt.

Configure in ~/.claude/settings.json:
    {
      "hooks": {
        "Stop": [{
          "hooks": [{"type": "command",
                     "command": "py C:\\\\Riot Commander\\\\tools\\\\bridge_post.py legion"}]
        }]
      }
    }

The single positional arg ('legion' or 'gamepc') tags the source so the
other side knows where the activity came from.
"""
import json
import re
import sys
import urllib.request

LEGION = "https://legion-rc:8888/api/bridge"
TIMEOUT = 1.5
MAX_LEN = 220   # one-line summary cap


def extract_summary(payload: dict) -> str:
    """Stop hook payload includes the conversation transcript path. We read
    the LAST assistant message and grab a short summary line."""
    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        return ""
    try:
        with open(transcript_path, encoding="utf-8") as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
    except Exception:
        return ""
    # Walk from end; find last assistant text content
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get("role") != "assistant" and row.get("type") != "assistant":
            continue
        content = row.get("content") or row.get("message", {}).get("content", [])
        if isinstance(content, str):
            return _shorten(content)
        if isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    txt = blk.get("text", "")
                    if txt.strip():
                        return _shorten(txt)
    return ""


def _shorten(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # Skip code/error blocks etc.; take the first 1-2 short sentences
    # bounded by length. Aim for "what just happened" not "full output".
    if len(text) <= MAX_LEN:
        return text
    cut = text[:MAX_LEN].rsplit(" ", 1)[0]
    return cut + "…"


def main() -> int:
    source = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}
    summary = extract_summary(payload)
    if not summary:
        return 0
    body = json.dumps({"source": source, "summary": summary}).encode()
    try:
        req = urllib.request.Request(
            LEGION, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=TIMEOUT).read()
    except Exception:
        # Bridge unreachable — fail silently; don't block Claude from finishing.
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
