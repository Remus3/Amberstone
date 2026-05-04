"""Thin HTTP client for the local Daemon Slayer engine on :8893.

Phase 7 wire-in. Coach ticks need a non-blocking call into the engine
that fails silently when the server isn't up — the engine is opt-in
infrastructure, never load-bearing. Timeouts are tight (250 ms connect,
500 ms read) so a slow engine can't stall a coach loop.

Owners of name→id resolution: see ``core.daemon_slayer_resolver``. This
module operates purely on item IDs (string).
"""
from __future__ import annotations

import json
import logging
import socket
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

logger = logging.getLogger("rc.core.daemon_slayer_client")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8893
DEFAULT_TIMEOUT = 0.5  # seconds, applied to connect+read combined


@dataclass(frozen=True)
class RankedItem:
    item_id: str
    item_name: str
    delta_dps: float
    gold: int

    @classmethod
    def from_dict(cls, d: dict) -> "RankedItem":
        return cls(
            item_id=str(d.get("item_id", "")),
            item_name=str(d.get("item_name", "")),
            delta_dps=float(d.get("delta_dps", 0.0)),
            gold=int(d.get("gold", 0)),
        )


def _post_json(path: str, body: dict, timeout: float = DEFAULT_TIMEOUT) -> Optional[dict]:
    url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}{path}"
    try:
        req = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8"))
    except (URLError, HTTPError, socket.timeout, TimeoutError, ConnectionError) as e:
        logger.debug("daemon_slayer %s unreachable: %s", path, e)
        return None
    except Exception as e:  # noqa: BLE001
        logger.debug("daemon_slayer %s unexpected: %s", path, e)
        return None


def is_engine_up(timeout: float = 0.25) -> bool:
    url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/health"
    try:
        with urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def rank_for(
    champion: str,
    *,
    level: int,
    item_ids: Iterable[str],
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    top: int = 8,
    sort_by: str = "delta",
    augments: Optional[Iterable[str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[list[RankedItem]]:
    """Call POST /rank and return the parsed top-N rows. None on engine failure.

    Empty list (vs. None) means the engine responded but had no candidates
    — e.g. champion already has 6 mode-legal items. Callers should treat
    None and [] differently (engine down vs. nothing to recommend).

    ``augments`` is an optional list of Arena augment apiName strings (e.g.
    ``["TheBrutalizer", "ItsCritical"]``); engine applies registered stat
    overlays before computing DPS. Unknown apiNames are silently skipped
    server-side.
    """
    body = {
        "champion": champion,
        "level": int(level),
        "items": [str(i) for i in item_ids if i],
        "mode": mode,
        "target_armor": float(target_armor),
        "target_mr": float(target_mr),
        "top": int(top),
        "sort": sort_by,
    }
    if augments:
        body["augments"] = [str(a) for a in augments if a]
    data = _post_json("/rank", body, timeout=timeout)
    if data is None:
        return None
    ranked = data.get("ranked") or []
    return [RankedItem.from_dict(r) for r in ranked]


def dps_for(
    champion: str,
    *,
    level: int,
    item_ids: Iterable[str],
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    augments: Optional[Iterable[str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[dict]:
    """Call POST /dps and return the raw result dict. None on failure."""
    body = {
        "champion": champion,
        "level": int(level),
        "items": [str(i) for i in item_ids if i],
        "mode": mode,
        "target_armor": float(target_armor),
        "target_mr": float(target_mr),
    }
    if augments:
        body["augments"] = [str(a) for a in augments if a]
    return _post_json("/dps", body, timeout=timeout)
