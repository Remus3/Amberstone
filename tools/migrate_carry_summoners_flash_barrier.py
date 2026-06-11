"""One-shot migration: flip stored SR carry summoners [4, 7] -> [4, 21].

Background (item 169):
  - Solo-ADC 16.10.x meta norm is Flash + Barrier, not Flash + Heal.
  - Heal stays correct for bot-lane duo synergy picks (Senna, Kalista)
    and bootsless/attached marksmen (Yuumi-attached carry partners).
  - `tools/champion_loadout_autogen.py` SR_SUMM_BY_ARCH["carry"] used to
    be [4, 7]; item 169 flipped it to [4, 21]. Item 166 hand-curate
    cloned the auto- seeds verbatim, so the stored variants in
    `data/champion_loadouts.json` still carry [4, 7] on nearly every
    carry-coded SR variant.

Scope:
  - SR only. Arena keeps [4, 7]. ARAM keeps [4, 32].
  - Carry-coded detection (any of):
      variant_key matches one of: sr-carry, adc-*, ad-crit, on-hit
        OR contains the literal substring "carry"
      `_archetype` field equals "carry"
      `runes.keystone` in {Lethal Tempo, Press the Attack, Fleet Footwork}

Per-champ denylist BOT_DUO_HEAL_KEEP = {"Senna", "Kalista", "Yuumi"}:
  - Senna + Kalista are pure ADC carries that DO live in bot lane and
    DO synergize with their support pick (Heal stays the meta choice).
  - Yuumi is the bootsless enchanter; she attaches to whatever carry
    her support is paired with - flip Yuumi to Barrier would actively
    confuse the LCU push since Yuumi never runs carry summoners.
  (Yuumi is enchanter-coded and won't normally pass the carry filter,
   but the denylist defends against future hand-curate that mis-tags
   her on a carry variant.)

Atomic write only (tmp.write_text + tmp.replace). ASCII content.

Invoke once:
  C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/migrate_carry_summoners_flash_barrier.py

Prints summary: champs_touched, variants_flipped, denylisted_kept.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LOADOUTS_PATH = _ROOT / "data" / "champion_loadouts.json"

# Per-champ denylist: keep [4, 7] on these even when carry-coded.
BOT_DUO_HEAL_KEEP: frozenset[str] = frozenset({"Senna", "Kalista", "Yuumi"})

# Carry-tagged keystones (runes.keystone) - inferred carry intent even
# when the variant_key doesn't carry an obvious string clue.
KEYSTONES_CARRY: frozenset[str] = frozenset(
    {"Lethal Tempo", "Press the Attack", "Fleet Footwork"}
)


def _is_carry_coded(variant_key: str, variant: dict) -> bool:
    """Return True if this variant should be treated as a carry pick.

    Matches any one of:
      - variant_key contains "sr-carry", "adc-", "ad-crit", "on-hit"
        or the literal substring "carry"
      - variant.get("_archetype") == "carry"
      - variant.get("runes", {}).get("keystone") in KEYSTONES_CARRY
    """
    key_lower = variant_key.lower()
    if (
        "sr-carry" in key_lower
        or "adc-" in key_lower
        or "ad-crit" in key_lower
        or "on-hit" in key_lower
        or "carry" in key_lower
    ):
        return True
    if variant.get("_archetype") == "carry":
        return True
    keystone = (variant.get("runes") or {}).get("keystone")
    if keystone in KEYSTONES_CARRY:
        return True
    return False


def _atomic_write(path: Path, payload: dict) -> None:
    """Atomic JSON write per CLAUDE.md hard rule."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def migrate(path: Path = _LOADOUTS_PATH) -> dict:
    """Mutate data/champion_loadouts.json in-place. Returns counts dict."""
    data = json.loads(path.read_text(encoding="utf-8"))
    champs = data.get("champions", {})

    champs_touched: set[str] = set()
    variants_flipped = 0
    denylisted_kept = 0

    for champ_name, info in champs.items():
        if not isinstance(info, dict):
            continue
        variants = info.get("variants", {})
        if not isinstance(variants, dict):
            continue
        for variant_key, variant in variants.items():
            if not isinstance(variant, dict):
                continue
            modes = variant.get("modes") or []
            if "sr" not in modes:
                continue
            summs = variant.get("summoners")
            if summs != [4, 7]:
                continue
            if not _is_carry_coded(variant_key, variant):
                continue
            if champ_name in BOT_DUO_HEAL_KEEP:
                denylisted_kept += 1
                continue
            variant["summoners"] = [4, 21]
            variants_flipped += 1
            champs_touched.add(champ_name)

    _atomic_write(path, data)

    return {
        "champs_touched": len(champs_touched),
        "variants_flipped": variants_flipped,
        "denylisted_kept": denylisted_kept,
        "denylist": sorted(BOT_DUO_HEAL_KEEP),
    }


def main() -> None:
    counts = migrate()
    print(
        f"champs_touched={counts['champs_touched']} "
        f"variants_flipped={counts['variants_flipped']} "
        f"denylisted_kept={counts['denylisted_kept']} "
        f"denylist={counts['denylist']}"
    )


if __name__ == "__main__":
    main()
