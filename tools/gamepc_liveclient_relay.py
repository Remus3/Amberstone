"""
gamepc_liveclient_relay.py - Game-PC agent that pushes Riot Live Client API
data to Legion every N seconds.

Riot's :2999 endpoint binds to 127.0.0.1 only; Legion can't reach it over
LAN. This relay polls /liveclientdata/allgamedata locally, then POSTs the
JSON to Legion's vision server which caches it for the dashboard / coaches.

Deploy on Game-PC (one time):
  1. Copy this file to C:\\RC-Agent\\
  2. C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe -m pip install requests urllib3
  3. C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe C:\\RC-Agent\\gamepc_liveclient_relay.py
  4. (optional task) schtasks /Create /TN "RC-LiveClientRelay" /SC ONLOGON /F /TR "C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe C:\\RC-Agent\\gamepc_liveclient_relay.py"

When in champ select / not in game, /liveclientdata returns 404 - relay
backs off and retries.
"""
import json
import ssl
import sys
import time
import urllib.request
import urllib.error

LIVE_URLS = [
    "https://127.0.0.1:2999/liveclientdata/allgamedata",
    "http://127.0.0.1:2999/liveclientdata/allgamedata",
]
LEGION_URL = "http://192.168.8.230:8889/upload-liveclient"

# AUDIT (2026-04-22): token resolver - env -> config file -> fallback.
import os as _os_tok
from pathlib import Path as _Path_tok
def _resolve_auth_token() -> str:
    env = _os_tok.environ.get("RC_VISION_TOKEN")
    if env: return env.strip()
    # Canonical source (item 242): repo config/vision_token.txt. The legacy
    # sibling vision_token.txt + the hardcode below are DEAD fallbacks - a
    # stale token 401s every /upload-liveclient silently (pythonw, no console)
    # -> relay cache empty -> the app never sees the live game -> coach dead.
    # Never reintroduce a token hardcode as the live path.
    _root = _Path_tok(__file__).resolve().parent.parent
    for cand in (_root / "config" / "vision_token.txt",
                 _Path_tok(__file__).resolve().parent / "vision_token.txt"):
        try:
            if cand.exists():
                line = cand.read_text(encoding="utf-8").splitlines()[0].strip()
                if line: return line
        except OSError:
            pass
    return "8e8f131e212b329438218eca27372dde"

TOKEN = _resolve_auth_token()
INTERVAL = 1.0   # seconds between polls when in-game
BACKOFF = 2.0    # seconds when not in-game (short so verbose log shows quickly)

# Riot's :2999 uses a self-signed cert with older crypto. Python 3.10+
# defaults reject it ("UNEXPECTED_EOF_WHILE_READING"). Loosen the context:
# - skip verification (self-signed)
# - drop the cipher security level (legacy ciphers OK for localhost)
# - allow older TLS versions
_ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE
try:
    _ssl_ctx.set_ciphers("ALL:@SECLEVEL=0")
except ssl.SSLError:
    pass
try:
    _ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1
except (AttributeError, ValueError):
    pass


def _try_one(url: str) -> tuple[bytes | None, str]:
    """Try one URL. Returns (payload, status_string)."""
    try:
        kwargs = {"timeout": 2}
        if url.startswith("https"):
            kwargs["context"] = _ssl_ctx
        with urllib.request.urlopen(url, **kwargs) as r:
            return r.read(), "ok"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, "404"
        return None, f"http {e.code} {e.reason}"
    except urllib.error.URLError as e:
        return None, f"url {e.reason}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def fetch_live() -> bytes | None:
    last_err = ""
    for url in LIVE_URLS:
        payload, status = _try_one(url)
        if payload is not None:
            return payload
        if status == "404":
            print(f"  [skip] {url} -> 404 (not in game)", flush=True)
            return None
        last_err = f"{url[:8]} -> {status}"
    print(f"  [err] tried both schemes, last: {last_err}", flush=True)
    return None


def upload(data: bytes) -> None:
    req = urllib.request.Request(
        LEGION_URL, data=data, method="POST",
        headers={"X-RC-Token": TOKEN, "Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=3).read()


def loop() -> None:
    print(f"liveclient relay -> {LEGION_URL} every {INTERVAL}s")
    while True:
        t0 = time.time()
        try:
            payload = fetch_live()
            if payload is None:
                time.sleep(BACKOFF)
                continue
            upload(payload)
            ms = int((time.time() - t0) * 1000)
            print(f"ok {len(payload)}B in {ms}ms", flush=True)
        except Exception as exc:
            print(f"err {exc}", flush=True)
        sleep_for = max(0.1, INTERVAL - (time.time() - t0))
        time.sleep(sleep_for)


if __name__ == "__main__":
    try:
        loop()
    except KeyboardInterrupt:
        sys.exit(0)
