"""DSP3 - build the per-champion ARAM archetype-override table (Cluster A).

Cross-eval Cluster A (ops/audit/ds_cross_eval/SYSTEMIC_FINDINGS.md): the default
``core.archetype_picks.get_archetype_for`` routes each champ to its KIT archetype
(correct by DDragon tag / lolmath damage-axis), but rewind ARAM win-data favors a
DIFFERENT build axis for a cluster of champions, so the kit-default scorer's whole
item pool misses the empirically winning ARAM build:

  - Zilean / Shaco / Shyvana: routed hps / burst / hybrid (AD-ish) but ARAM wins
    on AP (Liandry / Blackfire / Shadowflame / Rabadon / Riftmaker) -> mage.
  - Taric: routed hps (enchanter) but ARAM wins as a TANK (Unending Despair /
    Spirit Visage / Fimbulwinter) -> tank.
  - KogMaw / Kayle: routed mage (AP, post the P6-G1 axis correction) but ARAM
    wins on ON-HIT CARRY (Blade of the Ruined King / Wit's End / Terminus /
    Guinsoo) -> carry.

This is a CALIBRATION judgment, not a kit bug (the defaults ARE kit-correct; ARAM
is an off-meta where AP / tank / on-hit builds outperform the kit's intended
axis). So the override is WIN-anchored, not eyeballed: a champ's override is
emitted only when its empirical ARAM block (data/rewind_history.db, distilled by
the cross-eval) carries at least one above-baseline winning item ON the override
archetype's damage axis.

Selection is mechanical:
  - the per-champion cross-eval VERDICT flags ``archetype_ok == false`` (the
    172-agent WIN-anchored audit decided the archetype axis is wrong for ARAM);
  - AND the champ's archetype ``source == "default"`` - an operator pick
    (user_cs / user_ingame / nudge) is NEVER overridden (Lulu, MissFortune are
    user_cs and are skipped automatically).

The override TARGET archetype per champ comes from the audited ``_ARAM_OVERRIDE``
map below (the Cluster-A conclusion). The builder ASSERTS every selected champ is
in that map, so a future cross-eval that surfaces a NEW archetype_ok=false +
default champ fails LOUDLY (forces review) rather than silently dropping it.

Output: ``core/aram_archetype_override.json`` - consumed by
``core.archetype_picks.get_archetype_for(prefer_aram_win_axis=True)`` (the
DEFAULT-OFF DSP3 seam; the live default-ON flip is EXCLUDED -> appended to
docs/LIVE_GAME_GATED_SYNC.md). Re-run after a cross-eval refresh to keep current.

Hermetic: reads ONLY the small per-champ cross-eval JSONs (verdicts/ + data/).
The 1.8GB rewind_history.db is NEVER opened here.
"""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CE_DIR = _ROOT / "ops" / "audit" / "ds_cross_eval"
_VERDICTS_DIR = _CE_DIR / "verdicts"
_DATA_DIR = _CE_DIR / "data"
_OUT_PATH = _ROOT / "core" / "aram_archetype_override.json"

# An ARAM win-axis item is a real, winning build when the player base buys it
# enough (n) AND it is not an outright trap (loose WR band vs the mode baseline).
MIN_ITEM_N = 8       # matches the cross-eval outcome-tier n>=8
WR_MARGIN = 3.0      # DSP2 precedent

# Override archetype -> the damage axis its scorer itemizes. The WIN-anchor gate
# requires the champ's empirical ARAM winners to include an item on this axis.
_ARCHETYPE_TARGET_AXIS: dict[str, str] = {
    "mage": "ap", "enchanter": "ap",
    "carry": "ad", "bruiser": "ad", "assassin": "ad",
    "tank": "tank",
}

# Audited Cluster-A override targets (the WIN-anchored cross-eval conclusion).
# Every archetype_ok=false + source=default champ MUST appear here or the build
# raises (no silent miss). Operator-pick champs (Lulu/MissFortune user_cs) are
# filtered out BEFORE this map is consulted, so they are intentionally absent.
_ARAM_OVERRIDE: dict[str, str] = {
    "Zilean": "mage",
    "Shaco": "mage",
    "Shyvana": "mage",
    "Taric": "tank",
    "KogMaw": "carry",
    "Kayle": "carry",
}

# Item-name substrings per damage axis (case-insensitive). Compact, traceable,
# ASCII; every entry appears in the cross-eval empirical blocks of the Cluster-A
# champs. Each item is bucketed to a SINGLE axis to avoid cross-axis anchoring.
_AXIS_SIGNATURE: dict[str, tuple[str, ...]] = {
    "ap": (
        "liandry", "blackfire", "shadowflame", "rabadon", "luden", "riftmaker",
        "void staff", "malignance", "rylai", "cryptbloom", "seraph",
        "stormsurge", "rod of ages", "cosmic drive", "hextech", "bloodletter",
        "demonic", "zhonya", "lich bane", "nashor", "wooglet", "banshee",
    ),
    "ad": (
        "ruined king", "wit's end", "terminus", "guinsoo", "kraken",
        "collector", "infinity edge", "statikk", "navori", "recurve", "runaan",
        "essence reaver", "lord dominik", "mortal reminder", "bloodthirster",
        "stormrazor", "yun tal", "rapid firecannon", "vampiric", "black cleaver",
        "eclipse", "trinity force", "hubris", "youmuu", "opportunity",
        "serylda", "voltaic", "sundered sky", "death's dance", "stridebreaker",
        "phantom dancer", "muramana", "axiom",
    ),
    "tank": (
        "unending despair", "fimbulwinter", "heartsteel", "spirit visage",
        "thornmail", "warmog", "jak'sho", "sunfire", "randuin", "frozen heart",
        "titanic", "sterak", "kaenic", "guardian's horn", "iceborn",
        "dead man", "abyssal", "force of nature", "hollow radiance",
        "plated steelcaps", "mercury",
    ),
}


def _matches_axis(item_name: str, axis: str) -> bool:
    low = (item_name or "").lower()
    return any(sig in low for sig in _AXIS_SIGNATURE.get(axis, ()))


def _win_anchor_evidence(
    empirical_aram: dict, axis: str, min_item_n: int, wr_margin: float,
) -> list[dict]:
    """Return above-baseline ARAM winners on ``axis`` (self + all blocks).

    An item qualifies when, within its block, ``n >= min_item_n`` and
    ``wr >= block_baseline_wr - wr_margin`` and its name matches the axis
    signature. Dedup by name keeping the highest-n entry.
    """
    best: dict[str, dict] = {}
    for blk_name in ("self", "all"):
        blk = (empirical_aram or {}).get(blk_name) or {}
        base = blk.get("wr")
        if base is None:
            continue
        for it in blk.get("items") or []:
            name = it.get("name")
            n = it.get("n") or 0
            wr = it.get("wr")
            if (
                name
                and _matches_axis(name, axis)
                and n >= min_item_n
                and wr is not None
                and wr >= base - wr_margin
            ):
                prev = best.get(name)
                if prev is None or n > prev["n"]:
                    best[name] = {"name": name, "n": n, "wr": wr}
    return sorted(best.values(), key=lambda e: (-e["n"], e["name"]))


def build_table(
    verdicts_dir: Path = _VERDICTS_DIR,
    data_dir: Path = _DATA_DIR,
    min_item_n: int = MIN_ITEM_N,
    wr_margin: float = WR_MARGIN,
) -> dict:
    """Return the override table dict (does not write to disk)."""
    champions: dict[str, dict] = {}
    skipped_user_pick: list[str] = []
    skipped_no_win_anchor: list[str] = []
    considered = 0
    for fp in sorted(glob.glob(str(Path(verdicts_dir) / "*.json"))):
        verdict = json.loads(Path(fp).read_text(encoding="utf-8"))
        champ = verdict.get("champion")
        if not champ or verdict.get("archetype_ok") is not False:
            continue
        considered += 1
        data_fp = Path(data_dir) / f"{champ}.json"
        if not data_fp.exists():
            continue
        data = json.loads(data_fp.read_text(encoding="utf-8"))
        arc = data.get("archetype") or {}
        # Never override an operator pick (only the kit-tag default).
        if arc.get("source") != "default":
            skipped_user_pick.append(champ)
            continue
        if champ not in _ARAM_OVERRIDE:
            raise ValueError(
                f"{champ}: archetype_ok=false + source=default but absent from "
                "_ARAM_OVERRIDE - a new Cluster-A divergent champ needs a "
                "WIN-anchored override decision (review before shipping)."
            )
        override = _ARAM_OVERRIDE[champ]
        axis = _ARCHETYPE_TARGET_AXIS[override]
        evidence = _win_anchor_evidence(
            (data.get("empirical") or {}).get("ARAM") or {},
            axis, min_item_n, wr_margin,
        )
        if not evidence:
            skipped_no_win_anchor.append(champ)
            continue
        champions[champ] = {
            "default_primary": arc.get("primary"),
            "override": override,
            "axis": axis,
            "evidence": evidence,
        }
    patch = ""
    try:
        patch = (_ROOT / "data" / "daemon_slayer" / "current.txt").read_text(
            encoding="utf-8"
        ).strip()
    except OSError:
        patch = ""
    return {
        "_comment": (
            "DSP3 Cluster-A: per-champion ARAM archetype-override table. "
            "Consumed by core.archetype_picks.get_archetype_for("
            "prefer_aram_win_axis=True) (DEFAULT-OFF seam). Built by "
            "ops/audit/ds_perm_swarm/build_aram_archetype_override.py from the "
            "cross-eval empirical (rewind WIN+usage) data; each override is "
            "WIN-anchored to above-baseline ARAM items on the override axis. "
            "ASCII only."
        ),
        "patch": patch,
        "generated_from": "ops/audit/ds_cross_eval/{verdicts,data}",
        "min_item_n": min_item_n,
        "wr_margin": wr_margin,
        "considered_archetype_mismatch": considered,
        "skipped_user_pick": sorted(skipped_user_pick),
        "skipped_no_win_anchor": sorted(skipped_no_win_anchor),
        "champions": dict(sorted(champions.items())),
    }


def main() -> None:
    table = build_table()
    text = json.dumps(table, indent=2, ensure_ascii=True, sort_keys=False)
    tmp = _OUT_PATH.with_suffix(".json.tmp")
    tmp.write_text(text + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, _OUT_PATH)
    champs = table["champions"]
    print(f"wrote {_OUT_PATH}")
    print(
        f"considered={table['considered_archetype_mismatch']} "
        f"override_champs={len(champs)} "
        f"skipped_user_pick={table['skipped_user_pick']} "
        f"skipped_no_win_anchor={table['skipped_no_win_anchor']}"
    )
    for c, e in champs.items():
        ev = ", ".join(f"{x['name']}({x['n']}/{x['wr']})" for x in e["evidence"][:3])
        print(f"  {c}: {e['default_primary']} -> {e['override']} [{e['axis']}]  {ev}")


if __name__ == "__main__":
    main()
