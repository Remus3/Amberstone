"""Dev panel backend routes.

GET /api/dev/vision-status  — proxies to :8889 health + latest-frame/meta.

Module-level GET_ROUTES / POST_ROUTES consumed by dashboard._dispatch.
"""
import json
import logging
import time
import urllib.request as _ur

from dashboard._dispatch import equals

log = logging.getLogger("rc.dashboard.dev")

_VISION_BASE = "http://127.0.0.1:8889"


def _vision_token() -> str:
    from core.vision_token import get_vision_token
    return get_vision_token()


def _serve_vision_status(h) -> None:
    try:
        tok = _vision_token()

        health: dict = {}
        try:
            with _ur.urlopen(_VISION_BASE + "/health", timeout=2) as r:
                health = json.loads(r.read())
        except Exception as exc:
            health = {"error": str(exc)[:200]}

        meta: dict = {}
        try:
            req = _ur.Request(
                _VISION_BASE + "/latest-frame/meta",
                headers={"X-RC-Token": tok},
            )
            with _ur.urlopen(req, timeout=2) as r:
                meta = json.loads(r.read())
        except Exception as exc:
            meta = {"error": str(exc)[:200]}

        frame_age_s = None
        ts = meta.get("ts")
        if isinstance(ts, (int, float)) and ts > 0:
            frame_age_s = round(time.time() - ts, 1)

        result = {
            "vision_health": health,
            "latest_frame": meta,
            "frame_age_s": frame_age_s,
            "now": time.time(),
        }
        h._send(200, json.dumps(result).encode(), "application/json")
    except Exception as exc:
        log.warning("api/dev/vision-status: %s", exc)
        h._send(500, json.dumps({"error": str(exc)[:200]}).encode(),
                "application/json")


GET_ROUTES = [
    (equals("/api/dev/vision-status"), _serve_vision_status),
]

POST_ROUTES: list = []
