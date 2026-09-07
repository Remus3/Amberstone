# arch: cdragon per-spell stat sidecar extractor (character bins -> cdragon_spell_stats.json) | section=tools | frozen=no
"""CommunityDragon character-bin per-spell scalars -> per-champion sidecar JSON.

Item 225 (2026-05-30): a thin OPTIONAL DATA sidecar extractor that walks each
champion's CommunityDragon character bin and emits a per-spell record carrying 4
buckets of structured spell metadata the Meraki abilities dump does NOT carry:

  D. CHARGE / AMMO     - mMaxAmmo (per-rank int array) + mAmmoRechargeTime
                         (per-rank float array). Most spells have none; emitted
                         only when mMaxAmmo is present with a value > 0.
                         Verbatim live (16.11): Corki R (MissileBarrage)
                         mMaxAmmo=[4,4,4,4,4,4,4], mAmmoRechargeTime=[20.0,...].
  G. MISSILE SPEED     - missileSpeed (units/s). The primary cast record often
                         shows 0 or a tiny placeholder (20) while the REAL travel
                         speed lives on a sibling <Name>...Missile sub-record
                         under the SAME ability container. Verbatim: Leona E
                         (LeonaZenithBlade) cast record 1200 but the sibling
                         LeonaZenithBladeMissile 2000; Morgana W/E/R 20
                         (point-target, no travel). The extractor captures the
                         cast-record speed AND the best sibling-missile speed and
                         resolves a single ``missile_speed`` (prefers the sibling
                         travel speed when the cast record is 0/tiny <=20).
  F-lite. COARSE CC    - mSpellTags (string array). The CC-relevant tags only
                         (any tag containing ImmobilizingCC / Stun / Root /
                         Snare / Knockup / Knockback / Displacement / Charm /
                         Fear / Taunt / Suppress / Sleep / Slow). Verbatim: Leona
                         Q/E/R carry "Trait_ImmobilizingCCSpell". This is a COARSE
                         boolean CC-class flag (NOT a duration, NOT a
                         stun-vs-root discriminator). Tags are stored as-is EXCEPT
                         the ImmobilizingCC family: Riot 16.13 added an
                         "...ImmobilizingCCAbility" suffix twin to the legacy
                         "...ImmobilizingCCSpell"; we match the stable
                         "ImmobilizingCC" stem and canonicalize the suffix back to
                         "...Spell" so the flag survives the rename (the
                         SwapsInto-vs-direct distinction is preserved). See
                         _canon_cc_tag.
  H. AOE GEOMETRY      - castConeDistance + castConeAngle (cones, CLEAN - verbatim
                         Nautilus W dist=1400 angle=20.0) + castRadius (CONFLATED:
                         defaults to a boilerplate 210/100 on many point spells;
                         captured under ``cast_radius`` + flagged
                         ``cast_radius_conflated: true`` so a consumer knows not to
                         bulk-trust it) + mLineWidth / mMissileSpec.mMissileWidth
                         (line width) when present.

SOURCE (verified live this session, reachable via stdlib urllib + a
browser UA): the character bin at
``https://raw.communitydragon.org/<MAJOR.MINOR>/game/data/characters/<slug>/<slug>.bin.json``
where <slug> = lowercased DDragon id. CRITICAL: CDragon patch is 2-SEGMENT -
``/16.11/`` works, ``/16.11.1/`` 404s. The repo patch ``16.11.1`` (from
``data/daemon_slayer/current.txt``) is mapped to ``16.11`` for the URL.

BIN SHAPE (verbatim live): the JSON is a FLAT dict of dotted-path keys, e.g.
``Characters/Corki/Spells/MissileBarrageAbility/MissileBarrage``; each value is a
spell-record dict whose scalars live under an ``mSpell`` sub-dict. The
``Characters/<Name>/CharacterRecords/Root`` record holds ``spellNames`` - a
4-entry list in Q/W/E/R order, each ``<AbilityName>/<SpellName>`` - which is the
authoritative slot mapping. We key the output by Q/W/E/R via that list (a 5th
passive slot is NOT in spellNames so it is not emitted; documented in ``_note``).

NOT a live dependency: this is an OFFLINE patch-refresh tool, the SAME contract
as ``daemon_slayer_abilities_extract.py`` + ``daemon_slayer_wiki_stats_extract.py``.
The DS engine reads the committed sidecar JSON, never the network. No consumer
wires it yet (DATA-ONLY this session); it is INERT until a consumer opts in.

Run from any host that reaches raw.communitydragon.org:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_cdragon_spell_extract.py             # current.txt patch
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_cdragon_spell_extract.py --patch 16.11.1
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_cdragon_spell_extract.py --limit 4   # smoke a subset
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_cdragon_spell_extract.py --dry-run    # no write
Then inspect ``_with_*`` / ``_errors`` before trusting it: a run that edge-blocks
the host records 0 of everything (the fail-soft path), so a sidecar with every
``_with_*`` 0 means the host could not reach CDragon - the main() prints a
WARNING and the file is NOT committable.

Design (mirrors the wiki-stats extractor; don't re-litigate):
  * stdlib ``urllib`` only - no new pip dep (the DS data-pipeline rule).
  * User-Agent header set; CDragon ``latest``/patch CDN flaps -> a couple of
    backoff retries per fetch (mirror ``_fetch_with_retry``).
  * polite ``--sleep`` (default 0.5) between per-champ fetches.
  * fail-soft per champ: a bad/empty/blocked bin records an error + an empty
    spell map, never aborts the whole run.
  * Atomic write: tmp.write_text + os.replace (overlays poll mid-write).
  * ASCII-only output (ensure_ascii=True) + ASCII-only source - no em/en-dashes,
    no smart quotes (the hard repo rule).
  * champion-id source = the committed abilities snapshot's top-level ``data``
    dict (171 champs at 16.11.1; keyed by DDragon id). The CDragon slug is
    ``id.lower()`` (an override hook is kept for future patch drift).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data" / "daemon_slayer"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.daemon_slayer.mode_variants import canonical_champions  # noqa: E402

# CommunityDragon character-bin source. Filename is <slug>.bin.json (the bare
# <slug>.json 404s). The patch segment is 2-part (16.11, NOT 16.11.1).
CDRAGON_CHAR_URL = (
    "https://raw.communitydragon.org/{patch}/game/data/characters/{slug}/{slug}.bin.json"
)
HEADER_UA = (
    "Amberstone-DaemonSlayer/1.0 (offline patch-refresh extractor; local coaching tool)"
)
_HTTP_TIMEOUT = 40

# CDragon CDN 404s in short bursts while it rebuilds the patch symlink; a couple
# of backoff retries rides over a typical window. Module-level so tests can
# shrink them (the default sleeps would slow a fail-soft test).
_CDRAGON_RETRIES = 3
_CDRAGON_RETRY_BACKOFF_S = 3.0

# DDragon id -> CDragon slug override, for future patch drift. Empty: every
# 16.11.1 id resolves with the bare ``id.lower()`` slug (verified for the wiki
# extractor's identical bin fetch).
_CDRAGON_SLUG_OVERRIDES: dict[str, str] = {}

# A primary cast-record missileSpeed at or below this is a placeholder (point
# spell or pre-travel record); when a sibling <Name>...Missile sub-record carries
# a higher positive speed, that travel speed is the real value. Verbatim:
# Morgana W/E/R cast records = 20 (point); Leona E cast = 1200, sibling
# LeonaZenithBladeMissile = 2000. 20 is the observed placeholder ceiling.
_MISSILE_PLACEHOLDER_MAX = 20.0

# castRadius defaults that are the engine boilerplate (NOT a real AoE radius) on
# point-target spells. Captured but flagged ``cast_radius_conflated`` so a
# consumer does not bulk-trust them. Verbatim live: 210 on Corki GGSpray + many
# point spells; 100 the other boilerplate. A castRadius equal to one of these is
# flagged conflated.
_CONFLATED_CAST_RADII = (210.0, 100.0)

# mSpellTags substrings that mark a CC-relevant tag (coarse class flag only). The
# matching tags are stored (the ImmobilizingCC family suffix-canonicalized, see
# _canon_cc_tag); this is intentionally broad. Verbatim: Leona carries
# "Trait_ImmobilizingCCSpell". Riot's tag vocabulary is sparse on CC-type
# discrimination so the umbrella ImmobilizingCC is the main hit; the rest are
# defensive in case a bin carries a more specific tag. The stem is "ImmobilizingCC"
# (NOT "...CCSpell") so it also catches the 16.13 "...ImmobilizingCCAbility" /
# "...SwapsIntoImmobilizingCCAbility" twins Riot added (see _canon_cc_tag).
_CC_TAG_SUBSTRINGS = (
    "ImmobilizingCC",
    "Stun",
    "Root",
    "Snare",
    "Knockup",
    "Knockback",
    "Displacement",
    "Charm",
    "Fear",
    "Flee",
    "Taunt",
    "Suppress",
    "Sleep",
    "Slow",
    "Airborne",
)

# Riot 16.13 introduced a parallel CC trait suffix: the legacy
# "...ImmobilizingCCSpell" family gained "...ImmobilizingCCAbility" twins, and Riot
# moved several spells across the swap/direct line at the same time (verbatim live:
# Aphelios Q "Trait_SwapsIntoImmobilizingCCSpell" -> "...CCAbility" while staying a
# swap; Yasuo Q reclassified from "Trait_SwapsIntoImmobilizingCCSpell" to a DIRECT
# "Trait_ImmobilizingCCAbility"). The Spell/Ability suffix is Riot-internal churn
# with no coaching meaning, so we match the stable "ImmobilizingCC" stem (above)
# and canonicalize the captured literal back to the legacy "...Spell" form: the
# coarse CC-class flag stays stable across the rename while the SwapsInto-vs-direct
# distinction Riot DOES still track is preserved verbatim. This is the one place a
# cc_tags entry is NOT stored byte-as-is from the bin (documented in _note).
_CC_ABILITY_SUFFIX = "ImmobilizingCCAbility"
_CC_CANON_SUFFIX = "ImmobilizingCCSpell"


def _canon_cc_tag(tag: str) -> str:
    """Normalize a 16.13 "...ImmobilizingCCAbility" tag to the legacy
    "...ImmobilizingCCSpell" literal (suffix-only; a leading SwapsInto prefix, when
    present, is preserved). Non-ImmobilizingCC tags pass through unchanged."""
    if tag.endswith(_CC_ABILITY_SUFFIX):
        return tag[: -len(_CC_ABILITY_SUFFIX)] + _CC_CANON_SUFFIX
    return tag


# Standard 4-slot ordering of CharacterRecords/Root.spellNames.
_SLOT_KEYS = ("Q", "W", "E", "R")


def _fetch(url: str, timeout: int = _HTTP_TIMEOUT) -> str:
    """GET text with a UA header (CDragon serves UA-less but the wiki sibling
    extractor sets one; match for consistency)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": HEADER_UA, "Accept": "*/*"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _fetch_with_retry(url: str, retries: int = _CDRAGON_RETRIES,
                      backoff_s: float = _CDRAGON_RETRY_BACKOFF_S) -> str:
    """``_fetch`` with a few backoff retries (for the flapping CDragon CDN)."""
    last: Optional[Exception] = None
    for attempt in range(max(1, retries)):
        try:
            return _fetch(url)
        except Exception as exc:  # noqa: BLE001 - retry transient CDN 404/5xx
            last = exc
            if attempt + 1 < retries and backoff_s > 0:
                time.sleep(backoff_s * (attempt + 1))
    raise last if last is not None else RuntimeError("fetch failed")


def _resolve_patch(patch: Optional[str]) -> str:
    """The repo patch id (e.g. 16.11.1). Default from current.txt."""
    if patch:
        return patch
    cur = (DATA_DIR / "current.txt").read_text(encoding="utf-8").strip()
    if not cur:
        raise SystemExit("current.txt empty; pass --patch")
    return cur


def _cdragon_patch_segment(patch: str) -> str:
    """Map a repo patch id to the CDragon 2-segment URL form.

    CDragon URLs use ``MAJOR.MINOR`` only - ``16.11`` works, ``16.11.1`` 404s.
    Takes the first two dot-segments. A non-numeric label (e.g. ``latest``,
    ``pbe``) is passed through unchanged.
    """
    parts = patch.split(".")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return parts[0] + "." + parts[1]
    return patch


def _load_roster_champion_ids(patch: str) -> list[str]:
    """DDragon ids from the committed ROSTER snapshot (``champions.json``).

    A-26 / RM-95b. The abilities snapshot is a Meraki derivative frozen upstream
    since 2025-08-01 and is 2 champions short of the live roster (Locke,
    Zaahen). CDragon character bins for both DO exist, so this cap - not
    CDragon - is what keeps them out of the spell sidecar.
    OPT-IN ONLY - reached via ``_load_champion_ids(..., full_roster=True)``.
    """
    roster = DATA_DIR / patch / "champions.json"
    if not roster.exists():
        raise SystemExit(f"roster file missing: {roster} (run the champions extractor first)")
    raw = json.loads(roster.read_text(encoding="utf-8"))
    champs = raw.get("data") or {}
    if not champs:
        raise SystemExit(f"roster file {roster} has no 'data' champion container")
    # The snapshot is extracted verbatim and carries DDragon THROWBACK-MODE rows
    # from 16.15.1 (60 Jade_<Champion>); they are not live champions.
    return sorted(canonical_champions(champs))


def _load_champion_ids(patch: str) -> list[str]:
    """DDragon ids to extract, from the committed abilities snapshot.

    The abilities file keys champions under the top-level ``data`` dict (NOT
    ``champions``; the top level also holds version/fetched_at/source/count/
    coverage/engine_phase).
    """
    abil = DATA_DIR / patch / "champion_abilities.json"
    if not abil.exists():
        raise SystemExit(
            f"abilities file missing: {abil} (run the abilities extractor first)"
        )
    raw = json.loads(abil.read_text(encoding="utf-8"))
    champs = raw.get("data") or raw.get("champions") or {}
    if not champs:
        raise SystemExit(f"abilities file {abil} has no 'data' champion container")
    return sorted(champs.keys())


def _resolve_champion_ids(patch: str, full_roster: bool) -> list[str]:
    """Pick the champion keyspace: the abilities snapshot (default) or the roster.

    ``full_roster=False`` is the pre-A-26 behavior and MUST stay byte-identical:
    it delegates to ``_load_champion_ids`` unchanged.
    """
    if full_roster:
        return _load_roster_champion_ids(patch)
    return _load_champion_ids(patch)


def _cdragon_slug(ddragon_id: str) -> str:
    """DDragon id -> CDragon character slug (lowercased id, override-able)."""
    if ddragon_id in _CDRAGON_SLUG_OVERRIDES:
        return _CDRAGON_SLUG_OVERRIDES[ddragon_id]
    return ddragon_id.lower()


# --------------------------------------------------------------------------- parse helpers
def _num(v: Any) -> Optional[float]:
    """A scalar -> float, or None for bool / non-numeric."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _round6(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(float(v), 6)


def _int_array(v: Any) -> Optional[list[int]]:
    """A per-rank int array (mMaxAmmo) -> list[int], or None if not a usable array."""
    if not isinstance(v, list) or not v:
        return None
    out: list[int] = []
    for x in v:
        n = _num(x)
        if n is None:
            return None
        out.append(int(round(n)))
    return out


def _float_array(v: Any) -> Optional[list[float]]:
    """A per-rank float array (mAmmoRechargeTime) -> list[float], or None."""
    if not isinstance(v, list) or not v:
        return None
    out: list[float] = []
    for x in v:
        n = _num(x)
        if n is None:
            return None
        rounded = _round6(n)
        if rounded is None:
            return None
        out.append(rounded)
    return out


def _first_scalar(v: Any) -> Optional[float]:
    """A castRadius value (per-rank array OR scalar) -> the first/scalar float."""
    if isinstance(v, list):
        return _num(v[0]) if v else None
    return _num(v)


def _cc_tags(tags: Any) -> list[str]:
    """The CC-relevant subset of an mSpellTags list (matching strings, the
    ImmobilizingCC family suffix-canonicalized + deduped).

    Matches on the stable "ImmobilizingCC" stem so the 16.13 "...Ability" twins are
    caught, then canonicalizes that family to the legacy "...Spell" literal (see
    _canon_cc_tag) so the coarse CC-class flag survives Riot's Spell<->Ability
    rename. Non-Immobilizing CC substrings (Stun/Root/...) are matched + stored
    verbatim. Dedup preserves first-seen order (a slot carrying both the Spell and
    Ability twin collapses to one canonical entry)."""
    if not isinstance(tags, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for t in tags:
        if isinstance(t, str) and any(sub in t for sub in _CC_TAG_SUBSTRINGS):
            canon = _canon_cc_tag(t)
            if canon not in seen:
                seen.add(canon)
                out.append(canon)
    return out


def _ammo_bucket(mspell: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The charge/ammo bucket, or None when the spell has no real ammo.

    Emitted only when mMaxAmmo parses to an array with any value > 0 (most
    spells carry no ammo, or a degenerate ``-1`` sentinel).
    """
    max_arr = _int_array(mspell.get("mMaxAmmo"))
    if not max_arr or not any(x > 0 for x in max_arr):
        return None
    return {
        "max": max_arr,
        "recharge": _float_array(mspell.get("mAmmoRechargeTime")),
    }


def _geometry_bucket(mspell: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The AoE geometry bucket, or None when no geometry field is present.

    castConeDistance + castConeAngle are CLEAN cone fields. castRadius is
    CONFLATED (boilerplate default on point spells) so it is captured under
    ``cast_radius`` + flagged ``cast_radius_conflated`` when it equals a known
    boilerplate value. line_width comes from mLineWidth or
    mMissileSpec.mMissileWidth when present.
    """
    cone_d = _num(mspell.get("castConeDistance"))
    cone_a = _num(mspell.get("castConeAngle"))
    cast_r = _first_scalar(mspell.get("castRadius"))
    line_w = _num(mspell.get("mLineWidth"))
    if line_w is None:
        spec = mspell.get("mMissileSpec")
        if isinstance(spec, dict):
            line_w = _num(spec.get("mMissileWidth"))
    if cone_d is None and cone_a is None and cast_r is None and line_w is None:
        return None
    geo: dict[str, Any] = {
        "cone_distance": _round6(cone_d),
        "cone_angle": _round6(cone_a),
        "cast_radius": _round6(cast_r),
        "line_width": _round6(line_w),
    }
    if cast_r is not None:
        geo["cast_radius_conflated"] = any(
            abs(cast_r - b) < 1e-6 for b in _CONFLATED_CAST_RADII
        )
    return geo


def _spells_index(doc: dict[str, Any], char_name: str) -> dict[str, dict[str, Any]]:
    """Map ``<AbilityName>/<SpellName>`` (and bare ``<SpellName>``) -> mSpell dict.

    The bin is a flat dict of dotted-path keys. We index every spell record under
    ANY ``Characters/<Name>/Spells/`` prefix by both its full ``<Ability>/<Spell>``
    suffix and its bare trailing ``<Spell>`` name so the slot resolver + the
    sibling-missile scan can find records by either form. We scan ALL
    ``Characters/*/Spells/`` keys (not just ``char_name``'s) because some bins
    split the CharacterRecords/Root and the ability spell records across two name
    casings - Fiddlesticks holds the Root under ``FiddleSticks`` but the Q/W/E/R
    spells under ``Fiddlesticks`` - and the character bin is single-champion so
    there is no cross-champion contamination. ``char_name`` is accepted for call
    compatibility but no longer constrains the prefix.
    """
    marker = "/Spells/"
    out: dict[str, dict[str, Any]] = {}
    for key, rec in doc.items():
        if not isinstance(key, str) or not key.startswith("Characters/"):
            continue
        idx = key.find(marker)
        if idx < 0 or not isinstance(rec, dict):
            continue
        mspell = rec.get("mSpell")
        if not isinstance(mspell, dict):
            continue
        suffix = key[idx + len(marker):]  # e.g. "MissileBarrageAbility/MissileBarrage"
        out[suffix] = mspell
        bare = suffix.split("/")[-1]  # e.g. "MissileBarrage"
        out.setdefault(bare, mspell)
    return out


def _resolve_missile_speed(primary: dict[str, Any], ability_name: str,
                           spells: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Resolve a single missile_speed for a spell + record both the cast-record
    speed and the best sibling-missile speed.

    The primary cast record's ``missileSpeed`` is the cast-record value; when it
    is 0/tiny (<= placeholder) a sibling ``<...>Missile`` record under the SAME
    ability container often carries the real travel speed. Returns
    ``{missile_speed, _cast_record_speed, _missile_record_speed}`` (the resolved
    value prefers the sibling travel speed only when the cast record is a
    placeholder; a positive non-placeholder cast speed wins).
    """
    cast_ms = _num(primary.get("missileSpeed"))
    # best sibling: any spell whose <Ability>/<...> path is under this ability and
    # whose bare name ends in "Missile", carrying a positive missileSpeed.
    best_sib: Optional[float] = None
    ability_prefix = ability_name + "/"
    for suffix, mspell in spells.items():
        if "/" not in suffix:
            continue  # skip the bare-name aliases
        if not suffix.startswith(ability_prefix):
            continue
        bare = suffix.split("/")[-1]
        if not bare.endswith("Missile"):
            continue
        sib = _num(mspell.get("missileSpeed"))
        if sib is not None and sib > 0 and (best_sib is None or sib > best_sib):
            best_sib = sib
    # resolution: a real positive cast speed wins; else the sibling travel speed.
    resolved: Optional[float] = None
    if cast_ms is not None and cast_ms > _MISSILE_PLACEHOLDER_MAX:
        resolved = cast_ms
    elif best_sib is not None:
        resolved = best_sib
    elif cast_ms is not None and cast_ms > 0:
        resolved = cast_ms
    return {
        "missile_speed": _round6(resolved),
        "_cast_record_speed": _round6(cast_ms),
        "_missile_record_speed": _round6(best_sib),
    }


def _parse_spell_record(primary: dict[str, Any], ability_name: str,
                        spells: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build one slot's output record from its primary mSpell dict + the index."""
    ms = _resolve_missile_speed(primary, ability_name, spells)
    rec: dict[str, Any] = {
        "ammo": _ammo_bucket(primary),
        "missile_speed": ms["missile_speed"],
        "cc_tags": _cc_tags(primary.get("mSpellTags")),
        "geometry": _geometry_bucket(primary),
    }
    # provenance / debug fields for the missile resolution (kept compact).
    if ms["_cast_record_speed"] is not None or ms["_missile_record_speed"] is not None:
        rec["missile_cast_record"] = ms["_cast_record_speed"]
        rec["missile_sub_record"] = ms["_missile_record_speed"]
    return rec


def _char_root_name(doc: dict[str, Any], slug: str) -> Optional[str]:
    """The ``<Name>`` segment of the bin's Characters/<Name>/ keys.

    The bin's internal name can differ in casing from the slug (e.g.
    ``MonkeyKing`` vs ``wukong``). Some bins hold MULTIPLE ``Characters/<Name>``
    entries - an effigy/clone/trinket character that precedes the real champion
    (Fiddlesticks is the known case) - and only the real one carries a
    ``CharacterRecords/Root.spellNames`` list. So prefer the first <Name> whose
    Root has a non-empty spellNames; fall back to the first <Name> seen.
    """
    names: list[str] = []
    seen: set[str] = set()
    for key in doc:
        if isinstance(key, str) and key.startswith("Characters/"):
            parts = key.split("/")
            if len(parts) >= 2 and parts[1] and parts[1] not in seen:
                seen.add(parts[1])
                names.append(parts[1])
    for nm in names:
        root = doc.get("Characters/" + nm + "/CharacterRecords/Root")
        if isinstance(root, dict):
            sn = root.get("spellNames")
            if isinstance(sn, list) and sn:
                return nm
    return names[0] if names else None


def _parse_cdragon_spells(doc: dict[str, Any], slug: str) -> dict[str, dict[str, Any]]:
    """Walk a CDragon character bin -> {slot: spell-record} for Q/W/E/R.

    Uses CharacterRecords/Root.spellNames as the authoritative slot ordering (4
    entries, Q/W/E/R). Each entry is ``<AbilityName>/<SpellName>``. Falls back to
    an empty map when the bin has no recognizable Characters root or no
    spellNames (recorded as a parse miss by the caller).
    """
    char_name = _char_root_name(doc, slug)
    if not char_name:
        return {}
    root = doc.get("Characters/" + char_name + "/CharacterRecords/Root")
    spell_names = root.get("spellNames") if isinstance(root, dict) else None
    if not isinstance(spell_names, list) or not spell_names:
        return {}
    spells = _spells_index(doc, char_name)
    out: dict[str, dict[str, Any]] = {}
    for idx, slot in enumerate(_SLOT_KEYS):
        if idx >= len(spell_names):
            break
        entry = spell_names[idx]
        if not isinstance(entry, str) or not entry:
            continue
        ability_name = entry.split("/")[0]
        primary = spells.get(entry) or spells.get(entry.split("/")[-1])
        if not isinstance(primary, dict):
            continue
        out[slot] = _parse_spell_record(primary, ability_name, spells)
    return out


def _champ_spells(ddragon_id: str, patch_segment: str) -> dict[str, dict[str, Any]]:
    """Fetch + parse one champ's CDragon bin -> {slot: spell-record}.

    Raises on a transport / HTTP error (the caller fail-softs per champ).
    """
    url = CDRAGON_CHAR_URL.format(patch=patch_segment, slug=_cdragon_slug(ddragon_id))
    raw = _fetch_with_retry(url)
    return _parse_cdragon_spells(json.loads(raw), _cdragon_slug(ddragon_id))


def _atomic_write_json(path: Path, payload: Any) -> None:
    """tmp.write_text + os.replace - the repo atomic-write rule."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=True, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def extract(patch: str, sleep_s: float, limit: Optional[int],
            verbose: bool, *, full_roster: bool = False) -> dict[str, Any]:
    """Extract the per-spell sidecar payload for ``patch`` (does NOT write).

    One character-bin fetch per champ (with backoff retries). Per champ, the bin
    is walked for the 4 buckets keyed by Q/W/E/R via CharacterRecords/Root.
    spellNames. fail-soft per champ: a blocked/empty/unparseable bin records an
    error + an empty spell map.
    """
    patch_segment = _cdragon_patch_segment(patch)
    ids = _resolve_champion_ids(patch, full_roster)
    if limit:
        ids = ids[:limit]

    champions: dict[str, dict[str, Any]] = {}
    with_ammo = 0
    with_missile = 0
    with_cc = 0
    with_geo = 0
    errs: list[str] = []
    for n, ddragon_id in enumerate(ids):
        spells: dict[str, dict[str, Any]] = {}
        err_here = False
        try:
            spells = _champ_spells(ddragon_id, patch_segment)
            if not spells:
                errs.append(f"{ddragon_id}: no spellNames / Characters root in bin")
                err_here = True
        except Exception as exc:  # noqa: BLE001 - fail-soft per champ
            errs.append(f"{ddragon_id} cdragon: {type(exc).__name__}: {str(exc)[:120]}")
            err_here = True

        champions[ddragon_id] = {"spells": spells}

        a = sum(1 for s in spells.values() if s.get("ammo"))
        m = sum(1 for s in spells.values() if s.get("missile_speed") is not None)
        c = sum(1 for s in spells.values() if s.get("cc_tags"))
        g = sum(1 for s in spells.values() if s.get("geometry"))
        with_ammo += a
        with_missile += m
        with_cc += c
        with_geo += g

        if verbose:
            tag = "ERR" if err_here else "ok"
            print(
                f"[{n+1}/{len(ids)}] {ddragon_id}: slots={sorted(spells.keys())} "
                f"ammo={a} missile={m} cc={c} geo={g} {tag}"
            )
        if sleep_s > 0 and n + 1 < len(ids):
            time.sleep(sleep_s)

    return {
        "_source": (
            "CommunityDragon game/data/characters/<slug>/<slug>.bin.json "
            "(2-segment patch; CharacterRecords/Root.spellNames slot order)"
        ),
        "_patch": patch,
        "_patch_segment": patch_segment,
        "_slot_keying": "Q/W/E/R via CharacterRecords/Root.spellNames (passive not emitted)",
        "_buckets": ["ammo", "missile_speed", "cc_tags", "geometry"],
        "_note": (
            "OPTIONAL DS per-spell overlay. ammo = {max[],recharge[]} when the "
            "spell has real charges (else null). missile_speed = resolved travel "
            "speed (prefers the <...>Missile sub-record when the cast record is "
            "0/tiny; cast/sub speeds kept in missile_cast_record/missile_sub_record). "
            "cc_tags = COARSE CC-class flag from mSpellTags (the ImmobilizingCC "
            "umbrella, 16.13 ...CCAbility suffix canonicalized back to ...CCSpell; "
            "NOT a duration, NOT stun-vs-root). geometry.cast_radius is "
            "CONFLATED (boilerplate 210/100 on point spells) - trust cone_distance/"
            "cone_angle, check cast_radius_conflated before using cast_radius. "
            "Meraki stays authoritative for damage/ratios/CC durations. A run with "
            "every _with_* == 0 means the host could not reach CDragon - do NOT commit."
        ),
        "_champ_count": len(champions),
        "_with_ammo": with_ammo,
        "_with_missile": with_missile,
        "_with_cc_tags": with_cc,
        "_with_geometry": with_geo,
        "_errors": errs,
        "champions": champions,
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--patch", help="patch id, e.g. 16.11.1; default current.txt")
    ap.add_argument(
        "--out",
        help="output path; default data/daemon_slayer/<patch>/cdragon_spell_stats.json",
    )
    ap.add_argument(
        "--sleep", type=float, default=0.5,
        help="seconds between per-champ network calls (default 0.5)",
    )
    ap.add_argument(
        "--limit", type=int, default=0,
        help="extract only the first N champs (smoke test)",
    )
    ap.add_argument(
        "--full-roster", action="store_true",
        help="A-26/RM-95b: source champs from champions.json (173) instead of "
             "champion_abilities.json (171); the only way Locke + Zaahen are reached",
    )
    ap.add_argument("--dry-run", action="store_true", help="extract but do not write")
    ap.add_argument("-v", "--verbose", action="store_true", help="per-champ progress")
    args = ap.parse_args(argv)

    patch = _resolve_patch(args.patch)
    out_path = (
        Path(args.out) if args.out
        else (DATA_DIR / patch / "cdragon_spell_stats.json")
    )

    payload = extract(patch, args.sleep, args.limit or None, args.verbose,
                      full_roster=args.full_roster)
    print(
        f"patch={patch} (cdragon={payload['_patch_segment']}) "
        f"champs={payload['_champ_count']} with_ammo={payload['_with_ammo']} "
        f"with_missile={payload['_with_missile']} with_cc_tags={payload['_with_cc_tags']} "
        f"with_geometry={payload['_with_geometry']} errors={len(payload['_errors'])}"
    )
    if payload["_errors"]:
        for e in payload["_errors"][:10]:
            print("  ERR", e)
    all_zero = (
        payload["_with_ammo"] == 0 and payload["_with_missile"] == 0
        and payload["_with_cc_tags"] == 0 and payload["_with_geometry"] == 0
    )
    if all_zero:
        print(
            "WARNING: 0 spells resolved any bucket - host likely cannot reach "
            "CommunityDragon (edge block); NOT a committable sidecar."
        )

    if args.dry_run:
        print("(dry-run; not written)")
        return 0
    _atomic_write_json(out_path, payload)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
