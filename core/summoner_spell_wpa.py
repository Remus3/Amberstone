"""Per-summoner-spell Win Probability Added (WPA) over RC's own rewind
corpus.

The pre-game sibling of ``core.rune_wpa`` (and the third leaf of the
``core.item_wpa`` / ``core.skill_wpa`` family). Summoner spells are picked
BEFORE the game starts (in champ select), so unlike an item purchase or a
skill max there is no mid-game frame at which the choice "locks in". The
expected baseline is therefore the win-probability at the EARLIEST timeline
frame - the start-of-game state, which for an even lobby is ~0.5 - rather
than a state estimated at some later event timestamp. This is the honest
pre-game handling: a spell neither led nor trailed the team when it was
chosen, so its observed winrate is compared against the start-of-game
expectation.

    spell_wpa = winrate_observed - winrate_expected

where ``winrate_expected`` is the mean ``core.post_game_score`` win-prob of
the running participant's TEAM at the earliest frame, and
``winrate_observed`` is whether that team actually won. A positive residual
means that spell correlates with winning beyond the (near-coinflip)
baseline the choice was made under; a negative residual means the spell is
a habitual pick that the operator's play, not the spell, carries.

The unit is the single ``spell_id``: each participant row contributes its
two picks (``summoner1_id`` + ``summoner2_id``) as independent samples.
There is no secondary grouping - rune_wpa's keystone/minor split is a
slot-attribute split with no spell analog (D vs F slot order is a keybind
preference, not a choice), and a per-PAIR grouping would halve every n
under an already weak signal.

HONEST FRAMING - same as item_wpa / skill_wpa / rune_wpa: a DESCRIPTIVE
personal-corpus lens, NOT a global meta winrate and NOT redistributable.
Summoner spells are an even WEAKER per-choice signal than items (Flash is
near-universal; many modes force the second pick), so the ``min_n`` gate +
the ``shrink`` damping are LOAD-BEARING; a low-N spell must NOT surface a
confident wpa.

Reuse, not reinvention: the frame grouping + win-prob machinery is shared
with ``core.item_wpa`` (``_load_frames`` / ``_expected_win_for_team``) and
``core.post_game_score``. No new dependency (stdlib sqlite3 + json).
Connection-injected so a test can pass an in-memory sqlite fixture.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

from core.item_wpa import _expected_win_for_team, _load_frames
from core.post_game_score import WpaModel, load_model
from core.smoothed_rates import shrink

log = logging.getLogger("rc.summoner_spell_wpa")

# DDragon summoner-spell catalog for spell-id -> display name + icon slug.
# The DEFAULT resolves the patch-current bundle via _index.json
# ``latest_pulled`` (the marker lib.ddragon.fetch maintains);
# _SUMMONER_JSON is the pinned authoring-time fallback (verified at
# 16.11.1; ids/names are stable across recent patches). The dynamic
# resolve is load-bearing: the bundle cache keeps only a current+previous
# window (item 397 prune), so a fixed pin goes stale on the next patch and
# VANISHES one patch later, silently emptying the spell-WPA panel
# (deep-audit P2 W1-C). Mirrors core.rune_wpa.
_DDRAGON_DIR = Path("data") / "meta_build" / "ddragon"
_SUMMONER_JSON = _DDRAGON_DIR / "16.11.1" / "summoner.json"


def _latest_pulled_version() -> str:
    """The bundle version ``lib.ddragon.fetch`` recorded as current in
    ``_index.json`` (``latest_pulled``). "" when absent/malformed."""
    try:
        doc = json.loads(
            (_DDRAGON_DIR / "_index.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return ""
    ver = doc.get("latest_pulled") if isinstance(doc, dict) else ""
    return str(ver or "").strip()


def _default_summoner_json() -> Path:
    """Patch-current summoner catalog path, pinned-snapshot fallback.

    Prefers ``<latest_pulled>/summoner.json`` when that file exists;
    otherwise the pinned ``_SUMMONER_JSON`` (the pre-fix behavior).
    Fail-soft: any IO error degrades to the pin.
    """
    ver = _latest_pulled_version()
    if ver:
        try:
            cand = _DDRAGON_DIR / ver / "summoner.json"
            if cand.is_file():
                return cand
        except OSError:
            pass
    return _SUMMONER_JSON

# Shrink constant; same rationale as item_wpa / skill_wpa / rune_wpa
# (personal corpus).
_SHRINK_K = 5.0


def load_spell_catalog(
    summoner_json: Path | None = None,
) -> dict[int, tuple[str, str]]:
    """Return ``{spell_id: (name, icon)}`` for every summoner spell in the
    DDragon catalog. ``icon`` is the DDragon spell id slug (e.g.
    ``SummonerFlash``), which is both the local icon filename under
    ``/icons/spells/<slug>.png`` and the CDN ``img/spell/<slug>.png`` stem.

    Fail-soft: a missing or unparseable catalog returns ``{}``.
    """
    path = (
        Path(summoner_json) if summoner_json is not None
        else _default_summoner_json()
    )
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as exc:
        log.warning("load_spell_catalog: %s -> %s", path, exc)
        return {}
    out: dict[int, tuple[str, str]] = {}
    data = raw.get("data") if isinstance(raw, dict) else None
    for slug, spell in (data or {}).items():
        if not isinstance(spell, dict):
            continue
        try:
            sid = int(spell.get("key"))
        except (TypeError, ValueError):
            continue
        out[sid] = (str(spell.get("name") or sid),
                    str(spell.get("id") or slug))
    return out


def load_spell_names(summoner_json: Path | None = None) -> dict[int, str]:
    """Return ``{spell_id: name}`` (thin view over ``load_spell_catalog``).
    Fail-soft -> ``{}``."""
    return {sid: name for sid, (name, _icon)
            in load_spell_catalog(summoner_json).items()}


def _participant_spells(
    conn: sqlite3.Connection, match_id: str
) -> dict[int, tuple[int, int, list[int]]]:
    """Return ``{participant_id: (team_id, win, [spell1, spell2])}``.

    Authoritative from the ``participants`` table ``summoner1_id`` /
    ``summoner2_id`` columns. A participant with no spell columns is absent.
    """
    cur = conn.execute(
        "SELECT participant_id, team_id, win, summoner1_id, summoner2_id "
        "FROM participants WHERE match_id=?",
        (match_id,),
    )
    out: dict[int, tuple[int, int, list[int]]] = {}
    for row in cur:
        try:
            pid = int(row[0])
            team_id = int(row[1] or 0)
            win = int(row[2] or 0)
        except (TypeError, ValueError):
            continue
        spells = [int(row[3] or 0), int(row[4] or 0)]
        out[pid] = (team_id, win, spells)
    return out


def compute_summoner_spell_wpa(
    conn: sqlite3.Connection,
    *,
    min_n: int = 20,
    queue_id: int | None = None,
    patch: str | None = None,
    model: WpaModel | None = None,
    summoner_json: Path | None = None,
) -> dict:
    """Decompose each summoner spell's winrate into expected vs observed
    over the local rewind corpus.

    For every participant of every qualifying match, take the EARLIEST
    timeline frame (the pre-game baseline), estimate that team's win-prob
    there (expected), and record whether the team won (observed). Each of
    the participant's two spells accumulates a sample. Per ``spell_id``:

        observed_winrate = mean(observed)
        expected_winrate = mean(expected)
        wpa              = observed_winrate - expected_winrate
        wpa_shrunk       = wpa * shrink(n)

    Keys with ``n < min_n`` are gated out. ``queue_id`` / ``patch``
    optionally restrict the match set. Spell id 0 (empty slot) and ids not
    present in the DDragon catalog are skipped.

    Returns ``{ok, patch, queue_id, min_n, items: [...], elapsed_ms}`` where
    each row is ``{spell_id, name, icon, n, observed_winrate,
    expected_winrate, wpa, wpa_shrunk}`` sorted by ``wpa_shrunk`` desc.

    Fail-soft: a match with no frames is skipped; each match is wrapped so
    one bad row cannot abort the sweep.
    """
    t0 = time.time()
    catalog = load_spell_catalog(summoner_json)

    where = ["has_timeline=1"]
    params: list = []
    if queue_id is not None:
        where.append("queue_id=?")
        params.append(int(queue_id))
    if patch is not None:
        where.append("patch=?")
        params.append(str(patch))
    sql = "SELECT match_id FROM matches WHERE " + " AND ".join(where)
    match_ids = [r[0] for r in conn.execute(sql, params).fetchall()]

    # Accumulators keyed by spell_id.
    n_obs: dict[int, int] = {}
    sum_obs: dict[int, float] = {}
    sum_exp: dict[int, float] = {}

    for mid in match_ids:
        try:
            frames = _load_frames(conn, mid)
            if not frames:
                continue
            # Pre-game baseline = the EARLIEST frame's state.
            base_ts_ms, base_rows = frames[0]
            spells = _participant_spells(conn, mid)
            if not spells:
                continue
            for _pid, (team_id, win, spell_ids) in spells.items():
                exp = _expected_win_for_team(
                    base_rows, float(base_ts_ms or 0) / 1000.0, team_id, model
                )
                if exp is None:
                    continue
                for sid in spell_ids:
                    if sid <= 0 or sid not in catalog:
                        continue
                    n_obs[sid] = n_obs.get(sid, 0) + 1
                    sum_obs[sid] = sum_obs.get(sid, 0.0) + float(win)
                    sum_exp[sid] = sum_exp.get(sid, 0.0) + exp
        except Exception as exc:  # noqa: BLE001 - one bad match cannot abort
            log.warning("compute_summoner_spell_wpa: match %s -> %s", mid, exc)
            continue

    items_out: list[dict] = []
    for sid, n in n_obs.items():
        if n < min_n:
            continue
        observed = sum_obs[sid] / n
        expected = sum_exp[sid] / n
        wpa = observed - expected
        wpa_shrunk = wpa * shrink(float(n), _SHRINK_K)
        name, icon = catalog.get(sid, (str(sid), ""))
        items_out.append({
            "spell_id": sid,
            "name": name,
            "icon": icon,
            "n": n,
            "observed_winrate": round(observed, 4),
            "expected_winrate": round(expected, 4),
            "wpa": round(wpa, 4),
            "wpa_shrunk": round(wpa_shrunk, 4),
        })

    items_out.sort(key=lambda it: it["wpa_shrunk"], reverse=True)

    return {
        "ok": True,
        "patch": patch,
        "queue_id": queue_id,
        "min_n": min_n,
        "items": items_out,
        "elapsed_ms": int((time.time() - t0) * 1000),
    }


def compute_summoner_spell_wpa_from_db(
    db_path: Path | None = None,
    *,
    min_n: int = 20,
    queue_id: int | None = None,
    patch: str | None = None,
    model_path: Path | None = None,
) -> dict:
    """Convenience wrapper: open ``rewind_history.db`` read-only, load the
    persisted WPA model (or fall back), compute, close.

    Returns ``{"ok": False, "error": "rewind_history.db missing"}`` when
    the DB is absent.
    """
    src = Path(db_path) if db_path is not None else (Path("data") / "rewind_history.db")
    if not src.exists():
        return {"ok": False, "error": "rewind_history.db missing"}
    model = load_model(model_path)
    conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=5.0)
    try:
        return compute_summoner_spell_wpa(
            conn, min_n=min_n, queue_id=queue_id, patch=patch, model=model
        )
    finally:
        conn.close()
