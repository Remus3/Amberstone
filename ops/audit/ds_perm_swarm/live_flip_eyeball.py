"""Live-flip eyeball harness - dump every flag-ready DS seam OFF vs ON per champ.

Pre-session prep for the live-game-gated validation pass
(``docs/LIVE_GAME_GATED_SYNC.md``). Each DEFAULT-OFF scorer seam the headless
swarm shipped must be eyeballed against a real game ("saner not different")
before the loop can flip it default-ON. Doing that live means N DS ``:8893``
restarts mid-session - one per seam. This harness collapses that to ONE diff
per (champ, seam): it calls the relevant ranker in-process with the seam OFF
then ON and prints the top-K item delta, so the operator eyeballs a single
table per champ instead of flipping + restarting between games.

Covered (the 9 flag-ready RE-RANK seams; one ranker call each side):

  * DSV2  assume_takedown        burst.rank_items_by_burst
  * DSV3  assume_squishy_target  burst.rank_items_by_burst
  * DSV4  assume_ability_amp     burst.rank_items_by_burst
  * DSP8  target_preset=...      burst.rank_items_by_burst
  * DSP2  exempt_offclass_by_win rank.rank_items (dps)
  * DSP11 prefer_kit_axis_by_win rank.rank_items (dps) + burst.rank_items_by_burst
  * RF1   prefer_survivability_by_win  hybrid.rank_items_by_hybrid
  * RF2   prefer_survivability_by_win  hps.rank_items_by_hps
  * RF36  prefer_survivability_by_win  ehp.rank_items_by_ehp

NOT covered (deliberately - not a re-rank, so no OFF-vs-ON top-K diff):
  * DSP4 score_completion_runes - flips compute_burst_damage / compute_combo
    (a burst-NUMBER delta for a shielded Resolve carrier, needs a runes set),
    NOT rank_items_by_burst. Eyeball it with a direct compute_burst_damage
    call at flip time, not here.
  * DSP3 (RC-side archetype resolver, no engine math), DSP5/6/7 + anti-tank
    P3.2 (no consumer/producer wired yet) - all out of the ranker path.

This is read-only: no flags are persisted, no :8893 restart, the live server
stays seam-OFF. Run:
    python ops/audit/ds_perm_swarm/live_flip_eyeball.py            # tabled champs
    python ops/audit/ds_perm_swarm/live_flip_eyeball.py --champions Ezreal,Pyke,KSante
    python ops/audit/ds_perm_swarm/live_flip_eyeball.py --champion Talon --preset tank
Writes report/live_flip_eyeball.{json,md}.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_OUT_DIR = _ROOT / "ops" / "audit" / "ds_perm_swarm" / "report"
_CE_DIR = _ROOT / "ops" / "audit" / "ds_cross_eval" / "data"
_DS = _ROOT / "agents" / "daemon_slayer"
_LEVEL = 13
_TOP_K = 6


def _anchor_mode(champ: str) -> str:
    """Anchor mode from the champ's cross-eval data file; 'ARAM' if absent."""
    try:
        d = json.loads((_CE_DIR / f"{champ}.json").read_text(encoding="utf-8"))
        return d.get("anchor_mode") or "ARAM"
    except Exception:  # noqa: BLE001 - fail-soft to the dominant anchor mode
        return "ARAM"


def _table_champs(name: str) -> list[str]:
    try:
        raw = json.loads((_DS / name).read_text(encoding="utf-8"))
        return sorted((raw.get("champions") or {}).keys())
    except Exception:  # noqa: BLE001
        return []


def _default_champs() -> list[str]:
    """Union of every seam's WIN-anchored table - the champs a flip actually moves."""
    champs: set[str] = set()
    for name in (
        "survivability_item_credit.json",
        "survivability_item_credit_enchanter.json",
        "survivability_item_credit_tank.json",
        "kit_axis_item_credit.json",
        "marksman_offclass_exempt.json",
    ):
        champs.update(_table_champs(name))
    return sorted(champs)


def _top_names(result, top_k: int) -> list[str]:
    return [r.item_name for r in result.ranked[:top_k]]


def _diff(off: list[str], on: list[str]) -> dict:
    off_set, on_set = set(off), set(on)
    return {
        "off_top": off,
        "on_top": on,
        "entered": [n for n in on if n not in off_set],
        "left": [n for n in off if n not in on_set],
        "moves": off != on,
    }


def run(champs: list[str], *, top_k: int = _TOP_K, preset: str = "tank") -> list[dict]:
    """In-process OFF-vs-ON top-K diff for every flag-ready seam, per champ."""
    from agents.daemon_slayer import survivability_credit
    from agents.daemon_slayer.abilities import reset_default_cache
    from agents.daemon_slayer.burst import rank_items_by_burst
    from agents.daemon_slayer.data_loader import DataSnapshot
    from agents.daemon_slayer.ehp import rank_items_by_ehp
    from agents.daemon_slayer.hps import rank_items_by_hps
    from agents.daemon_slayer.hybrid import rank_items_by_hybrid
    from agents.daemon_slayer.rank import rank_items

    reset_default_cache()
    survivability_credit.reset_cache()
    snap = DataSnapshot.load()
    out: list[dict] = []
    for champ in champs:
        mode = _anchor_mode(champ)

        def burst(**kw):
            return rank_items_by_burst(snap, champ, _LEVEL, mode=mode, top_n=45, **kw)

        def dps(**kw):
            return rank_items(snap, champ, _LEVEL, mode=mode, top_n=45, **kw)

        seams: dict[str, dict] = {}
        # burst-lane seams
        b_off = _top_names(burst(), top_k)
        seams["DSV2_assume_takedown"] = _diff(
            b_off, _top_names(burst(assume_takedown=True), top_k))
        seams["DSV3_assume_squishy_target"] = _diff(
            b_off, _top_names(burst(assume_squishy_target=True), top_k))
        seams["DSV4_assume_ability_amp"] = _diff(
            b_off, _top_names(burst(assume_ability_amp=True), top_k))
        seams[f"DSP8_target_preset={preset}"] = _diff(
            b_off, _top_names(burst(target_preset=preset), top_k))
        seams["DSP11_kit_axis_burst"] = _diff(
            b_off, _top_names(burst(prefer_kit_axis_by_win=True), top_k))
        # dps-lane seams
        d_off = _top_names(dps(), top_k)
        seams["DSP2_exempt_offclass"] = _diff(
            d_off, _top_names(dps(exempt_offclass_by_win=True), top_k))
        seams["DSP11_kit_axis_dps"] = _diff(
            d_off, _top_names(dps(prefer_kit_axis_by_win=True), top_k))
        # survivability lanes (RF1/RF2/RF36) - each its own scorer
        seams["RF1_survivability_hybrid"] = _diff(
            _top_names(rank_items_by_hybrid(snap, champ, _LEVEL, mode=mode, top_n=45), top_k),
            _top_names(rank_items_by_hybrid(
                snap, champ, _LEVEL, mode=mode, top_n=45,
                prefer_survivability_by_win=True), top_k))
        seams["RF2_survivability_hps"] = _diff(
            _top_names(rank_items_by_hps(snap, champ, _LEVEL, mode=mode, top_n=45), top_k),
            _top_names(rank_items_by_hps(
                snap, champ, _LEVEL, mode=mode, top_n=45,
                prefer_survivability_by_win=True), top_k))
        seams["RF36_survivability_ehp"] = _diff(
            _top_names(rank_items_by_ehp(snap, champ, _LEVEL, mode=mode, top_n=45), top_k),
            _top_names(rank_items_by_ehp(
                snap, champ, _LEVEL, mode=mode, top_n=45,
                prefer_survivability_by_win=True), top_k))

        out.append({
            "champion": champ,
            "mode": mode,
            "level": _LEVEL,
            "moved_seams": sorted(k for k, v in seams.items() if v["moves"]),
            "seams": seams,
        })
    return out


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _render_md(rows: list[dict]) -> str:
    lines = [
        "# Live-Flip Eyeball - DS seam OFF vs ON (top-6 re-rank diff)",
        "",
        "Read-only in-process re-rank; the live :8893 stays seam-OFF. For each",
        "champ + seam, ON should be SANER not RANDOM (charter 4b). A seam with no",
        "move for a champ is a no-op there (expected for non-tabled champs).",
        "",
        f"champs: {len(rows)} | level {_LEVEL} | top-6",
        "",
    ]
    for row in rows:
        lines.append(f"## {row['champion']} ({row['mode']})")
        if not row["moved_seams"]:
            lines.append("  (no seam moves the top-6 for this champ)")
            lines.append("")
            continue
        for seam in row["moved_seams"]:
            d = row["seams"][seam]
            lines.append(f"- **{seam}**")
            lines.append(f"    OFF: {', '.join(d['off_top'])}")
            lines.append(f"    ON : {', '.join(d['on_top'])}")
            if d["entered"]:
                lines.append(f"    +in : {', '.join(d['entered'])}")
            if d["left"]:
                lines.append(f"    -out: {', '.join(d['left'])}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DS live-flip eyeball harness (OFF vs ON)")
    ap.add_argument("--champions", help="CSV of canonical champion ids")
    ap.add_argument("--champion", help="single canonical champion id")
    ap.add_argument("--preset", default="tank",
                    help="DSP8 target_preset to test (squishy/bruiser/tank/high_cc)")
    ap.add_argument("--top-k", type=int, default=_TOP_K)
    ap.add_argument("--out-dir", default=str(_OUT_DIR))
    args = ap.parse_args(argv)

    if args.champion:
        champs = [args.champion]
    elif args.champions:
        champs = [c.strip() for c in args.champions.split(",") if c.strip()]
    else:
        champs = _default_champs()
    if not champs:
        print("[eyeball] no champions resolved")
        return 2

    rows = run(champs, top_k=args.top_k, preset=args.preset)
    out = Path(args.out_dir)
    _atomic_write(out / "live_flip_eyeball.json", json.dumps(rows, indent=2))
    _atomic_write(out / "live_flip_eyeball.md", _render_md(rows))
    n_moved = sum(1 for r in rows if r["moved_seams"])
    print(f"[eyeball] {len(rows)} champs, {n_moved} with >=1 moving seam; wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
