"""Execute / threshold-amp pre-filter - finds the Kindred-E archetype
the constant-k pair scanner (ds_cond_pair_prefilter.py) structurally
MISSES.

That scanner requires every shared scaling field to scale by ONE
constant k. The execute archetype is two SAME-shape damage blocks where
the amp is concentrated in a target-HP coefficient (Kindred E: 5% ->
7.5% missing-HP, base unchanged) - different per-field ratios, so the
constant-k scanner rejects it.

Signature here: an ability FORM with two filtered damage blocks B_lo,
B_hi of the same shape (same non-zero scaling-field key set) where
at least one of {target_missing_hp_pct, target_current_hp_pct,
target_max_hp_pct} is strictly larger in B_hi, and every other shared
field is >= its B_lo value (B_hi is a monotone threshold-amp of B_lo -
the discrete execute pair). Filters keys already conditional.

High-precision shortlist; HAND-VERIFY each against real mechanics +
Meraki before any registry entry (the s229-s231 lesson).

Usage:  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/ds_execute_prefilter.py
"""
import json

PATCH = open(r"data/daemon_slayer/current.txt").read().strip()
D = json.load(open(rf"data/daemon_slayer/{PATCH}/champion_abilities.json"))["data"]
REG = json.load(open(r"agents/daemon_slayer/champion_block_index.json"))["champions"]

HP_FIELDS = ("target_missing_hp_pct", "target_current_hp_pct",
             "target_max_hp_pct")
SCALE_FIELDS = (
    "base", "total_ad_pct", "bonus_ad_pct", "ap_pct",
    "caster_max_hp_pct", "caster_bonus_hp_pct", "caster_missing_hp_pct",
    "target_max_hp_pct", "target_missing_hp_pct", "target_current_hp_pct",
    "target_bonus_hp_pct", "target_armor_pct", "bonus_armor_pct",
    "bonus_mr_pct", "caster_max_mp_pct",
)


def _shape(b):
    return frozenset(f for f in SCALE_FIELDS if b.get(f))


def _filtered(form):
    return [b for b in form.get("damage_blocks", [])
            if b.get("attribute_kind") == "damage"]


def _first(b, f):
    v = b.get(f) or []
    return v[0] if v else 0.0


def _is_threshold_amp(b_lo, b_hi):
    """B_hi is a monotone threshold-amp of same-shape B_lo, with the
    increase touching at least one target-HP coefficient."""
    sh = _shape(b_lo)
    if not sh or sh != _shape(b_hi):
        return None
    hp_bump = False
    for f in sh:
        lo, hi = _first(b_lo, f), _first(b_hi, f)
        if hi < lo - 1e-9:
            return None  # not monotone - a different facet, not an amp
        if f in HP_FIELDS and hi > lo + 1e-9:
            hp_bump = True
    if not hp_bump:
        return None
    # describe the dominant HP-coeff jump
    parts = []
    for f in HP_FIELDS:
        if f in sh:
            lo, hi = _first(b_lo, f), _first(b_hi, f)
            if hi > lo + 1e-9:
                parts.append(f"{f}:{lo}->{hi}")
    return ",".join(parts)


def main() -> None:
    rows = []
    for champ, keys in D.items():
        if not isinstance(keys, dict):
            continue
        reg = REG.get(champ, {})
        for key in ("P", "Q", "W", "E", "R"):
            forms = keys.get(key)
            if not isinstance(forms, list):
                continue
            cur = reg.get(key)
            for fi, form in enumerate(forms):
                fb = _filtered(form)
                if len(fb) < 2:
                    continue
                for i in range(len(fb)):
                    for j in range(len(fb)):
                        if i == j:
                            continue
                        desc = _is_threshold_amp(fb[i], fb[j])
                        if desc is None:
                            continue
                        rows.append((champ, key, fi, i, j, desc,
                                     sorted(_shape(fb[i])), cur))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    print(f"# execute / threshold-amp candidates - {len(rows)} hits "
          f"(patch {PATCH})")
    print("#   HAND-VERIFY mechanic + Meraki before any registry entry")
    for champ, key, fi, i, j, desc, shape, cur in rows:
        if isinstance(cur, dict):
            tag = "ALREADY-CONDITIONAL"
        elif cur is None:
            tag = "UNMAPPED"
        elif cur == j:
            tag = f"mapped->amp({cur})"
        elif cur == i:
            tag = f"UNDER->cur={cur}(lo)"
        else:
            tag = f"cur={cur}"
        print(f"{champ:14s} {key} f{fi} {i}->{j}  {tag:20s} "
              f"{desc}  shape={shape}")


if __name__ == "__main__":
    main()
