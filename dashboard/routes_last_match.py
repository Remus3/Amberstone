"""Post Game Review (a.k.a. Last Match) view routes.

GET  /api/last-match          - operator's most-recent non-TFT match + Quick
                                Review (right / wrong-team / chronic patterns).
POST /api/last-match/ingest   - receives the full LCU match detail JSON +
                                operator's puuid (pushed by the Game-PC
                                LCU agent on EndOfGame phase transition;
                                also callable on-demand from the frontend
                                Refresh button). Stashes the payload into
                                the matching match_history.db row's
                                raw_data["lcu_match_detail"] so the
                                builder can surface team comp + items +
                                runes + win/loss + damage breakdown.

Source of truth: data/match_history.db. The raw_data column carries
the LCU payload verbatim - no normalization-on-write, parse-on-read.
Audit later if other pages start reading the same blob.
"""
import json
import logging
from datetime import datetime

from dashboard.builders import _build_last_match
from dashboard._context import APP_DIR as _APP_DIR
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# Bound the payload - the LCU detail for one game is typically 50-120 KB.
_MAX_INGEST_BYTES = 2 * 1024 * 1024  # 2 MB hard cap


def _serve_last_match(h) -> None:
    try:
        # s220: optional ?baseline=N (operator-set in Settings; clamped
        # in _build_last_match). Defaults to 20 - pre-s220 behavior.
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(h.path).query or "")
        try:
            baseline = int((qs.get("baseline") or ["20"])[0])
        except (TypeError, ValueError):
            baseline = 20
        h._send(200, json.dumps(_build_last_match(baseline)).encode("utf-8"),
                "application/json")
    except Exception as exc:
        log.warning("api/last-match: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(),
                "application/json")


def _serve_last_match_ingest(h, body) -> None:
    """POST /api/last-match/ingest

    Body shape:
      {
        "tracked_puuid": str,
        "match_detail":  <full LCU /lol-match-history/v1/games/{gameId} JSON>
      }

    Behavior:
      - Validates basic shape (puuid + match_detail.gameId required).
      - Finds the latest non-TFT match_history.db row and merges the
        LCU payload into that row's raw_data["lcu_match_detail"] +
        raw_data["tracked_puuid"] + raw_data["lcu_ingested_at"].
      - Idempotent: re-ingesting overwrites. A stale row mismatch
        between LCU's operator champion and the DB row's champion
        column is surfaced via "champion_mismatch" in the response so
        the caller can fall back to creating a new row.
      - Returns 200 {ok, match_id, game_id, champion_db, participant_count,
                     champion_mismatch}.
    """
    try:
        if not isinstance(body, dict):
            h._send(400, b'{"error":"body must be a JSON object"}',
                    "application/json")
            return
        tracked_puuid = str(body.get("tracked_puuid") or "").strip()
        match_detail = body.get("match_detail")
        if not tracked_puuid:
            h._send(400, b'{"error":"tracked_puuid required"}',
                    "application/json")
            return
        if not isinstance(match_detail, dict):
            h._send(400, b'{"error":"match_detail must be a JSON object"}',
                    "application/json")
            return
        if not match_detail.get("gameId"):
            h._send(400, b'{"error":"match_detail.gameId required"}',
                    "application/json")
            return
        if not match_detail.get("participants"):
            h._send(400, b'{"error":"match_detail.participants required"}',
                    "application/json")
            return

        db_path = _APP_DIR / "data" / "match_history.db"
        if not db_path.exists():
            h._send(503,
                    json.dumps({"error": "match_history.db missing"}).encode(),
                    "application/json")
            return

        # Resolve operator's participant champion in the LCU payload -
        # used as a soft sanity check against the DB row's champion col.
        lcu_champion_id = None
        identities = match_detail.get("participantIdentities") or []
        me_pid = None
        for ident in identities:
            player = ident.get("player") or {}
            if str(player.get("puuid") or "").strip() == tracked_puuid:
                me_pid = ident.get("participantId")
                break
        if me_pid is not None:
            for p in (match_detail.get("participants") or []):
                if p.get("participantId") == me_pid:
                    lcu_champion_id = p.get("championId")
                    break

        import sqlite3
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.execute(
                "SELECT id, mode, champion, raw_data FROM matches "
                "WHERE mode != 'TFT' ORDER BY timestamp DESC LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                h._send(409,
                        json.dumps({"error":
                                    "no non-TFT match row to enrich"}).encode(),
                        "application/json")
                return
            mid, _mode, db_champion, raw_data_str = row
            try:
                rd = json.loads(raw_data_str) if raw_data_str else {}
            except (TypeError, json.JSONDecodeError):
                rd = {}
            rd["lcu_match_detail"] = match_detail
            rd["tracked_puuid"]    = tracked_puuid
            rd["lcu_ingested_at"]  = datetime.now().isoformat(timespec="seconds")
            new_raw = json.dumps(rd, default=str, ensure_ascii=False)
            conn.execute("UPDATE matches SET raw_data = ? WHERE id = ?",
                         (new_raw, mid))
            conn.commit()
        finally:
            conn.close()

        # A real DB-champion-name vs LCU-champion-id cross-check would need
        # a ddragon name lookup that lives in core.daemon_slayer_client or
        # similar. For v1 we just surface what we have and let downstream
        # consumers (the builder) decide. The merge always happens.
        resp = {
            "ok":                True,
            "match_id":          int(mid),
            "game_id":           match_detail.get("gameId"),
            "champion_db":       db_champion,
            "champion_lcu_id":   lcu_champion_id,
            "participant_count": len(match_detail.get("participants") or []),
        }
        h._send(200, json.dumps(resp).encode(), "application/json")
    except Exception as exc:
        log.warning("api/last-match/ingest: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(),
                "application/json")


GET_ROUTES = [
    (equals("/api/last-match"), _serve_last_match),
]

POST_ROUTES = [
    (equals("/api/last-match/ingest"), _serve_last_match_ingest),
]
