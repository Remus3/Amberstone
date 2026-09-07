"""
liveclient_relay.py - Legion-local liveclient relay (relocated 2026-05-29,
ADR-011); self-heals in-process.

Polls Riot's local Live Client API (:2999 /liveclientdata/allgamedata) and
POSTs the JSON to the in-process vision server which caches it for the
dashboard / coaches. Post 1-PC consolidation everything runs on Legion, so
the relay reads :2999 in-process and self-heals when the cached snapshot
goes stale.

Run (one time):
  1. $env:LOCALAPPDATA/Programs/Python/Python314/python.exe -m pip install requests urllib3
  2. $env:LOCALAPPDATA/Programs/Python/Python314/python.exe C:\\RC-Agent\\liveclient_relay.py
  3. (optional task) schtasks /Create /TN "RC-LiveClientRelay" /SC ONLOGON /F /TR "$env:LOCALAPPDATA/Programs/Python/Python314/python.exe C:\\RC-Agent\\liveclient_relay.py"

When in champ select / not in game, /liveclientdata returns 404 - relay
backs off and retries.
"""
import logging
import os
import ssl
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

LIVE_URLS = [
    "https://127.0.0.1:2999/liveclientdata/allgamedata",
    "http://127.0.0.1:2999/liveclientdata/allgamedata",
]

_ROOT = Path(__file__).resolve().parent.parent

# Lane 8 audit 2026-08-03. The scheduled task runs this under pythonw.exe
# (read from the RC-LiveClientRelay task XML), which has NO CONSOLE, so every
# print() this module used to emit went nowhere - including the errors. The
# module even documented that exact failure ("401s ... silently (pythonw, no
# console) -> coach dead") and then reported through print() anyway. Log to a
# file, on the in-tree precedent at tools/daemon_slayer_extract.py:98-105.
_LOG_FILE = _ROOT / "logs" / "liveclient_relay.log"
_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(_LOG_FILE), encoding="utf-8"),
    ],
)
log = logging.getLogger("liveclient_relay")


def _upload_url() -> str:
    """Where to POST the snapshot.

    Defaults to LOOPBACK. This used to be a hardcoded `192.168.8.230`, which
    still resolves on this box but is wrong on both counts post-ADR-011: both
    ends are the same machine, so the X-RC-Token crossed the LAN interface in
    cleartext for nothing, and a DHCP change would have killed the relay
    silently (see the logging note above). Overridable for the same reason
    `core/game_host.py` is - the host is config, not code.
    """
    return os.environ.get(
        "RC_VISION_UPLOAD_URL", "http://127.0.0.1:8889/upload-liveclient")


def _token_candidates() -> list[Path]:
    """Config files searched for the vision token, in priority order."""
    return [_ROOT / "config" / "vision_token.txt",
            Path(__file__).resolve().parent / "vision_token.txt"]


def _resolve_auth_token() -> str:
    """env -> config file -> "" (NEVER a hardcoded token).

    Canonical source (item 242) is repo config/vision_token.txt. There used to
    be a hardcoded 32-hex fallback here, directly beneath a comment saying
    "Never reintroduce a token hardcode as the live path". It was dead (it did
    not match the live token) but it was actively harmful in two ways: a
    missing config silently produced a WRONG token, so every upload 401'd with
    no report; and `dashboard/routes_static.py` serves this file's SOURCE at
    /agent/liveclient_relay.py with no auth check, on a `::` bind - so the
    literal was published to the LAN and tailnet. Returning "" instead lets
    the caller fail loudly.
    """
    env = os.environ.get("RC_VISION_TOKEN")
    if env:
        return env.strip()
    for cand in _token_candidates():
        try:
            if cand.exists():
                line = cand.read_text(encoding="utf-8").splitlines()[0].strip()
                if line:
                    return line
        except OSError:
            pass
    return ""


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
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def fetch_live() -> bytes | None:
    last_err = ""
    for url in LIVE_URLS:
        payload, status = _try_one(url)
        if payload is not None:
            _note_fetch_recovered()
            return payload
        if status == "404":
            log.debug("skip %s -> 404 (not in game)", url)
            return None
        last_err = f"{url[:8]} -> {status}"
    _log_fetch_failure(last_err)
    return None


_last_fetch_failure: str | None = None


def _log_fetch_failure(detail: str) -> None:
    """WARNING on a CHANGE of failure mode, DEBUG while it repeats.

    Caught immediately after deploying the FileHandler, by reading the log
    the old code could never write: with no game running, :2999 is not
    listening, so every poll fails and the first version logged a WARNING
    every ~6 seconds forever - roughly 2 MB/day of identical lines, which
    would bury the one line that matters (the 401 this audit exists to make
    visible). Giving the module a real output channel is only half the job;
    the other half is not flooding it. The transition is the signal.
    """
    global _last_fetch_failure
    if detail != _last_fetch_failure:
        log.warning("liveclient fetch failing: %s", detail)
        _last_fetch_failure = detail
    else:
        log.debug("liveclient fetch still failing: %s", detail)


def _note_fetch_recovered() -> None:
    global _last_fetch_failure
    if _last_fetch_failure is not None:
        log.info("liveclient fetch recovered")
        _last_fetch_failure = None


def upload(data: bytes) -> None:
    req = urllib.request.Request(
        _upload_url(), data=data, method="POST",
        headers={"X-RC-Token": TOKEN, "Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=3).read()


def loop() -> None:
    target = _upload_url()
    log.info("liveclient relay -> %s every %ss", target, INTERVAL)
    while True:
        t0 = time.time()
        try:
            payload = fetch_live()
            if payload is None:
                time.sleep(BACKOFF)
                continue
            upload(payload)
            log.debug("ok %dB in %dms", len(payload),
                      int((time.time() - t0) * 1000))
        except urllib.error.HTTPError as exc:
            # 401 here is the documented killer: a stale or missing token
            # means the relay cache stays empty and the coach never sees the
            # live game. It must be loud in the LOG, which is the only channel
            # that survives pythonw.
            log.error("upload failed: HTTP %s %s", exc.code, exc.reason)
        except Exception as exc:  # noqa: BLE001
            log.error("relay tick failed: %s", exc)
        sleep_for = max(0.1, INTERVAL - (time.time() - t0))
        time.sleep(sleep_for)


if __name__ == "__main__":
    if not TOKEN:
        # Exit non-zero so the scheduled task's Last Result is not a
        # reassuring 0 while the relay does nothing.
        log.error("no vision token: set RC_VISION_TOKEN or create %s",
                  _token_candidates()[0])
        sys.exit(2)
    try:
        loop()
    except KeyboardInterrupt:
        sys.exit(0)
