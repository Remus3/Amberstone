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

Run (background):   python tools/live_flip_watcher.py
Abort:              drop ops/audit/ds_perm_swarm/report/WATCHER_STOP  (or Ctrl-C)
"""
from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_REPORT = _ROOT / "ops" / "audit" / "ds_perm_swarm" / "report"
_DS = _ROOT / "agents" / "daemon_slayer"
_STOP = _REPORT / "WATCHER_STOP"
_VERDICT_MD = _REPORT / "live_verdict.md"
_VERDICT_JSONL = _REPORT / "live_verdict.jsonl"
_STATE_URL = "https://127.0.0.1:8888/api/state"
_POLL_S = 8.0
_LIVE_MODES = {"sr", "arena", "aram", "tft", "brawl"}

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
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(_STATE_URL, timeout=6, context=ctx) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - dashboard down / mid-restart -> idle
        return None


def _table_names(fname: str, champ: str) -> set[str]:
    """The champ's WIN-table item NAMES (fail-soft to empty)."""
    try:
        raw = json.loads((_DS / fname).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return set()
    champs = raw.get("champions", raw)
    entry = champs.get(champ)
    if entry is None:
        return set()
    if isinstance(entry, list):  # marksman_offclass_exempt: champ -> [names]
        return {str(n) for n in entry}
    items = entry.get("items", []) if isinstance(entry, dict) else []
    return {it.get("name", "") for it in items if isinstance(it, dict)}


def _load_report(preset_dir: str | None) -> dict[str, dict]:
    """champion -> row, from the baked eyeball report (base or a preset dir)."""
    path = (_REPORT / preset_dir if preset_dir else _REPORT) / "live_flip_eyeball.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {r["champion"]: r for r in rows}


def _pick_preset(enemy_names: list[str]) -> str:
    """tank (>=2 tank/bruiser) / bruiser (>=2 frontline) / squishy."""
    try:
        from coach_integration.enemy_stats import _count_tanky
        from core.aram_comp_verdict import compute_factors
    except Exception:  # noqa: BLE001
        return "tank"
    tanky = _count_tanky(enemy_names)
    if tanky >= 2:
        return "tank"
    try:
        frontline = compute_factors(enemy_names).get("frontline_count", 0)
    except Exception:  # noqa: BLE001
        frontline = 0
    return "bruiser" if frontline >= 2 else "squishy"


def _resolve_game(state: dict) -> tuple[str, str, list[str]] | None:
    """(my_canonical, mode_key, enemy_canonical_names) or None if not a live game."""
    mode = (state.get("mode_key") or "").strip().lower()
    if mode not in _LIVE_MODES:
        return None
    lc = state.get("liveclient") or {}
    players = lc.get("allPlayers") or []
    if not players:
        return None
    coach = state.get("coach") or {}
    my_disp = coach.get("champion")
    if not my_disp:
        return None
    try:
        from core.archetype_picks import canonical_champion_id
    except Exception:  # noqa: BLE001
        return None
    my_canon = canonical_champion_id(my_disp)
    my_team = None
    for p in players:
        if canonical_champion_id(p.get("championName", "")) == my_canon:
            my_team = p.get("team")
            break
    enemies = [
        canonical_champion_id(p.get("championName", ""))
        for p in players
        if p.get("team") != my_team
    ]
    return my_canon, mode, [e for e in enemies if e]


def _classify(row: dict, dsp8_row: dict | None, champ: str) -> dict:
    """Split the champ's moved seams into flip-ready (WIN-table SANER) vs check."""
    seams = dict(row.get("seams", {}))
    if dsp8_row:  # graft the comp-correct DSP8 entry over the base (tank) one
        for k, v in dsp8_row.get("seams", {}).items():
            if k.startswith("DSP8_target_preset="):
                seams = {kk: vv for kk, vv in seams.items()
                         if not kk.startswith("DSP8_target_preset=")}
                seams[k] = v
    flip_ready, check = [], []
    for seam, d in seams.items():
        if not d.get("moves"):
            continue
        entered = d.get("entered", [])
        if seam in _WIN_TABLE:
            tbl = _table_names(_WIN_TABLE[seam], champ)
            saner = bool(entered) and all(e in tbl for e in entered)
            tag = "SANER" if saner else ("reorder" if not entered else "REVIEW")
            flip_ready.append((seam, tag, entered))
        else:
            check.append((seam, entered))
    return {"flip_ready": flip_ready, "check": check, "n_moved": len(flip_ready) + len(check)}


def _short(seam: str) -> str:
    return seam.split("_")[0].replace("target", "").replace("preset=", "") or seam


def _toast(title: str, body: str) -> None:
    """Fire a native Windows toast via hidden PowerShell WinRT (no console flash)."""
    ps = f"""$ErrorActionPreference='SilentlyContinue'
[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null
[Windows.UI.Notifications.ToastNotification,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null
[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]|Out-Null
$t=@'
<toast><visual><binding template="ToastGeneric"><text>{title}</text><text>{body}</text></binding></visual></toast>
'@
$x=New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml($t)
$n=New-Object Windows.UI.Notifications.ToastNotification $x
$app='{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show($n)
"""
    tmp = _REPORT / "_toast.ps1"
    try:
        tmp.write_text(ps, encoding="ascii")
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-WindowStyle", "Hidden", "-File", str(tmp)],
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except Exception:  # noqa: BLE001 - toast is best-effort; the file always lands
        pass


def _emit(champ: str, mode: str, preset: str, verdict: dict, enemies: list[str]) -> None:
    fr = verdict["flip_ready"]
    ck = verdict["check"]
    if verdict["n_moved"] == 0:
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
    _toast(title, body)

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
    if verdict["n_moved"] == 0:
        lines.append("(no seam moves this champ's top-6 - any build is baseline)")
    _VERDICT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with _VERDICT_JSONL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"champ": champ, "mode": mode, "preset": preset,
                             "enemies": enemies, "verdict": verdict}) + "\n")
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
                    row = base.get(champ)
                    dsp8 = (base if preset == "tank" else presets.get(preset, {})).get(champ)
                    if row is None:
                        _emit(champ, mode, preset,
                              {"flip_ready": [], "check": [], "n_moved": 0}, enemies)
                    else:
                        _emit(champ, mode, preset, _classify(row, dsp8, champ), enemies)
                    last = key
            else:
                last = None  # back to lobby -> re-arm for the next game
        time.sleep(_POLL_S)
    print("[watcher] STOP file seen; exiting")
    try:
        _STOP.unlink()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
