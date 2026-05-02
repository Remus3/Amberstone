"""
core/bridge.py — RC↔Peer cross-Claude bridge client + config readers.

Mirrors Peer's `core/bridge.py` per docs io RC peer/RC_BRIDGE_CONTRACT.md (v0).

Wire format (POST body to peer's /api/bridge/inbox):
    {source, summary, kind?, id?, target?, body?, in_reply_to?}

Auth: Authorization: Bearer <shared_secret>

Config lives in ops/local_paths.json (gitignored, per-host secrets):
    {"bridge_shared_secret": "...", "bridge_remote_url": "https://..."}

Empty/missing → bridge is OFF: send() returns (False, "bridge_not_configured")
and the inbox endpoint (in dashboard/routes_bridge.py) returns 503. Bridge
is opt-in; nothing happens until both sides set the secret.
"""
from __future__ import annotations

import json
import logging
import secrets
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

_log = logging.getLogger("rc.bridge")

# Project root: this file is at <root>/core/bridge.py
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOCAL_PATHS_FILE = _PROJECT_ROOT / "ops" / "local_paths.json"

# Module-scope cache so we don't re-read local_paths.json on every send().
# Refreshed by reload(). Mtime-based invalidation isn't worth the cost —
# operator restart picks up changes (the file changes infrequently).
_CONFIG: Optional[dict] = None


def _load_config() -> dict:
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG
    try:
        if _LOCAL_PATHS_FILE.exists():
            _CONFIG = json.loads(_LOCAL_PATHS_FILE.read_text(encoding="utf-8"))
        else:
            _CONFIG = {}
    except (OSError, ValueError) as exc:
        _log.warning("local_paths.json unreadable: %s — bridge disabled", exc)
        _CONFIG = {}
    return _CONFIG


def reload() -> None:
    """Force a re-read of local_paths.json. Call after operator edits."""
    global _CONFIG
    _CONFIG = None


def shared_secret() -> str:
    """Return the shared bearer token, or '' if unconfigured."""
    return str(_load_config().get("bridge_shared_secret") or "").strip()


def remote_url() -> str:
    """Return the peer's base URL (no trailing slash), or '' if unconfigured."""
    url = str(_load_config().get("bridge_remote_url") or "").strip()
    return url.rstrip("/")


def is_configured() -> bool:
    """True iff both shared_secret and remote_url are non-empty."""
    return bool(shared_secret() and remote_url())


def send(*, source: str,
         summary: str,
         kind: str = "note",
         entry_id: Optional[str] = None,
         target: Optional[str] = "peer",
         body: Optional[dict] = None,
         in_reply_to: Optional[str] = None,
         timeout_s: float = 4.0) -> Tuple[bool, str]:
    """POST a bridge message to the peer. Returns (ok, detail).

    Never raises — bridge failure is a normal state. Caller can log the
    detail string but should not treat failure as fatal.

    On success: (True, "ok").
    On config absent: (False, "bridge_not_configured").
    On network/HTTP error: (False, "<short reason>").
    """
    if not is_configured():
        return (False, "bridge_not_configured")

    # Auto-stamp id when caller doesn't supply one. Without an id, tasks
    # get filtered out by bridge_pull_tasks.py (`m.get("id")` gate), so
    # auto-execute on the peer never fires. Symmetric with Peer's planned
    # core/bridge.py fix per the 2026-05-02 e2e validate result.
    # Shape: <kind>-<12 hex chars> — short, collision-free, sortable enough
    # that operators can eyeball pairs in the log.
    if not entry_id:
        entry_id = f"{kind}-{secrets.token_hex(6)}"

    payload: dict = {
        "source":  source,
        "summary": summary,
        "kind":    kind,
        "id":      entry_id,
    }
    if target:      payload["target"]      = target
    if body is not None: payload["body"]   = body
    if in_reply_to: payload["in_reply_to"] = in_reply_to

    url = remote_url() + "/api/bridge/inbox"
    body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body_bytes,
        method="POST",
        headers={
            "Content-Type":  "application/json",
            "Authorization": "Bearer " + shared_secret(),
            "User-Agent":    "rc-bridge/0",
        },
    )

    # Self-signed certs are the norm for loopback/LAN dashboards. The
    # shared-secret bearer is the actual auth — TLS here is just transport
    # confidentiality, not identity. When real certs land (cross-host),
    # flip verify back on by passing context=ssl.create_default_context().
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, timeout=timeout_s, context=ctx) as r:
            status = r.status
            if status == 200:
                return (True, "ok")
            return (False, f"http_{status}")
    except urllib.error.HTTPError as exc:
        # Read short error body for context (capped — peer's error JSON is
        # tiny; don't need more than a few hundred bytes).
        try:
            err_body = exc.read(500).decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        return (False, f"http_{exc.code}: {err_body[:200]}")
    except urllib.error.URLError as exc:
        return (False, f"urlerror: {str(exc.reason)[:120]}")
    except (TimeoutError, OSError) as exc:
        return (False, f"network: {str(exc)[:120]}")


def status_summary() -> dict:
    """Read-only status block for the dashboard / health endpoints.
    Surfaces enough that the operator can tell at a glance whether the
    bridge is wired and pointed at the right place — without leaking
    the secret itself."""
    cfg = _load_config()
    secret = str(cfg.get("bridge_shared_secret") or "").strip()
    url    = str(cfg.get("bridge_remote_url") or "").strip()
    return {
        "configured":        bool(secret and url),
        "remote_url":        url,                          # OK to expose
        "secret_present":    bool(secret),
        "secret_len":        len(secret),
        "local_paths_file":  str(_LOCAL_PATHS_FILE),
        "local_paths_present": _LOCAL_PATHS_FILE.exists(),
        "ts": time.time(),
    }
