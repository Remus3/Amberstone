"""Ad-hoc conditional-candidate inspector.

Dumps the per-form damage blocks for a (champion, key) so the discrete-pair
requirement for a conditional block_index conversion can be verified against
the live Meraki snapshot - NOT against ROADMAP/_meta recollection.

Usage:  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/ds_cond_inspect.py <Champion> [KEY ...]
"""
import json
import sys

PATCH = open(r"data/daemon_slayer/current.txt").read().strip()
D = json.load(open(rf"data/daemon_slayer/{PATCH}/champion_abilities.json"))["data"]

SCALE_FIELDS = (
    "base", "total_ad_pct", "bonus_ad_pct", "ap_pct",
    "caster_max_hp_pct", "caster_bonus_hp_pct", "caster_missing_hp_pct",
    "target_max_hp_pct", "target_missing_hp_pct", "target_current_hp_pct",
    "target_bonus_hp_pct", "target_armor_pct", "bonus_armor_pct",
    "bonus_mr_pct", "caster_max_mp_pct",
)


def show(champ: str, keys: list[str]) -> None:
    c = D.get(champ)
    if c is None:
        print(f"!! champion {champ!r} not in snapshot")
        return
    for key in keys:
        forms = c.get(key)
        print(f"\n===== {champ} {key} =====")
        if not forms:
            print("  (no forms)")
            continue
        for fi, form in enumerate(forms):
            print(f"  -- form {fi}: name={form.get('name')!r} "
                  f"dmg_type={form.get('damage_type')} "
                  f"parse_status={form.get('parse_status')}")
            blocks = form.get("damage_blocks", [])
            for bi, b in enumerate(blocks):
                sc = {f: b.get(f) for f in SCALE_FIELDS if b.get(f)}
                print(f"     block[{bi}] name={b.get('name')!r} "
                      f"kind={b.get('attribute_kind')} "
                      f"type={b.get('damage_type')}  {sc}")
            if not blocks:
                print("     (no damage_blocks)")


if __name__ == "__main__":
    champ = sys.argv[1]
    keys = sys.argv[2:] or ["P", "Q", "W", "E", "R"]
    show(champ, keys)
