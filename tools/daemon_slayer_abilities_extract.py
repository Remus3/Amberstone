"""tools/daemon_slayer_abilities_extract.py — Phase 4a champion ability extractor.

Pulls the Meraki Analytics bulk champions endpoint and produces a versioned
snapshot at ``data/daemon_slayer/<patch>/champion_abilities.json`` mirroring
the same patch directory ``daemon_slayer_extract.py`` writes to.

Each champion exports five ability keys (P/Q/W/E/R); some champions ship
multiple forms per key (Aphelios weapon stances, Jayce/Elise/Karma stance
swaps, LeeSin/Nidalee form swaps, Sylas E direction). Each form is
normalized into:

* ``name``, ``icon``, ``cooldown[]``, ``cost[]``
* ``damage_type`` — ``"PHYSICAL"`` / ``"MAGIC"`` / ``"TRUE"`` / ``"MIXED"`` / ``None``
* ``targeting``, ``affects``, ``resource``, ``is_aoe``
* ``damage_blocks`` — list of per-attribute leveling normalized to typed
  scaling fields (``base``, ``total_ad_pct``, ``bonus_ad_pct``, ``ap_pct``,
  ``caster_max_hp_pct``, ``caster_bonus_hp_pct``, ``target_max_hp_pct``,
  ``target_missing_hp_pct``, ``target_current_hp_pct``,
  ``target_bonus_hp_pct``, ``target_armor_pct``, ``bonus_armor_pct``,
  ``bonus_mr_pct``, ``caster_max_mp_pct``)
* ``parse_status`` — ``"ok"`` (all damage modifiers typed),
  ``"partial"`` (some unparsed), ``"unparsed"`` (no recognized fields)

Phase 4b will layer a formula evaluator on top of this snapshot. Phase 4a
is data ingest only — we do not evaluate per-cast damage here.

Usage::

    py tools/daemon_slayer_abilities_extract.py            # extract for DDragon current patch
    py tools/daemon_slayer_abilities_extract.py --force    # re-fetch even if file exists
    py tools/daemon_slayer_abilities_extract.py --patch 16.9.1  # override patch label
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
DATA_ROOT = ROOT / "data" / "daemon_slayer"
LOG_FILE = ROOT / "logs" / "daemon_slayer_abilities_extract.log"

MERAKI_BULK_URL = (
    "https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/champions.json"
)
DDRAGON_BASE = "https://ddragon.leagueoflegends.com"
USER_AGENT = "RiotCommander/DaemonSlayer-abilities-extract/1.0"

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
    ],
)
log = logging.getLogger("daemon_slayer_abilities_extract")


# ─── Unit → typed-scaling-field map ──────────────────────────────────────────

# Meraki ships modifier values + units; we normalize units to typed field
# names so Phase 4b's evaluator can resolve per-level damage without a regex
# every call. Variants (double-space, possessive pronouns) are pinned here so
# parse_status="ok" survives Meraki's text-formatting drift.
_UNIT_TO_FIELD: dict[str, str] = {
    "": "base",
    "% AD": "total_ad_pct",
    "% bonus AD": "bonus_ad_pct",
    "% AP": "ap_pct",
    "% maximum health": "caster_max_hp_pct",
    "% bonus health": "caster_bonus_hp_pct",
    "% of his bonus health": "caster_bonus_hp_pct",
    "% of her bonus health": "caster_bonus_hp_pct",
    "% of their bonus health": "caster_bonus_hp_pct",
    # s224: caster-max-health pronoun + champion-name forms (Sejuani W
    # "her", Gnar/Skarner E "his", Braum Q / Zac Q name-specific). Mirror
    # of the existing "% of his bonus health" caster-bonus family — these
    # scale with the CASTER's own max HP and were dropped pre-s224.
    "% of his maximum health": "caster_max_hp_pct",
    "% of her maximum health": "caster_max_hp_pct",
    "% of Braum's maximum health": "caster_max_hp_pct",
    "% of Zac's maximum health": "caster_max_hp_pct",
    "% of target's maximum health": "target_max_hp_pct",
    "%  of target's maximum health": "target_max_hp_pct",
    # s224: Meraki text-drift "the target's" + double-space variants of
    # the target-health family (Gwen Q/R, Varus W Blight, Trundle R,
    # Ambessa Q, Maokai Q, TahmKench R, Briar W, Fiddlesticks Q). Same
    # semantic as the no-"the" forms above — pure formatting drift.
    "% of the target's maximum health": "target_max_hp_pct",
    "%  of the target's maximum health": "target_max_hp_pct",
    "% of target's missing health": "target_missing_hp_pct",
    "%  of target's missing health": "target_missing_hp_pct",
    "% of the target's missing health": "target_missing_hp_pct",
    "% of target's current health": "target_current_hp_pct",
    "%  of target's current health": "target_current_hp_pct",
    "% of target's bonus health": "target_bonus_hp_pct",
    "% of primary target's bonus health": "target_bonus_hp_pct",
    "% of target's armor": "target_armor_pct",
    "% bonus armor": "bonus_armor_pct",
    "% bonus magic resistance": "bonus_mr_pct",
    "% maximum mana": "caster_max_mp_pct",
}

# Set of unit strings recognized as non-damage so we don't mis-flag them as
# unparsed when they appear under a Damage attribute (rare but happens).
_KNOWN_NON_DAMAGE_UNITS: set[str] = {
    " seconds",
    "  seconds",
    "%",  # bare percent — usually a stat, not a damage scalar
    "% maximum mana",  # caster_max_mp_pct; tracked but not a damage modifier
    "% of missing mana",
    "% of damage dealt",
    "% of damage stored",
}

# Meraki nests conditional sub-scalings inside the unit string itself, e.g.
# Kindred E "% (+ 0.5% per Mark) of target's missing health" or K'Sante W's
# doubly-nested "% (+ 2% per 100 bonus armor) (+ 2% per 100 bonus magic
# resistance) of target's maximum health". The paired ``values`` list is the
# canonical no-stack / no-scaling coefficient; the "(+ ...)" parentheticals
# are conditional bonuses the single-value schema deliberately drops — the
# same operator-commits-to-canonical-state model the block_index registry
# uses. Stripping every "(+ ...)" group (innermost-first so nested parens
# collapse) leaves a residue that matches a base _UNIT_TO_FIELD key.
_NESTED_COND_RE = re.compile(r"\s*\(\+[^()]*\)")


def _canonicalize_unit(unit: str) -> str:
    """Strip Meraki's nested conditional "(+ ...)" groups from a unit string.

    No-op for units without "(+" (the overwhelming common case) — returned
    byte-identical, so an already recognized unit is never perturbed. Only
    previously-unparsed nested-syntax units (Kindred E missing-health;
    Cho'Gath E / K'Sante W / Sett Q / Shen Q / Zac W / Amumu W / Evelynn E /
    Elise Q / Kled W maximum/current-health) gain a typed mapping.
    """
    if "(+" not in unit:
        return unit
    prev = None
    cur = unit
    while prev != cur:
        prev = cur
        cur = _NESTED_COND_RE.sub("", cur)
    return re.sub(r"\s{2,}", " ", cur).strip()


# Heuristic: "damage" in attribute name flags it as a damage-bearing block.
# Some abilities use words like "Bolt"/"Burn"/"Bleed" without "Damage" in
# the attribute — extend the allowlist when coverage drops.
_DAMAGE_ATTRIBUTE_HINTS = re.compile(
    r"\b(damage|burn|bleed|smite|strike|bolt|shock|burst)\b",
    re.IGNORECASE,
)

# Denylist: attribute names that *contain* "damage" but describe a modifier
# (Damage Reduction, Damage Increase, Critical Damage multiplier, etc.) rather
# than a raw damage source. These are filtered to "modifier" attribute_kind so
# they don't redden parse_status — Phase 4b's evaluator never reads them.
_NON_DAMAGE_HINTS = re.compile(
    r"\b(reduction|reduce|amplification|amplify|increase|absorb|"
    r"resistance|resist|critical damage|damage taken|damage dealt|"
    r"non-champion|monster|minion|damage stored|"
    r"damage modifier)\b",
    re.IGNORECASE,
)


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def _fetch_text(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _fetch_json(url: str, timeout: int = 60) -> Any:
    return json.loads(_fetch_text(url, timeout=timeout))


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# ─── Normalization ──────────────────────────────────────────────────────────

def _normalize_damage_type(raw: str | None) -> str | None:
    if not raw:
        return None
    s = str(raw).upper().replace("_DAMAGE", "").strip()
    if s in {"PHYSICAL", "MAGIC", "TRUE", "MIXED"}:
        return s
    return None


def _is_aoe(affects: str | None, targeting: str | None) -> bool:
    """Heuristic: ability hits multiple enemies if ``affects`` contains 'Enemies'
    (plural) or ``targeting`` is a direction/location/vector style.
    """
    a = (affects or "").lower()
    t = (targeting or "").lower()
    if "enemies" in a:
        return True
    if any(kw in t for kw in ("direction", "location", "vector")):
        return True
    return False


def _values_tuple(raw: Any) -> list[float] | None:
    """Convert a Meraki ``values`` list to a list of floats, or None if mixed."""
    if not isinstance(raw, list) or not raw:
        return None
    out: list[float] = []
    for v in raw:
        if isinstance(v, (int, float)):
            out.append(float(v))
        elif isinstance(v, str):
            # Some entries are strings like "5%"; strip non-numeric and try.
            cleaned = re.sub(r"[^0-9.\-]", "", v)
            if not cleaned:
                return None
            try:
                out.append(float(cleaned))
            except ValueError:
                return None
        else:
            return None
    return out


def _normalize_cooldown_or_cost(raw: Any) -> list[float] | None:
    """Meraki ships cost/cooldown as ``{"modifiers": [{"values": [...], "units": [...]}]}``.

    Older snapshots and a few oddly-shaped ability forms ship the values as
    a bare list (e.g. ``[14, 12, 10, 8, 6]``); tolerate both. We take the
    first modifier's ``values`` list since cooldown/cost rarely have
    multi-component scaling (and when they do — e.g. cost ``[30, 35, 40,
    45, 50] - 0% bonus AD`` — the secondary modifier is usually a CDR
    reduction we'd skip anyway).
    """
    if isinstance(raw, list):
        return _values_tuple(raw)
    if isinstance(raw, dict):
        mods = raw.get("modifiers") or []
        if not mods:
            return None
        first = mods[0]
        if not isinstance(first, dict):
            return None
        return _values_tuple(first.get("values"))
    return None


def _normalize_modifiers(modifiers: list[dict]) -> tuple[dict[str, list[float]], list[dict]]:
    """Return (typed_fields, unparsed_modifiers).

    Each modifier in ``modifiers`` carries ``values: [...]`` paired with
    ``units: [...]`` of the same length. We group by unit and emit one
    list per recognized typed field. Unrecognized units are appended to
    ``unparsed`` verbatim for downstream auditing.
    """
    typed: dict[str, list[float]] = {}
    unparsed: list[dict] = []

    for mod in modifiers:
        if not isinstance(mod, dict):
            continue
        values = mod.get("values")
        units = mod.get("units")
        if not isinstance(values, list) or not isinstance(units, list):
            unparsed.append(mod)
            continue

        # Meraki convention: each (value[i], unit[i]) pair tags one rank.
        # All units should match within a single modifier; pick the first
        # non-empty if they differ.
        unit_set = {u for u in units if u is not None}
        if len(unit_set) == 0:
            unit = ""
        elif len(unit_set) == 1:
            unit = next(iter(unit_set))
        else:
            # Heterogeneous units within one modifier: take the first; mark unparsed.
            unparsed.append(mod)
            continue

        # Raw match wins (zero behavior change for recognized units);
        # nested-conditional units fall back to the canonicalized residue.
        lookup_unit = unit if unit in _UNIT_TO_FIELD else _canonicalize_unit(unit)
        if lookup_unit in _UNIT_TO_FIELD:
            field = _UNIT_TO_FIELD[lookup_unit]
            vals = _values_tuple(values)
            if vals is None:
                unparsed.append(mod)
                continue
            # If we somehow get two modifiers mapping to the same field
            # within one block (rare — e.g. Sweetspot + Sweetspot), sum
            # them; the Phase 4b evaluator only sees the aggregate.
            if field in typed:
                # Sum elementwise; pad shorter list with zeros.
                a, b = typed[field], vals
                n = max(len(a), len(b))
                merged = [
                    (a[i] if i < len(a) else 0.0) + (b[i] if i < len(b) else 0.0)
                    for i in range(n)
                ]
                typed[field] = merged
            else:
                typed[field] = vals
        elif unit in _KNOWN_NON_DAMAGE_UNITS:
            # Recognized but not a damage scalar — silently drop (it's likely
            # under a non-damage attribute we should have filtered earlier).
            continue
        else:
            unparsed.append(mod)

    return typed, unparsed


def _classify_attribute(attribute: str) -> str:
    """Return ``"damage"`` if the attribute name hints at damage scaling,
    else ``"heal"`` / ``"shield"`` / ``"slow"`` / ``"duration"`` / ``"modifier"``
    / ``"other"``.

    Order matters: the ``_NON_DAMAGE_HINTS`` denylist is checked BEFORE the
    damage allowlist so attributes like "Damage Reduction" or "Critical
    Damage" (a multiplier, not a damage source) get tagged ``modifier`` and
    skip the damage-typing path. Phase 4b's evaluator only consumes
    ``attribute_kind == "damage"`` blocks.
    """
    s = attribute.lower()
    if _NON_DAMAGE_HINTS.search(s):
        return "modifier"
    if _DAMAGE_ATTRIBUTE_HINTS.search(s):
        return "damage"
    if "heal" in s:
        return "heal"
    if "shield" in s:
        return "shield"
    if "slow" in s:
        return "slow"
    if "duration" in s or "range" in s or "speed" in s or "width" in s or "radius" in s:
        return "duration"
    return "other"


def _build_damage_block(leveling: dict) -> dict:
    """Normalize one Meraki ``leveling`` entry → a damage_block record."""
    attribute = leveling.get("attribute") or ""
    kind = _classify_attribute(attribute)
    modifiers = leveling.get("modifiers") or []
    if kind != "damage":
        # Non-damage block: preserve identity + raw modifiers, skip field-typing.
        return {
            "attribute": attribute,
            "attribute_kind": kind,
            "raw_modifiers": modifiers,
        }
    typed, unparsed = _normalize_modifiers(modifiers)
    block: dict[str, Any] = {
        "attribute": attribute,
        "attribute_kind": "damage",
    }
    for field, vals in typed.items():
        block[field] = vals
    if unparsed:
        block["unparsed_modifiers"] = unparsed
    return block


def _build_form(form: dict, form_index: int, ability_key: str) -> dict:
    """Normalize one Meraki ability form (single stance) → a structured record."""
    name = form.get("name") or ability_key
    cooldown = _normalize_cooldown_or_cost(form.get("cooldown"))
    cost = _normalize_cooldown_or_cost(form.get("cost"))
    damage_type = _normalize_damage_type(form.get("damageType"))
    targeting = form.get("targeting")
    affects = form.get("affects")
    resource = form.get("resource")

    damage_blocks: list[dict] = []
    raw_effects_count = 0
    raw_leveling_count = 0
    parse_notes: list[str] = []

    for eff in form.get("effects") or []:
        raw_effects_count += 1
        if not isinstance(eff, dict):
            continue
        levelings = eff.get("leveling") or []
        for lvl in levelings:
            raw_leveling_count += 1
            if not isinstance(lvl, dict):
                continue
            damage_blocks.append(_build_damage_block(lvl))

    # Compute parse status across the damage-classified blocks. Three
    # dispositions: typed (has scaling fields), unparsed (has at least one
    # modifier we couldn't normalize), empty (damage attribute declared but
    # Meraki ships no modifiers — common for aggregate fields like
    # "Maximum Increased Damage" that downstream values derive from).
    _META_KEYS = {"attribute", "attribute_kind", "unparsed_modifiers", "raw_modifiers"}
    typed_blocks = 0
    unparsed_blocks = 0
    empty_blocks = 0
    for b in damage_blocks:
        if b.get("attribute_kind") != "damage":
            continue
        has_typed = any(k for k in b if k not in _META_KEYS)
        has_unparsed = bool(b.get("unparsed_modifiers"))
        if has_typed:
            typed_blocks += 1
        elif has_unparsed:
            unparsed_blocks += 1
        else:
            empty_blocks += 1
    damage_block_count = typed_blocks + unparsed_blocks + empty_blocks

    if damage_block_count == 0:
        # No damage attribute at all — likely a passive utility or pure-stat ability.
        parse_status = "no_damage"
    elif unparsed_blocks == 0 and empty_blocks == 0:
        parse_status = "ok"
    elif typed_blocks > 0:
        parse_status = "partial"
    else:
        parse_status = "unparsed"
        parse_notes.append("no damage modifiers normalized")

    return {
        "key": ability_key,
        "name": name,
        "form_index": form_index,
        "icon": form.get("icon"),
        "cooldown": cooldown,
        "cost": cost,
        "damage_type": damage_type,
        "targeting": targeting,
        "affects": affects,
        "resource": resource,
        "is_aoe": _is_aoe(affects, targeting),
        "damage_blocks": damage_blocks,
        "raw_effects_count": raw_effects_count,
        "raw_leveling_count": raw_leveling_count,
        "parse_status": parse_status,
        "parse_notes": parse_notes,
    }


def _build_champion(name: str, payload: dict) -> dict:
    """Normalize a Meraki champion record → ``{P,Q,W,E,R: [form, ...]}``."""
    abilities = payload.get("abilities") or {}
    out: dict[str, list[dict]] = {}
    for key in ("P", "Q", "W", "E", "R"):
        forms = abilities.get(key) or []
        if not isinstance(forms, list):
            continue
        out[key] = [
            _build_form(form, idx, key)
            for idx, form in enumerate(forms)
            if isinstance(form, dict)
        ]
    return out


# ─── Coverage ────────────────────────────────────────────────────────────────

def _coverage_summary(data: dict[str, dict[str, list[dict]]]) -> dict[str, Any]:
    """Return per-status counts for the coverage check."""
    status_counts: dict[str, int] = {"ok": 0, "partial": 0, "unparsed": 0, "no_damage": 0}
    by_key: dict[str, dict[str, int]] = {k: dict(status_counts) for k in ("P", "Q", "W", "E", "R")}
    total_forms = 0
    multiform = 0

    for _champ, keymap in data.items():
        for key, forms in keymap.items():
            if len(forms) > 1:
                multiform += 1
            for form in forms:
                total_forms += 1
                status = form.get("parse_status", "unparsed")
                status_counts[status] = status_counts.get(status, 0) + 1
                if key in by_key:
                    by_key[key][status] = by_key[key].get(status, 0) + 1

    damage_eligible = total_forms - status_counts["no_damage"]
    ok_rate = (status_counts["ok"] / damage_eligible) if damage_eligible else 0.0
    parsed_rate = ((status_counts["ok"] + status_counts["partial"]) / damage_eligible) if damage_eligible else 0.0

    return {
        "total_forms": total_forms,
        "multiform_keys": multiform,
        "status_counts": status_counts,
        "by_key": by_key,
        "damage_eligible": damage_eligible,
        "ok_rate": round(ok_rate, 4),
        "parsed_rate": round(parsed_rate, 4),
    }


# ─── Entry point ─────────────────────────────────────────────────────────────

def _resolve_patch(override: str | None) -> str:
    if override:
        return override
    pointer = DATA_ROOT / "current.txt"
    if pointer.exists():
        txt = pointer.read_text(encoding="utf-8").strip()
        if txt:
            return txt
    # Fall back to DDragon's current version.
    versions = _fetch_json(f"{DDRAGON_BASE}/api/versions.json")
    return versions[0]


def main() -> int:
    ap = argparse.ArgumentParser(description="Daemon Slayer Phase 4a champion abilities extractor.")
    ap.add_argument("--force", action="store_true",
                    help="re-extract even if the abilities file already exists")
    ap.add_argument("--patch", default=None,
                    help="override patch label for the output directory (default: data/daemon_slayer/current.txt)")
    args = ap.parse_args()

    log.info("=" * 60)
    log.info("daemon_slayer abilities extract starting (force=%s)", args.force)

    patch = _resolve_patch(args.patch)
    patch_dir = DATA_ROOT / patch
    out_path = patch_dir / "champion_abilities.json"

    if out_path.exists() and not args.force:
        log.info("abilities file already exists at %s — skip (use --force to redo)", out_path)
        return 0

    log.info("fetching Meraki bulk champions: %s", MERAKI_BULK_URL)
    t0 = time.time()
    raw = _fetch_json(MERAKI_BULK_URL, timeout=90)
    fetch_elapsed = time.time() - t0
    if not isinstance(raw, dict):
        raise RuntimeError(f"expected dict from Meraki bulk, got {type(raw).__name__}")
    log.info("Meraki bulk fetched: %d champions (%.1fs)", len(raw), fetch_elapsed)

    data_out: dict[str, dict[str, list[dict]]] = {}
    for name, payload in raw.items():
        if not isinstance(payload, dict):
            continue
        # Meraki bulk uses the DDragon-style ID as the top-level dict key
        # (Aatrox, MonkeyKing, KSante, …). Inside each record, ``id`` is the
        # numeric Riot key and ``key`` is the DDragon string — the per-champion
        # endpoint reverses them. The top-level key is the only reliable
        # cross-source canonical anchor, so use it directly.
        data_out[name] = _build_champion(name, payload)

    coverage = _coverage_summary(data_out)
    log.info(
        "coverage: %d forms · ok=%d partial=%d unparsed=%d no_damage=%d (ok_rate=%.1f%% parsed_rate=%.1f%%)",
        coverage["total_forms"],
        coverage["status_counts"]["ok"],
        coverage["status_counts"]["partial"],
        coverage["status_counts"]["unparsed"],
        coverage["status_counts"]["no_damage"],
        coverage["ok_rate"] * 100,
        coverage["parsed_rate"] * 100,
    )

    snapshot = {
        "version": patch,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z") or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": MERAKI_BULK_URL,
        "engine_phase": "4a",
        "count": len(data_out),
        "coverage": coverage,
        "data": data_out,
    }

    _atomic_write_json(out_path, snapshot)
    log.info("✓ wrote %s (%d champions, %d forms)",
             out_path, len(data_out), coverage["total_forms"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
