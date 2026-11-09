"""Live-flip watcher - auto-surface the pre-baked DS seam verdicts for the champ
the operator is actually playing, so the live-game-gated eyeball pass
(docs/LIVE_GAME_GATED_SYNC.md section B) needs ZERO mid-game .md reading.

On each poll it reads the live ``/api/state``; when a real game is up it resolves
the operator's champ + the enemy comp, picks the comp-appropriate DSP8 preset
(tank / bruiser / squishy), pulls the matching pre-baked OFF-vs-ON top-6 diff from
``ops/audit/ds_perm_swarm/report/``, AUTO-CLASSIFIES each WIN-table-backed seam
(RF1 / RF2 / RF36 / DSP11 / DSP2) as SANER-by-construction when every entered item
is in that champ's rewind-WIN credit table, and fires ONE Windows toast + writes a
compact verdict file. It NEVER flips a seam (charter 4b do-not-flip-blind); it only
tells the operator which seams to authorize after the game.

Read-only: polls the dashboard + reads baked reports + credit tables. No engine
call, no :8860 restart, no env change.

Every input is untrusted shape-wise (S144-T-707): a wrong-typed field in
/api/state, a baked report or a credit table reads as "not a live game" / "no
row" / "empty table" instead of raising out of the poll loop, and a verdict file
that cannot be written is reported, never fatal.

Run (background):   python tools/live_flip_watcher.py
Abort:              drop ops/audit/ds_perm_swarm/report/WATCHER_STOP  (or Ctrl-C)
"""
from __future__ import annotations

import http.client
import json
import ssl
import sys
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import operator_notify, polled_json  # noqa: E402 - needs the repo root on sys.path

_REPORT = _ROOT / "ops" / "audit" / "ds_perm_swarm" / "report"
_DS = _ROOT / "agents" / "daemon_slayer"
_STOP = _REPORT / "WATCHER_STOP"
_VERDICT_MD = _REPORT / "live_verdict.md"
_VERDICT_JSONL = _REPORT / "live_verdict.jsonl"
_STATE_URL = "https://127.0.0.1:8888/api/state"
_POLL_S = 8.0
_LIVE_MODES = {"sr", "arena", "aram", "tft", "brawl"}
# /api/state is far smaller than this; a body past it is not the dashboard's
# state and reads as idle instead of being buffered without bound.
_MAX_STATE_BYTES = 8 * 1024 * 1024
_DSP8 = "DSP8_target_preset="
_ABSENT = object()

# WIN-table-backed seams: a move is SANER-by-construction when every entered item
# is in that champ's rewind-WIN credit table (the seam exists to surface exactly
# those). Maps the eyeball-report seam key -> the credit-table file.
_WIN_TABLE = {
    "RF1_survivability_hybrid": "survivability_item_credit.json",
    "RF2_survivability_hps": "survivability_item_credit_enchanter.json",
    "RF36_survivability_ehp": "survivability_item_credit_tank.json",
    "DSP11_kit_axis_burst": "kit_axis_item_credit.json",
    "DSP11_kit_axis_dps": "kit_axis_item_credit.json",
    "DSP2_exempt_offclass": "marksman_offclass_exempt.json",
}


def _fetch_state() -> dict | None:
    """The live /api/state object, or None when the dashboard is down,
    mid-restart, or answers with anything that is not one JSON object.

    Only transport and decode failures read as idle; anything else is a
    programming error and raises instead of masquerading as "dashboard down".
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(_STATE_URL, timeout=6, context=ctx) as r:
            raw = r.read(_MAX_STATE_BYTES + 1)
    except (OSError, http.client.HTTPException):  # down / mid-restart -> idle
        return None
    if len(raw) > _MAX_STATE_BYTES:
        return None
    try:
        state = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):  # torn / non-UTF-8 / not JSON -> idle
        return None
    return state if isinstance(state, dict) else None


def _read_json(path: Path) -> object:
    """Parsed JSON at ``path``, or None when it is missing or unparseable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None


def _names(values: object) -> list[str]:
    """The non-empty str entries of a list; anything else contributes nothing."""
    if not isinstance(values, list):
        return []
    return [v for v in values if isinstance(v, str) and v]


def _table_names(fname: str, champ: str) -> set[str]:
    """The champ's WIN-table item NAMES (fail-soft to empty on any bad shape)."""
    raw = _read_json(_DS / fname)
    if not isinstance(raw, dict):
        return set()
    champs = raw.get("champions", raw)
    if not isinstance(champs, dict):
        return set()
    entry = champs.get(champ)
    if isinstance(entry, list):  # marksman_offclass_exempt: champ -> [names]
        return set(_names(entry))
    if not isinstance(entry, dict) or not isinstance(entry.get("items"), list):
        return set()
    return set(_names([it.get("name") for it in entry["items"] if isinstance(it, dict)]))


def _load_report(preset_dir: str | None) -> dict[str, dict]:
    """champion -> row, from the baked eyeball report (base or a preset dir).

    A report that is not a list reads as empty; a row that is not an object or
    carries no non-empty str "champion" is skipped.
    """
    path = (_REPORT / preset_dir if preset_dir else _REPORT) / "live_flip_eyeball.json"
    rows = _read_json(path)
    if not isinstance(rows, list):
        return {}
    return {r["champion"]: r for r in rows
            if isinstance(r, dict) and isinstance(r.get("champion"), str) and r["champion"]}


def _pick_preset(enemy_names: list[str]) -> str:
    """tank (>=2 tank/bruiser) / bruiser (>=2 frontline) / squishy."""
    try:
        from coach_integration.enemy_stats import _count_tanky
        from core.aram_comp_verdict import compute_factors
    except ImportError:
        return "tank"
    tanky = _count_tanky(enemy_names)
    if tanky >= 2:
        return "tank"
    try:
        frontline = compute_factors(enemy_names).get("frontline_count", 0)
    except Exception:  # noqa: BLE001 - comp factors are best-effort; squishy is the floor
        frontline = 0
    if isinstance(frontline, bool) or not isinstance(frontline, (int, float)):
        frontline = 0
    return "bruiser" if frontline >= 2 else "squishy"


def _resolve_game(state: object) -> tuple[str, str, list[str]] | None:
    """(my_canonical, mode_key, enemy_canonical_names) or None if not a live game.

    A wrong-typed field reads as "not a live game" rather than raising out of
    the poll loop. A player entry that is not an object, or has no str
    championName, is skipped. When the coach's champion is not among
    allPlayers the teams are unknowable, so the game is NOT resolved (it used
    to list every player - allies and the operator too - as an enemy).
    """
    if not isinstance(state, dict):
        return None
    mode = state.get("mode_key")
    if not isinstance(mode, str):
        return None
    mode = mode.strip().lower()
    if mode not in _LIVE_MODES:
        return None
    lc = state.get("liveclient")
    players = lc.get("allPlayers") if isinstance(lc, dict) else None
    if not isinstance(players, list) or not players:
        return None
    coach = state.get("coach")
    my_disp = coach.get("champion") if isinstance(coach, dict) else None
    if not isinstance(my_disp, str) or not my_disp.strip():
        return None
    try:
        from core.archetype_picks import canonical_champion_id
    except ImportError:
        return None
    my_canon = canonical_champion_id(my_disp)
    roster = [(canonical_champion_id(p["championName"]), p.get("team"))
              for p in players
              if isinstance(p, dict) and isinstance(p.get("championName"), str)
              and p["championName"]]
    my_team = next((team for canon, team in roster if canon == my_canon), _ABSENT)
    if my_team is _ABSENT:
        return None
    return my_canon, mode, [canon for canon, team in roster if team != my_team and canon]


def _seams_of(row: object) -> dict:
    """A copy of the row's seams mapping; {} for any malformed row."""
    seams = row.get("seams") if isinstance(row, dict) else None
    return dict(seams) if isinstance(seams, dict) else {}


def _classify(row: dict, dsp8_row: dict | None, champ: str) -> dict:
    """Split the champ's moved seams into flip-ready (WIN-table SANER) vs check.

    Every comp-correct DSP8 entry of ``dsp8_row`` replaces the row's own. A
    seam detail that is not an object, or whose "entered" is not a list,
    makes no verdict claim; non-str entered items are dropped.
    """
    seams = _seams_of(row)
    comp = {k: v for k, v in _seams_of(dsp8_row).items() if k.startswith(_DSP8)}
    if comp:  # graft the comp-correct DSP8 entry over the base (tank) one
        seams = {k: v for k, v in seams.items() if not k.startswith(_DSP8)}
        seams.update(comp)
    flip_ready, check = [], []
    for seam, d in seams.items():
        if not isinstance(d, dict) or not d.get("moves"):
            continue
        raw_entered = d.get("entered", [])
        if not isinstance(raw_entered, list):
            continue
        entered = _names(raw_entered)
        if seam in _WIN_TABLE:
            tbl = _table_names(_WIN_TABLE[seam], champ)
            saner = bool(entered) and all(e in tbl for e in entered)
            tag = "SANER" if saner else ("reorder" if not entered else "REVIEW")
            flip_ready.append((seam, tag, entered))
        else:
            check.append((seam, entered))
    return {"flip_ready": flip_ready, "check": check, "n_moved": len(flip_ready) + len(check)}


def _verdict_for(champ: str, preset: str, base: dict[str, dict],
                 presets: dict[str, dict[str, dict]]) -> dict:
    """The champ's verdict against the ``preset`` comp, from the baked reports.

    Only the DSP8 seam depends on the preset; every other seam is computed
    identically in each report (ops/audit/ds_perm_swarm/live_flip_eyeball.py
    ``run``), so a champ missing from the base (tank) report is read from a
    preset report that has it - it used to be announced as "any build is
    baseline". When the comp-correct DSP8 entry was never baked, the row's own
    DSP8 entry belongs to ANOTHER comp and is dropped rather than printed under
    this preset's label. A champ in no report is ``baked: False``: no verdict,
    never a baseline claim.
    """
    comp_report = base if preset == "tank" else (presets.get(preset) or {})
    comp_row = comp_report.get(champ)
    row = base.get(champ) or comp_row or next(
        (rep[champ] for rep in presets.values() if rep.get(champ)), None)
    if row is None:
        return {"flip_ready": [], "check": [], "n_moved": 0, "baked": False}
    if comp_row is None:
        row = {**row, "seams": {k: v for k, v in _seams_of(row).items()
                                if not k.startswith(_DSP8)}}
    verdict = _classify(row, comp_row, champ)
    verdict["baked"] = True
    return verdict


def _short(seam: str) -> str:
    return seam.split("_", 1)[0].replace("target", "").replace("preset=", "") or seam


def _emit(champ: str, mode: str, preset: str, verdict: dict, enemies: list[str]) -> None:
    fr = verdict["flip_ready"]
    ck = verdict["check"]
    baked = verdict.get("baked", True)
    if not baked:
        title = f"RC: {champ} ({mode}) - not baked"
        body = "No eyeball row for this champ in any baked report; no verdict."
    elif verdict["n_moved"] == 0:
        title = f"RC: {champ} ({mode}) - no tabled seams"
        body = "Any build is baseline (byte-identical). Nothing to flip."
    else:
        ready_txt = " | ".join(
            f"{_short(s)} {tag} +{','.join(e[:2]) or 'reorder'}" for s, tag, e in fr
        ) or "(none)"
        check_txt = " | ".join(
            f"{_short(s)}[{preset}] +{','.join(e[:2])}" for s, e in ck if e
        ) or "(none)"
        title = f"RC: {champ} ({mode}) vs {preset}-comp"
        body = f"FLIP-READY: {ready_txt}\nCHECK: {check_txt}"

    lines = [f"# Live-flip verdict - {champ} ({mode}), {preset}-comp",
             f"enemies: {', '.join(enemies) or '-'}", ""]
    if fr:
        lines.append("## FLIP-READY (WIN-table backed)")
        for s, tag, e in fr:
            lines.append(f"- {s}: {tag}  +{', '.join(e) or '(reorder only)'}")
    if ck:
        lines.append("## CHECK vs the live comp (burst-assumption seams)")
        for s, e in ck:
            lines.append(f"- {s}: +{', '.join(e) or '(reorder)'}")
    if not baked:
        lines.append("(not baked: no eyeball row for this champ - no verdict)")
    elif verdict["n_moved"] == 0:
        lines.append("(no seam moves this champ's top-6 - any build is baseline)")
    # The .md goes through the atomic helper (it was written in place), and a
    # verdict write that fails is reported, never fatal to the poll loop.
    try:
        polled_json.atomic_write_text(_VERDICT_MD, "\n".join(lines) + "\n")
        with _VERDICT_JSONL.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"champ": champ, "mode": mode, "preset": preset,
                                 "enemies": enemies, "verdict": verdict}) + "\n")
    except OSError as exc:
        print(f"[watcher] verdict file write failed: {exc!r}", file=sys.stderr)
    # Y-02: one notify path (escaped toast, jsonl floor); never raises.
    operator_notify.notify(title, body, tags=("live-flip",))
    print(f"[watcher] emitted verdict: {champ} ({mode}) vs {preset}-comp; "
          f"{len(fr)} flip-ready, {len(ck)} check")


def main() -> int:
    base = _load_report(None)
    presets = {p: _load_report(p) for p in ("squishy", "bruiser")}
    if not base:
        print("[watcher] no baked report - run live_flip_eyeball.py first")
        return 2
    print(f"[watcher] armed; polling {_STATE_URL} every {int(_POLL_S)}s. "
          f"Stop: drop {_STOP.name}")
    last = None
    while not _STOP.exists():
        state = _fetch_state()
        if state:
            resolved = _resolve_game(state)
            if resolved:
                champ, mode, enemies = resolved
                key = (champ, mode)
                if key != last:
                    preset = _pick_preset(enemies)
                    _emit(champ, mode, preset,
                          _verdict_for(champ, preset, base, presets), enemies)
                    last = key
            else:
                last = None  # back to lobby -> re-arm for the next game
        time.sleep(_POLL_S)
    print("[watcher] STOP file seen; exiting")
    try:
        _STOP.unlink()
    except OSError:  # already gone or locked: the loop has exited either way
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
