"""Coach / replay / cost routes.

Slice 2C-5 (2026-05-01): handlers carved out of web_dashboard._Handler.
Group 5 — read-only, self-contained endpoints. All consumers live in
core.* / coaches.* — no `_VISION_TOKEN`, no Live Client probes, no
imports from web_dashboard, so no deferred-import circular guard
needed (compare with routes_diag).

Each handler receives the BaseHTTPRequestHandler (`h`) and writes its
response via `h._send(code, body, ctype)`. Module-level GET_ROUTES is
consumed by `dashboard._dispatch`.
"""
import json
import logging
import time
from urllib.parse import parse_qs, urlparse

from dashboard._context import APP_DIR, read_json
from dashboard._dispatch import equals, prefix

log = logging.getLogger("rc.web_dashboard")


def _serve_cost(h) -> None:
    # Daily spend ledger from core.cost_tracker. Tile data source.
    try:
        from core.cost_tracker import get_tracker as _gt
        t = _gt()
        payload = {
            "spend":  t.daily_spend(),
            "banner": t.banner_state(),
            "allowed": t.allow_call(),
        }
        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:
        log.warning("api/cost: %s", exc)
        h._send(500, json.dumps({"error": str(exc)[:200]}).encode(),
                "application/json")


def _serve_coach_trace(h) -> None:
    # Most recent coach calls (prompt + response + tokens). Used by
    # the "why did the coach say that?" dashboard tab.
    try:
        qs = parse_qs(urlparse(h.path).query)
        limit = int((qs.get("limit") or ["50"])[0])
        limit = max(1, min(limit, 200))
        from core.coach_trace import read_recent as _read_recent
        h._send(200, json.dumps({"records": _read_recent(limit)}).encode("utf-8"),
                "application/json")
    except Exception as exc:
        log.warning("api/coach/trace: %s", exc)
        h._send(500, json.dumps({"error": str(exc)[:200]}).encode(),
                "application/json")


def _serve_replay_matches(h) -> None:
    # AUDIT 2026-04-28 (suggestion 2.3): replay scrubber match list.
    try:
        qs = parse_qs(urlparse(h.path).query)
        limit = int((qs.get("limit") or ["25"])[0])
        limit = max(1, min(limit, 200))
        queue = (qs.get("queue") or [""])[0]
        from core.replay_history import list_matches as _lm
        out = _lm(limit=limit, queue_filter=int(queue) if queue.isdigit() else None)
        h._send(200, json.dumps({"matches": out}).encode("utf-8"),
                "application/json")
    except Exception as exc:
        log.warning("api/replay/matches: %s", exc)
        h._send(500, json.dumps({"error": str(exc)[:200]}).encode(),
                "application/json")


def _serve_replay_match(h) -> None:
    # /api/replay/match/<match_id>
    try:
        mid = h.path[len("/api/replay/match/"):].split("?", 1)[0]
        # match_id format: "NA1_5438342899" — alnum + underscore only.
        import re as _re
        if not _re.match(r"^[A-Z0-9_]{6,40}$", mid):
            h._send(400, b'{"error":"bad match_id"}', "application/json")
            return
        from core.replay_history import match_detail as _md
        d = _md(mid)
        if d is None:
            h._send(404, json.dumps({"error": "not found"}).encode(),
                    "application/json")
            return
        h._send(200, json.dumps(d).encode("utf-8"), "application/json")
    except Exception as exc:
        log.warning("api/replay/match: %s", exc)
        h._send(500, json.dumps({"error": str(exc)[:200]}).encode(),
                "application/json")


def _serve_recommend_champ(h) -> None:
    # AUDIT 2026-04-28 (suggestion 2.6): champ-pool recommender.
    # Query: ?pool=Vayne,Jinx,Tristana&enemy=Malphite,Vi,Akali,Lulu,Thresh&min_games=3
    try:
        qs = parse_qs(urlparse(h.path).query)
        pool = [c.strip() for c in (qs.get("pool") or [""])[0].split(",") if c.strip()]
        enemy = [c.strip() for c in (qs.get("enemy") or [""])[0].split(",") if c.strip()]
        min_games = int((qs.get("min_games") or ["3"])[0])
        min_games = max(1, min(min_games, 50))
        if not pool:
            h._send(400, b'{"error":"pool required"}', "application/json")
            return
        from coaches.champ_pool_recommender import recommend as _rec
        t0 = time.time()
        out = _rec(pool, enemy, min_games=min_games)
        h._send(200, json.dumps({
            "recommendations": out,
            "query": {"pool": pool, "enemy": enemy, "min_games": min_games},
            "elapsed_ms": int((time.time() - t0) * 1000),
        }).encode("utf-8"), "application/json")
    except Exception as exc:
        log.warning("api/recommend-champ: %s", exc)
        h._send(500, json.dumps({"error": str(exc)[:200]}).encode(),
                "application/json")


def _serve_coach_state(h) -> None:
    # Per-mode coach kill-switch state. GET only; toggle via POST.
    try:
        from core.cost_tracker import _COACH_CFG, CFG_COACH_DISABLED_MODES
        cfg = read_json(str(_COACH_CFG)) if _COACH_CFG.exists() else {}
        disabled = cfg.get(CFG_COACH_DISABLED_MODES, []) or []
        modes = ["sr", "aram", "arena", "brawl", "tft"]
        state = {m: (m not in {x.lower() for x in disabled}) for m in modes}
        h._send(200, json.dumps({"enabled": state, "disabled": disabled}).encode(),
                "application/json")
    except Exception as exc:
        log.warning("api/coach/state: %s", exc)
        h._send(500, json.dumps({"error": str(exc)[:200]}).encode(),
                "application/json")


def _serve_logs(h) -> None:
    # Tail today's log. Optional ?n=200 (max 1000) and ?q=substring.
    try:
        qs = parse_qs(urlparse(h.path).query)
        n = int((qs.get("n") or ["200"])[0])
        n = max(1, min(n, 1000))
        q = (qs.get("q") or [""])[0]
        day = time.strftime("%Y-%m-%d")
        p = APP_DIR / "logs" / f"{day}.log"
        if not p.exists():
            h._send(200, json.dumps({"day": day, "lines": [],
                                      "missing": True}).encode("utf-8"),
                    "application/json")
            return
        # Stream tail without loading the whole file. Cap at 4 MiB
        # read window, and walk from the end.
        with p.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            cap = min(size, 1 << 22)
            f.seek(size - cap)
            chunk = f.read(cap)
        text = chunk.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if q:
            lines = [l for l in lines if q in l]
        tail = lines[-n:]
        h._send(200, json.dumps({"day": day, "lines": tail,
                                  "total_lines_in_window": len(lines)}).encode("utf-8"),
                "application/json")
    except Exception as exc:
        log.warning("api/logs: %s", exc)
        h._send(500, json.dumps({"error": str(exc)[:200]}).encode(),
                "application/json")


# ── route table ──────────────────────────────────────────────────────

# Ordering: more-specific paths first. /api/replay/match/ uses prefix()
# for the trailing match_id; everything else is exact (with optional
# query string handled by equals()).
GET_ROUTES = [
    (equals("/api/cost"),             _serve_cost),
    (equals("/api/coach/trace"),      _serve_coach_trace),
    (equals("/api/coach/state"),      _serve_coach_state),
    (equals("/api/replay/matches"),   _serve_replay_matches),
    (prefix("/api/replay/match/"),    _serve_replay_match),
    (equals("/api/recommend-champ"),  _serve_recommend_champ),
    (equals("/api/logs"),             _serve_logs),
]

POST_ROUTES: list = []
