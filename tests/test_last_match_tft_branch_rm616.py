"""Post Game Review after a TFT match shows THAT match (s134 QA defect D4).

MEASURED (QA_REPORT.md section 1 D4, dash_0054_el2059.jpg): after a TFT 1st
place the Post Game Review showed "ARAM - 83d ago" - `_build_last_match`
(dashboard/builders_last_match.py) selected the newest row `WHERE mode !=
'TFT'` while the view still auto-flipped to POST GAME REVIEW at game end.

FIX CONTRACT pinned here:
  - the live path (no match_ts) compares the newest TFT game in the RM-616
    store (tft/tft_placement.py, data/tft_matches/) with the newest non-TFT
    match_history.db row and serves whichever ENDED later;
  - a TFT payload carries kind "tft", the placement, the final board, the
    traits and the augments (with an honest "not recorded" flag - the client
    records none), and an empty HP curve flagged unrecorded;
  - the historical path (match_ts) is unchanged and never serves TFT;
  - match_history.db TFT rating rows (estimated placement) stay excluded;
  - the /api/last-match response cache keys on the store, so a TFT record
    landing after the game-end fetch is served by the 10 s retry
    (web/js/main.js post-game arm) instead of a cached stale match.
  - web/js/panels/last_match.js renders the TFT branch into #lm-tft and
    hides the LoL body (grep contract; no jsdom harness for page code).

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from tft import tft_placement as tp

REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "tests" / "fixtures"
EOG_DOC = json.loads((FIX / "tft_eog_stats_set18.json").read_text(encoding="utf-8"))
HIST_DOC = json.loads((FIX / "tft_match_history_set18.json").read_text(encoding="utf-8"))
LOCAL_PUUID = "11111111-1111-1111-1111-111111111111"
# hist fixture :10 game_datetime 1700002099924 ms -> this local wall clock.
TFT_END = tp._stamp(1700002099.924)


def _make_db(path: Path, rows) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE matches ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  timestamp TEXT, mode TEXT, champion TEXT, grade TEXT,"
        "  kda_str TEXT, game_time_s INTEGER, game_id INTEGER DEFAULT 0,"
        "  kills INTEGER, deaths INTEGER, assists INTEGER,"
        "  cs INTEGER, cs_per_min REAL, gold INTEGER, gold_per_min REAL,"
        "  kp_pct REAL, label TEXT, raw_data TEXT, tft_placement INTEGER DEFAULT 0)")
    for ts, mode, champ in rows:
        conn.execute(
            "INSERT INTO matches (timestamp, mode, champion, grade, kda_str,"
            " game_time_s, kills, deaths, assists, cs, cs_per_min, gold,"
            " gold_per_min, kp_pct, label, raw_data, tft_placement)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, mode, champ, "D", "13/13/15", 1500, 13, 13, 15, 40, 1.6,
             11000, 440, 50, "", "", 3 if mode == "TFT" else 0))
    conn.commit()
    conn.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    import dashboard.builders_last_match as blm
    from dashboard import _context
    app = tmp_path / "app"
    (app / "data").mkdir(parents=True)
    store = tmp_path / "tft_matches"
    monkeypatch.setattr(blm, "_APP_DIR", app)
    monkeypatch.setattr(tp, "_STORE_DIR", store)
    yield app, store
    cached = getattr(_context.DB_CONN_LOCAL, "conns", {}).pop(
        str(app / "data" / "match_history.db"), None)
    if cached is not None:
        cached.close()


def _store_game(store, *, with_history=True):
    tp.persist(tp.parse_eog(EOG_DOC, now=1700002110.0), store_dir=store)
    if with_history:
        tp.persist(tp.parse_history(HIST_DOC, LOCAL_PUUID)[0], store_dir=store)


def _build(**kw):
    import dashboard.builders_last_match as blm
    return blm._build_last_match(**kw)


def test_a_newer_tft_game_beats_an_older_aram_row(env):
    app, store = env
    _make_db(app / "data" / "match_history.db",
             [("2023-08-03 12:00:00", "ARAM", "Caitlyn")])
    _store_game(store)
    out = _build()
    assert out["found"] is True and out["kind"] == "tft"
    m = out["match"]
    assert m["mode"] == "TFT"
    assert m["game_id"] == 1000000001
    assert m["timestamp"] == TFT_END
    assert m["placement"] == 1 and m["lobby_size"] == 8
    assert m["hp_final"] == 100
    assert (m["level"], m["gold_left"], m["last_round"]) == (9, 32, 33)
    assert m["set_core_name"] == "TFTSet18" and m["queue_id"] == 1090
    assert m["duration_s"] == 2097
    assert [u["name"] for u in m["board"]][:2] == ["Draven", "Taric"]
    assert m["board"][0]["items"][0]["name"] == "Thief's Gloves"
    active = {t["name"] for t in m["traits"] if t["active"]}
    assert "Flora Fatalis" in active and "Defender" not in active
    assert m["augments"] == [] and m["augments_recorded"] is False
    assert m["hp_curve"] == [] and m["hp_curve_recorded"] is False
    assert [p["placement"] for p in m["lobby"]] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert m["lobby"][0]["is_local"] is True
    assert out["history_count"] == 0
    assert set(out["quick_review"]) == {"right", "wrong_team", "my_chronic"}
    blob = json.dumps(out)
    assert "player1" not in blob and "TAG" not in blob


def test_a_newer_aram_row_beats_an_older_tft_game(env):
    app, store = env
    _make_db(app / "data" / "match_history.db",
             [("2099-01-01 00:00:00", "ARAM", "Caitlyn")])
    _store_game(store)
    out = _build()
    assert out.get("kind") != "tft"
    assert out["match"]["champion"] == "Caitlyn"


def test_eog_only_record_is_served_with_capture_time(env):
    app, store = env
    _make_db(app / "data" / "match_history.db",
             [("2023-08-03 12:00:00", "ARAM", "Caitlyn")])
    _store_game(store, with_history=False)
    out = _build()
    assert out["kind"] == "tft"
    assert out["match"]["timestamp"] == tp._stamp(1700002110.0)
    assert out["match"]["level"] is None
    assert all(t["active"] is None for t in out["match"]["traits"])


def test_tft_is_served_when_match_history_db_is_missing(env):
    _app, store = env
    _store_game(store)
    out = _build()
    assert out["found"] is True and out["kind"] == "tft"
    assert "error" not in out


def test_no_tft_store_keeps_the_pre_rm616_path(env):
    app, _store = env
    _make_db(app / "data" / "match_history.db",
             [("2023-08-03 12:00:00", "ARAM", "Caitlyn")])
    out = _build()
    assert out["match"]["champion"] == "Caitlyn" and "kind" not in out


def test_match_history_tft_rating_rows_stay_excluded(env):
    """Estimated-placement rating rows never drive the PGR (only the store)."""
    app, _store = env
    _make_db(app / "data" / "match_history.db",
             [("2023-08-03 12:00:00", "ARAM", "Caitlyn"),
              ("2099-01-01 00:00:00", "TFT", "Comp")])
    out = _build()
    assert out["match"]["champion"] == "Caitlyn"


def test_historical_match_ts_path_never_serves_tft(env):
    app, store = env
    _make_db(app / "data" / "match_history.db",
             [("2023-08-03 12:00:00", "ARAM", "Caitlyn")])
    _store_game(store)
    out = _build(match_ts="2023-08-03 12:00:00")
    assert out["match"]["champion"] == "Caitlyn" and "kind" not in out
    assert _build(match_ts=TFT_END)["found"] is False


def test_a_broken_store_degrades_to_the_lol_path(env, monkeypatch):
    app, _store = env
    _make_db(app / "data" / "match_history.db",
             [("2023-08-03 12:00:00", "ARAM", "Caitlyn")])

    def boom(*a, **k):
        raise OSError("disk gone")
    monkeypatch.setattr(tp, "latest", boom)
    out = _build()
    assert out["match"]["champion"] == "Caitlyn"


# -- the response cache keys on the store ----------------------------------------

class _H:
    def __init__(self):
        self.path = "/api/last-match"
        self.body = None

    def _send(self, status, body, ct):
        self.body = json.loads(body)


def test_route_cache_serves_a_tft_record_that_lands_after_the_first_fetch(env):
    import dashboard.routes_last_match as rlm
    app, store = env
    _make_db(app / "data" / "match_history.db",
             [("2023-08-03 12:00:00", "ARAM", "Caitlyn")])
    rlm._cache_clear()
    try:
        h1 = _H()
        rlm._serve_last_match(h1)
        assert h1.body["match"]["champion"] == "Caitlyn"
        _store_game(store)
        h2 = _H()
        rlm._serve_last_match(h2)
        assert h2.body.get("kind") == "tft", "a cached stale match was served"
        h3 = _H()
        rlm._serve_last_match(h3)
        assert h3.body == h2.body
    finally:
        rlm._cache_clear()


# -- front-end grep contract ---------------------------------------------------

def _js() -> str:
    return (REPO / "web" / "js" / "panels" / "last_match.js").read_text(encoding="utf-8")


def _html() -> str:
    return (REPO / "web" / "index.html").read_text(encoding="utf-8")


def test_frontend_has_a_tft_branch_before_the_lol_renderers():
    js = _js()
    i = js.find("function renderLastMatch(data) {")
    assert i != -1
    body = js[i:js.find("\n}\n", i)]
    tft = body.find('data.kind === "tft"')
    hero = body.find("_setHero(m, enriched)")
    assert tft != -1 and hero != -1 and tft < hero
    assert "_renderTftLastMatch(data)" in body
    assert "function _renderTftLastMatch(data)" in js
    j = js.find("function _renderTftLastMatch(data)")
    seg = js[j:js.find("\n}\n", j)]
    assert "innerHTML" in seg


def _templates(src: str):
    """Every backtick template in `src` (nested ones included) as
    (literal_text, [interpolation expressions]). A small scanner that skips
    quoted strings and matches ${ } braces - enough for this one function."""
    out = []

    def skip_quote(s, i):
        q = s[i]
        i += 1
        while i < len(s) and s[i] != q:
            i += 2 if s[i] == "\\" else 1
        return i + 1

    def template(s, i):              # s[i] == "`"
        i += 1
        lit, exprs = [], []
        while i < len(s) and s[i] != "`":
            if s[i] == "\\":
                lit.append(s[i:i + 2])
                i += 2
            elif s.startswith("${", i):
                i += 2
                start, depth = i, 1
                while depth:
                    ch = s[i]
                    if ch in "'\"":
                        i = skip_quote(s, i)
                        continue
                    if ch == "`":
                        i = template(s, i)
                        continue
                    depth += {"{": 1, "}": -1}.get(ch, 0)
                    i += 1
                exprs.append(s[start:i - 1].strip())
            else:
                lit.append(s[i])
                i += 1
        out.append(("".join(lit), exprs))
        return i + 1

    i = 0
    while i < len(src):
        if src[i] in "'\"":
            i = skip_quote(src, i)
        elif src[i] == "`":
            i = template(src, i)
        elif src.startswith("//", i):
            i = src.find("\n", i) + 1 or len(src)
        else:
            i += 1
    return out


_SAFE_EXPR = (
    re.compile(r"^_escHtml\("),                          # escaped value
    re.compile(r"^\w+(Html|Rows)$"),                      # composed, itself checked
    re.compile(r"^\w+(Html|Rows) \|\| '[^'<>]*(<[^'$]*)?'$"),   # composed or literal
    re.compile(r"^[\w.]+ \? \"[^\"]*\" : \"[^\"]*\"$"),   # literal ternary
    re.compile(r"^act$"),                                 # "1" / "0" / "" only
    re.compile(r"^\w+\.map\("),                           # its own templates checked
)


def test_frontend_tft_markup_escapes_every_interpolated_value():
    """Every ${...} inside an HTML-bearing template of _renderTftLastMatch is
    escaped, a composed HTML fragment (itself checked here), or a constant."""
    js = _js()
    j = js.find("function _renderTftLastMatch(data)")
    seg = js[j:js.find("\n}\n", j)]
    html_templates = [(lit, ex) for lit, ex in _templates(seg) if "<" in lit]
    assert len(html_templates) >= 6, "scanner found too few markup templates"
    bad = [e for _lit, exprs in html_templates for e in exprs
           if not any(p.match(e) for p in _SAFE_EXPR)]
    assert bad == [], bad
    # The positive control: an unescaped value is caught.
    probe = _templates("x = `<li>${u.name}</li>`;")
    assert [e for _l, ex in probe for e in ex
            if not any(p.match(e) for p in _SAFE_EXPR)] == ["u.name"]


def test_frontend_tft_mount_lives_in_the_pgr_section():
    html = _html()
    sec = html.find('<section id="view-last-match"')
    end = html.find("</section>", sec)
    seg = html[sec:end]
    assert 'id="lm-tft"' in seg and 'id="lm-body"' in seg
    assert seg.find('id="lm-tft"') < seg.find('id="lm-body"')
    tag = seg[seg.find('id="lm-tft"') - 60: seg.find('id="lm-tft"') + 80]
    assert "hidden" in tag


def test_frontend_empty_and_lol_paths_hide_the_tft_mount():
    js = _js()
    for fn in ("function _setEmptyState(errMsg) {", "function renderLastMatch(data) {"):
        i = js.find(fn)
        seg = js[i:js.find("\n}\n", i)]
        assert "_showTftMount(false)" in seg, fn
