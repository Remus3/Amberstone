"""
tft/tft_prompt.py
The TFT coach SYSTEM prompt, built per resolved set from ingested data (RM-845).

Before RM-845 both engines carried a hand-written Set 17 "Space Gods" system
prompt: tft/tft_coach_engine.py TFT_SYSTEM_PROMPT (3471 chars - Realm of Gods
round structure, nine gods with S/A/B boon tiers) and tft/tft_pbe_engine.py
TFT_PBE_SYSTEM_PROMPT (9821 chars - patch 17.3 notes, a "META S-TIER COMPS"
list; that engine was deleted by RM-292 (b), 2026-10-25). RM-840 made the data set-agnostic (tft/tft_set.py) and Set 18 became
the default, so a Set 18 game was coached on Set 17 mechanics and on tier
claims no data backed.

One prompt, three parts, for the TFT engine (tft/tft_coach_engine.py, the
only one since RM-292 (b) deleted its PBE twin):
  shared rules  set-independent coaching rules and the 9-field output format.
  SET block     ONLY what the resolved set's ingested files hold:
                data/meta/tft_set<N>_cdragon.json (CommunityDragon: trait
                breakpoints, unit costs, augment text) when present, else the
                game-data fields of the set's own meta file (all_traits,
                unit_costs); plus the meta's mechanic record - set_mechanics,
                or, on an RM-846 skeleton that has none, the round-structure
                keys of its factual _patch_notes_* summaries. A set
                with neither gets a "no game data ingested" line, never another
                set's data (tft/tft_set.py never borrows a file across sets).
  META line     whether the set's meta file holds comp data. An absent or
                skeleton meta (Set 18 and, since RM-846, Set 17 are "SKELETON -
                UNVERIFIED") is labelled UNVERIFIED and the model is told to
                make no tier or comp claims. meta_verified() is the same test
                for the engine's per-call message: its comp, augment-rating
                and Double Up lines need a verified meta.

The 6th output field (payload key god_pick) is labelled from the data too:
"God pick" when the set's meta records the carousel replaced by Realm of the
Gods (Set 17: _patch_notes_17.1 carousel / realm_of_gods), "Carousel" when
the set's CommunityDragon augment text names carousel rounds (Set 18), else
"Pick". The engine's parser maps all three labels onto its pick key.

Cost: the prompt is the cached system block of every coach call. It sits
below the prompt-cache floor before and after RM-845 (docs/COST_TRACE.md), so
the budget is the pre-RM-845 live size, not the cache: MAX_PROMPT_CHARS, held
by construction (data lines share what the fixed text leaves). The text is
byte-stable per set and data-file version, cached on the files' mtimes and
sizes.

No LLM call happens here: string assembly from files on disk only
(Haiku-to-zero north star - RM-845 adds no live call).
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import dataclass

from tft import tft_set

logger = logging.getLogger("rc.tft.prompt")

# Pre-RM-845 live system prompt: 3471 chars (tft/tft_coach_engine.py
# TFT_SYSTEM_PROMPT at 4b0bc3ce4). The set block replaces ~1300 chars of
# hand-written god copy, so the cap leaves the old size ~15 percent headroom.
MAX_PROMPT_CHARS = 4000

PICK_GODS = "God pick"
PICK_CAROUSEL = "Carousel"
PICK_GENERIC = "Pick"
_PICK_DESC = {
    PICK_GODS: "Realm of the Gods offering choice (component -> carry)",
    PICK_CAROUSEL: "carousel pick (component or unit -> carry)",
    PICK_GENERIC: "next reward or item choice (component -> carry)",
}

_NAME_MAX = 32
_TEXT_MAX = 120
_MECH_MAX = 420

_HEAD = (
    # "Challenger" (the old opener) is also a Set 17 trait name: shared text
    # must not carry a word any set uses as a unit or trait.
    "Expert TFT coach, top-ladder level. Max density, no padding. Plain ASCII.\n"
    "\n"
    "GROUND TRUTH: the SET block below is the only knowledge of this set you"
    " may use. Name only units, traits and augments it lists or the game"
    " state shows. Never describe a mechanic it does not show; never borrow"
    " another set's units, traits or mechanics. Tier and comp claims only"
    " from a SELECTED COMP block in the message, never from memory."
)

_RULES = (
    "LEVEL TIMING: Lv6@3-2, Lv7@4-1, Lv8@4-2(rolldown), Lv9@5-1+. Fast8=Lv8@4-1"
    " with 50g+. Fast9=Lv9@5-1 needs econ aug or winstreak. HP<35=roll now,"
    " board>econ. Never suggest Lv9 before stage 5.\n"
    "\n"
    "AUGMENTS: Reflect active augments in Action/Items/Econ/Upgrade every"
    " call. Never invent augment names.\n"
    "\n"
    "DOUBLE UP (only when the message says MODE: DOUBLE UP): Shared HP pool."
    " Placement carries a donation note every round (\"Donate X to partner\" /"
    " \"Hold\"). Partner HP<30=donate 2nd tank now. Never contest partner"
    " reroll targets. Stagger rolldowns. Split AD/AP carry between boards.\n"
    "\n"
    "BOARD (Row A=front/enemy, D=back/bench, cols 1-7): Tanks A-row spread"
    " wide (A1,A3,A5). Ranged carry D6-7. Melee carry B-row. Support C-row"
    " near carry. Anti-assassin: move carry to D1. HP>40=fine. HP<35=low"
    " pressure. HP<25=critical. Stage 1 HP=100 (vision error if lower).\n"
    "\n"
    "COMP ID: Name after dominant trait (most units). 1-unit splash = ignore."
    " Commit to ID once set.\n"
    "\n"
    "FEASIBILITY: Never suggest actions that require gold you don't have. No"
    " PvP tips during PVE rounds."
)

_OUTPUT = (
    "OUTPUT - 9 fields only, no markdown, no bullets, max 15 words each:\n"
    "Action: ALL-CAPS 1-3 words\n"
    "Board: actual unit names + grid positions (tanks A wide, carries D6-7)\n"
    "Econ: level/gold timing\n"
    "Rolldown: trigger + stagger note\n"
    "Items: component names + holder\n"
    "{label}: {desc}\n"
    "Placement: anti-flank (+ Double Up donation/request)\n"
    "Upgrade: pivot trigger\n"
    "Risk: single threat (include partner HP if critical)"
)


@dataclass(frozen=True)
class SetProfile:
    """What the resolved set's ingested files say - nothing else."""
    set_number: int
    set_name: str            # meta _set_name, "" when absent
    source: str              # "cdragon" | "meta" | "none"
    source_label: str
    traits: tuple            # ((name, "2/4/6" or ""), ...)
    units_by_cost: tuple     # ((cost, (name, ...)), ...)
    mechanics: tuple         # (("key", "value"), ...) from meta set_mechanics
    gods: bool               # meta records Realm of the Gods replacing carousel
    carousel: bool           # CDragon augment text names carousel rounds
    meta_file: str
    meta_state: str          # "verified" | "skeleton" | "unverified" | "absent"
    meta_comps: int
    meta_patch: str
    meta_updated: str

    @property
    def pick_label(self) -> str:
        if self.gods:
            return PICK_GODS
        if self.carousel:
            return PICK_CAROUSEL
        return PICK_GENERIC


# -- text hygiene: data reaches the system block, so it is untrusted ----------

_NAME_BAD = re.compile(r"[^A-Za-z0-9 .'&+/-]")
_VARIANT = re.compile(r"\s*\([^)]*\)\s*$")


def _ascii(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def _clean_name(value) -> str:
    """One short single-line ASCII name; '' for anything unusable."""
    if not isinstance(value, str):
        return ""
    s = " ".join(_NAME_BAD.sub(" ", _ascii(value)).split())
    return s[:_NAME_MAX].strip()


def _clean_text(value, limit: int = _TEXT_MAX) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return ", ".join(t for t in (_clean_text(v, limit) for v in value) if t)[:limit]
    if not isinstance(value, str):
        return ""
    s = re.sub(r"[^ -~]", " ", _ascii(value))
    return " ".join(s.split())[:limit].rstrip()


def _int(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _short_version(value) -> str:
    m = re.match(r"^\s*(\d+\.\d+)", value) if isinstance(value, str) else None
    return m.group(1) if m else ""


# -- profile ------------------------------------------------------------------

def _traits(cd: dict, meta: dict) -> tuple:
    rows = cd.get("traits")
    out: dict = {}
    if isinstance(rows, list) and rows:
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = _clean_name(row.get("name"))
            if not name or name in out:
                continue
            # A scalar here once raised out of set_profile and erased the
            # whole set block; any other shape keeps the row, without
            # breakpoints.
            raw = row.get("breakpoints")
            bps: list = []
            for b in raw if isinstance(raw, (list, tuple)) else []:
                b = _int(b)
                if b is not None and b not in bps:
                    bps.append(b)
            out[name] = "/".join(str(b) for b in bps)
    else:
        names = cd.get("all_traits") or meta.get("all_traits") or []
        for raw in names if isinstance(names, list) else []:
            name = _clean_name(raw)
            if name and name not in out:
                out[name] = ""
    return tuple(sorted(out.items(), key=lambda kv: kv[0].lower()))


def _units_by_cost(cd: dict, meta: dict) -> tuple:
    costs = cd.get("unit_costs") if isinstance(cd.get("unit_costs"), dict) else None
    if not costs:
        costs = meta.get("unit_costs") if isinstance(meta.get("unit_costs"), dict) else {}
    groups: dict = {}
    for raw, cost in costs.items():
        cost = _int(cost)
        name = _clean_name(_VARIANT.sub("", raw)) if isinstance(raw, str) else ""
        if cost is None or not name:
            continue
        groups.setdefault(cost, set()).add(name)
    return tuple((c, tuple(sorted(groups[c], key=str.lower))) for c in sorted(groups))


# Round-structure keys read from a meta's factual patch-note summaries
# (_patch_notes_<patch> dicts). RM-846 cut tft_set17_meta.json to a skeleton
# with no set_mechanics but kept _patch_notes_17.1 / 17.2 as factual
# summaries; its "carousel" / "realm_of_gods" entries are the one data record
# of the Realm of the Gods mechanic left. Balance notes in the same dicts are
# not mechanics and are never read.
_ROUND_KEYS = ("carousel", "realm_of_gods")


def _mechanic_record(meta: dict) -> dict:
    """set_mechanics when the meta has one, else the patch-note round keys."""
    sm = meta.get("set_mechanics")
    if isinstance(sm, dict) and sm:
        return sm
    record: dict = {}
    for key in sorted(k for k in meta if isinstance(k, str) and k.startswith("_patch_notes")):
        notes = meta[key]
        if isinstance(notes, dict):
            record.update({k: notes[k] for k in _ROUND_KEYS if k in notes})
    return record


def _mechanics(meta: dict) -> tuple:
    out = []
    for key, value in _mechanic_record(meta).items():
        k, v = _clean_name(key), _clean_text(value)
        if k and v:
            out.append((k, v))
    return tuple(out)


def _gods(meta: dict) -> bool:
    rec = _mechanic_record(meta)
    carousel = rec.get("carousel")
    return (rec.get("carousel_removed") is True or "realm_of_gods" in rec
            or (isinstance(carousel, str) and "removed" in carousel.lower()))


def _carousel(cd: dict) -> bool:
    augs = cd.get("augments")
    if not isinstance(augs, list):
        return False
    return any(isinstance(a, dict) and "carousel" in str(a.get("desc", "")).lower()
               for a in augs)


def _meta_state(meta: dict) -> str:
    """verified = comp data on file and not flagged; anything else is not."""
    if not meta:
        return "absent"
    note = str(meta.get("_note", ""))
    if re.search(r"skeleton", note, re.IGNORECASE):
        return "skeleton"
    comps = meta.get("comps")
    if re.search(r"unverified", note, re.IGNORECASE) or not (isinstance(comps, dict) and comps):
        return "unverified"
    return "verified"


def _stamp(path):
    """(mtime_ns, size) of a data file, None when absent. Size too: a rewrite
    that keeps the mtime (a copy2-style restore) must still miss the cache."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


_CACHE: dict = {}
_WARNED: list = [None]  # the data-version key last warned about


def _resolve(set_number, pbe, root):
    n = set_number if set_number is not None else tft_set.resolve_set(root=root)
    flag = bool(tft_set.pbe_flag(root)) if pbe is None else bool(pbe)
    return n, flag


def _no_data(n, meta_file: str, meta_state: str = "absent") -> SetProfile:
    return SetProfile(n, "", "none", "", (), (), (), False, False,
                      meta_file, meta_state, 0, "", "")


def set_profile(set_number=None, *, pbe=None, root=None) -> SetProfile:
    """The resolved set's profile, rebuilt when either data file changes.

    Malformed data degrades to the RESOLVED set's no-data profile, logged once
    per data version and cached like a healthy one, so a bad file is neither
    re-read nor re-logged on every coach call. One exception, on purpose: an
    existing file that loads as {} (unreadable this instant, or not a JSON
    object) is never cached, so it is re-read until it parses - still logged
    at most once per data version.
    """
    n, flag = _resolve(set_number, pbe, root)
    cdp = tft_set.cdragon_path(n, root=root)
    mp = tft_set.meta_path(n, pbe=flag, root=root)
    cd_stamp, mp_stamp = _stamp(cdp), _stamp(mp)
    key = (n, str(cdp), cd_stamp, str(mp), mp_stamp)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    cd = tft_set.load_json_file(cdp)
    meta = tft_set.load_json_file(mp)
    try:
        prof = _build_profile(n, cdp, mp, cd, meta)
    except Exception as exc:  # noqa: BLE001 - any data defect degrades, never stops coaching
        if _WARNED[0] != key:
            _WARNED[0] = key
            logger.warning("TFT prompt: set %s data unusable, using no-data block: %r", n, exc)
        prof = _no_data(n, mp.name, "unverified" if meta else "absent")
    # load_json_file returns {} for ANY OSError or bad JSON, so an existing
    # file that loaded empty may only have been unreadable this instant (a
    # sharing violation mid-replace): serve it, never pin it until a change.
    if (cd_stamp is not None and not cd) or (mp_stamp is not None and not meta):
        return prof
    _CACHE.clear()  # one live entry: the set or a file changed
    _CACHE[key] = prof
    return prof


def _build_profile(n, cdp, mp, cd: dict, meta: dict) -> SetProfile:
    if cd:
        source = "cdragon"
        ver, fetched = _short_version(cd.get("_content_version")), _clean_text(cd.get("_fetched"), 20)
        detail = ", ".join(x for x in (f"CommunityDragon {ver}" if ver else "CommunityDragon",
                                       f"fetched {fetched}" if fetched else "") if x)
        label = f"{cdp.name} ({detail})"
    elif meta and (meta.get("all_traits") or meta.get("unit_costs")):
        source = "meta"
        origin = ("roster re-derived from CommunityDragon"
                  if "communitydragon" in str(meta.get("_source", "")).lower()
                  else "no CommunityDragon extract ingested")
        label = f"{mp.name} game-data fields ({origin})"
    else:
        source, label = "none", ""
    comps = meta.get("comps")
    return SetProfile(
        set_number=n,
        set_name=_clean_name(meta.get("_set_name")),
        source=source,
        source_label=label,
        traits=_traits(cd, meta),
        units_by_cost=_units_by_cost(cd, meta),
        mechanics=_mechanics(meta),
        gods=_gods(meta),
        carousel=_carousel(cd),
        meta_file=mp.name,
        meta_state=_meta_state(meta),
        meta_comps=len(comps) if isinstance(comps, dict) else 0,
        meta_patch=_clean_text(meta.get("_patch"), 12),
        meta_updated=_clean_text(meta.get("_updated"), 20),
    )


# -- assembly -----------------------------------------------------------------

def _capped(parts: list, sep: str, budget: int) -> str:
    """Join parts within budget; the cut is announced as '+N more'."""
    out: list = []
    used = 0
    for i, part in enumerate(parts):
        add = len(part) + (len(sep) if out else 0)
        if used + add > budget:
            out.append(f"+{len(parts) - i} more")
            break
        out.append(part)
        used += add
    return sep.join(out)


def _units_line(prof: SetProfile, budget: int) -> str:
    head = "Units by cost (may include summons): " if prof.source == "cdragon" else "Units by cost: "
    budget -= len(head)
    total = sum(len(names) for _c, names in prof.units_by_cost)
    groups: list = []
    used = shown = 0
    for cost, names in prof.units_by_cost:
        prefix = f"{cost}: "
        add = len(prefix) + (2 if groups else 0)
        if used + add + 12 > budget:
            break
        taken: list = []
        for name in names:
            step = len(name) + (2 if taken else 0)
            if used + add + step + 12 > budget:
                break
            taken.append(name)
            add += step
        if not taken:
            break
        groups.append(prefix + ", ".join(taken))
        used += add
        shown += len(taken)
        if len(taken) < len(names):
            break
    line = head + "; ".join(groups)
    if shown < total:
        line += f" +{total - shown} more"
    return line


def _set_block(prof: SetProfile, budget: int) -> str:
    """Header, traits, units, then the data-shown mechanics, within budget."""
    n = prof.set_number
    title = f'SET {n} "{prof.set_name}"' if prof.set_name else f"SET {n}"
    if prof.source == "none":
        return (f"{title} - no game data ingested for this set. Name no"
                " set-specific unit, trait or mechanic beyond what the game"
                " state shows.")
    head = f"{title} - from {prof.source_label}. No other mechanic of this set is known."
    tail: list = []
    if prof.carousel:
        tail.append("Carousel: this set's augment text names carousel rounds.")
    if prof.mechanics:
        label = "Set mechanics (meta record): "
        tail.append(label + _capped([f"{k}: {v}" for k, v in prof.mechanics],
                                    " | ", _MECH_MAX - len(label)))
    rest = budget - len(head) - sum(len(t) + 1 for t in tail)
    body: list = []
    if prof.traits:
        has_bp = any(bp for _n, bp in prof.traits)
        lead = "Traits (breakpoints): " if has_bp else "Traits (no breakpoints in this data): "
        parts = [f"{name} {bp}" if bp else name for name, bp in prof.traits]
        share = rest // 2 if prof.units_by_cost else rest
        body.append(lead + _capped(parts, ", ", max(40, share - len(lead) - 13)))
        rest -= len(body[-1]) + 1
    if prof.units_by_cost:
        body.append(_units_line(prof, max(60, rest - 1)))
    return "\n".join([head] + body + tail)


def _meta_line(prof: SetProfile) -> str:
    if prof.meta_state == "verified":
        stamp = ", ".join(x for x in (
            f"patch {prof.meta_patch}" if prof.meta_patch else "",
            f"updated {prof.meta_updated}" if prof.meta_updated else "") if x)
        stamp = f" ({stamp})" if stamp else ""
        return (f"META: {prof.meta_file}{stamp} holds {prof.meta_comps} comps; cite"
                " one only through the SELECTED COMP block.")
    what = {
        "skeleton": f"{prof.meta_file} is an UNVERIFIED skeleton",
        "absent": f"no {prof.meta_file} on file - UNVERIFIED",
    }.get(prof.meta_state, f"{prof.meta_file} is UNVERIFIED")
    return (f"META: {what} - no comp or tier data exists for this set. Make NO"
            " tier or meta-comp claims; coach from the game state and the"
            " data above.")


def _assemble(prof: SetProfile) -> str:
    output = _OUTPUT.format(label=prof.pick_label, desc=_PICK_DESC[prof.pick_label])
    meta = _meta_line(prof)
    fixed = "\n\n".join((_HEAD, "", meta, _RULES, output))
    budget = MAX_PROMPT_CHARS - len(fixed) - 4
    block = _set_block(prof, budget)
    return "\n\n".join((_HEAD, block, meta, _RULES, output))


def build_system_prompt(set_number=None, *, pbe=None, root=None) -> str:
    """The system prompt for the resolved set (live set > RC_TFT_SET > newest).

    Never raises: a profile failure degrades to the shared rules plus a
    no-data SET block, so a malformed data file cannot stop coaching.
    set_profile degrades malformed data itself, for the resolved set; this
    catch is only reached when the set cannot even be resolved.
    """
    try:
        prof = set_profile(set_number, pbe=pbe, root=root)
    except Exception as exc:  # noqa: BLE001
        logger.warning("TFT prompt: set unresolvable, using no-data block: %r", exc)
        n = set_number if isinstance(set_number, int) else tft_set.FALLBACK_SET
        prof = _no_data(n, f"tft_set{n}_meta.json")
    text = _assemble(prof)
    if len(text) > MAX_PROMPT_CHARS:  # cannot happen by construction; loud if it does
        logger.warning("TFT prompt %d chars over the %d budget - set block dropped",
                       len(text), MAX_PROMPT_CHARS)
        text = _assemble(SetProfile(prof.set_number, prof.set_name, "none", "", (), (), (),
                                    prof.gods, prof.carousel, prof.meta_file,
                                    prof.meta_state, prof.meta_comps,
                                    prof.meta_patch, prof.meta_updated))
    return text


def set_has_gods(set_number=None, *, pbe=None, root=None) -> bool:
    """True only when the resolved set's meta records Realm of the Gods."""
    try:
        return set_profile(set_number, pbe=pbe, root=root).gods
    except Exception:  # noqa: BLE001
        return False


def meta_verified(set_number=None, *, pbe=None, root=None) -> bool:
    """True only when the resolved set's meta holds comp data and is not
    flagged skeleton / unverified - the gate for meta opinion in a message."""
    try:
        return set_profile(set_number, pbe=pbe, root=root).meta_state == "verified"
    except Exception:  # noqa: BLE001
        return False


def pick_label(set_number=None, *, pbe=None, root=None) -> str:
    try:
        return set_profile(set_number, pbe=pbe, root=root).pick_label
    except Exception:  # noqa: BLE001
        return PICK_GENERIC
