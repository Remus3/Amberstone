"""Conditional-pair pre-filter - finds discrete amped/un-amped damage-block
pairs across every champion, the signature of a `target_no_setup`-style
conditional block_index candidate (Fiddle Q / Anivia E / Brand W shape).

A candidate is a single ability FORM with two filtered (attribute_kind==
'damage') blocks B_lo, B_hi of the SAME shape (identical set of non-zero
scaling-field keys) where B_hi is a near-constant scalar k>1 multiple of
B_lo across every rank position. That is the clean discrete pair the
rigor bar requires (NOT continuous in-block %HP scaling).

Output is a high-precision SHORTLIST only - every hit must still be
hand-verified with tools/ds_cond_inspect.py + real-mechanic knowledge
before it enters the registry (the s229/s230 lesson: recollection
mis-names mechanics ~half the time).

Usage:  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/ds_cond_pair_prefilter.py [min_k]
"""
import json
import sys

PATCH = open(r"data/daemon_slayer/current.txt").read().strip()
D = json.load(open(rf"data/daemon_slayer/{PATCH}/champion_abilities.json"))["data"]
REG = json.load(open(r"agents/daemon_slayer/champion_block_index.json"))["champions"]

SCALE_FIELDS = (
    "base", "total_ad_pct", "bonus_ad_pct", "ap_pct",
    "caster_max_hp_pct", "caster_bonus_hp_pct", "caster_missing_hp_pct",
    "target_max_hp_pct", "target_missing_hp_pct", "target_current_hp_pct",
    "target_bonus_hp_pct", "target_armor_pct", "bonus_armor_pct",
    "bonus_mr_pct", "caster_max_mp_pct",
)


def _shape(b):
    return frozenset(f for f in SCALE_FIELDS if b.get(f))


def _ratio(b_lo, b_hi):
    """Return constant k if b_hi == k*b_lo elementwise across the shared
    shape (first 5 ranks), else None."""
    sh = _shape(b_lo)
    if not sh or sh != _shape(b_hi):
        return None
    ks: list[float] = []
    for f in sh:
        lo = b_lo.get(f) or []
        hi = b_hi.get(f) or []
        n = min(len(lo), len(hi), 5)
        if n == 0:
            return None
        for i in range(n):
            if lo[i] == 0:
                if hi[i] != 0:
                    return None
                continue
            ks.append(hi[i] / lo[i])
    if not ks:
        return None
    k = sum(ks) / len(ks)
    if k <= 1.05:
        return None
    if max(abs(x - k) for x in ks) > 0.02 * k:
        return None
    return k


def _filtered(form):
    return [b for b in form.get("damage_blocks", [])
            if b.get("attribute_kind") == "damage"]


def main(min_k: float) -> None:
    rows = []
    for champ, keys in D.items():
        if champ in ("version", "fetched_at", "source",
                     "engine_phase", "count", "coverage", "data"):
            continue
        if not isinstance(keys, dict):
            continue
        reg_entry = REG.get(champ, {})
        for key in ("P", "Q", "W", "E", "R"):
            forms = keys.get(key)
            if not isinstance(forms, list):
                continue
            cur = reg_entry.get(key)
            for fi, form in enumerate(forms):
                fb = _filtered(form)
                if len(fb) < 2:
                    continue
                for i in range(len(fb)):
                    for j in range(i + 1, len(fb)):
                        k = _ratio(fb[i], fb[j])
                        if k is None or k < min_k:
                            continue
                        rows.append((
                            round(k, 3), champ, key, fi, i, j,
                            sorted(_shape(fb[i])),
                            json.dumps(cur) if cur is not None else "-",
                        ))
    rows.sort(key=lambda r: (-r[0], r[1]))
    print(f"# discrete-pair candidates (k>={min_k}) - {len(rows)} hits")
    print(f"#   patch {PATCH}; HAND-VERIFY each before registry entry")
    print(f"{'k':>6}  {'champ':14s} key f  lo->hi  shape "
          f"/ current_registry")
    for k, champ, key, fi, i, j, shape, cur in rows:
        flag = ""
        if cur == "-":
            flag = "  <== UNMAPPED key"
        elif "default" in cur or "[" in cur:
            flag = "  (already conditional/list)"
        print(f"{k:6.3f}  {champ:14s} {key}  {fi}  {i}->{j}  "
              f"{shape}  cur={cur}{flag}")


if __name__ == "__main__":
    mk = float(sys.argv[1]) if len(sys.argv) > 1 else 1.2
    main(mk)
