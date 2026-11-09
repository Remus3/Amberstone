"""s156 S3: the draft routes that serve hand-curated meta report its age.

/api/champ-select/ban-suggestions (global_top_bans.json), and
/api/champ-select/counter-picks + /api/champ-select/pickban-recs
(champion_counters.json) each gain an additive ``freshness`` /
``counters_freshness`` object from core.draft_meta_freshness, so the UI or a
coach can say "counters from 16.10.1, 12 patches old" instead of presenting
them as current.
"""
from __future__ import annotations

import json

from dashboard import routes_ban_suggestions as rbsu
from dashboard import routes_pickban as rpb

_KEYS = {"source_patch", "source_updated", "current_patch", "patches_behind",
         "age_days", "stale"}


class _H:
    def __init__(self, path: str):
        self.path = path
        self.headers = {}
        self.client_address = ("127.0.0.1", 0)
        self.responses: list = []

    def _send(self, code, body, ctype="application/json"):
        self.responses.append((code, body, ctype))

    @property
    def doc(self) -> dict:
        return json.loads(self.responses[-1][1].decode("utf-8"))


def _write(tmp_path, name, doc):
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="ascii")
    return p


def test_ban_suggestions_reports_freshness(tmp_path, monkeypatch):
    monkeypatch.setattr(rbsu, "_BANS_PATH", _write(
        tmp_path, "bans.json",
        {"patch": "16.10.1", "updated": "2026-05-15", "top_bans": []}))
    h = _H("/api/champ-select/ban-suggestions?top=4")
    rbsu._serve_ban_suggestions(h)
    doc = h.doc
    assert doc["ok"] is True
    assert set(doc["freshness"]) == _KEYS
    assert doc["freshness"]["source_patch"] == "16.10.1"
    assert doc["freshness"]["stale"] is True
    # legacy field unchanged
    assert doc["patch"] == "16.10.1"


def test_ban_suggestions_freshness_on_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(rbsu, "_BANS_PATH", tmp_path / "absent.json")
    h = _H("/api/champ-select/ban-suggestions")
    rbsu._serve_ban_suggestions(h)
    assert h.doc["freshness"]["source_patch"] is None
    assert h.doc["freshness"]["stale"] is True


def test_counter_picks_reports_counters_freshness(tmp_path, monkeypatch):
    monkeypatch.setattr(rpb, "_COUNTERS_PATH", _write(
        tmp_path, "counters.json",
        {"patch": "16.10.1", "updated": "2026-05-15", "counters": {}}))
    monkeypatch.setattr(rpb, "_COUNTERS_INDEX", None)
    h = _H("/api/champ-select/counter-picks?enemies=")
    rpb._serve_counter_picks(h)
    doc = h.doc
    assert doc["ok"] is True
    assert set(doc["freshness"]) == _KEYS
    assert doc["freshness"]["source_patch"] == "16.10.1"


def test_pickban_recs_reports_counters_freshness(tmp_path, monkeypatch):
    monkeypatch.setattr(rpb, "_COUNTERS_PATH", _write(
        tmp_path, "counters.json",
        {"patch": "16.10.1", "updated": "2026-05-15", "counters": {}}))
    db = tmp_path / "rewind_history.db"
    db.write_bytes(b"")
    monkeypatch.setattr(rpb, "_REWIND_DB", db)
    monkeypatch.setattr(rpb, "_cache_get", lambda *a, **k: False)
    monkeypatch.setattr(rpb, "_cache_put", lambda *a, **k: None)

    class _Conn:
        def close(self):
            pass

    monkeypatch.setattr(rpb, "_open_ro_with_puuid", lambda h: (_Conn(), "p"))
    monkeypatch.setattr(rpb, "_build_pickban_recs",
                        lambda *a, **k: ([], [], None, None))
    h = _H("/api/champ-select/pickban-recs?role=TOP")
    rpb._serve_pickban_recs(h)
    doc = h.doc
    assert doc["ok"] is True, doc
    assert set(doc["counters_freshness"]) == _KEYS
    assert doc["counters_freshness"]["source_patch"] == "16.10.1"
