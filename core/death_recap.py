"""
core/death_recap.py - RM-608 / X-08 (external reference B, clean-room).

ESTIMATED death recap ("what killed you"), Tier A: deterministic, no LLM, no
OCR. Everything this module emits is a MODEL, not a measurement, and is tagged
``provenance="estimated"`` on every row and every line of text.

Why estimated
-------------
The modern Live Client exposes only ``ChampionKill`` (KillerName, VictimName,
Assisters, EventTime). There is no per-hit damage log, so the physical / magic
/ true split of a death is reconstructed from the contributors' builds:

  1. Snapshot the killer and assisters from allgamedata (champion, level,
     items). Names are resolved against allPlayers by player name first
     (summonerName / riotIdGameName / riotId, with or without the #TAG), then
     by champion name: RM-673 found KillerName may carry either form.
  2. For each contributor, ask Daemon Slayer for a single-combo BURST profile
     against OUR live resists (``core.daemon_slayer_client.burst_for`` ->
     ``POST /burst``). Route choice, measured:
       * ``POST /rank`` is forbidden for this use (directive).
       * ``/dps`` returns a weighted AA DPS scalar with no damage-type field
         (agents/daemon_slayer/dps.py DpsResult.to_dict), so it cannot split.
       * ``/rank-<archetype>`` ranks candidate ITEMS, not a build's damage.
       * ``/burst`` returns ``per_cast[]`` rows each carrying ``damage_type``
         (PHYSICAL / MAGIC / TRUE, AA rows PHYSICAL) and ``final_damage``
         already mitigated by the target armor / MR we send
         (agents/daemon_slayer/burst.py ComboCast.to_dict). That is the split.
     Seam transport: this call arms NO seam. It sends only the base keys
     (champion, level, items, mode, target_armor, target_mr, target_max_hp),
     all parsed by server.py ``_route_burst``; every DEFAULT-OFF seam stays
     omitted, so the body is byte-identical to a default /burst call.
     Untyped burst extras (spellblade, rune procs) are not in per_cast and are
     not counted.
  3. LOCAL FALLBACK when DS is down, slow, or returns no typed row: DDragon
     ``info.attack`` / ``info.magic`` (1..10 ratings RC already ships in
     data/meta/ddragon_champions.json, read via
     ``core.defensive_picks.compute_threat_profile``), each scaled by the
     standard resist multiplier for our live armor / MR. True share is 0 on
     this path (DDragon has no true-damage rating).

Combining contributors
----------------------
When EVERY champion contributor has a usable DS profile, each contributor's
split is weighted by its modelled mitigated burst total (basis "ds"). If any
contributor fell back, magnitudes are not comparable across the two sources,
so weights become fixed: killer ``KILLER_WEIGHT``, assister ``ASSIST_WEIGHT``
(basis "local" or "mixed"). Those weights are OUR OWN choice, not measured.

Rows never carry player names (public-repo hygiene): contributors are stored by
champion name only.

Wiring
------
``install_if_enabled()`` registers ``on_liveclient_snapshot`` on
``core.liveclient_cache.add_listener``; it is called from
``core.liveclient_cache._install_optional_taps()`` in its own try-block.
DEFAULT OFF: env ``RC_DEATH_RECAP`` must be truthy. The listener only detects
new own-death ChampionKill events by EventID high-water (cheap) and hands the
work to ONE daemon worker thread, so DS calls never run on the poll loop.
core/decision_detector.py and core/event_callouts.py are not touched.

Persistence: one JSON line per recap in ``DEFAULT_RECAPS_PATH``
(data/coaching/death_recaps.jsonl, gitignored). The log is append-only, so the
tmp+replace rule for state files does not apply (same reasoning as
core/live_session_recorder.py); a single writer lock keeps lines whole and
``read_rows`` skips a torn line. scripts/postmortem_analyze.py aggregates it
into the ``damage_recap`` section of data/coaching/death_patterns.json.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

_log = logging.getLogger("rc.death_recap")

FLAG_ENV = "RC_DEATH_RECAP"
_TRUTHY = frozenset({"1", "true", "yes", "on"})
PROVENANCE = "estimated"
ROW_SCHEMA = 1

_PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_RECAPS_PATH = _PROJECT_DIR / "data" / "coaching" / "death_recaps.jsonl"

# Our own choices (not measured): per-call DS timeout is kept under the client
# default (0.5s) and the engine-up probe is the client's own 0.25s default.
DS_TIMEOUT_S = 0.4
KILLER_WEIGHT = 2.0
ASSIST_WEIGHT = 1.0
# A new game is assumed when gameTime drops by more than this (seconds).
_GAME_RESET_DROP_S = 5.0
_QUEUE_MAX = 16
WORKER_THREAD_NAME = "rc-death-recap-worker"

# Live Client gameMode -> DS mode string. Unknown modes fall back to SR.
_DS_MODE_BY_GAMEMODE = {
    "CLASSIC": "SR",
    "ARAM": "ARAM",
    "KIWI": "ARAM",
    "CHERRY": "ARENA",
}

_TYPE_ALIASES = {
    "physical": "physical",
    "magic": "magic",
    "magical": "magic",
    "true": "true",
}


# -- small pure helpers -------------------------------------------------------

def _as_dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _norm(s: Any) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def _name_keys(name: Any) -> set[str]:
    """Normalized keys for a Live Client name: full form plus the part before
    any '#TAG', so 'Name#TAG' and 'Name' both match."""
    if not isinstance(name, str) or not name.strip():
        return set()
    keys = {_norm(name)}
    if "#" in name:
        keys.add(_norm(name.split("#", 1)[0]))
    keys.discard("")
    return keys


def _player_name_keys(p: Mapping) -> set[str]:
    out: set[str] = set()
    for k in ("summonerName", "riotIdGameName", "riotId"):
        out |= _name_keys(p.get(k))
    return out


def _all_players(data: Any) -> list[dict]:
    raw = _as_dict(data).get("allPlayers")
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, dict)]


def _events(data: Any) -> list[dict]:
    raw = _as_dict(_as_dict(data).get("events")).get("Events")
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict)]


def _num(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if f == f else default  # NaN guard


def active_player_keys(data: Any) -> set[str]:
    """Normalized name keys identifying the active player (activePlayer
    summonerName / riotIdGameName / riotId)."""
    return _player_name_keys(_as_dict(_as_dict(data).get("activePlayer")))


def is_self_death(kill_event: Any, data: Any) -> bool:
    ev = _as_dict(kill_event)
    if ev.get("EventName") != "ChampionKill":
        return False
    me = active_player_keys(data)
    return bool(me) and bool(_name_keys(ev.get("VictimName")) & me)


def resolve_player(name: Any, all_players: list[dict]) -> Optional[dict]:
    """Resolve a KillerName / Assister entry to an allPlayers row.

    RM-673: the field may carry a player name OR a champion name. Player-name
    match wins; a champion-name match is accepted only when it is unique.
    Structures / minions / monsters resolve to None."""
    keys = _name_keys(name)
    if not keys:
        return None
    for p in all_players:
        if keys & _player_name_keys(p):
            return p
    hits = [p for p in all_players if _norm(p.get("championName")) in keys]
    return hits[0] if len(hits) == 1 else None


def _items_of(p: Mapping) -> list[str]:
    out: list[str] = []
    raw = p.get("items")
    if not isinstance(raw, list):
        return out
    for it in raw:
        iid = _as_dict(it).get("itemID")
        if isinstance(iid, (int, str)) and str(iid).strip() and str(iid) != "0":
            out.append(str(iid))
    return out


def resolve_contributors(kill_event: Any, data: Any) -> list[dict]:
    """Killer then assisters, champion contributors only, de-duplicated.
    Each: {role, champion, level, items}. No player names."""
    ev = _as_dict(kill_event)
    players = _all_players(data)
    names: list[tuple[str, Any]] = [("killer", ev.get("KillerName"))]
    assisters = ev.get("Assisters")
    if isinstance(assisters, list):
        names += [("assister", a) for a in assisters]
    out: list[dict] = []
    seen: set[int] = set()
    for role, nm in names:
        p = resolve_player(nm, players)
        if p is None or id(p) in seen:
            continue
        seen.add(id(p))
        champ = p.get("championName")
        if not isinstance(champ, str) or not champ:
            continue
        out.append({
            "role": role,
            "champion": champ,
            "level": int(_num(p.get("level"), 1.0)) or 1,
            "items": _items_of(p),
        })
    return out


def our_resists_from(data: Any) -> dict:
    stats = _as_dict(_as_dict(_as_dict(data).get("activePlayer")).get("championStats"))
    return {
        "armor": _num(stats.get("armor")),
        "mr": _num(stats.get("magicResist")),
        "max_hp": _num(stats.get("maxHealth")),
    }


def ds_mode_for(data: Any) -> str:
    gm = _as_dict(_as_dict(data).get("gameData")).get("gameMode")
    return _DS_MODE_BY_GAMEMODE.get(str(gm or "").upper(), "SR")


def _resist_mult(r: float) -> float:
    """Standard League resist multiplier (our own restatement of the public
    formula): 100/(100+R) for R>=0, 2-100/(100-R) for R<0."""
    if r >= 0:
        return 100.0 / (100.0 + r)
    return 2.0 - 100.0 / (100.0 - r)


def split_from_ds_profile(profile: Any) -> Optional[tuple[float, float, float, float]]:
    """(physical, magic, true, total) from a /burst result, or None when the
    profile carries no positive typed damage."""
    rows = _as_dict(profile).get("per_cast")
    if not isinstance(rows, list):
        return None
    acc = {"physical": 0.0, "magic": 0.0, "true": 0.0}
    for r in rows:
        r = _as_dict(r)
        kind = _TYPE_ALIASES.get(str(r.get("damage_type") or "").lower())
        if kind is None:
            continue
        dmg = _num(r.get("final_damage"))
        if dmg > 0:
            acc[kind] += dmg
    total = acc["physical"] + acc["magic"] + acc["true"]
    if total <= 0:
        return None
    return (acc["physical"] / total, acc["magic"] / total, acc["true"] / total, total)


def split_from_local(champion: str, resists: Mapping) -> tuple[float, float, float]:
    """Local fallback: DDragon info.attack / info.magic scaled by our resists."""
    try:
        from core.defensive_picks import compute_threat_profile
        prof = compute_threat_profile([champion])
        atk = _num(prof.get("ad_threat"), 5.0)
        mag = _num(prof.get("ap_threat"), 5.0)
    except Exception:  # noqa: BLE001
        atk, mag = 5.0, 5.0
    phys = max(0.0, atk) * _resist_mult(_num(resists.get("armor")))
    magic = max(0.0, mag) * _resist_mult(_num(resists.get("mr")))
    tot = phys + magic
    if tot <= 0:
        return (0.5, 0.5, 0.0)
    return (phys / tot, magic / tot, 0.0)


def _finish_shares(p: float, m: float, t: float) -> dict:
    tot = p + m + t
    if tot <= 0:
        p, m, t, tot = 0.5, 0.5, 0.0, 1.0
    p, m = round(p / tot, 4), round(m / tot, 4)
    t = round(max(0.0, 1.0 - p - m), 4)
    # absorb rounding residue into the largest share so the sum is exactly 1
    resid = 1.0 - (p + m + t)
    if resid:
        if p >= m and p >= t:
            p += resid
        elif m >= t:
            m += resid
        else:
            t += resid
    return {"physical": p, "magic": m, "true": t}


# -- the pure builder ---------------------------------------------------------

def build_recap(kill_event: Any, allgamedata: Any, ds_profiles: Optional[Mapping],
                our_resists: Optional[Mapping]) -> Optional[dict]:
    """Pure: an ESTIMATED recap row for a ChampionKill on the active player,
    or None for any other event. ``ds_profiles`` maps champion name -> /burst
    result (may be empty). Never raises on malformed input."""
    try:
        if not is_self_death(kill_event, allgamedata):
            return None
        ev = _as_dict(kill_event)
        profiles = ds_profiles if isinstance(ds_profiles, Mapping) else {}
        resists = our_resists if isinstance(our_resists, Mapping) else {}
        contribs = resolve_contributors(ev, allgamedata)
        killer_is_champ = any(c["role"] == "killer" for c in contribs)
        for c in contribs:
            ds = split_from_ds_profile(profiles.get(c["champion"]))
            if ds is not None:
                c["source"] = "ds_burst"
                c["split"] = {"physical": round(ds[0], 4), "magic": round(ds[1], 4),
                              "true": round(ds[2], 4)}
                c["_ds_total"] = ds[3]
            else:
                lp = split_from_local(c["champion"], resists)
                c["source"] = "local_ddragon"
                c["split"] = {"physical": round(lp[0], 4), "magic": round(lp[1], 4),
                              "true": round(lp[2], 4)}
                c["_ds_total"] = None
        if not contribs:
            basis = "none"
            shares = None
        else:
            all_ds = all(c["source"] == "ds_burst" for c in contribs)
            any_ds = any(c["source"] == "ds_burst" for c in contribs)
            basis = "ds" if all_ds else ("mixed" if any_ds else "local")
            acc = [0.0, 0.0, 0.0]
            for c in contribs:
                w = c["_ds_total"] if all_ds else (
                    KILLER_WEIGHT if c["role"] == "killer" else ASSIST_WEIGHT)
                c["weight"] = round(float(w), 2)
                s = c["split"]
                acc[0] += w * s["physical"]
                acc[1] += w * s["magic"]
                acc[2] += w * s["true"]
            shares = _finish_shares(*acc)
        for c in contribs:
            c.pop("_ds_total", None)
        return {
            "schema": ROW_SCHEMA,
            "provenance": PROVENANCE,
            "event_id": ev.get("EventID"),
            "game_time_s": _num(ev.get("EventTime")),
            "mode": ds_mode_for(allgamedata),
            "killer_kind": "champion" if killer_is_champ else "other",
            "contributors": contribs,
            "shares": shares,
            "basis": basis,
            "our_resists": {"armor": _num(resists.get("armor")),
                            "mr": _num(resists.get("mr"))},
            "recorded_at": round(time.time(), 3),
        }
    except Exception as exc:  # noqa: BLE001
        _log.debug("death_recap build failed: %s", exc)
        return None


def format_line(row: Optional[Mapping]) -> str:
    """One ASCII panel line, always labelled 'estimated'. '' for no row."""
    if not isinstance(row, Mapping):
        return ""
    champs = ", ".join(c.get("champion", "?") for c in row.get("contributors") or [])
    shares = row.get("shares")
    if not shares:
        return f"Death recap (estimated): {champs or 'non-champion'} - no damage split"
    pct = {k: int(round(100 * _num(shares.get(k)))) for k in ("physical", "magic", "true")}
    return (f"Death recap (estimated): {champs} - "
            f"{pct['physical']}% physical / {pct['magic']}% magic / {pct['true']}% true")


# -- DS fetch (fail-soft) -----------------------------------------------------

def _default_up() -> bool:
    from core.daemon_slayer_client import is_engine_up
    return bool(is_engine_up())


def fetch_ds_profiles(contributors: list[dict], our_resists: Mapping, mode: str, *,
                      burst_fn: Optional[Callable[..., Any]] = None,
                      up_fn: Optional[Callable[[], bool]] = None,
                      timeout: float = DS_TIMEOUT_S) -> dict:
    """champion -> /burst result for each contributor. {} when the engine is
    down; any per-call failure just omits that champion. Never raises."""
    out: dict = {}
    try:
        if burst_fn is None:
            from core.daemon_slayer_client import burst_for as burst_fn  # noqa: N813
        up = up_fn or _default_up
        if not up():
            return out
    except Exception as exc:  # noqa: BLE001
        _log.debug("death_recap DS probe failed: %s", exc)
        return out
    for c in contributors or []:
        champ = c.get("champion")
        if not champ or champ in out:
            continue
        try:
            res = burst_fn(
                champ,
                level=int(c.get("level") or 1),
                item_ids=list(c.get("items") or []),
                mode=mode,
                target_armor=_num(our_resists.get("armor")),
                target_mr=_num(our_resists.get("mr")),
                target_max_hp=_num(our_resists.get("max_hp")),
                timeout=min(float(timeout), 0.5),
            )
        except Exception as exc:  # noqa: BLE001
            _log.debug("death_recap DS /burst %s failed: %s", champ, exc)
            continue
        if isinstance(res, dict):
            out[champ] = res
    return out


# -- persistence --------------------------------------------------------------

_write_lock = threading.Lock()


def append_row(row: Mapping, path: Optional[Path] = None) -> bool:
    p = Path(path) if path is not None else DEFAULT_RECAPS_PATH
    try:
        line = json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n"
        with _write_lock:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8", newline="\n") as f:
                f.write(line)
                f.flush()
        return True
    except Exception as exc:  # noqa: BLE001
        _log.debug("death_recap append failed: %s", exc)
        return False


def read_rows(path: Optional[Path] = None) -> list[dict]:
    p = Path(path) if path is not None else DEFAULT_RECAPS_PATH
    out: list[dict] = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except OSError:
        return []
    return out


_latest: Optional[dict] = None


def latest_recap() -> Optional[dict]:
    """Most recent recap built in this process (None before the first)."""
    return _latest


def process_kill(kill_event: Any, allgamedata: Any, *, path: Optional[Path] = None,
                 burst_fn: Optional[Callable[..., Any]] = None,
                 up_fn: Optional[Callable[[], bool]] = None) -> Optional[dict]:
    """Worker body: fetch DS profiles (fail-soft), build, persist. Never raises."""
    global _latest
    try:
        resists = our_resists_from(allgamedata)
        contribs = resolve_contributors(kill_event, allgamedata)
        profiles = fetch_ds_profiles(contribs, resists, ds_mode_for(allgamedata),
                                     burst_fn=burst_fn, up_fn=up_fn)
        row = build_recap(kill_event, allgamedata, profiles, resists)
        if row is None:
            return None
        append_row(row, path)
        _latest = row
        return row
    except Exception as exc:  # noqa: BLE001
        _log.debug("death_recap process failed: %s", exc)
        return None


# -- trigger ------------------------------------------------------------------

def _event_id(ev: Mapping) -> Optional[int]:
    v = ev.get("EventID")
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    return None


class DeathRecapTap:
    """Detects NEW own-death ChampionKill events by EventID high-water.

    The first snapshot only sets the high-water mark (no backfill of deaths
    that happened before RC was watching). A new game (EventIDs going
    backwards, or gameTime dropping) resets the mark."""

    def __init__(self, dispatch: Callable[[dict, dict], Any]):
        self._dispatch = dispatch
        self._hw: Optional[int] = None
        self._last_gt: Optional[float] = None
        self._lock = threading.Lock()

    def on_snapshot(self, snap: Any) -> None:
        data = getattr(snap, "data", None)
        if not isinstance(data, dict):
            return
        events = _events(data)
        ids = [i for i in (_event_id(e) for e in events) if i is not None]
        max_id = max(ids) if ids else -1
        gt = _num(_as_dict(data.get("gameData")).get("gameTime"), -1.0)
        new: list[dict] = []
        with self._lock:
            if self._hw is None:
                self._hw = max_id
                self._last_gt = gt
                return
            if max_id < self._hw or (
                    self._last_gt is not None and gt >= 0
                    and gt < self._last_gt - _GAME_RESET_DROP_S):
                self._hw = -1
            self._last_gt = gt
            for e in events:
                eid = _event_id(e)
                if eid is None or eid <= self._hw:
                    continue
                if is_self_death(e, data):
                    new.append(e)
            if max_id > self._hw:
                self._hw = max_id
        for e in new:
            try:
                self._dispatch(e, data)
            except Exception as exc:  # noqa: BLE001
                _log.debug("death_recap dispatch failed: %s", exc)


_queue: "queue.Queue[tuple[dict, dict]]" = queue.Queue(maxsize=_QUEUE_MAX)
_worker: Optional[threading.Thread] = None
_worker_lock = threading.Lock()


def _worker_loop() -> None:
    while True:
        ev, data = _queue.get()
        try:
            process_kill(ev, data)
        finally:
            _queue.task_done()


def _enqueue(ev: dict, data: dict) -> None:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_loop, daemon=True,
                                       name=WORKER_THREAD_NAME)
            _worker.start()
    try:
        _queue.put_nowait((ev, data))
    except queue.Full:
        _log.debug("death_recap queue full; dropping event %r", ev.get("EventID"))


_tap = DeathRecapTap(dispatch=_enqueue)
_installed = False
_install_lock = threading.Lock()


def on_liveclient_snapshot(snap: Any) -> None:
    """liveclient_cache listener: cheap detection only; work goes to a worker."""
    _tap.on_snapshot(snap)


def is_enabled(environ: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(FLAG_ENV, "0")).strip().lower() in _TRUTHY


def install_if_enabled(environ: Optional[Mapping[str, str]] = None) -> bool:
    """Register the listener once, only when RC_DEATH_RECAP is truthy."""
    global _installed
    if not is_enabled(environ):
        return False
    with _install_lock:
        if _installed:
            return False
        try:
            from core import liveclient_cache
            liveclient_cache.add_listener(on_liveclient_snapshot)
        except Exception as exc:  # noqa: BLE001
            _log.warning("death recap install failed: %s", exc)
            return False
        _installed = True
    _log.info("death recap (estimated) enabled -> %s", DEFAULT_RECAPS_PATH)
    return True


def _reset_for_tests() -> None:
    global _installed, _latest, _tap
    with _install_lock:
        _installed = False
    _latest = None
    _tap = DeathRecapTap(dispatch=_enqueue)
