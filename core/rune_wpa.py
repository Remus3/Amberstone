"""Per-rune (keystone + minor) Win Probability Added (WPA) over RC's own
rewind corpus.

The pre-game analog of ``core.item_wpa`` / ``core.skill_wpa``. The
decision-bearing rune choices are made BEFORE the game starts (in champ
select), so unlike an item purchase or a skill max there is no mid-game
frame at which the choice "locks in". The expected baseline is therefore
the win-probability at the EARLIEST timeline frame - the start-of-game
state, which for an even lobby is ~0.5 - rather than a state estimated at
some later event timestamp. This is the honest pre-game handling: a rune
neither led nor trailed the team when it was chosen, so its observed
winrate is compared against the start-of-game expectation.

    rune_wpa = winrate_observed - winrate_expected

where ``winrate_expected`` is the mean ``core.post_game_score`` win-prob of
the running participant's TEAM at the earliest frame, and
``winrate_observed`` is whether that team actually won. A positive residual
means that rune correlates with winning beyond the (near-coinflip) baseline
the choice was made under; a negative residual means the rune is a habitual
pick that the operator's play, not the rune, carries.

The unit is ``(rune_id, slot_kind)`` where ``slot_kind`` is "keystone"
(the primary-tree row-0 keystone, e.g. Electrocute) or "minor" (any of the
remaining primary + secondary perk selections). Stat shards
(``statPerks`` - the 5000-series flat-stat picks) are EXCLUDED: they are
not named runes in ``runesReforged.json`` and the operator does not "choose"
them the way they choose a keystone. The keystone vs minor split keeps a
keystone's residual from being diluted by the dozens of minor picks that
share a tree.

HONEST FRAMING - same as item_wpa / skill_wpa: a DESCRIPTIVE personal-corpus
lens, NOT a global meta winrate and NOT redistributable. Runes are an even
WEAKER per-choice signal than items (a keystone is largely champion-fixed -
most kits have one obvious keystone), so the ``min_n`` gate + the ``shrink``
damping are LOAD-BEARING; a low-N rune must NOT surface a confident wpa.

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

log = logging.getLogger("rc.rune_wpa")


def _proc_modeled_rune_ids() -> frozenset:
    """Rune ids the DS engine mechanically models as a combat proc
    (``agents.daemon_slayer.rune_procs.RUNE_PROCS``). DSP4 cross-links the
    EMPIRICAL WPA lens here with the MECHANICAL proc model so a WPA row can
    flag whether the rune also has a modeled combat proc. Fail-soft: a
    missing/broken engine import degrades to an empty set -> every row
    proc_modeled=False, so the rune-WPA panel never breaks on the cross-link.
    The degrade is LOGGED: a silent empty set reads as "no rune has a
    modeled proc", which is a wrong answer, not an absent one."""
    try:
        from agents.daemon_slayer.rune_procs import RUNE_PROCS  # noqa: PLC0415
        return frozenset(RUNE_PROCS.keys())
    except Exception as exc:  # noqa: BLE001 - the panel must survive any engine error
        log.warning("rune_wpa: agents.daemon_slayer.rune_procs unavailable, "
                    "every proc_modeled flag is False -> %s: %s",
                    type(exc).__name__, exc)
        return frozenset()


_PROC_MODELED_RUNE_IDS = _proc_modeled_rune_ids()

# DDragon runesReforged catalog for rune-id -> display name. The DEFAULT
# resolves the patch-current bundle via _index.json ``latest_pulled`` (the
# marker lib.ddragon.fetch maintains); _RUNES_JSON is the pinned
# authoring-time fallback (verified at 16.11.1; names are stable across
# recent patches). The dynamic resolve is load-bearing: the bundle cache
# keeps only a current+previous window (item 397 prune), so a fixed pin
# goes stale on the next patch and VANISHES one patch later, silently
# emptying the rune-WPA panel (deep-audit P2 W1-C). Anchored to the repo
# root, never the CWD (RM-1022).
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DDRAGON_DIR = _DATA_DIR / "meta_build" / "ddragon"
_REWIND_DB = _DATA_DIR / "rewind_history.db"
_RUNES_JSON = _DDRAGON_DIR / "16.11.1" / "runesReforged.json"


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


def _default_runes_json() -> Path:
    """Patch-current runes catalog path, pinned-snapshot fallback.

    Prefers ``<latest_pulled>/runesReforged.json`` when that file exists;
    otherwise the pinned ``_RUNES_JSON`` (the pre-fix behavior). Fail-soft:
    any IO error degrades to the pin.
    """
    ver = _latest_pulled_version()
    if ver:
        try:
            cand = _DDRAGON_DIR / ver / "runesReforged.json"
            if cand.is_file():
                return cand
        except OSError:
            pass
    return _RUNES_JSON

# Shrink constant; same rationale as item_wpa / skill_wpa (personal corpus).
_SHRINK_K = 5.0

# slot_kind labels.
_KEYSTONE = "keystone"
_MINOR = "minor"

# What a malformed MATCH (bad frame / participant values) can raise inside
# the per-match sweep. Deliberately narrow, mirroring core.item_wpa:
# sqlite3.Error is not here (it must propagate - a locked DB is not a bad
# row), and neither is any other class (a defect must surface, not be
# logged once per match and answered ok=True).
_MATCH_DATA_ERRORS = (TypeError, ValueError, ArithmeticError)


def _opt_int(value: object) -> int | None:
    """``int(value)``, or ``None`` when it is missing, a bool or not a
    number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _dicts(value: object) -> list[dict]:
    """The dict entries of ``value`` when it is a list, else ``[]``."""
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, dict)]


def load_rune_catalog(
    runes_json: Path | None = None,
) -> dict[int, tuple[str, str]]:
    """Return ``{rune_id: (name, icon)}`` for every named rune in the
    runesReforged catalog (keystones + minors across all trees). ``icon``
    is the DDragon perk-images relative path (e.g.
    ``perk-images/Styles/Domination/Electrocute/Electrocute.png``). Stat
    shards are NOT in this file, so they are naturally absent.

    Fail-soft: a missing, unparseable or wrong-shape catalog returns
    ``{}``. A tree / slot / rune entry that is not an object, a ``slots``
    or ``runes`` field that is not a list, and a rune whose id is missing,
    a bool or not a number are each skipped; the rest is kept.
    """
    path = Path(runes_json) if runes_json is not None else _default_runes_json()
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as exc:
        log.warning("load_rune_catalog: %s -> %s", path, exc)
        return {}
    if not isinstance(raw, list):
        log.warning("load_rune_catalog: %s -> not a list of rune trees", path)
        return {}
    out: dict[int, tuple[str, str]] = {}
    for tree in _dicts(raw):
        for slot in _dicts(tree.get("slots")):
            for rune in _dicts(slot.get("runes")):
                rid = _opt_int(rune.get("id"))
                if rid is None:
                    continue
                out[rid] = (str(rune.get("name") or rid),
                            str(rune.get("icon") or ""))
    return out


def load_rune_names(runes_json: Path | None = None) -> dict[int, str]:
    """Return ``{rune_id: name}`` for every named rune (thin view over
    ``load_rune_catalog``). Stat shards are absent. Fail-soft -> ``{}``."""
    return {rid: name for rid, (name, _icon)
            in load_rune_catalog(runes_json).items()}


def _participant_runes(
    conn: sqlite3.Connection, match_id: str
) -> dict[int, tuple[int, int, list[int]]]:
    """Return ``{participant_id: (team_id, win, [keystone, *minors])}``.

    The first id in the rune list is the keystone (``rune_keystone_id``,
    which mirrors ``rune_p0``); the rest are the minor selections
    (``rune_p1..p3`` + ``rune_s0..s1``). Authoritative from the
    ``participants`` table. A participant whose id / team / win is not a
    number is absent. A rune column that is NULL or not a number reads as
    0 (an empty slot the caller skips), so one malformed rune drops that
    rune only - never the participant, never the rest of the match.
    """
    cur = conn.execute(
        "SELECT participant_id, team_id, win, rune_keystone_id, "
        "rune_p1, rune_p2, rune_p3, rune_s0, rune_s1 "
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
        rune_ids = [_opt_int(v) or 0 for v in row[3:9]]
        out[pid] = (team_id, win, rune_ids)
    return out


def compute_rune_wpa(
    conn: sqlite3.Connection,
    *,
    min_n: int = 20,
    queue_id: int | None = None,
    patch: str | None = None,
    model: WpaModel | None = None,
    runes_json: Path | None = None,
) -> dict:
    """Decompose each ``(rune, slot_kind)`` winrate into expected vs
    observed over the local rewind corpus.

    For every participant of every qualifying match, take the EARLIEST
    timeline frame (the pre-game baseline), estimate that team's win-prob
    there (expected), and record whether the team won (observed). The
    participant's keystone and each minor rune each accumulate a sample.
    Per ``(rune_id, slot_kind)``:

        observed_winrate = mean(observed)
        expected_winrate = mean(expected)
        wpa              = observed_winrate - expected_winrate
        wpa_shrunk       = wpa * shrink(n)

    Keys with ``n < min_n`` are gated out. ``queue_id`` / ``patch``
    optionally restrict the match set. Rune id 0 (empty slot) and stat
    shards (ids not present in runesReforged) are skipped.

    Returns ``{ok, patch, queue_id, min_n, items: [...], elapsed_ms}`` where
    each row is ``{rune_id, name, slot_kind, n, observed_winrate,
    expected_winrate, wpa, wpa_shrunk}`` sorted by ``wpa_shrunk`` desc.

    A participant contributes at most ONE sample per ``(rune_id,
    slot_kind)``: a rune repeated across a corrupt row's minor slots is
    counted once.

    ``min_n`` must be an ``int >= 0`` (``bool`` refused); anything else is
    a ``ValueError`` raised before the sweep.

    Fail-soft on DATA, fail-loud on everything else (the core.item_wpa
    contract):
      * a match with no frames or no participants is skipped, and a
        malformed rune column skips that rune only;
      * a match whose frames are malformed (``TypeError`` / ``ValueError``
        / ``ArithmeticError``) is skipped WHOLE: its contribution is rolled
        back, so a skipped match is never half-counted;
      * ``sqlite3.Error`` (for example "database is locked") PROPAGATES - a
        partial sweep must not be served, or cached, as a complete corpus
        (/api/rune-wpa maps it to a 503);
      * any other exception is a defect and propagates too.
    """
    if isinstance(min_n, bool) or not isinstance(min_n, int) or min_n < 0:
        raise ValueError("min_n must be an int >= 0")
    t0 = time.perf_counter()
    catalog = load_rune_catalog(runes_json)

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

    # Accumulators keyed by (rune_id, slot_kind).
    n_obs: dict[tuple[int, str], int] = {}
    sum_obs: dict[tuple[int, str], float] = {}
    sum_exp: dict[tuple[int, str], float] = {}

    for mid in match_ids:
        # Per-match observations, merged only when the whole match is read
        # cleanly, so a match skipped half-way contributes nothing.
        obs: list[tuple[tuple[int, str], float, float]] = []
        try:
            frames = _load_frames(conn, mid)
            if not frames:
                continue
            # Pre-game baseline = the EARLIEST frame's state.
            base_ts_ms, base_rows = frames[0]
            runes = _participant_runes(conn, mid)
            if not runes:
                continue
            base_t_s = float(base_ts_ms or 0) / 1000.0
            for team_id, win, rune_ids in runes.values():
                exp = _expected_win_for_team(base_rows, base_t_s, team_id,
                                             model)
                if exp is None:
                    continue
                seen: set[tuple[int, str]] = set()
                for idx, rid in enumerate(rune_ids):
                    if rid <= 0 or rid not in catalog:
                        continue
                    key = (rid, _KEYSTONE if idx == 0 else _MINOR)
                    if key in seen:  # one sample per participant per key
                        continue
                    seen.add(key)
                    obs.append((key, float(win), float(exp)))
        except _MATCH_DATA_ERRORS as exc:
            log.warning("compute_rune_wpa: match %s skipped -> %s: %s",
                        mid, type(exc).__name__, exc)
            continue
        for key, win_f, exp_f in obs:
            n_obs[key] = n_obs.get(key, 0) + 1
            sum_obs[key] = sum_obs.get(key, 0.0) + win_f
            sum_exp[key] = sum_exp.get(key, 0.0) + exp_f

    items_out: list[dict] = []
    for (rid, slot_kind), n in n_obs.items():
        if n < min_n:
            continue
        observed = sum_obs[(rid, slot_kind)] / n
        expected = sum_exp[(rid, slot_kind)] / n
        wpa = observed - expected
        wpa_shrunk = wpa * shrink(float(n), _SHRINK_K)
        name, icon = catalog.get(rid, (str(rid), ""))
        items_out.append({
            "rune_id": rid,
            "name": name,
            "icon": icon,
            "slot_kind": slot_kind,
            "n": n,
            "proc_modeled": rid in _PROC_MODELED_RUNE_IDS,
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
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


def compute_rune_wpa_from_db(
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
    the DB is absent (or the path is not a regular file). ``sqlite3.Error``
    from the sweep propagates (see ``compute_rune_wpa``).

    The read-only URI goes through ``Path.as_uri``, which percent-encodes
    the path: an f-string ``file:{path}?mode=ro`` let a '#' in the checkout
    path cut the URI short, so SQLite opened (and, with ``?mode=ro`` lost
    in the fragment, CREATED) a different file.
    """
    src = Path(db_path) if db_path is not None else _REWIND_DB
    if not src.is_file():
        return {"ok": False, "error": "rewind_history.db missing"}
    model = load_model(model_path)
    uri = src.absolute().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    try:
        return compute_rune_wpa(
            conn, min_n=min_n, queue_id=queue_id, patch=patch, model=model
        )
    finally:
        conn.close()
