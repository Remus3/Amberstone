"""Item 263 - Kai'Sa ARAM rebuild + Ashe SR ADC paths (data-only, atomic).

Carry from the 2026-06-02 live-watch DEFERRED note:

  Kai'Sa ``aram-collapsed`` had an ``ap-hybrid`` path (label "AP Hybrid",
  4 AD items, 0 AP) and a ``bruiser-trinity`` path (label "Trinity", no
  Trinity Force). The ``on-hit`` path is a legit ARAM Kai'Sa build and is
  KEPT. Replace the two junk paths with proven-clean builds mirroring the
  item-213 Kai'Sa SR set (AP burst + crit), boots integral, ARAM summs
  [4, 32].

  Ashe ``sr-collapsed`` had a thin 2-path set, one of which (``sr-enchanter``)
  was a full enchanter build on a ranged ADC. KEEP the ``utility-adc`` path,
  replace the enchanter path with a crit path, add an on-hit path so Ashe
  has 3 coherent ADC paths like Caitlyn / Jinx, SR-ADC summs [4, 21].

The item-167 root (auto-seed coverage gap + the align tool routing a
ranged ADC through an enchanter archetype) is unchanged; this is the
data-side hand-curate, mirroring tools/hotfix_sr_adc_loadouts_item167.py
(quarantined in RC2 P7.3, no longer tracked; recover it from git history).
Idempotent + atomic: the write goes through
core.polled_json.atomic_write_bytes (fsync, WinError 5 retry, no scratch left
behind; ensure_ascii=True, LF, no trailing newline as before).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"

from core import polled_json  # noqa: E402


def path(key, label, items, ks, prim, sec, summs, arch="", is_primary=False):
    r = {
        "key": key,
        "label": label,
        "items": list(items),
        "runes": {"keystone": ks, "primary": prim, "secondary": sec},
        "summoners": list(summs),
        "_source_variant_key": key,
    }
    if arch:
        r["_archetype"] = arch
    if is_primary:
        r["_is_primary"] = True
    return r


# (champion, variant_key) -> ordered build_paths. First with _is_primary
# drives the variant-level items/runes/summoners.
PATCH = {
    ("Kai'Sa", "aram-collapsed"): [
        path("on-hit", "On-Hit",
             ["Blade of The Ruined King", "Berserker's Greaves", "Wit's End",
              "Guinsoo's Rageblade", "Terminus", "Sterak's Gage"],
             "Lethal Tempo", "Precision", "Resolve", (4, 32), is_primary=True),
        path("ap-burst", "AP",
             ["Hubris", "Berserker's Greaves", "Nashor's Tooth",
              "Rabadon's Deathcap", "Void Staff", "Shadowflame"],
             "Electrocute", "Domination", "Sorcery", (4, 32)),
        path("adc-crit", "Crit",
             ["Yun Tal Wildarrows", "Berserker's Greaves", "Infinity Edge",
              "Rapid Firecannon", "Lord Dominik's Regards", "Runaan's Hurricane"],
             "Press the Attack", "Precision", "Domination", (4, 32)),
    ],
    ("Ashe", "sr-collapsed"): [
        path("utility-adc", "Utility ADC",
             ["Blade of The Ruined King", "Berserker's Greaves", "Runaan's Hurricane",
              "Lord Dominik's Regards", "Yun Tal Wildarrows", "Infinity Edge"],
             "Press the Attack", "Precision", "Sorcery", (4, 21), is_primary=True),
        path("adc-crit", "Crit",
             ["Yun Tal Wildarrows", "Berserker's Greaves", "Infinity Edge",
              "Rapid Firecannon", "Lord Dominik's Regards", "Runaan's Hurricane"],
             "Lethal Tempo", "Precision", "Domination", (4, 21)),
        path("adc-on-hit", "On-Hit",
             ["Blade of The Ruined King", "Berserker's Greaves", "Runaan's Hurricane",
              "Wit's End", "Lord Dominik's Regards", "Phantom Dancer"],
             "Lethal Tempo", "Precision", "Domination", (4, 21)),
    ],
}


def main() -> None:
    d = json.loads(_LOADOUTS.read_text(encoding="utf-8"))
    ch = d["champions"]
    flips = 0
    for (name, vk), paths in PATCH.items():
        if name not in ch:
            print(f"SKIP {name} not in roster")
            continue
        v = ch[name]["variants"].get(vk)
        if not v:
            print(f"SKIP {name} no {vk}")
            continue
        prim = next(pp for pp in paths if pp.get("_is_primary"))
        v["runes"] = dict(prim["runes"])
        v["summoners"] = list(prim["summoners"])
        v["items"] = list(prim["items"])
        v["build_paths"] = paths
        flips += 1
        print(f"  patched {name} {vk}: PRIMARY = {prim['label']} {prim['items'][:3]}...")
    text = json.dumps(d, ensure_ascii=True, indent=2)
    polled_json.atomic_write_bytes(_LOADOUTS, text.encode("utf-8"))
    print(f"OK {flips} variants patched, atomic write done")


if __name__ == "__main__":
    main()
