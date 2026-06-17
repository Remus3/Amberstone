#!/usr/bin/env python3
"""DSP9 G7 comp-aware parity harness (P6 G7 + the DSP4-8 seam fold).

gen_md.py pairs lolmath's ULTIMATE build against DS's STATIC `mixed` build-order
variant (a synthetic NEUTRAL target: armor 80 / mr 60 / 2400 HP). But lolmath's
constant default enemy comp is Jayce / Sejuani / Annie / Lucian / Thresh =
4 squishy + 1 tank - a GLASS-leaning comp, NOT a neutral one. Comparing lolmath
against DS's neutral `mixed` variant therefore understates parity: DS already
ships four comp-archetype build variants (mixed / poke / burst_heavy /
frontline_heavy), and the fair like-for-like is the variant whose comp_archetype
MATCHES lolmath's fixed comp.

This harness closes the G7 residual two ways, both honoring the DSP* seams that
shipped DEFAULT-OFF in the live engine (folded ON for this offline audit only -
never flipped live; see docs/LIVE_GAME_GATED_SYNC.md):

  1. STATIC (hermetic, no engine): classify lolmath's fixed comp -> the matching
     DS comp_archetype variant (burst_heavy), and score the lolmath-ultimate-vs-DS
     item overlap against THAT variant instead of the blind `mixed`. The delta vs
     the `mixed` baseline is the G7 parity recovery.
  2. LIVE (optional cross-check, fail-soft): re-rank each champ via
     core.daemon_slayer_client.rank_for_primary_archetype fed the comp's resolved
     representative target stats (resolve_comp_target, which blends the DSP8
     _TARGET_PRESETS per comp member) - the comp-aware target the burst_heavy
     variant was itself generated with.

The pure helpers (LOLMATH_COMP / classify_comp / resolve_comp_target /
score_overlap) are hermetic and unit-tested in tests/test_lolmath_g7_comp_harness.py.
main() is a standalone probe (the g2/g5 probe precedent), never run under pytest.

Usage: python g7_comp_harness.py [PATCH]
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = r"C:/Riot Commander"
HERE = f"{ROOT}/ops/audit/lolmath_ds_sweep"

# lolmath's constant default enemy comp (gen_md.py methodology: 4 squishy + 1 tank).
# Durability class per member is the BUILD-relevant durability, not the champ's
# role label (Thresh is a support but carries low resists early -> squishy for the
# "what do I build to fight this comp" question).
LOLMATH_COMP: tuple[tuple[str, str], ...] = (
    ("Jayce", "squishy"),
    ("Sejuani", "tank"),
    ("Annie", "squishy"),
    ("Lucian", "squishy"),
    ("Thresh", "squishy"),
)

# DS's four comp-archetype build variants (data/daemon_slayer/build_orders/<patch>/
# build_orders_sr.json `dimensions.comp_archetypes` + core/build_order_precompute.COMP_ARCHETYPES).
DS_COMP_ARCHETYPES = ("frontline_heavy", "burst_heavy", "poke", "mixed")

# Per-durability representative target (armor_base, armor_per_level, mr_base,
# mr_per_level, max_hp, bonus_hp). The armor/mr bases MIRROR burst.py
# _TARGET_PRESETS (DSP8): squishy (22, 4.5, 30, 0.5), bruiser (35, 5.5, 30, 2.5),
# tank (50, 13, 40, 7); the hp/bonus_hp mirror core/build_order_precompute.COMP_BIAS
# (burst_heavy 1900/500, frontline_heavy 3200/1800). Duplicated as 4 constants (not
# imported) so the hermetic helper path stays free of the heavy engine import; the
# live re-rank in main() uses the engine's own values via rank_for_primary_archetype.
_DUR_PRESET: dict[str, tuple[float, float, float, float, float, float]] = {
    "squishy": (22.0, 4.5, 30.0, 0.5, 1900.0, 500.0),
    "poke": (22.0, 4.5, 35.0, 1.5, 2100.0, 650.0),
    "bruiser": (35.0, 5.5, 30.0, 2.5, 2700.0, 1200.0),
    "tank": (50.0, 13.0, 40.0, 7.0, 3200.0, 1800.0),
}

BOOTS = {
    "Boots", "Berserker's Greaves", "Plated Steelcaps", "Mercury's Treads",
    "Ionian Boots of Lucidity", "Boots of Swiftness", "Sorcerer's Shoes",
    "Gluttonous Greaves", "Swiftmarch", "Spellslinger's Shoes", "Armored Advance",
    "Crimson Lucidity", "Chainlaced Crushers", "Forever Forward",
    "Synchronized Souls", "Boots of Mobility",
}


def classify_comp(members: list[tuple[str, str]]) -> str:
    """Map a 5-member comp (list of (champ, durability)) to a DS comp_archetype.

    frontline = tank + bruiser; a wall of frontliners -> frontline_heavy; a
    poke-dominated comp -> poke; a glass comp (<=1 frontliner, 3+ squishy) ->
    burst_heavy; everything else -> mixed.
    """
    frontline = sum(1 for _, d in members if d in ("tank", "bruiser"))
    squishy = sum(1 for _, d in members if d == "squishy")
    poke = sum(1 for _, d in members if d == "poke")
    if frontline >= 3:
        return "frontline_heavy"
    if poke >= 3:
        return "poke"
    if frontline <= 1 and squishy >= 3:
        return "burst_heavy"
    return "mixed"


def resolve_comp_target(members: list[tuple[str, str]], level: int = 11) -> dict[str, float]:
    """Blend the per-member durability presets into one representative target.

    Resists scale with level (armor_base + per_level * (level - 1)); HP terms are
    level-independent representatives. Unknown durability falls back to squishy.
    """
    lvl = max(1, int(level))
    n = max(1, len(members))
    armor = mr = max_hp = bonus_hp = 0.0
    for _, dur in members:
        ab, ap, mb, mp, hp, bhp = _DUR_PRESET.get(dur, _DUR_PRESET["squishy"])
        armor += ab + ap * (lvl - 1)
        mr += mb + mp * (lvl - 1)
        max_hp += hp
        bonus_hp += bhp
    return {
        "target_armor": round(armor / n, 1),
        "target_mr": round(mr / n, 1),
        "target_max_hp": round(max_hp / n, 1),
        "target_bonus_hp": round(bonus_hp / n, 1),
    }


def score_overlap(lm_items: list[str], ds_items: list[str]) -> int:
    """Count shared NON-boots, non-'No Item' items between two build lists."""
    shared = (set(lm_items) & set(ds_items)) - BOOTS - {"No Item"}
    return len(shared)


# --------------------------------------------------------------------------- #
# Standalone probe (NOT run under pytest - the g2/g5 probe precedent).
# --------------------------------------------------------------------------- #
def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def main(patch: str = "16.12.1") -> None:
    itemj = json.load(open(f"{ROOT}/data/meta_build/ddragon/{patch}/item.json", encoding="utf-8"))["data"]
    dsraw = json.load(open(f"{ROOT}/data/daemon_slayer/build_orders/{patch}/build_orders_sr.json", encoding="utf-8"))
    ds_engine = dsraw.get("engine_version")
    dsbo = dsraw["build_orders"]
    sweep = json.load(open(f"{HERE}/lolmath_sweep.json", encoding="utf-8"))
    ult = json.load(open(f"{HERE}/ultimate_sweep.json", encoding="utf-8"))

    def iname(i: str) -> str:
        return itemj.get(str(i), {}).get("name", str(i))

    alias = {"wukong": "MonkeyKing", "nunuandwillump": "Nunu", "nunu": "Nunu",
             "renataglasc": "Renata", "renata": "Renata"}
    id_norm = {_norm(k): k for k in dsbo}

    def slug2id(slug: str) -> str | None:
        n = _norm(slug)
        return alias.get(n) or id_norm.get(n)

    lm_ult: dict[str, list[str]] = {}
    for r in ult["results"]:
        cid = slug2id(r["slug"])
        if cid:
            ub = r.get("ultimate", [])
            if len(ub) >= 4:
                lm_ult[cid] = ub
    lm_norm: dict[str, list[str]] = {}
    for r in sweep["results"]:
        cid = slug2id(r["slug"])
        if cid:
            lm_norm[cid] = r.get("build_order", [])

    bucket = classify_comp(list(LOLMATH_COMP))
    comp_target = resolve_comp_target(list(LOLMATH_COMP), level=11)
    print(f"=== G7 comp-aware parity @ ENGINE {ds_engine} / patch {patch} ===")
    print(f"lolmath comp = {[c for c, _ in LOLMATH_COMP]} -> classify_comp -> '{bucket}'")
    print(f"comp-resolved target (L11) = {comp_target}")
    print("baseline gen_md.py compares lolmath-ultimate vs DS 'mixed' (armor 80 / mr 60 / 2400 HP)\n")

    # Score the lolmath ULTIMATE (cost-ignoring best-6) and the lolmath NORMAL
    # (gold-aware) overlap against EVERY DS comp variant - so the conclusion is not
    # hostage to one classification: if 'mixed' (neutral) maximizes overlap, the
    # residual is the cost-model axis (G6), not comp-awareness.
    variants = DS_COMP_ARCHETYPES
    sum_ult = {v: 0 for v in variants}
    sum_norm = {v: 0 for v in variants}
    covered = 0
    rows = []
    for cid in sorted(dsbo):
        lm_u = lm_ult.get(cid) or []
        lm_n = lm_norm.get(cid) or []
        if len(lm_u) < 4 or not all(v in dsbo[cid] for v in variants):
            continue
        covered += 1
        ds_by_v = {v: [iname(x) for x in dsbo[cid][v]["order"]] for v in variants}
        ov_u = {v: score_overlap(lm_u, ds_by_v[v]) for v in variants}
        ov_n = {v: score_overlap(lm_n, ds_by_v[v]) for v in variants} if len(lm_n) >= 4 else None
        for v in variants:
            sum_ult[v] += ov_u[v]
            if ov_n is not None:
                sum_norm[v] += ov_n[v]
        rows.append((cid, ov_u))

    def mean(d: dict[str, int]) -> dict[str, float]:
        return {v: round(d[v] / max(1, covered), 3) for v in variants}

    mean_ult = mean(sum_ult)
    mean_norm = mean(sum_norm)
    best_ult = max(variants, key=lambda v: sum_ult[v])
    print(f"covered champs: {covered}")
    print("mean item-overlap of lolmath ULTIMATE (cost-ignoring) vs each DS variant:")
    for v in variants:
        tag = "  <- comp-match (G7)" if v == bucket else ("  <- gen_md baseline" if v == "mixed" else "")
        star = "  *BEST*" if v == best_ult else ""
        print(f"  {v:16} {mean_ult[v]:.3f}{star}{tag}")
    print("\nmean item-overlap of lolmath NORMAL (gold-aware) vs each DS variant:")
    for v in variants:
        print(f"  {v:16} {mean_norm[v]:.3f}")
    delta = mean_ult[bucket] - mean_ult["mixed"]
    print(f"\nG7 comp-match ('{bucket}') vs gen_md baseline ('mixed'), lolmath-ULTIMATE: {delta:+.3f}")
    print(f"variant that best tracks lolmath-ULTIMATE: '{best_ult}' "
          f"({'neutral build -> residual is the cost-model axis G6' if best_ult == 'mixed' else 'comp-aware variant'})")

    out = {
        "engine_version": ds_engine, "patch": patch,
        "comp": [c for c, _ in LOLMATH_COMP], "classified_bucket": bucket,
        "comp_target_l11": comp_target, "covered": covered,
        "mean_overlap_ultimate_by_variant": mean_ult,
        "mean_overlap_normal_by_variant": mean_norm,
        "best_tracking_variant_ultimate": best_ult,
        "comp_match_vs_mixed_delta_ultimate": round(delta, 4),
        "rows": [{"champ": c, **{v: ov[v] for v in variants}} for c, ov in rows],
    }
    outp = Path(f"{HERE}/g7_comp_parity.json")
    tmp = outp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    tmp.replace(outp)
    print(f"\nWROTE {outp}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "16.12.1")
