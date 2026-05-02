"""
bridge_fetch.py - UserPromptSubmit hook.

Fetches recent cross-Claude bridge messages from Legion's web dashboard
and prints them to stdout, where Claude Code's UserPromptSubmit hook
captures them and prepends to the conversation as additional context.

Tracks "last seen" timestamp per machine in
%LOCALAPPDATA%\\rc-bridge-last-seen.txt so it only injects NEW messages.

Configure in ~/.claude/settings.json:
    {
      "hooks": {
        "UserPromptSubmit": [{
          "hooks": [{"type": "command",
                     "command": "py C:\\\\Riot Commander\\\\tools\\\\bridge_fetch.py"}]
        }]
      }
    }

(On Game-PC, use C:\\RC-Agent\\bridge_fetch.py if you copy the file there.)
"""
import json
import os
import ssl
import sys
import time
import urllib.request

LEGION = "https://legion-rc:8888/api/bridge"
TIMEOUT = 1.5
# Legion uses a mkcert-issued self-signed cert. The root CA is installed on
# Game-PC's trusted store, but to be safe against fresh deploys this script
# skips cert verification — traffic is LAN-only between two trusted hosts.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_local = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
LAST_SEEN_FILE = os.path.join(_local, "rc-bridge-last-seen.txt")


def read_last_seen() -> float:
    try:
        return float(open(LAST_SEEN_FILE, "r", encoding="utf-8").read().strip())
    except Exception:
        # First run: only show messages from the last 30 minutes
        return time.time() - 1800


def write_last_seen(ts: float) -> None:
    try:
        with open(LAST_SEEN_FILE, "w", encoding="utf-8") as f:
            f.write(str(ts))
    except Exception:
        pass


def main() -> int:
    since = read_last_seen()
    try:
        url = f"{LEGION}?since={since}&limit=20"
        with urllib.request.urlopen(url, timeout=TIMEOUT, context=_SSL_CTX) as r:
            data = json.loads(r.read())
    except Exception:
        # Bridge unreachable — silently skip; don't block the user's prompt.
        return 0
    msgs = data.get("messages") or []
    if not msgs:
        return 0
    lines = ["[Cross-Claude bridge — recent activity from the other machine]"]
    for m in msgs:
        ts = time.strftime("%H:%M:%S", time.localtime(m.get("ts", 0)))
        src = m.get("source", "?")
        sm  = m.get("summary", "")
        lines.append(f"  [{ts} · {src}] {sm}")
    print("\n".join(lines))
    write_last_seen(data.get("now", time.time()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
