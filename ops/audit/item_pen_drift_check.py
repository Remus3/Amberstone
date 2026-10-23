"""Item PENETRATION drift-check (DDragon <stats> truth vs engine pins).

CLAUDE.md Settled: item PEN / LETHALITY magnitudes come from DDragon
``<stats>`` only (never Meraki). The engine credits them ONLY through
hand-pinned ``ITEM_EFFECTS`` fields - no generic stat key carries
penetration - so a patch that re-values one drifts silently. RM-766 found
exactly that: DDragon 16.21.1 moved Bastionbreaker (2520) Lethality 22 -> 18
and nothing compared the two. This is the sibling of
``ops/audit/item_ah_drift_check.py`` (Ability Haste), with the same shape.

Axes (DDragon ``<stats>`` line -> ITEM_EFFECTS field):

  * ``<attention>N</attention> Lethality``           -> ``lethality``
  * ``<attention>N%</attention> Armor Penetration``  -> ``armor_pen_pct`` (N/100)
  * ``<attention>N</attention> Magic Penetration``   -> ``magic_pen_flat``
  * ``<attention>N%</attention> Magic Penetration``  -> ``magic_pen_pct`` (N/100)
  * ``armor_pen_flat`` has no DDragon stat line, so any non-zero engine value
    is reported as REMOVED unless it is passive-sourced (see below).

Resist-reduction axes (RM-806). DDragon states no reduction in ``<stats>``;
it states it in the PASSIVE prose as a per-stack magnitude and a stack count,
and the engine credits the full-stack steady state (per-stack x stacks, the
Black Cleaver convention). Meraki is never the source (CLAUDE.md Settled).

  * ``reduces ... <scaleArmor>Armor by N%</scaleArmor> ... (stacks K times)``
                                         -> ``armor_reduction_pct`` (N*K/100)
  * ``reduces ... <scaleMR>Magic Resist by N%</scaleMR> ...``
                                         -> ``mr_reduction_pct``    (N*K/100)
  * ``shreds N <scaleArmor>Armor</scaleArmor> [and <scaleMR>Magic Resist
    </scaleMR>] ... stacking up to K times``
                                         -> ``armor_reduction_flat`` / ``mr_reduction_flat`` (N*K)
  * no stack phrase in the passive = one application (K = 1).

Coverage is classified, never silently skipped:

  * buyable       - a pen line (or reduction passive) on a non-Ornn canonical
                    item; diffed per axis.
  * ornn          - an Ornn masterwork (``<ornnBonus>`` in its description, the
                    marker agents/daemon_slayer/rank.py ``_is_ornn_masterwork``
                    uses). Diffed ONLY where the engine already has a row;
                    otherwise excluded by design (never purchasable).
  * band_skipped  - the throwback item band
                    (agents/daemon_slayer/mode_variants.is_mode_variant_item),
                    which the DS snapshot drops and the engine never scores.
  * unparsed      - a ``<stats>`` line naming Lethality / Penetration, or a
                    resist reduction stating a number, that no axis
                    understands; this FAILS so a new tag shape cannot hide.
  * reduction_unstated - a resist reduction whose prose states NO magnitude
                    (Malignance Hatefog at 16.21.1): nothing to diff, listed;
                    an engine value on such an item is still REMOVED.

``PASSIVE_SOURCED`` lists (item, axis) pairs whose pen is a PASSIVE (not a
``<stats>`` magnitude), each with its reason. The exemption covers ONLY that
axis of that item: drift on any other axis of the row is still reported
(RM-806). A listed pair that DDragon starts stating, or that the engine stops
crediting, is a stale exemption and fails.

Read-only. Exit 0 = in sync, 1 = drift / unparsed / stale exemption,
2 = no item.json.

    python ops/audit/item_pen_drift_check.py [<ddragon item.json path>]
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
_CURRENT_TXT = ROOT / "data" / "daemon_slayer" / "current.txt"

AXES = ("lethality", "armor_pen_pct", "magic_pen_flat", "magic_pen_pct")
# RM-806: resist reduction, read from the passive prose (never <stats>).
REDUCTION_AXES = (
    "armor_reduction_pct", "armor_reduction_flat", "mr_reduction_pct", "mr_reduction_flat",
)
# Engine fields compared; armor_pen_flat has no DDragon axis.
ENGINE_FIELDS = AXES + ("armor_pen_flat",) + REDUCTION_AXES

_STATS_BLOCK = re.compile(r"<stats>(.*?)</stats>", re.S)
_LINE_SPLIT = re.compile(r"<br\s*/?>", re.I)
_PEN_ANY = re.compile(r"Lethality|Penetration")
_ORNN_MARKER = "<ornnBonus>"
_TAG = r"(?:attention|ornnBonus)"
_AXIS_RE = {
    "lethality": re.compile(rf"<{_TAG}>([0-9.]+)</{_TAG}>\s*Lethality"),
    "armor_pen_pct": re.compile(rf"<{_TAG}>([0-9.]+)%</{_TAG}>\s*Armor Penetration"),
    "magic_pen_flat": re.compile(rf"<{_TAG}>([0-9.]+)</{_TAG}>\s*Magic Penetration"),
    "magic_pen_pct": re.compile(rf"<{_TAG}>([0-9.]+)%</{_TAG}>\s*Magic Penetration"),
}

# Resist-reduction prose (passive text outside <stats>). A MENTION is a
# reduction verb whose object is a resist; each mention must match a SHAPE.
_RESIST = r"(?:Armor|Magic Resist)"
_REDUCE_MENTION = re.compile(
    r"(?:[Rr]educ\w*|[Ss]hreds?)\s+(?:the target's\s+|their\s+|the\s+)?"
    rf"(?:[0-9.]+\s+)?(?:<scale(?:Armor|MR)>)?\s*{_RESIST}\b"
)
_REDUCE_PCT = re.compile(
    r"[Rr]educ\w*\s+(?:the target's\s+|their\s+|the\s+)?"
    rf"<scale(Armor|MR)>{_RESIST} by ([0-9.]+)%</scale\1>"
)
_SCALED = rf"<scale(?:Armor|MR)>{_RESIST}</scale(?:Armor|MR)>"
_REDUCE_FLAT = re.compile(rf"[Ss]hreds?\s+([0-9.]+)\s+({_SCALED}(?:\s+and\s+{_SCALED})?)")
_SCALE_TAG = re.compile(r"<scale(Armor|MR)>")
_STACKS = re.compile(r"[Ss]tack(?:s|ing)?\s+(?:up to\s+)?([0-9]+)\s+times")
_SECTION_END = re.compile(r"<br\s*/?>\s*<br\s*/?>|<passive>|</mainText>")
_SENTENCE_END = re.compile(r"\.(?=\s|<|$)")
_TAG_ANY = re.compile(r"<[^>]+>")
_REDUCTION_FIELD = {
    ("Armor", "pct"): "armor_reduction_pct",
    ("MR", "pct"): "mr_reduction_pct",
    ("Armor", "flat"): "armor_reduction_flat",
    ("MR", "flat"): "mr_reduction_flat",
}

# Engine pen that is a PASSIVE, not a <stats> magnitude, keyed (item, axis):
# the exemption covers that axis only (RM-806). Measured 2026-10-22 (RM-766)
# against DDragon 16.21.1: these are the only engine pen axes with no matching
# <stats> line. The prose states the per-stack pen but no stack count, so the
# credited full-stack value cannot be re-derived from DDragon.
_TERMINUS_SR = (
    "Terminus Juxtaposition: per-stack armor + magic pen in the passive "
    "prose, credited at the full-stack steady state (Black Cleaver / "
    "Guinsoo convention; agents/daemon_slayer/tests/test_pen_pct_catalog_r160.py "
    "_STACKING_FULL_STACK)"
)
_TERMINUS_ARENA = (
    "Terminus Arena mirror: same Juxtaposition full-stack convention as "
    "3302 (test_pen_pct_catalog_r160.py _STACKING_FULL_STACK)"
)
PASSIVE_SOURCED: dict[tuple[str, str], str] = {
    ("3302", "armor_pen_pct"): _TERMINUS_SR,
    ("3302", "magic_pen_pct"): _TERMINUS_SR,
    ("223302", "armor_pen_pct"): _TERMINUS_ARENA,
    ("223302", "magic_pen_pct"): _TERMINUS_ARENA,
}


def _default_item_json() -> Path:
    """The live-patch DDragon item.json, resolved from current.txt (never a literal)."""
    patch = _CURRENT_TXT.read_text(encoding="utf-8").strip()
    return ROOT / "data" / "meta_build" / "ddragon" / patch / "item.json"


def _is_band(iid: str) -> bool:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from agents.daemon_slayer.mode_variants import is_mode_variant_item

    return is_mode_variant_item(iid)


@dataclass
class PenClassification:
    buyable: dict[str, dict[str, float]] = field(default_factory=dict)
    ornn: dict[str, dict[str, float]] = field(default_factory=dict)
    band_skipped: list[str] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)
    reduction_unstated: list[str] = field(default_factory=list)


@dataclass
class PenReport:
    changed: dict[tuple[str, str], tuple[float, float]] = field(default_factory=dict)
    added: list[tuple[str, str]] = field(default_factory=list)
    removed: list[tuple[str, str]] = field(default_factory=list)
    stale_allowlist: list[tuple[str, str]] = field(default_factory=list)

    @property
    def drift(self) -> bool:
        return bool(self.changed or self.added or self.removed or self.stale_allowlist)


def _parse_block(block: str) -> tuple[dict[str, float], bool]:
    """(axis -> value, unparsed?) for one <stats> block."""
    row: dict[str, float] = {}
    unparsed = False
    for line in _LINE_SPLIT.split(block):
        if not _PEN_ANY.search(line):
            continue
        for axis, rx in _AXIS_RE.items():
            m = rx.search(line)
            if m:
                v = float(m.group(1))
                row[axis] = v / 100.0 if axis.endswith("_pct") else v
                break
        else:
            unparsed = True
    return row, unparsed


def _parse_reductions(body: str) -> tuple[dict[str, float], bool, bool]:
    """(axis -> full-stack value, unparsed?, unstated?) for the passive prose.

    ``body`` is the description with its <stats> block removed. Every
    reduction mention must match a shape; one that states a number but no
    shape is unparsed, one that states no number is unstated.
    """
    row: dict[str, float] = {}
    unparsed = unstated = False
    for m in _REDUCE_MENTION.finditer(body):
        start = m.start()
        sec_end = _SECTION_END.search(body, start)
        section = body[start:sec_end.start() if sec_end else len(body)]
        stacks = _STACKS.search(section)
        k = int(stacks.group(1)) if stacks else 1
        hits: list[tuple[str, float]] = []
        pct = _REDUCE_PCT.match(body, start)
        flat = _REDUCE_FLAT.match(body, start)
        if pct:
            hits = [(_REDUCTION_FIELD[(pct.group(1), "pct")], float(pct.group(2)) * k / 100.0)]
        elif flat:
            n = float(flat.group(1))
            hits = [(_REDUCTION_FIELD[(r, "flat")], n * k) for r in _SCALE_TAG.findall(flat.group(2))]
        else:
            sent_end = _SENTENCE_END.search(section)
            sentence = section[:sent_end.start() if sent_end else len(section)]
            if re.search(r"[0-9]", _TAG_ANY.sub("", sentence)):
                unparsed = True
            else:
                unstated = True
        for axis, v in hits:
            if axis in row:
                unparsed = True  # two shapes on one axis: never silently merged
            row[axis] = v
    return row, unparsed, unstated


def classify_ddragon(item_json: Path) -> PenClassification:
    """Bucket every pen-bearing <stats> block and every resist-reduction
    passive: buyable / ornn / band / unparsed / reduction_unstated."""
    blob = json.loads(item_json.read_text(encoding="utf-8"))
    out = PenClassification()
    for iid, it in blob["data"].items():
        desc = it.get("description", "") or ""
        m = _STATS_BLOCK.search(desc)
        stats_pen = bool(m and _PEN_ANY.search(m.group(1)))
        body = _STATS_BLOCK.sub("", desc)
        if not stats_pen and not _REDUCE_MENTION.search(body):
            continue
        if _is_band(iid):
            out.band_skipped.append(iid)
            continue
        row, unparsed = _parse_block(m.group(1)) if stats_pen else ({}, False)
        red_row, red_unparsed, unstated = _parse_reductions(body)
        row.update(red_row)
        if unparsed or red_unparsed:
            out.unparsed.append(iid)
        if unstated:
            out.reduction_unstated.append(iid)
        if row:
            (out.ornn if _ORNN_MARKER in desc else out.buyable)[iid] = row
    out.band_skipped.sort(key=int)
    out.unparsed.sort(key=int)
    out.reduction_unstated.sort(key=int)
    return out


def load_engine() -> dict[str, dict[str, float]]:
    """Non-zero pen and resist-reduction fields of every ITEM_EFFECTS row."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from agents.daemon_slayer.effects import ITEM_EFFECTS

    out: dict[str, dict[str, float]] = {}
    for iid, eff in ITEM_EFFECTS.items():
        row = {f: float(getattr(eff, f, 0.0) or 0.0) for f in ENGINE_FIELDS}
        row = {f: v for f, v in row.items() if v}
        if row:
            out[str(iid)] = row
    return out


def diff(cls: PenClassification, engine: dict[str, dict[str, float]],
         passive_sourced: dict[tuple[str, str], str] | None = None) -> PenReport:
    """Per (item, axis) diff of DDragon <stats> / reduction prose vs engine pins.

    ``passive_sourced`` exempts single (item, axis) pairs, never a whole row.
    """
    allow = PASSIVE_SOURCED if passive_sourced is None else passive_sourced
    rep = PenReport()
    stated: dict[str, dict[str, float]] = dict(cls.buyable)
    # Ornn masterworks are compared only where the engine already has a row.
    stated.update({i: r for i, r in cls.ornn.items() if i in engine})
    for iid in sorted(set(stated) | set(engine), key=int):
        dd, en = stated.get(iid, {}), engine.get(iid, {})
        for axis in sorted(set(dd) | set(en)):
            if (iid, axis) in allow:
                continue
            if axis in dd and axis in en:
                if abs(dd[axis] - en[axis]) > 1e-9:
                    rep.changed[(iid, axis)] = (en[axis], dd[axis])
            elif axis in dd:
                rep.added.append((iid, axis))
            else:
                rep.removed.append((iid, axis))
    for iid, axis in sorted(allow, key=lambda k: (int(k[0]), k[1])):
        if axis in stated.get(iid, {}) or axis not in engine.get(iid, {}):
            rep.stale_allowlist.append((iid, axis))
    return rep


def main() -> int:
    item_json = Path(sys.argv[1]) if len(sys.argv) > 1 else _default_item_json()
    if not item_json.exists():
        print(f"NO DDragon item.json at {item_json}", file=sys.stderr)
        return 2
    blob = json.loads(item_json.read_text(encoding="utf-8"))
    names = {k: v.get("name", "?") for k, v in blob["data"].items()}
    cls = classify_ddragon(item_json)
    engine = load_engine()
    rep = diff(cls, engine)

    print(f"DDragon {blob.get('version')}: {len(cls.buyable)} buyable pen / reduction items "
          f"| engine pen / reduction rows: {len(engine)} "
          f"| Ornn masterwork items: {len(cls.ornn)} "
          f"| throwback band skipped: {len(cls.band_skipped)} "
          f"| unparsed lines: {len(cls.unparsed)} "
          f"| reduction prose with no magnitude: {len(cls.reduction_unstated)} "
          f"| passive-sourced (item, axis) exemptions: {len(PASSIVE_SOURCED)}")
    print(f"changed={len(rep.changed)} added={len(rep.added)} removed={len(rep.removed)} "
          f"stale_exemptions={len(rep.stale_allowlist)}")
    if rep.changed:
        print("\n-- CHANGED (value drift: engine -> DDragon) --")
        for (i, axis), (en, dd) in sorted(rep.changed.items(), key=lambda kv: int(kv[0][0])):
            print(f"  {i:>7} {names.get(i, '?'):32} {axis}: engine={en} -> DDragon={dd}")
    if rep.added:
        print("\n-- ADDED (DDragon <stats> / passive states it, engine credits nothing) --")
        for i, axis in rep.added:
            print(f"  {i:>7} {names.get(i, '?'):32} {axis}")
    if rep.removed:
        print("\n-- REMOVED (engine credits it, DDragon <stats> / passive states nothing) --")
        for i, axis in rep.removed:
            print(f"  {i:>7} {names.get(i, '?'):32} {axis}")
    if rep.stale_allowlist:
        print("\n-- STALE PASSIVE_SOURCED exemption (axis now stated by DDragon, or not credited) --")
        for i, axis in rep.stale_allowlist:
            print(f"  {i:>7} {names.get(i, '?'):32} {axis}")
    excluded = sorted((i for i in cls.ornn if i not in engine), key=int)
    if excluded:
        print("\n-- EXCLUDED BY DESIGN (Ornn masterwork, no engine row) --")
        for i in excluded:
            print(f"  {i:>7} {names.get(i, '?'):32} {cls.ornn[i]}")
    if cls.reduction_unstated:
        print("\n-- NO MAGNITUDE (reduction prose states no number; nothing to diff) --")
        for i in cls.reduction_unstated:
            print(f"  {i:>7} {names.get(i, '?')}")
    if cls.unparsed:
        print("\n-- UNPARSED (pen / reduction line no axis understands) --")
        for i in cls.unparsed:
            print(f"  {i:>7} {names.get(i, '?')}")
    drift = rep.drift or bool(cls.unparsed)
    print("\nRESULT:", "DRIFT" if drift else "IN SYNC")
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
