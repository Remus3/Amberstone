"""DS on-hit-AP broad-scan classifier (Slice B Task 9, 2026-07-16).

Flags champion candidates for the on-hit-AP axis-coherence roster
(core/ds_onhit_ap_roster.json + core/ds_onhit_ap_roster.py, consumed by
core/daemon_slayer_client.py::_onhit_coherence_for). A candidate must be
BOTH:

  (1) AP-axis for on-hit purposes - agents.daemon_slayer.onhit_dps
      ._onhit_ap_axis. NOT raw DDragon info.magic > info.attack alone (a
      known repo gotcha: DDragon info is zeroed for several champions, and
      even where it is not, the raw split misrates Gwen/Kog'Maw as AD).
      ``_onhit_ap_axis`` first tries hybrid.py's ``_damage_axis`` (the raw
      DDragon split) then falls back to the champion's own AA-routed
      on-hit passive's bilinear AP term - built precisely to fix the
      Gwen/Kog'Maw misrate.

  (2) AS/on-hit-reliant, ANY of:
        (a) agents.daemon_slayer._passive_damage_overrides
            .aa_routed_on_hit_entry is not None - the engine already
            models a real every-AA magic rider for this champ. Strongest
            signal (Gwen/Kayle/KogMaw/Orianna/Warwick; Warwick fails (1)).
        (b) agents.daemon_slayer._passive_as_overrides.passive_as_entry is
            not None - the engine models a real innate self-attack-speed
            steroid (Irelia/Jax/Ezreal/Volibear at 16.14.1). None of these
            four pass (1) today - kept for completeness / future patches,
            not dead code.
        (c) elevated stats.attackspeedperlevel (>= ASP_THRESHOLD) - a
            broader, DDragon-stat-only speculative net for a hybrid whose
            AS-scaling kit is not yet registry-modeled. Documented in the
            Task 9 report as precision-poor in isolation (dominated by
            Support/Tank archetypes with base-kit-quirk AS growth and ZERO
            on-hit reliance: Azir/Braum/Neeko/Thresh/Janna/Milio/Rakan/...).
            Kept per the task-9 brief as a transparency net for
            --calibrate to falsify with live evidence, never a keep
            verdict by itself.

  excluding core.archetype_picks._AP_ASSASSIN_IDS (those already route to
  the ds.burst scorer).

Usage:
  python tools/ds_onhit_ap_prefilter.py                # scan only, print candidates
  python tools/ds_onhit_ap_prefilter.py --calibrate     # + probe live :8860/rank-onhit

--calibrate requires the DS engine running at http://127.0.0.1:8860 (plain
HTTP). Uses stdlib urllib only - no requests/curl dependency.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.daemon_slayer._passive_as_overrides import passive_as_entry
from agents.daemon_slayer._passive_damage_overrides import aa_routed_on_hit_entry
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.onhit_dps import _onhit_ap_axis
from core.archetype_picks import _AP_ASSASSIN_IDS

DS_URL = "http://127.0.0.1:8860"

# Calibration target context - lifted VERBATIM from the already-green,
# already-committed Task 5 regression
# (agents/daemon_slayer/tests/test_onhit_dps.py::test_nashors_surfaces_with_coherence),
# which is the proof that Nashor's surfaces top-8 for Gwen/Kayle/KogMaw at
# coherence 1.0/0.3/0.6 respectively. Reusing it keeps this tool's live
# probes apples-to-apples with that test instead of inventing a new context.
LEVEL = 13
TARGET_ARMOR = 105.0
TARGET_MR = 52.0
TARGET_MAX_HP = 2430.0
TOP_N = 8
COHERENCE_VALUES = (0.0, 0.3, 0.6, 1.0)

# Seed 3 (T5-validated, do not re-tune) + their required coherence.
SEED_CHAMPS: dict[str, float] = {"Gwen": 1.0, "Kayle": 0.3, "KogMaw": 0.6}

# "Elevated" attackspeedperlevel threshold (Task 9 empirical scan, patch
# 16.14.1). The seed 3 sit at Gwen 2.25 / Kayle 1.50 / KogMaw 2.65 - all
# already caught by signal (a), so this branch does not need to reach them.
# 3.0 sits one clean step above KogMaw (the highest seed) and captures the
# next tier of AP-axis champs (Orianna 3.5, Kennen 3.4, Malphite 3.4,
# Teemo 3.38, DrMundo/Ekko 3.3, ...) without pulling in the bulk-baseline
# caster/support band (Karma 2.30, Zoe 2.50, Nami 2.61). See
# .superpowers/sdd/task-9-report.md for the full distribution and why this
# signal is precision-poor used alone (dominated by Support/Tank false
# positives with no on-hit kit mechanic at all).
ASP_THRESHOLD = 3.0

# Items whose tags include this are AP-axis-coherent for on-hit purposes -
# the EXACT tag the live gate itself reads (rank_items_by_onhit._coherence_key:
# "SpellDamage" in tags). Reusing it here keeps "does the top-8 read
# AP-coherent" judged by the same definition the engine already enforces,
# not a second, possibly-inconsistent heuristic.
_AP_TAG = "SpellDamage"
_DAMAGE_TAG = "Damage"
NASHORS_ID = "3115"


def _onhit_reliant_reasons(snap: DataSnapshot, champ: str) -> list[str]:
    """Return the list of matched signal(2) reasons, empty if none match."""
    reasons: list[str] = []
    if aa_routed_on_hit_entry(champ) is not None:
        reasons.append("kit-onhit(aa_routed)")
    if passive_as_entry(champ) is not None:
        reasons.append("as-steroid")
    rec = snap.champions.get(champ) or {}
    asp = float((rec.get("stats") or {}).get("attackspeedperlevel", 0.0) or 0.0)
    if asp >= ASP_THRESHOLD:
        reasons.append(f"elevated-asp({asp:.2f})")
    return reasons


def scan(snap: DataSnapshot) -> list[tuple[str, list[str]]]:
    """Iterate the champion snapshot and flag (champ, reasons) candidates."""
    candidates: list[tuple[str, list[str]]] = []
    for champ in sorted(snap.champions):
        if champ in _AP_ASSASSIN_IDS:
            continue
        if _onhit_ap_axis(snap, champ) != "ap":
            continue
        reasons = _onhit_reliant_reasons(snap, champ)
        if reasons:
            candidates.append((champ, reasons))
    return candidates


def _post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{DS_URL}{path}",
        data=data,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def calibrate_one(champ: str) -> dict[float, dict]:
    """Probe /rank-onhit at each coherence value; return {coherence: summary}."""
    out: dict[float, dict] = {}
    for coh in COHERENCE_VALUES:
        try:
            result = _post(
                "/rank-onhit",
                {
                    "champion": champ,
                    "level": LEVEL,
                    "items": [],
                    "mode": "SR",
                    "target_armor": TARGET_ARMOR,
                    "target_mr": TARGET_MR,
                    "target_max_hp": TARGET_MAX_HP,
                    "top": TOP_N,
                    "ap_ad_coherence": coh,
                },
            )
        except (urllib.error.URLError, OSError, ValueError) as e:
            out[coh] = {"error": str(e)}
            continue
        ranked = result.get("ranked") or []
        top = [
            (r["item_id"], r["item_name"], tuple(r.get("tags") or ()))
            for r in ranked[:TOP_N]
        ]
        ap_hits = [t for t in top if _AP_TAG in t[2]]
        ad_hits = [t for t in top if _AP_TAG not in t[2] and _DAMAGE_TAG in t[2]]
        nashors_rank = next((i + 1 for i, t in enumerate(top) if t[0] == NASHORS_ID), None)
        out[coh] = {
            "top": top,
            "ap_count": len(ap_hits),
            "ad_count": len(ad_hits),
            "nashors_rank": nashors_rank,
        }
    return out


def main() -> int:
    do_calibrate = "--calibrate" in sys.argv
    snap = DataSnapshot.load()
    candidates = scan(snap)

    print(f"AP-axis + on-hit-reliant candidates (excl. _AP_ASSASSIN_IDS): {len(candidates)}")
    for champ, reasons in candidates:
        print(f"  {champ:16s} {','.join(reasons)}")
    print("\nFLAGGED=" + ",".join(c for c, _ in candidates))

    if not do_calibrate:
        return 0

    all_champs = sorted(set(SEED_CHAMPS) | {c for c, _ in candidates})
    print(
        f"\n--- live calibration ({DS_URL}/rank-onhit, "
        f"level={LEVEL} armor={TARGET_ARMOR} mr={TARGET_MR} "
        f"target_max_hp={TARGET_MAX_HP}) ---"
    )
    for champ in all_champs:
        tag = " [SEED]" if champ in SEED_CHAMPS else ""
        print(f"\n{champ}{tag}:")
        results = calibrate_one(champ)
        for coh in COHERENCE_VALUES:
            r = results[coh]
            if "error" in r:
                print(f"  coh={coh:.1f}  ERROR {r['error']}")
                continue
            names = [t[1] for t in r["top"][:3]]
            print(
                f"  coh={coh:.1f}  ap_in_top8={r['ap_count']}  "
                f"ad_in_top8={r['ad_count']}  nashors_rank={r['nashors_rank']}  "
                f"top3={names}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
