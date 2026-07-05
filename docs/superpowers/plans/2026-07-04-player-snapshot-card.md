# Player Snapshot Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a reuse-first Hextech player-snapshot card (rating dial + 4 bars + 3 tags + KDA/WR/K-P minis + rank/streak header + View-Profile radar) mounted on the rc-shell companion in two contexts: Home (GPI 24h self-relative, per mode tab) and PGR (role-rubric, this match), absorbing the overlapping Home + PGR panels.

**Architecture:** One presentational `renderPlayerSnapshot(el, model)` fed by two per-context adapters. Home adapter fetches a new DB-pure `/api/player-snapshot` route; PGR adapter composes the model client-side from the last-match + post-game-rubric payloads already in hand. Backend work extends `core/player_gpi.py` (time window, win/streak/K-P, strongest-axis) plus the thin new route. All backend derivation is from the local `rewind_history.db` (no Riot API, no Claude).

**Tech Stack:** Python 3.14 stdlib (sqlite3, http.server-style route handlers), vanilla ESM JS panels, CSS custom properties (`web/css/tokens.css`). Tests: `pytest` (backend + DOM-string), Playwright snapshot panels (`tests/snapshot_panels/`).

**Host (TASK 1 resolved):** The rc-shell COMPANION window ([rc-shell/src/main.js:509](rc-shell/src/main.js:509) `mainWindow.loadURL(cfg.origin)`, default `https://legion-rc:8888`) renders the shared `web/` dashboard tree inside a frameless Electron window. Mounting "on the companion" == building in `web/index.html` + `web/js/main.js` + `web/js/panels/*` + `web/css/*`. v1 needs ZERO `rc-shell/src` edits - the card auto-appears in the companion because the companion loads the dashboard. ADR-008 asset-hash auto-reload applies to `web/{js,css}/panels/*` (no RC restart for asset-only). The rc-shell OVERLAY surface (`?overlay=1`, `.ovx-widget`, `overlay_layout.js`) is v2 and out of scope.

## Global Constraints

- **ASCII only.** No em-dashes / en-dashes / smart quotes anywhere (code, comments, docstrings, commit messages). Use ` - ` for clause breaks. Enforced by `tools/precommit_gate.py`.
- **TDD-first.** Write the failing test, run it red, implement minimally, run it green, commit. Non-negotiable (CLAUDE.md TDD First).
- **Tier scope = Tier-1/2** (core module + web routes + web panels; NOT an engine / ENGINE_VERSION / DS item-effect change). Run the relevant module tests + `tests/` web/route/DOM tests. Do NOT run the full DS dual-suite or bump ENGINE_VERSION. No DS `:8893` restart, no Share mirror.
- **Never surface raw API/error strings** in any panel. Catch, render a friendly degraded state, log the raw error to `logs/` (CLAUDE.md Error Handling).
- **No reflow on data absence.** Reserve the slot, render a `-` sentinel, never shift sibling panels (memory `feedback_no_reflow_on_data_absence`).
- **Provenance tags.** Every mini/bar carries `provenance: "source_truth" | "inferred"`. K-P is `inferred`; everything else `source_truth` (memory `feedback_metric_provenance_tagging`).
- **Idempotent renderers.** Stash a payload signature on the mount element, skip the rebuild when unchanged (pattern at [duration_winrate.js:28](web/js/panels/duration_winrate.js:28); memory `feedback_dashboard_render_idempotency`).
- **`py_compile` before any restart.** Syntax errors crash silently under `pythonw.exe`.
- **UI fixture ritual BEFORE commit** (Task 9), not after. Every MUST-FIX resolved in the same slice.
- **Frozen files:** none of the touched files are frozen (verified: `player_gpi.py`, the new route, `_dispatch.py`, `player_snapshot.js`, `index.html`, `main.js`, `last_match.js` are all off the CLAUDE.md frozen list). Do not touch any frozen file.
- **Subject = SELF only in v1.** Data contract stays opponent-ready but no opponent fetch (ADR-006 rate wall).

## Contract: the normalized model (spec 4.2)

Every adapter produces, and `renderPlayerSnapshot` consumes, this exact shape:

```
PlayerSnapshotModel = {
  header: {
    name: str|null, rank_tier: str|null, rank_lp: int|null, level: int|null,
    streak: { kind: "win"|"loss", n: int }|null,
    champion_id: int|null,          // most-played (Home) or played (PGR)
    result: "win"|"loss"|null       // PGR only; null on Home
  },
  dial:  { value: number(0..100), band: "good"|"ok"|"poor", label: str },
  minis: [ { key: "kda"|"winrate"|"kp", value: str, provenance: "source_truth"|"inferred" } ],
  bars:  [ { key: "income"|"combat"|"objectives"|"vision", label: str, score: number(0..100),
             provenance: "source_truth"|"inferred" } ],
  tags:  [ { label: str, tone: "strong"|"neutral"|"weak" } ],   // exactly 3
  profile_ref: { mode: str, window: str|null, match_id: str|null },
  confidence: "high"|"low"|"insufficient",
  sample_n: int,
  empty: bool                       // true -> reserved slot + "-" sentinel, no reflow
}
```

## Dial bands (spec 4.5, verified against [post_game_rubric.py:390](core/post_game_rubric.py:390))

Reuse the SHIPPED grade cutoffs. `value` is 0..100 on both contexts:
- `good` when `value >= 65` (A / S / S+)
- `ok`   when `35 <= value < 65` (B / C)
- `poor` when `value < 35` (D)

## Tag vocabulary (spec 4.6) - axis -> (high word, low word)

```
aggression  -> ("Aggressive",       "Passive")
farming     -> ("Strong Farmer",    "Weak Farm")
vision      -> ("Vision Control",   "Visionless")
objectives  -> ("Objective Focused","Objective Shy")
survival    -> ("Survivor",         "Gank Prone")
tempo       -> ("Snowballer",       "Slow Starter")
versatility -> ("Generalist",       "One-Trick")     # shape: NEUTRAL slot only
consistency -> ("Consistent",       "Streaky")       # shape: NEUTRAL slot only
```
Selection: GREEN/strong = high word of the strongest of the 6 relative axes; RED/weak = low word of the weakest of the 6 relative axes; YELLOW/neutral = the more pronounced shape axis (versatility else consistency), always a descriptor, never a weakness. Tone -> color: strong=`--signal-good`, neutral=`--signal-warn`, weak=`--signal-bad`.

---

## File Structure

**Backend (create):**
- `dashboard/routes_player_snapshot.py` - the `/api/player-snapshot` GET route + the `_derive_snapshot_tags` + `_build_snapshot_model` helpers. One responsibility: assemble the DB-pure Home model.
- `tests/test_player_gpi_window.py` - time-window filter + win/streak/K-P + strongest-axis unit tests.
- `tests/test_routes_player_snapshot.py` - route contract / empty / degraded tests.

**Backend (modify):**
- `core/player_gpi.py` - add `since_ts=` recent-set filter, `p.win` + team-kills to the SELECT, `win_streak` / `win_rate` / `kp_pct` / `strongest_axis` / `window_n` to the payload.
- `dashboard/_dispatch.py:92` and `:149` - register the new route module.

**Frontend (create):**
- `web/js/panels/player_snapshot.js` - `renderPlayerSnapshot(el, model)` presentational component (ESM, ASCII, idempotent).
- `web/css/panels/player_snapshot.css` - card layout, composed from `tokens.css` primitives. Linked from `web/index.html` head.
- `tests/snapshot_panels/test_player_snapshot_view.py` - Playwright snapshot of the card (full / empty / low-confidence fixtures).
- `tests/test_player_snapshot_dom.py` - DOM-string assertions on `player_snapshot.js` render output.

**Frontend (modify):**
- `web/index.html` - Home card mount + Home hero absorb (spec 7.1, ~103-356); PGR card mount + PGR hero/rubric refactor (spec 7.2, ~1633-1950); `<link>` the new CSS; ship the GPI radar block behind View Profile.
- `web/js/main.js` - Home adapter (mode-tab fetch + render + hero absorb, ~3036-3607); View-Profile expand mounting `renderPlayerGpi`.
- `web/js/panels/last_match.js` - PGR adapter (assemble model from in-hand last-match + rubric data; suppress `_setHeroScore` / `_setHeroRoleGrade` / `_setRubricComponents` standalone rows).

**Do NOT modify:** any `rc-shell/src/*` (v1 is companion-only, auto-loaded), any frozen file, `core/post_game_rubric.py` (consumed as-is), `core/draft_elo_db.py`.

---

## Task 1: player_gpi time-window filter (`since_ts`)

**Files:**
- Modify: `core/player_gpi.py` (`_relative_axis`, `_versatility_axis`, `_consistency_axis`, `compute_gpi`)
- Test: `tests/test_player_gpi_window.py` (create)

**Interfaces:**
- Consumes: existing `_fetch_operator_games(conn, mode, champion)` rows (each dict has `ts` = `game_creation_ts`, Unix ms - verified [routes_personal_vs.py:122](dashboard/routes_personal_vs.py:122)).
- Produces: `compute_gpi(mode, window=20, champion=None, conn=None, since_ts=None) -> dict` where the returned payload gains `window_n: int`. When `since_ts` (epoch ms) is passed, the "recent" set that axes/aggregate are scored over is `[g for g in games if g["ts"] and g["ts"] >= since_ts]`; the percentile BASELINE stays the full `games` history. When `since_ts` is None, behavior is byte-identical to today (`games[:window]`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_player_gpi_window.py
"""since_ts time-window filter for compute_gpi (player-snapshot card, spec 5.1).

The recent-set that axes are scored over is filtered to games at or after
since_ts; the percentile baseline stays the full history. game_creation_ts is
Unix milliseconds (schema comment; routes_personal_vs.py:122).
"""
import sqlite3

from core import player_gpi


def _seed(conn, rows):
    conn.executescript(
        "CREATE TABLE matches (match_id TEXT PRIMARY KEY, game_duration_s INTEGER,"
        " game_creation_ts INTEGER, has_stats INTEGER, map_id INTEGER,"
        " tracked_champion_id INTEGER, tracked_team_id INTEGER);"
        "CREATE TABLE participants (match_id TEXT, champion_id INTEGER, team_id INTEGER,"
        " total_minions_killed INTEGER, neutral_minions_killed INTEGER, vision_score INTEGER,"
        " gold_earned INTEGER, total_damage_dealt_to_champs INTEGER, deaths INTEGER,"
        " kills INTEGER, assists INTEGER, dragon_kills INTEGER, baron_kills INTEGER,"
        " turret_takedowns INTEGER, inhibitor_takedowns INTEGER, win INTEGER);"
    )
    for r in rows:
        conn.execute(
            "INSERT INTO matches VALUES (?,?,?,1,11,?,100)",
            (r["mid"], 1800, r["ts"], r["champ"]),
        )
        conn.execute(
            "INSERT INTO participants VALUES (?,?,100,180,20,30,12000,18000,?,?,?,?,?,?,?,?)",
            (r["mid"], r["champ"], r["deaths"], r["kills"], r["assists"],
             r["drag"], 0, 0, 0, r["win"]),
        )
    conn.commit()


def _rows(n, base_ts):
    # n games, one per hour going back from base_ts, alternating deaths so the
    # window subset differs measurably from the full history.
    out = []
    for i in range(n):
        out.append({"mid": f"M{i}", "ts": base_ts - i * 3600_000, "champ": 64,
                    "deaths": 2 if i % 2 else 8, "kills": 6, "assists": 4,
                    "drag": 1, "win": 1 if i % 2 else 0})
    return out


def test_since_ts_filters_recent_set_but_not_baseline():
    now = 1_700_000_000_000
    conn = sqlite3.connect(":memory:")
    _seed(conn, _rows(20, now))
    # Window = last 3h -> only the 3 newest games are in the recent set.
    since = now - 3 * 3600_000
    out = player_gpi.compute_gpi(mode="sr", conn=conn, since_ts=since)
    assert out["ok"] is True
    assert out["window_n"] == 3            # exactly the 3 games inside 3h
    assert out["n_games"] == 20            # baseline unchanged (full history)
    # A survival axis exists and was scored over the 3-game window, not all 20.
    axes = {a["key"]: a for a in out["axes"]}
    assert axes["survival"]["sample_n"] == 3


def test_since_ts_none_is_unchanged_behavior():
    now = 1_700_000_000_000
    conn = sqlite3.connect(":memory:")
    _seed(conn, _rows(20, now))
    out = player_gpi.compute_gpi(mode="sr", conn=conn)   # no since_ts
    assert out["window_n"] == min(player_gpi.DEFAULT_WINDOW, 20)
    assert out["n_games"] == 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe -m pytest tests/test_player_gpi_window.py -v`
Expected: FAIL - `compute_gpi() got an unexpected keyword argument 'since_ts'` (and `KeyError: 'window_n'`).

- [ ] **Step 3: Implement the minimal change in `core/player_gpi.py`**

Add `recent` params to the three axis helpers (default preserves old behavior):

```python
def _relative_axis(spec, games: list[dict], window: int, recent=None) -> dict:
    key, label, unit, higher, sel = spec
    sign = 1.0 if higher else -1.0
    baseline = sorted(sign * sel(g) for g in games)
    recent = games[:window] if recent is None else recent
    pcts = [_percentile(baseline, sign * sel(g)) for g in recent]
    score = 100.0 * sum(pcts) / len(pcts) if pcts else 50.0
    recent_raw = [sel(g) for g in recent]
    return {
        "key": key, "label": label, "unit": unit, "scoring": "relative",
        "higher_is_better": higher, "score": round(score, 1),
        "recent_value": round(sum(recent_raw) / len(recent_raw), 2) if recent_raw else 0.0,
        "baseline_p50": round(_median([sel(g) for g in games]), 2),
        "sample_n": len(recent),
    }
```

Add `recent=None` with the same `recent = games[:window] if recent is None else recent` line at the top of `_versatility_axis` and `_consistency_axis` (replace their internal `recent = games[:window]`).

In `compute_gpi`, add the param and compute the recent set once:

```python
def compute_gpi(mode: str = "sr", window: int = DEFAULT_WINDOW,
                champion: Optional[int] = None,
                conn: Optional[sqlite3.Connection] = None,
                since_ts: Optional[int] = None) -> dict:
    ...
    n_games = len(games)
    if n_games < MIN_GAMES:
        return _empty(mode, window, n_games, champion, "insufficient")

    if since_ts is not None:
        recent = [g for g in games if g["ts"] and g["ts"] >= since_ts]
    else:
        recent = games[:window]

    axes = [_relative_axis(spec, games, window, recent) for spec in _RELATIVE_AXES]
    axes.append(_versatility_axis(games, window, recent))
    axes.append(_consistency_axis(games, window, recent))
    ...
    out["window_n"] = len(recent)
```

Add `"window_n": 0` to the `_empty()` dict so the key is always present.

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe -m pytest tests/test_player_gpi_window.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Regression - run the existing GPI suite**

Run: `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe -m pytest tests/test_routes_player_profile.py tests/test_player_gpi_this_match.py -q`
Expected: PASS (unchanged - `since_ts=None` path is byte-identical).

- [ ] **Step 6: Commit**

```bash
git add core/player_gpi.py tests/test_player_gpi_window.py
git commit -F <ascii-tmpfile>   # message: "feat(gpi): since_ts time-window filter for player-snapshot card"
```

---

## Task 2: player_gpi win-streak, window win-rate, K-P, strongest-axis

**Files:**
- Modify: `core/player_gpi.py` (`_fetch_operator_games` SELECT + row unpack, `compute_gpi` payload)
- Test: `tests/test_player_gpi_window.py` (extend)

**Interfaces:**
- Consumes: Task 1's `recent` set + `_fetch_operator_games` rows.
- Produces: `compute_gpi(...)` payload gains: `win_streak: {kind: "win"|"loss", n: int}|null` (current streak from newest game backward over full history), `win_rate: float|null` (0..1 over the recent/window set), `kp_pct: float|null` (mean kill-participation over the recent set, from team kills - `inferred`), `strongest_axis: str|null` (key of the highest of the 6 relative axes, symmetric to `weakest_axis`). Each game dict gains `win: int` and `kp: float`.

- [ ] **Step 1: Write the failing test (append to `tests/test_player_gpi_window.py`)**

```python
def test_win_streak_winrate_kp_strongest():
    now = 1_700_000_000_000
    conn = sqlite3.connect(":memory:")
    # Newest 3 games are wins (streak), older ones losses. Team kills = operator
    # kills only in this seed (single participant), so KP == 1.0.
    rows = []
    for i in range(15):
        rows.append({"mid": f"M{i}", "ts": now - i * 3600_000, "champ": 64,
                     "deaths": 3, "kills": 5, "assists": 5,
                     "drag": 1, "win": 1 if i < 3 else 0})
    _seed(conn, rows)
    out = player_gpi.compute_gpi(mode="sr", conn=conn, since_ts=now - 24 * 3600_000)
    assert out["win_streak"] == {"kind": "win", "n": 3}
    assert 0.0 <= out["win_rate"] <= 1.0
    assert out["kp_pct"] == 100.0           # sole participant -> 100% KP
    assert out["strongest_axis"] in {a["key"] for a in out["axes"]
                                     if a["scoring"] == "relative"}
    assert out["strongest_axis"] != out["weakest_axis"]
```

Note: the K-P team-kill subquery sums all `participants.kills` for the operator's team in the match. The single-participant seed above yields team_kills == operator kills, so KP == 100%. A richer multi-participant fixture belongs in Task 4's route test.

- [ ] **Step 2: Run test to verify it fails**

Run: `...python.exe -m pytest tests/test_player_gpi_window.py::test_win_streak_winrate_kp_strongest -v`
Expected: FAIL - `KeyError: 'win_streak'`.

- [ ] **Step 3: Implement in `core/player_gpi.py`**

In `_fetch_operator_games`, add `p.win` and a correlated team-kills subquery to the SELECT column list and the row unpack:

```python
sql = (
    "SELECT m.match_id, m.game_duration_s, m.game_creation_ts, "
    "p.champion_id, "
    "p.total_minions_killed, p.neutral_minions_killed, p.vision_score, "
    "p.gold_earned, p.total_damage_dealt_to_champs, p.deaths, p.kills, "
    "p.assists, p.dragon_kills, p.baron_kills, p.turret_takedowns, "
    "p.inhibitor_takedowns, p.win, "
    "(SELECT SUM(p2.kills) FROM participants p2 "
    " WHERE p2.match_id = m.match_id AND p2.team_id = m.tracked_team_id) "
    "AS team_kills "
    "FROM matches m JOIN participants p ON p.match_id = m.match_id "
    "AND p.champion_id = m.tracked_champion_id "
    "AND p.team_id = m.tracked_team_id "
    "WHERE " + " AND ".join(where) + " "
    "ORDER BY m.game_creation_ts DESC"
)
```

Unpack the two new columns and add `win` + `kp` to each game dict:

```python
(mid, dur_s, ts, champ, minions, neutral, vis, gold, dmg, deaths,
 kills, assists, drag, baron, turret, inhib, win, team_kills) = row
...
team_k = float(team_kills or 0)
games.append({
    ...
    "win": int(win or 0),
    "kp": (float(kills or 0) + float(assists or 0)) / team_k if team_k > 0 else 0.0,
})
```

In `compute_gpi`, after `axes` are built, derive the new fields over `recent` (and streak over full `games`):

```python
# Current streak from the newest game backward (full history).
streak = None
if games:
    kind = "win" if games[0]["win"] else "loss"
    want = games[0]["win"]
    n = 0
    for g in games:
        if int(g["win"]) == want:
            n += 1
        else:
            break
    streak = {"kind": kind, "n": n}
out["win_streak"] = streak
out["win_rate"] = (sum(g["win"] for g in recent) / len(recent)) if recent else None
out["kp_pct"] = round(100.0 * sum(g["kp"] for g in recent) / len(recent), 1) if recent else None

# Strongest relative axis (symmetric to weakest_axis; relative axes only).
rel_axes = [a for a in axes if a["key"] in _AXIS_TIPS]
strongest = max(rel_axes, key=lambda a: a["score"]) if rel_axes else None
out["strongest_axis"] = strongest["key"] if strongest else None
```

Add `"win_streak": None, "win_rate": None, "kp_pct": None, "strongest_axis": None` to `_empty()` so keys are always present.

- [ ] **Step 4: Run test to verify it passes**

Run: `...python.exe -m pytest tests/test_player_gpi_window.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Regression**

Run: `...python.exe -m pytest tests/test_routes_player_profile.py tests/test_player_gpi_this_match.py -q`
Expected: PASS (new fields are additive; the profile route ignores them).

- [ ] **Step 6: Commit**

```bash
git add core/player_gpi.py tests/test_player_gpi_window.py
git commit -F <ascii-tmpfile>   # "feat(gpi): win-streak, window win-rate, K-P (inferred), strongest-axis"
```

---

## Task 3: tag-derivation helper

**Files:**
- Create: `dashboard/routes_player_snapshot.py` (the `_derive_snapshot_tags` function only, this task)
- Test: `tests/test_routes_player_snapshot.py` (create, tag cases only this task)

**Interfaces:**
- Consumes: a `compute_gpi` payload (has `axes`, `strongest_axis`, `weakest_axis`).
- Produces: `_derive_snapshot_tags(gpi: dict) -> list[dict]` returning EXACTLY 3 `{label, tone}` dicts in order [strong, neutral, weak], using the spec-4.6 vocabulary. Shape axes (versatility/consistency) are barred from the strong/weak slots; the neutral slot is the more pronounced shape axis.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_routes_player_snapshot.py
"""Contract tests for /api/player-snapshot and its helpers (player-snapshot card)."""
from dashboard import routes_player_snapshot as rps


def _gpi(strongest, weakest, versat=70.0, consist=40.0):
    axes = [
        {"key": "aggression", "score": 80.0, "scoring": "relative"},
        {"key": "farming", "score": 30.0, "scoring": "relative"},
        {"key": "vision", "score": 50.0, "scoring": "relative"},
        {"key": "objectives", "score": 55.0, "scoring": "relative"},
        {"key": "survival", "score": 45.0, "scoring": "relative"},
        {"key": "tempo", "score": 60.0, "scoring": "relative"},
        {"key": "versatility", "score": versat, "scoring": "absolute"},
        {"key": "consistency", "score": consist, "scoring": "absolute"},
    ]
    return {"axes": axes, "strongest_axis": strongest, "weakest_axis": weakest}


def test_tags_are_three_with_correct_tones_and_words():
    tags = rps._derive_snapshot_tags(_gpi("aggression", "farming"))
    assert len(tags) == 3
    assert tags[0] == {"label": "Aggressive", "tone": "strong"}
    assert tags[2] == {"label": "Weak Farm", "tone": "weak"}
    # neutral slot is the shape axis (versatility 70 > consistency 40) high word.
    assert tags[1] == {"label": "Generalist", "tone": "neutral"}


def test_neutral_slot_uses_consistency_when_it_dominates():
    tags = rps._derive_snapshot_tags(_gpi("tempo", "vision", versat=20.0, consist=85.0))
    assert tags[1] == {"label": "Consistent", "tone": "neutral"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `...python.exe -m pytest tests/test_routes_player_snapshot.py -v`
Expected: FAIL - `ModuleNotFoundError: No module named 'dashboard.routes_player_snapshot'`.

- [ ] **Step 3: Create `dashboard/routes_player_snapshot.py` with the helper**

```python
"""GET /api/player-snapshot - DB-pure Home player-snapshot model (read-only).

Feeds the Home player-snapshot card (spec docs/superpowers/specs/
2026-07-04-player-snapshot-card-design.md). Assembles the normalized model
from core.player_gpi (self-relative GPI over a time window) plus a net-new
tag heuristic. No Riot API, no Claude. Rank/level/name are NOT here (they are
LCU-live, merged client-side from /api/home/summary); this route stays
rewind_history.db-pure and deterministic.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import parse_qs, urlparse

from core import player_gpi

log = logging.getLogger(__name__)

# axis key -> (high word / strong, low word / weak). Spec 4.6.
_TAG_WORDS: dict[str, tuple[str, str]] = {
    "aggression": ("Aggressive", "Passive"),
    "farming": ("Strong Farmer", "Weak Farm"),
    "vision": ("Vision Control", "Visionless"),
    "objectives": ("Objective Focused", "Objective Shy"),
    "survival": ("Survivor", "Gank Prone"),
    "tempo": ("Snowballer", "Slow Starter"),
    "versatility": ("Generalist", "One-Trick"),
    "consistency": ("Consistent", "Streaky"),
}


def _derive_snapshot_tags(gpi: dict) -> list[dict]:
    """Three tags in [strong, neutral, weak] order (spec 4.6)."""
    strong_key = gpi.get("strongest_axis") or "aggression"
    weak_key = gpi.get("weakest_axis") or "farming"
    axes = {a["key"]: a for a in gpi.get("axes", [])}
    versat = (axes.get("versatility") or {}).get("score") or 0.0
    consist = (axes.get("consistency") or {}).get("score") or 0.0
    shape_key = "versatility" if versat >= consist else "consistency"
    shape_score = versat if shape_key == "versatility" else consist
    # High word when the shape axis reads at/above its midpoint, else low word;
    # either way it is a descriptor, never a weakness.
    shape_label = _TAG_WORDS[shape_key][0 if shape_score >= 50.0 else 1]
    return [
        {"label": _TAG_WORDS[strong_key][0], "tone": "strong"},
        {"label": shape_label, "tone": "neutral"},
        {"label": _TAG_WORDS[weak_key][1], "tone": "weak"},
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `...python.exe -m pytest tests/test_routes_player_snapshot.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Lint**

Run: `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe -m ruff check dashboard/routes_player_snapshot.py tests/test_routes_player_snapshot.py`
Expected: no findings.

- [ ] **Step 6: Commit**

```bash
git add dashboard/routes_player_snapshot.py tests/test_routes_player_snapshot.py
git commit -F <ascii-tmpfile>   # "feat(snapshot): tag-derivation heuristic (spec 4.6 vocabulary)"
```

---

## Task 4: /api/player-snapshot route + model assembly + dispatch registration

**Files:**
- Modify: `dashboard/routes_player_snapshot.py` (add `_build_snapshot_model` + `_serve_player_snapshot` + `GET_ROUTES`)
- Modify: `dashboard/_dispatch.py:92` (import) and `:149` (GET assembly)
- Test: `tests/test_routes_player_snapshot.py` (extend)

**Interfaces:**
- Consumes: `player_gpi.compute_gpi(mode, since_ts=...)`, `_derive_snapshot_tags`.
- Produces: `GET /api/player-snapshot?mode=<sr|aram|arena>&hours=<int, default 24>` -> the normalized model JSON. `_build_snapshot_model(gpi: dict, mode: str, hours: int) -> dict` is the pure assembler. Never raises; returns `empty: true` + `confidence: "insufficient"` on a thin/zero-game window or DB error. Bars per spec 4.4 Home: INCOME=mean(farming, tempo), COMBAT=aggression, OBJECTIVES=objectives, VISION=vision. Minis: KDA (source_truth), Win-Rate (source_truth), K-P (inferred). Dial: `value=overall`, band by the 65/35 cutoffs. `header` carries `champion_id` (most-played in window) + `result=null`; `name/rank_tier/rank_lp/level` are `null` here (merged client-side).

- [ ] **Step 1: Write the failing test (append)**

```python
import sqlite3
from tests.test_player_gpi_window import _seed, _rows   # reuse the seed helpers


class _FakeHandler:
    def __init__(self, path):
        self.path = path
        self.status = None
        self.body = None
    def _send(self, status, body, ctype):
        self.status = status
        self.body = json.loads(body.decode("utf-8"))


def test_build_model_shape_and_bands():
    now = 1_700_000_000_000
    conn = sqlite3.connect(":memory:")
    _seed(conn, _rows(20, now))
    gpi = player_gpi.compute_gpi(mode="sr", conn=conn, since_ts=now - 24 * 3600_000)
    model = rps._build_snapshot_model(gpi, "sr", 24)
    assert set(model) >= {"header", "dial", "minis", "bars", "tags",
                          "profile_ref", "confidence", "sample_n", "empty"}
    assert model["empty"] is False
    assert len(model["tags"]) == 3
    assert {b["key"] for b in model["bars"]} == {"income", "combat", "objectives", "vision"}
    assert {m["key"] for m in model["minis"]} == {"kda", "winrate", "kp"}
    kp = next(m for m in model["minis"] if m["key"] == "kp")
    assert kp["provenance"] == "inferred"
    assert model["dial"]["band"] in {"good", "ok", "poor"}
    assert model["profile_ref"]["mode"] == "sr"


def test_empty_window_returns_empty_model_no_error():
    now = 1_700_000_000_000
    conn = sqlite3.connect(":memory:")
    _seed(conn, _rows(20, now))
    # A window in the far past -> zero games inside it.
    gpi = player_gpi.compute_gpi(mode="sr", conn=conn, since_ts=now + 3600_000)
    model = rps._build_snapshot_model(gpi, "sr", 24)
    assert model["empty"] is True
    assert model["confidence"] in {"insufficient", "low"}


def test_route_never_leaks_raw_error():
    h = _FakeHandler("/api/player-snapshot?mode=sr&hours=24")
    rps._serve_player_snapshot(h)          # real DB path; must not raise
    assert h.status == 200
    assert h.body.get("empty") in (True, False)   # a valid model either way
```

- [ ] **Step 2: Run test to verify it fails**

Run: `...python.exe -m pytest tests/test_routes_player_snapshot.py -v`
Expected: FAIL - `AttributeError: module ... has no attribute '_build_snapshot_model'`.

- [ ] **Step 3: Implement `_build_snapshot_model`, `_serve_player_snapshot`, `GET_ROUTES`**

```python
_MODES = {"sr", "aram", "arena"}


def _band(value: float) -> str:
    if value >= 65.0:
        return "good"
    if value >= 35.0:
        return "ok"
    return "poor"


def _mean(*vals: float) -> float:
    return round(sum(vals) / len(vals), 1)


def _build_snapshot_model(gpi: dict, mode: str, hours: int) -> dict:
    axes = {a["key"]: a for a in gpi.get("axes", [])}
    window_n = int(gpi.get("window_n") or 0)
    insufficient = gpi.get("confidence") == "insufficient"
    empty = insufficient or window_n == 0
    label = f"{mode.upper()} last {hours}h"

    def _score(k):
        return float((axes.get(k) or {}).get("score") or 0.0)

    if empty:
        return {
            "header": {"name": None, "rank_tier": None, "rank_lp": None,
                       "level": None, "streak": gpi.get("win_streak"),
                       "champion_id": None, "result": None},
            "dial": {"value": 0, "band": "poor", "label": label},
            "minis": [], "bars": [], "tags": [],
            "profile_ref": {"mode": mode, "window": f"{hours}h", "match_id": None},
            "confidence": "insufficient" if insufficient else "low",
            "sample_n": window_n, "empty": True,
        }

    overall = float(gpi.get("overall") or 0.0)
    wr = gpi.get("win_rate")
    kp = gpi.get("kp_pct")
    kda_axis = axes.get("aggression")  # KDA rides as a mini; combat bar = aggression
    minis = [
        {"key": "kda", "value": _fmt_kda(gpi), "provenance": "source_truth"},
        {"key": "winrate",
         "value": f"{round(100.0 * wr)}%" if wr is not None else "-",
         "provenance": "source_truth"},
        {"key": "kp", "value": f"{round(kp)}%" if kp is not None else "-",
         "provenance": "inferred"},
    ]
    bars = [
        {"key": "income", "label": "INCOME",
         "score": _mean(_score("farming"), _score("tempo")), "provenance": "source_truth"},
        {"key": "combat", "label": "COMBAT",
         "score": _score("aggression"), "provenance": "source_truth"},
        {"key": "objectives", "label": "OBJECTIVES",
         "score": _score("objectives"), "provenance": "source_truth"},
        {"key": "vision", "label": "VISION",
         "score": _score("vision"), "provenance": "source_truth"},
    ]
    return {
        "header": {"name": None, "rank_tier": None, "rank_lp": None, "level": None,
                   "streak": gpi.get("win_streak"), "champion_id": _top_champ(gpi),
                   "result": None},
        "dial": {"value": round(overall), "band": _band(overall), "label": label},
        "minis": minis, "bars": bars, "tags": _derive_snapshot_tags(gpi),
        "profile_ref": {"mode": mode, "window": f"{hours}h", "match_id": None},
        "confidence": gpi.get("confidence") or "low",
        "sample_n": window_n, "empty": False,
    }


def _fmt_kda(gpi: dict) -> str:
    a = {x["key"]: x for x in gpi.get("axes", [])}
    # KDA is not a GPI axis; recompute from the this_match/aggregate is out of
    # scope - surface the aggression axis recent_value proxy label instead is
    # wrong. Use the mean KDA the module already tracks via consistency input.
    # Simplest correct source: gpi carries no mean KDA, so compute at route
    # time is unavailable -> show "-" when absent (no fabrication).
    return gpi.get("kda_display") or "-"
```

Note for the implementer: `_fmt_kda` needs a real mean-KDA. `compute_gpi` already computes per-game `kda` in each game dict but does not surface a window mean. Add ONE line to Task 2's `compute_gpi` (fold forward): `out["kda_mean"] = round(sum(g["kda"] for g in recent) / len(recent), 2) if recent else None`, and here return `f"{gpi['kda_mean']:.2f}"` when present else `"-"`. Add the failing assertion `assert model["minis"][0]["value"] != "-"` to Step 1 first (TDD), then wire `kda_mean`.

```python
def _top_champ(gpi: dict):
    tm = gpi.get("this_match") or {}
    return tm.get("champion_id")   # most-recent played; window-mode == self


def _serve_player_snapshot(h) -> None:
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        mode = (qs.get("mode") or ["sr"])[0].strip().lower()
        if mode not in _MODES:
            mode = "sr"
        try:
            hours = max(1, int((qs.get("hours") or ["24"])[0]))
        except (TypeError, ValueError):
            hours = 24
        import time
        since = int(time.time() * 1000) - hours * 3600_000
        gpi = player_gpi.compute_gpi(mode=mode, since_ts=since)
        model = _build_snapshot_model(gpi, mode, hours)
        h._send(200, json.dumps(model).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/player-snapshot: %s", exc)
        # Never leak raw error text; return a friendly empty model.
        empty = {"header": {}, "dial": {"value": 0, "band": "poor", "label": "-"},
                 "minis": [], "bars": [], "tags": [],
                 "profile_ref": {"mode": "sr", "window": None, "match_id": None},
                 "confidence": "insufficient", "sample_n": 0, "empty": True}
        try:
            h._send(200, json.dumps(empty).encode("utf-8"), "application/json")
        except Exception:  # noqa: BLE001
            pass


def _equals(p: str):
    def m(path: str) -> bool:
        return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/player-snapshot"), _serve_player_snapshot),
]
```

Register in `dashboard/_dispatch.py`: add `routes_player_snapshot,` to the import tuple after `routes_player_profile,` ([_dispatch.py:92](dashboard/_dispatch.py:92)) and add `+ list(routes_player_snapshot.GET_ROUTES)` after the `routes_player_profile.GET_ROUTES` line ([_dispatch.py:149](dashboard/_dispatch.py:149)).

- [ ] **Step 4: Run tests to verify they pass**

Run: `...python.exe -m pytest tests/test_routes_player_snapshot.py -v`
Expected: PASS (all).

- [ ] **Step 5: Verify dispatch registration**

Run: `...python.exe -c "from dashboard import _dispatch; paths=[m.__self__ if hasattr(m,'__self__') else m for (pred,_) in _dispatch._get_get_routes()]; print('registered')"`
(If `_get_get_routes` is not the accessor name, grep `_dispatch.py` for the function that returns `_GET_CACHE` and call it; assert a predicate matches `/api/player-snapshot`.) Simpler: add a test asserting registration mirroring [test_routes_player_profile.py:231](tests/test_routes_player_profile.py:231).

- [ ] **Step 6: py_compile + lint + commit**

```bash
...python.exe -m py_compile dashboard/routes_player_snapshot.py dashboard/_dispatch.py
...python.exe -m ruff check dashboard/routes_player_snapshot.py
git add dashboard/routes_player_snapshot.py dashboard/_dispatch.py tests/test_routes_player_snapshot.py core/player_gpi.py
git commit -F <ascii-tmpfile>   # "feat(snapshot): /api/player-snapshot route + model assembly + dispatch"
```

---

## Task 5: presentational renderPlayerSnapshot component + CSS

**Files:**
- Create: `web/js/panels/player_snapshot.js`
- Create: `web/css/panels/player_snapshot.css`
- Modify: `web/index.html` (add `<link rel="stylesheet" href="css/panels/player_snapshot.css?v=...">` in the head, next to the other panel CSS links)
- Test: `tests/test_player_snapshot_dom.py` (create)

**Interfaces:**
- Consumes: the normalized model (contract above).
- Produces: `export function renderPlayerSnapshot(el, model)`. Pure render, no fetch. Idempotent: stash `el.dataset.sig = JSON.stringify(model)` and early-return when unchanged (pattern [duration_winrate.js:28](web/js/panels/duration_winrate.js:28)). On `model.empty === true`, render the reserved-height card with a `-` sentinel and the `label` message, NO reflow. Exposes a `data-testid="player-snapshot"` root, `.ps-dial`, `.ps-bar[data-key]`, `.ps-mini[data-key]`, `.ps-tag[data-tone]`, `.ps-viewprofile` button.

- [ ] **Step 1: Write the failing DOM test**

```python
# tests/test_player_snapshot_dom.py
"""DOM-string assertions on web/js/panels/player_snapshot.js.

No browser - asserts the source exports the render fn, uses only tokens.css
custom properties (no hardcoded hex), and branches on model.empty.
"""
from pathlib import Path

SRC = Path("web/js/panels/player_snapshot.js").read_text(encoding="utf-8")


def test_exports_render_and_is_idempotent():
    assert "export function renderPlayerSnapshot(" in SRC
    assert "dataset.sig" in SRC          # idempotent signature stash


def test_no_hardcoded_hex_colors():
    import re
    # Card composes tokens; a raw #rrggbb is a token-sprawl regression.
    assert not re.search(r"#[0-9a-fA-F]{6}", SRC)


def test_handles_empty_and_ascii_only():
    assert "model.empty" in SRC
    assert all(ord(c) < 128 for c in SRC)   # ASCII-only (no em-dash/smart quote)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `...python.exe -m pytest tests/test_player_snapshot_dom.py -v`
Expected: FAIL - `FileNotFoundError: web/js/panels/player_snapshot.js`.

- [ ] **Step 3: Create `web/js/panels/player_snapshot.js`**

Write a pure ESM module. Skeleton (the implementer fleshes out the SVG dial + bar rows; all colors via `var(--signal-*)` / `var(--hextech-*)` / `var(--fs-*)` / `var(--space-*)`; ASCII only):

```javascript
// web/js/panels/player_snapshot.js
// Presentational player-snapshot card (spec docs/superpowers/specs/
// 2026-07-04-player-snapshot-card-design.md). Pure render, no fetch,
// idempotent. Host-agnostic: it takes a model, it does not know its surface.
// Discipline mirrors player_gpi.js / duration_winrate.js: ESM, ASCII only.

const _BAND_VAR = { good: "--signal-good", ok: "--signal-warn", poor: "--signal-bad" };
const _TONE_VAR = { strong: "--signal-good", neutral: "--signal-warn", weak: "--signal-bad" };

export function renderPlayerSnapshot(el, model) {
  if (!el || !model) return;
  const sig = JSON.stringify(model);
  if (el.dataset.sig === sig) return;      // idempotent
  el.dataset.sig = sig;
  el.classList.add("player-snapshot");
  el.setAttribute("data-testid", "player-snapshot");
  if (model.empty) { el.innerHTML = _emptyHtml(model); return; }
  el.innerHTML =
    _headerHtml(model.header) +
    _dialHtml(model.dial) +
    _minisHtml(model.minis) +
    _barsHtml(model.bars) +
    _tagsHtml(model.tags) +
    _viewProfileHtml(model.profile_ref);
}

function _emptyHtml(m) {
  // Reserved-height card + "-" sentinel; no reflow (feedback_no_reflow_on_data_absence).
  const msg = (m.dial && m.dial.label) ? m.dial.label : "No data";
  return '<div class="ps-empty" style="min-height:var(--space-8)">'
       + '<span class="ps-sentinel">-</span>'
       + '<span class="ps-empty-msg">' + _esc(msg) + '</span></div>';
}
// ... _headerHtml/_dialHtml/_minisHtml/_barsHtml/_tagsHtml/_viewProfileHtml/_esc ...
```

Create `web/css/panels/player_snapshot.css` composing only tokens (grid layout for dial + bars, `.ps-tag` chips colored by `--signal-*`, `.ps-empty` reserved height). Add the `<link>` in `web/index.html` head with the `?v=` hash placeholder the other panel CSS links use.

- [ ] **Step 4: Run test to verify it passes**

Run: `...python.exe -m pytest tests/test_player_snapshot_dom.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Snapshot fixture test**

Create `tests/snapshot_panels/test_player_snapshot_view.py` mirroring [test_player_gpi_view.py](tests/snapshot_panels/test_player_gpi_view.py): mount a `<div id="ps-fixture">`, `import { renderPlayerSnapshot }`, call it with a full model, an empty model, and a low-confidence model; assert the dial band class, 4 bars, 3 tags, and (empty case) the `-` sentinel + reserved height. Run:
`...python.exe -m pytest tests/snapshot_panels/test_player_snapshot_view.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/js/panels/player_snapshot.js web/css/panels/player_snapshot.css web/index.html tests/test_player_snapshot_dom.py tests/snapshot_panels/test_player_snapshot_view.py
git commit -F <ascii-tmpfile>   # "feat(ui): presentational renderPlayerSnapshot card + tokens CSS"
```

---

## Task 6: Home adapter (mode-tab, 24h) + Home hero absorb (spec 7.1)

**Files:**
- Modify: `web/js/main.js` (Home render + mode-tab handler, ~3036-3607; rank/level source ~3397-3407)
- Modify: `web/index.html` (Home card mount + hero-element refactor, ~103-356)
- Test: `tests/snapshot_panels/test_home_snapshot_card.py` (create), extend `tests/snapshot_panels/test_home_mode_tabs.py` coverage

**Interfaces:**
- Consumes: `renderPlayerSnapshot` (Task 5), `GET /api/player-snapshot?mode&hours=24` (Task 4), the existing `/api/home/summary` payload the Home view already fetches (for rank/level/name merge).
- Produces: a Home adapter that, on initial Home render and on every mode-tab change (the same handler [test_home_mode_tabs.py](tests/snapshot_panels/test_home_mode_tabs.py) drives, which refetches `/api/home/summary?mode=<tab>`), fetches the snapshot model, merges `header.rank_tier/rank_lp/level/name` from the home-summary payload, and calls `renderPlayerSnapshot(mountEl, model)`. Absorbs the Home hero elements per spec 7.1.

Spec 7.1 absorb/refactor table (grep exact current lines during TDD):
- `#home-hero-rank-tier` + WR -> ABSORB into card header
- `#home-hero-kda` (14D) -> ABSORB (card = 24h value)
- `#home-hero-headline` (momentum verdict) -> ABSORB into tag row
- `#home-rank-wl` (last-20 W/L pips) -> REFACTOR: keep pips as a detail row UNDER the card
- `#home-hero-cs` (14D CS/min) -> REFACTOR: keep sparkline as trajectory only
- RECENT 3 / THIS WEEK champ chart / TONIGHT'S PICK -> KEEP untouched

- [ ] **Step 1: Write the failing snapshot test**

Create `tests/snapshot_panels/test_home_snapshot_card.py` mirroring [test_home_mode_tabs.py](tests/snapshot_panels/test_home_mode_tabs.py): stub `**/api/player-snapshot*` with a fixed model per mode and `**/api/home/summary` with a rank/level payload; load the Home view; assert `[data-testid="player-snapshot"]` is present in the Home mount, the dial band matches the model, and switching the mode tab refetches `/api/player-snapshot?mode=<newtab>` and re-renders. Also assert the absorbed `#home-hero-rank-tier` standalone element is gone/hidden (no duplicate rank).

- [ ] **Step 2: Run test to verify it fails**

Run: `...python.exe -m pytest tests/snapshot_panels/test_home_snapshot_card.py -v`
Expected: FAIL - no `player-snapshot` node in the Home view.

- [ ] **Step 3: Implement the Home adapter + HTML refactor**

In `web/index.html`, add the card mount `<div id="home-snapshot-card"></div>` at the top of the Home hero region (~103-356) and remove/repurpose the absorbed hero elements per the table (keep `#home-rank-wl` pips + `#home-hero-cs` sparkline, relocated under the card). In `web/js/main.js`, add:

```javascript
import { renderPlayerSnapshot } from "./panels/player_snapshot.js";

async function _renderHomeSnapshot(mode, homeSummary) {
  const el = document.getElementById("home-snapshot-card");
  if (!el) return;
  let model;
  try {
    const r = await fetch("/api/player-snapshot?mode=" + encodeURIComponent(mode)
                          + "&hours=24", { cache: "no-store" });
    model = await r.json();
  } catch (e) {
    model = { empty: true, dial: { label: "coaching paused - retrying" },
              confidence: "insufficient", sample_n: 0 };
  }
  // Merge LCU rank/level/name from the home-summary payload already in hand.
  if (model && model.header && homeSummary) {
    model.header.rank_tier = homeSummary.rank_tier ?? model.header.rank_tier;
    model.header.rank_lp = homeSummary.rank_lp ?? model.header.rank_lp;
    model.header.level = homeSummary.level ?? model.header.level;
    model.header.name = homeSummary.name ?? model.header.name;
  }
  renderPlayerSnapshot(el, model);
}
```

Call `_renderHomeSnapshot(activeMode, homeSummaryPayload)` from the Home render entry and from the mode-tab change handler (grep the handler that refetches `/api/home/summary?mode=`; the exact call site is what [test_home_mode_tabs.py](tests/snapshot_panels/test_home_mode_tabs.py) drives). Use the real home-summary field names for rank/level (grep `main.js:3397-3407`); adjust the merge keys to match.

- [ ] **Step 4: Run test to verify it passes**

Run: `...python.exe -m pytest tests/snapshot_panels/test_home_snapshot_card.py tests/snapshot_panels/test_home_mode_tabs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/js/main.js web/index.html tests/snapshot_panels/test_home_snapshot_card.py
git commit -F <ascii-tmpfile>   # "feat(ui): Home player-snapshot adapter (24h per mode) + hero absorb"
```

---

## Task 7: PGR adapter (this match, role-rubric) + PGR refactor (spec 7.2)

**Files:**
- Modify: `web/js/panels/last_match.js` (`renderLastMatch` ~410; `_setHeroScore` ~816, `_setHeroRoleGrade` ~847, `_setRubricComponents` ~905)
- Modify: `web/index.html` (PGR card mount + hero/rubric refactor, ~1633-1950)
- Test: extend `tests/snapshot_panels/test_last_match_view.py`

**Interfaces:**
- Consumes: `renderPlayerSnapshot` (Task 5); the `data` object `renderLastMatch(data)` already holds (last-match payload); the rubric `data` object `_setHeroRoleGrade` already fetches from `/api/post-game-rubric` and passes to `_setRubricComponents(data)` ([last_match.js:877](web/js/panels/last_match.js:877)). NO new fetch.
- Produces: a `_buildPgrSnapshotModel(lastMatch, rubric)` client-side assembler + a render into a `#pgr-snapshot-card` mount. Bars per spec 4.4 PGR: INCOME=rubric CS/min component, COMBAT=mean(rubric KDA, DPM), OBJECTIVES=rubric obj, VISION=rubric vision, each scaled to 0..100 (a rubric component is `weight * clamp(raw/baseline,0,2)`; normalize to 0..100 by `component / (weight * 2) * 100`, or reuse `total_score`-style scaling - implementer picks one and asserts it in the test). Dial: `value = rubric.total_score`, band by 65/35, label = `rubric.percentile_grade`. Minis: KDA from last-match (source_truth), Win-Rate = null/`-` (single match - no window), K-P from last-match team kills if present else `inferred`/`-`. Header: `result` from last-match win, `champion_id` from last-match.

- [ ] **Step 1: Write the failing test**

Extend `tests/snapshot_panels/test_last_match_view.py`: with the SR fixture + the fixed `/api/post-game-rubric` payload it already stubs ([test_last_match_view.py:183](tests/snapshot_panels/test_last_match_view.py:183)), assert `[data-testid="player-snapshot"]` appears in the PGR view, the dial label equals the rubric `percentile_grade`, there are 4 bars, and the standalone `#lm-rubric-components` rows are suppressed (not double-rendered).

- [ ] **Step 2: Run test to verify it fails**

Run: `...python.exe -m pytest tests/snapshot_panels/test_last_match_view.py -v`
Expected: FAIL - no `player-snapshot` node in the PGR view.

- [ ] **Step 3: Implement the PGR adapter + refactor**

In `web/index.html` add `<div id="pgr-snapshot-card"></div>` at the top of the PGR hero region (~1633-1950). In `last_match.js`, add `import { renderPlayerSnapshot } from "./player_snapshot.js";` and a `_buildPgrSnapshotModel(m, rubric)` that maps the rubric components -> 4 bars + `total_score` -> dial + last-match -> header/minis. Call the card render at the point `_setRubricComponents(data)` receives the rubric ([last_match.js:877](web/js/panels/last_match.js:877)): build the model from the in-scope `m`/`data` (last-match) + `data` (rubric) and `renderPlayerSnapshot(document.getElementById("pgr-snapshot-card"), model)`. Then SUPPRESS the standalone rows: make `_setHeroScore` and `_setRubricComponents` no-op their DOM writes (or hide their host elements) so the card is the single source; keep `#lm-result-badge` / `#lm-grade-badge` / `#lm-rank-compare` / roster / lane-compare untouched (spec 7.2 KEEP). Preserve the 8-stat grid as a collapsible "Detailed stats" row (do not delete).

- [ ] **Step 4: Run test to verify it passes**

Run: `...python.exe -m pytest tests/snapshot_panels/test_last_match_view.py -v`
Expected: PASS.

- [ ] **Step 5: Regression - the historical PGR + role-grade DOM tests**

Run: `...python.exe -m pytest tests/test_last_match_role_grade_dom.py tests/snapshot_panels/test_historical_pgr_view.py -q`
Expected: PASS (refactor keeps the kept elements intact).

- [ ] **Step 6: Commit**

```bash
git add web/js/panels/last_match.js web/index.html tests/snapshot_panels/test_last_match_view.py
git commit -F <ascii-tmpfile>   # "feat(ui): PGR player-snapshot adapter (role-rubric) + hero/rubric refactor"
```

---

## Task 8: View Profile -> mount the GPI radar

**Files:**
- Modify: `web/js/main.js` (or `last_match.js` / a small `view_profile.js`) to lazily mount `renderPlayerGpi`
- Modify: `web/index.html` (a hidden radar container the expand reveals)
- Test: `tests/snapshot_panels/test_view_profile_radar.py` (create)

**Interfaces:**
- Consumes: `renderPlayerGpi(blockEl, payload, activeMode, activeChampion)` ([player_gpi.js:343](web/js/panels/player_gpi.js:343)) and its `fetchPlayerProfile` self-fetch of `/api/player-profile` ([player_gpi.js:105](web/js/panels/player_gpi.js:105)); the card's `model.profile_ref.mode`.
- Produces: clicking the card `.ps-viewprofile` button reveals a `#player-gpi-radar` block and mounts the never-before-mounted radar for `profile_ref.mode`. This is the first production mount of `player_gpi.js`.

- [ ] **Step 1: Write the failing test**

Create `tests/snapshot_panels/test_view_profile_radar.py` mirroring [test_player_gpi_view.py](tests/snapshot_panels/test_player_gpi_view.py) (stub `/api/player-profile` with the 8-axis payload): render the card, click `.ps-viewprofile`, assert `#player-gpi-radar svg` (the radar polygon) appears.

- [ ] **Step 2: Run test to verify it fails**

Run: `...python.exe -m pytest tests/snapshot_panels/test_view_profile_radar.py -v`
Expected: FAIL - the radar container stays empty (no mount).

- [ ] **Step 3: Implement the lazy mount**

Add `<div id="player-gpi-radar" hidden></div>` after the card mount(s) in `web/index.html`. Wire a click handler on `.ps-viewprofile` that un-hides the container and calls the `player_gpi.js` mount entry ([player_gpi.js:449](web/js/panels/player_gpi.js:449) shows the `fetchPlayerProfile(...) -> renderPlayerGpi(...)` pattern), passing `profile_ref.mode`. Import from `./panels/player_gpi.js`.

- [ ] **Step 4: Run test to verify it passes**

Run: `...python.exe -m pytest tests/snapshot_panels/test_view_profile_radar.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/js/main.js web/js/panels/last_match.js web/index.html tests/snapshot_panels/test_view_profile_radar.py
git commit -F <ascii-tmpfile>   # "feat(ui): View Profile mounts the GPI radar (first production mount)"
```

---

## Task 9: UI fixture ritual (5-phase audit) BEFORE final commit

**Files:** no new files; audit + in-slice MUST-FIX edits to `player_snapshot.css`, `player_snapshot.js`, `index.html`.

**Interfaces:** consumes the rendered Home + PGR cards; produces a clean 5-phase audit with every MUST-FIX resolved in this slice.

- [ ] **Step 1: Dispatch the visual-hierarchy / fixture audit subagent** over the Home card and the PGR card (both companion-rendered). Run all 5 phases: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY (memory `feedback_phase3_fixture_ritual`). Fonts must respect the floors (`--fs-xs`=16px and up). Tap targets: the View-Profile button and any tag chips >= the hit-target minimum. ASCII: no em-dash/smart quote in any rendered string.
- [ ] **Step 2: Resolve every MUST-FIX** inline in `player_snapshot.css` / `player_snapshot.js` / `index.html`. Re-run `tests/test_player_snapshot_dom.py` + the snapshot tests after each fix.
- [ ] **Step 3: Verify against the render** using the preview tools (companion loads `:8888`): `preview_start`, `preview_snapshot` for structure, `preview_inspect` for the dial band colors + font sizes (do NOT trust a screenshot for color/size - memory `reference_overlay_live_verify_technique`). Capture one `preview_screenshot` of the Home card + one of the PGR card as proof.
- [ ] **Step 4: Commit any audit fixes**

```bash
git add web/css/panels/player_snapshot.css web/js/panels/player_snapshot.js web/index.html
git commit -F <ascii-tmpfile>   # "fix(ui): player-snapshot fixture-audit MUST-FIX resolutions"
```

---

## Task 10: verifier gate + relevant-tier suite + push

**Files:** none (verification + ship).

- [ ] **Step 1: Run the relevant-tier suite fresh** (Tier-1/2 scope - core module + web routes + DOM/snapshot; NOT the DS dual-suite):

```bash
...python.exe -m pytest tests/test_player_gpi_window.py tests/test_routes_player_snapshot.py tests/test_player_snapshot_dom.py tests/test_routes_player_profile.py tests/test_last_match_role_grade_dom.py tests/snapshot_panels/test_player_snapshot_view.py tests/snapshot_panels/test_home_snapshot_card.py tests/snapshot_panels/test_last_match_view.py tests/snapshot_panels/test_view_profile_radar.py -v
```
Expected: all PASS. Record the exact pass/fail counts observed THIS run (CLAUDE.md Verification Discipline - never carry a count forward).

- [ ] **Step 2: Dispatch the read-only `verifier` subagent** to independently re-run the suite from clean, confirm every cited test file exists on disk, and cross-check the pass counts (memory `feedback_verify_generated_reports`). Do not trust a self-reported green.
- [ ] **Step 3: precommit gate + ruff on the full staged set**

```bash
...python.exe -m ruff check core/player_gpi.py dashboard/routes_player_snapshot.py dashboard/_dispatch.py
```
Expected: no net-new findings (the PreToolUse precommit gate also enforces this + the ASCII glyph ban).

- [ ] **Step 4: Restart RC + live-verify the route** (asset-only JS/CSS auto-reloads via ADR-008, but the new Python route needs a reload):

```bash
echo restart > "C:\Riot Commander\restart_trigger.txt"
```
Then confirm health + the live route:
```bash
curl -k "https://127.0.0.1:8888/api/player-snapshot?mode=sr&hours=24"
```
Read `ops/runtime/health.json`: confirm new `pid`, `alive=true`, `last_reload_ok=true`. The curl returns a valid model (or a friendly `empty:true` if no recent games) - never a raw error.

- [ ] **Step 5: Push** (branch `feat/player-snapshot-card`, only when green):

```bash
git push origin feat/player-snapshot-card
```

- [ ] **Step 6: Append the LEDGER entry** to `docs/LEDGER.md` (newest-first; NOT CLAUDE.md) summarizing the card + the Home/PGR de-dup, then confirm CI green.

---

## Self-Review (against the spec)

**Spec coverage:**
- 2 (reuse) -> Tasks 1-8 reuse `player_gpi`, `post_game_rubric`, `tokens.css`, `player_gpi.js`. Covered.
- 3 locked decisions: self-only (no opponent fetch - covered), Home+PGR same component (Tasks 5-7), de-dup (Tasks 6-7 tables), baseline-per-context (Task 4 GPI vs Task 7 rubric), rc-shell companion host (plan header - v1 companion auto-loads), View Profile radar (Task 8), K-P inferred (Task 2/4). Covered.
- 4.1 presentational -> Task 5. 4.2 model -> contract block + Task 5. 4.3 adapters -> Tasks 6/7. 4.4 bars -> Task 4 (Home) + Task 7 (PGR). 4.5 dial bands -> dial-band block, Tasks 4/7. 4.6 tags -> Task 3. Covered.
- 5.1 player_gpi -> Tasks 1/2. 5.2 route -> Task 4. Covered.
- 6 empty/degraded -> Task 4 (`empty` model) + Task 5 (reserved slot / `-` sentinel). Covered.
- 7.1 Home reorg -> Task 6. 7.2 PGR reorg -> Task 7. Covered.
- 9 testing plan -> each task is TDD-first; the six named test areas map to Tasks 1/2/3/4/7. Covered.
- 10 UI audit -> Task 9. 11 frozen-file -> Global Constraints (none touched). Covered.

**Placeholder scan:** `_fmt_kda` is flagged in Task 4 with an explicit fold-forward fix (add `kda_mean` to `compute_gpi` in Task 2, assert it in Task 4 Step 1 first). No other placeholders. Frontend tasks name exact element ids + function anchors + the test that pins each call site; the implementer greps current line numbers during TDD (they drift; the ids/function names are stable).

**Type consistency:** `renderPlayerSnapshot(el, model)` signature identical across Tasks 5/6/7/8. `compute_gpi(..., since_ts=)` param + `window_n`/`win_streak`/`win_rate`/`kp_pct`/`kda_mean`/`strongest_axis` payload keys consistent across Tasks 1/2/4. `_derive_snapshot_tags` / `_build_snapshot_model` names consistent across Tasks 3/4. Dial band cutoffs (65/35) identical in the dial-band block + Tasks 4/7. Tag vocabulary identical in the vocab block + Task 3.
