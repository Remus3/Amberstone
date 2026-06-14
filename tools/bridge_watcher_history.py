"""bridge_watcher_history.py - past-task memory for the auto-action lane.

Stores every auto-action outcome (prompt + lane + status + cost + latency)
in a sqlite ledger. Two read paths the watcher uses:

  1. lookup_recent_match(prompt, lane) - exact-or-similar prompt seen recently?
     Returns the cached outcome so the watcher can short-circuit:
       - recent OK match  -> return cached body, $0 cost, 0ms latency
       - recent ERR match -> escalate (don't burn tokens repeating a failure)

  2. pattern_stats(pattern, since_ts) - success rate for one classifier pattern.
     Watcher emits this in heartbeat so operator can spot weak patterns to
     downgrade.

Inspired by ruvnet/ruflo's AgentDB trajectory pattern. MVP uses **token-jaccard
similarity** instead of dense embeddings (no extra deps, deterministic, fast at
RC's 10-50 tasks/day scale). The interface is shaped so a future swap to
HNSW + sentence-transformers requires only swapping the `_similarity()` function.

Storage: ops/runtime/bridge_action_history.db (sqlite, single-writer, WAL).
Schema is conservative: append-only, dedup by (task_id, lane); never UPDATEd
in place. Operator can `sqlite3 ... 'select * from outcomes order by ts desc limit 20'`
for ad-hoc spelunking.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

_log = logging.getLogger("rc.bridge_watcher.history")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outcomes (
    rowid           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL,
    ts              REAL NOT NULL,
    source          TEXT,
    lane            TEXT,
    pattern_matched TEXT,
    status          TEXT,
    cost_usd        REAL DEFAULT 0.0,
    latency_s       REAL DEFAULT 0.0,
    summary         TEXT,
    prompt          TEXT,
    body_keys       TEXT,
    error_brief     TEXT
);
CREATE INDEX IF NOT EXISTS idx_outcomes_ts      ON outcomes(ts);
CREATE INDEX IF NOT EXISTS idx_outcomes_pattern ON outcomes(pattern_matched);
CREATE INDEX IF NOT EXISTS idx_outcomes_lane_ts ON outcomes(lane, ts);
"""

_RECENT_S      = 6 * 3600  # 6h: a "recent" cached outcome
_SIMILARITY_HI = 0.85      # >= this = "same enough to short-circuit"
_SIMILARITY_LO = 0.65      # >= this = "similar enough to surface as related"


# -- Tokenization + similarity ------------------------------------------


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokens(text: str) -> set:
    if not text:
        return set()
    return {t.lower() for t in _TOKEN_RE.findall(text) if len(t) >= 3}


def _similarity(a: str, b: str) -> float:
    """Jaccard similarity over 3+-char alphanumeric tokens.

    Cheap, deterministic, no ML. For RC's 10-50 tasks/day this is plenty;
    swap for cosine over sentence-transformer embeddings if the volume ever
    grows past ~10K rows.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


# -- DB lifecycle --------------------------------------------------------


_CONN_CACHE: dict = {}


def _conn(db_path: Path) -> sqlite3.Connection:
    key = str(db_path)
    if key in _CONN_CACHE:
        return _CONN_CACHE[key]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(db_path), timeout=2.0, isolation_level=None,
                        check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.executescript(_SCHEMA)
    c.row_factory = sqlite3.Row
    _CONN_CACHE[key] = c
    return c


# -- Write path ----------------------------------------------------------


def record_outcome(*, db_path: Path, envelope: dict, lane: str,
                   pattern_matched: Optional[str],
                   status: str, cost_usd: float, latency_s: float,
                   summary: str, body: dict,
                   error_brief: Optional[str] = None) -> None:
    """Append one outcome row. Never raises (ledger writes are best-effort)."""
    try:
        prompt = ""
        bd = envelope.get("body") or {}
        if isinstance(bd, dict):
            prompt = str(bd.get("prompt") or "")
        body_keys = ""
        if isinstance(body, dict):
            body_keys = ",".join(sorted(k for k in body if not k.startswith("_")))[:240]
        c = _conn(db_path)
        c.execute(
            "INSERT INTO outcomes (task_id, ts, source, lane, pattern_matched, "
            "status, cost_usd, latency_s, summary, prompt, body_keys, error_brief) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(envelope.get("id") or "unknown"),
                float(envelope.get("ts") or time.time()),
                str(envelope.get("source") or "unknown"),
                lane,
                pattern_matched,
                status,
                float(cost_usd or 0.0),
                float(latency_s or 0.0),
                (summary or "")[:240],
                prompt[:8000],
                body_keys,
                (error_brief or "")[:500],
            ),
        )
    except (sqlite3.Error, OSError) as exc:
        _log.warning("history write failed (non-fatal): %s", exc)


# -- Read path: cached-result short-circuit -----------------------------


def lookup_recent_match(*, db_path: Path, prompt: str, lane: str,
                        recent_s: float = _RECENT_S) -> Optional[dict]:
    """Search for a recent outcome with similar prompt + same lane.

    Returns dict {match_type, similarity, rowid, status, summary, cost_usd,
    latency_s, hours_ago, original_task_id} OR None.

    `match_type` in {"exact_id", "high_sim", "moderate_sim", None}.
    Caller decides what to do per match_type:
      - exact_id  -> already processed this task; skip
      - high_sim  -> recent same-prompt success; return cached as auto-action OK,
                    or recent same-prompt failure; escalate without re-spawning
      - moderate_sim -> just surface as context; still spawn
    """
    if not prompt:
        return None
    try:
        c = _conn(db_path)
        cutoff = time.time() - recent_s
        rows = c.execute(
            "SELECT rowid, task_id, ts, status, summary, cost_usd, latency_s, prompt "
            "FROM outcomes WHERE lane = ? AND ts >= ? ORDER BY ts DESC LIMIT 200",
            (lane, cutoff),
        ).fetchall()
    except sqlite3.Error as exc:
        _log.warning("history lookup failed (non-fatal): %s", exc)
        return None

    best_sim = 0.0
    best_row = None
    for r in rows:
        sim = _similarity(prompt, r["prompt"] or "")
        if sim > best_sim:
            best_sim = sim
            best_row = r

    if best_row is None:
        return None

    if best_sim >= _SIMILARITY_HI:
        match_type = "high_sim"
    elif best_sim >= _SIMILARITY_LO:
        match_type = "moderate_sim"
    else:
        return None

    return {
        "match_type":         match_type,
        "similarity":         round(best_sim, 3),
        "rowid":              best_row["rowid"],
        "status":             best_row["status"],
        "summary":            best_row["summary"],
        "cost_usd":           best_row["cost_usd"],
        "latency_s":          best_row["latency_s"],
        "hours_ago":          round((time.time() - best_row["ts"]) / 3600, 2),
        "original_task_id":   best_row["task_id"],
    }


# -- Read path: per-pattern stats (for heartbeat / operator surface) ----


def pattern_stats(*, db_path: Path, since_ts: Optional[float] = None,
                  limit: int = 20) -> list:
    """Aggregate by pattern_matched for the time window. Returns a list of
    dicts sorted by attempts desc - caller can also re-sort by success_rate.
    """
    if since_ts is None:
        since_ts = time.time() - 7 * 86400  # 7d default
    try:
        c = _conn(db_path)
        rows = c.execute(
            "SELECT pattern_matched, "
            "  COUNT(*)                                           AS n, "
            "  SUM(CASE WHEN status='ok'       THEN 1 ELSE 0 END) AS ok, "
            "  SUM(CASE WHEN status='error'    THEN 1 ELSE 0 END) AS err, "
            "  SUM(CASE WHEN status='escalate' THEN 1 ELSE 0 END) AS esc, "
            "  AVG(cost_usd)                                      AS avg_cost, "
            "  AVG(latency_s)                                     AS avg_lat "
            "FROM outcomes WHERE ts >= ? AND pattern_matched IS NOT NULL "
            "GROUP BY pattern_matched ORDER BY n DESC LIMIT ?",
            (since_ts, limit),
        ).fetchall()
    except sqlite3.Error as exc:
        _log.warning("pattern_stats failed (non-fatal): %s", exc)
        return []
    out = []
    for r in rows:
        n = r["n"] or 0
        ok = r["ok"] or 0
        out.append({
            "pattern":      r["pattern_matched"],
            "attempts":     n,
            "ok":           ok,
            "err":          r["err"] or 0,
            "escalate":     r["esc"] or 0,
            "success_rate": round(ok / n, 3) if n else 0.0,
            "avg_cost_usd": round(r["avg_cost"] or 0.0, 4),
            "avg_latency_s":round(r["avg_lat"]  or 0.0, 1),
        })
    return out


def hot_failures(*, db_path: Path, since_ts: Optional[float] = None,
                 limit: int = 5) -> list:
    """Most recent failure summaries - operator-facing 'why are tasks erroring'."""
    if since_ts is None:
        since_ts = time.time() - 24 * 3600
    try:
        c = _conn(db_path)
        rows = c.execute(
            "SELECT task_id, ts, lane, pattern_matched, summary, error_brief, cost_usd "
            "FROM outcomes WHERE status='error' AND ts >= ? ORDER BY ts DESC LIMIT ?",
            (since_ts, limit),
        ).fetchall()
    except sqlite3.Error as exc:
        _log.warning("hot_failures failed (non-fatal): %s", exc)
        return []
    return [dict(r) for r in rows]


# -- Self-test ----------------------------------------------------------


def _test() -> None:
    import tempfile
    db = Path(tempfile.gettempdir()) / "bridge_watcher_history_test.db"
    if db.exists():
        db.unlink()

    cases = []
    fail = 0

    # Test similarity bounds
    cases.append(("identical strings sim=1.0",
                  abs(_similarity("hello world foo", "hello world foo") - 1.0) < 1e-6))
    cases.append(("disjoint strings sim=0",
                  _similarity("alpha beta gamma", "delta epsilon zeta") == 0.0))
    cases.append(("partial overlap 2/4 sim=0.5",
                  abs(_similarity("apple banana cherry date", "apple banana grape kiwi") - 0.333) < 0.01))
    cases.append(("empty -> 0", _similarity("", "anything") == 0.0))

    # Test record + retrieve
    env1 = {"id": "task-aaa", "ts": time.time() - 100,
            "source": "peer", "kind": "task",
            "body": {"prompt": "show me the state of the bridge_watcher_health.json file"}}
    record_outcome(db_path=db, envelope=env1, lane="auto-read",
                   pattern_matched="show .* state", status="ok",
                   cost_usd=0.01, latency_s=8.0, summary="returned 4 fields",
                   body={"pid": 123, "alive": True})

    # Lookup very similar
    hit = lookup_recent_match(db_path=db, lane="auto-read",
                              prompt="show me the state of the bridge_watcher_health.json file")
    cases.append(("identical-prompt lookup -> high_sim",
                  hit is not None and hit["match_type"] == "high_sim" and hit["similarity"] > 0.99))

    # Lookup similar-but-not-identical
    hit2 = lookup_recent_match(db_path=db, lane="auto-read",
                               prompt="show me the bridge_watcher_health.json file state currently")
    cases.append(("paraphrase lookup -> moderate or high sim",
                  hit2 is not None and hit2["match_type"] in ("moderate_sim", "high_sim")))

    # Lookup unrelated
    hit3 = lookup_recent_match(db_path=db, lane="auto-read",
                               prompt="something completely different about cats and dogs")
    cases.append(("unrelated-prompt lookup -> None", hit3 is None))

    # Lookup wrong lane
    hit4 = lookup_recent_match(db_path=db, lane="auto-ops",
                               prompt="show me the state of the bridge_watcher_health.json file")
    cases.append(("wrong-lane lookup -> None", hit4 is None))

    # Add a failure + record stats
    env2 = {"id": "task-bbb", "ts": time.time() - 50,
            "source": "peer", "body": {"prompt": "tail today's log"}}
    record_outcome(db_path=db, envelope=env2, lane="auto-read",
                   pattern_matched="tail .* log", status="error",
                   cost_usd=0.04, latency_s=12.0, summary="max-turns hit",
                   body={}, error_brief="Reached maximum number of turns (4)")

    stats = pattern_stats(db_path=db)
    cases.append(("pattern_stats has 2 rows", len(stats) == 2))
    show_state = next((s for s in stats if s["pattern"] == "show .* state"), None)
    cases.append(("show.*state stats: 1 attempt, 100% success",
                  show_state and show_state["attempts"] == 1 and show_state["success_rate"] == 1.0))

    fails_list = hot_failures(db_path=db)
    cases.append(("hot_failures returns the tail-log error",
                  len(fails_list) == 1 and "max-turns" in (fails_list[0]["summary"] or "")))

    for label, ok in cases:
        marker = "OK " if ok else "FAIL"
        print(f"  [{marker}] {label}")
        if not ok:
            fail += 1

    # Close pooled conns before unlink (WAL keeps file locked)
    for c in list(_CONN_CACHE.values()):
        try: c.close()
        except sqlite3.Error: pass
    _CONN_CACHE.clear()
    for ext in ("", "-wal", "-shm"):
        f = db.with_name(db.name + ext)
        if f.exists():
            try: f.unlink()
            except OSError: pass
    print(f"\n{len(cases) - fail}/{len(cases)} passed")
    raise SystemExit(0 if fail == 0 else 1)


if __name__ == "__main__":
    _test()
