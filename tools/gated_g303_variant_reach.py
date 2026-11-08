"""gated_g303_variant_reach.py - can this champion roll the G3-03 VARIANT verdict?

G3-03 in ``docs/LIVE_GAME_GATED_SYNC.md`` waits for an ARAM champ select whose
comp-verdict banner reads ``VARIANT -> <key>``. The engine
(``core.aram_comp_verdict.comp_verdict``) returns ``variant`` only when a
damage or sustain gap is open AND ``_find_variant`` finds a NON-current posted
variant whose key / label / summary text contains one of the gap's keywords
(``_AP_VARIANT_KW`` / ``_AD_VARIANT_KW`` / ``_SUSTAIN_VARIANT_KW``). The panel
posts the build-chooser rows (``_csvCompVerdictVariants`` over
``_csvBuildVariantsFor``), which come from ``POST /api/loadout/list``: the
curated ``coaches.loadout_resolver.list_variants`` rows plus the operator's
``coaches.sr_user_builds`` rows (key ``userbuild_<id>``). No producer serves a
``summary``, so only key + label are matched.

The keyword test is a plain SUBSTRING test, so a hit can be accidental: the
curated ARAM key ``aram-collapsed`` contains "ap" (col-l-AP-sed) and matches
the AP keyword set for every champion. This tool reports, per champion, which
row each gap would pick and whether the keyword that matched is a WHOLE WORD
(``genuine``) or only a substring of a longer word (``substring``). A
``substring`` hit is the keyword false positive: a banner reading VARIANT for
it is NOT G3-03 evidence. A damage gap the champion's own primary lean
supplies (``self_closes``) cannot open, because my_team carries the local cell;
``genuine_gaps`` lists only whole-word hits on gaps that can open.

Read-only: it imports the resolver and the user-build store, writes nothing,
calls no network. Run from the repo root (the user-build store is the
gitignored ``data/daemon_slayer/user_builds.json`` of the checkout it runs
in). This is PREP for the live check, never a tick: the engine reading of a
row list is the compute half.

    python tools/gated_g303_variant_reach.py Caitlyn Vayne
    python tools/gated_g303_variant_reach.py --all --reachable-only
    python tools/gated_g303_variant_reach.py Caitlyn --current userbuild_abc
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Callable, Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Gap name -> the engine's keyword-set attribute. "ap" = the comp LACKS AP
# (an all-AD comp), so the engine looks for an AP variant; "ad" mirrors it.
GAPS = (("ap", "_AP_VARIANT_KW"), ("ad", "_AD_VARIANT_KW"),
        ("sustain", "_SUSTAIN_VARIANT_KW"))

# Mirrors core.aram_comp_verdict._variant_addresses: each field cut to 256.
_FIELDS = ("key", "label", "summary")
_FIELD_CAP = 256


def _text(row: dict) -> str:
    return " ".join(str(row.get(k) or "")[:_FIELD_CAP] for k in _FIELDS).lower()


def _whole_word(kw: str, text: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])",
                     text) is not None


def panel_rows(curated: Iterable[dict], user_builds: Iterable[dict]) -> list:
    """The rows the panel POSTs, in chooser order (curated first).

    ``curated`` = list_variants rows; ``user_builds`` = format_for_display
    dicts. Mirrors the /api/loadout/list merge (``"userbuild_" + key``, label
    default "user build") and _csvCompVerdictVariants (drop a falsy or
    "empty" key; label falls back to key; summary "" when absent).
    """
    rows = []
    for v in curated or []:
        if isinstance(v, dict):
            rows.append({"key": v.get("key"), "label": v.get("label"),
                         "summary": v.get("summary")})
    for s in user_builds or []:
        if isinstance(s, dict):
            rows.append({"key": "userbuild_" + str(s.get("key") or ""),
                         "label": s.get("label") or "user build"})
    out = []
    for v in rows:
        if not v["key"] or v["key"] == "empty":
            continue
        key = str(v["key"])
        out.append({"key": key, "label": str(v["label"] or key),
                    "summary": str(v.get("summary") or "")})
    return out


def reach(rows: list, current: str, engine=None) -> dict:
    """Per gap: the row the engine picks, the keyword that hit, and its kind.

    ``kind`` is "genuine" when the first keyword found in the picked row's
    text is a whole word anywhere in it, "substring" when every keyword of
    the set that occurs does so only inside a longer word, None when no row
    is picked.
    """
    if engine is None:
        import core.aram_comp_verdict as engine
    variants = engine._variants(rows)
    out = {}
    for gap, attr in GAPS:
        kws = getattr(engine, attr)
        v = engine._find_variant(variants, current, kws)
        if not v:
            out[gap] = {"variant_to": None, "keyword": None, "kind": None}
            continue
        text = _text(v)
        hits = [kw for kw in kws if kw in text]
        whole = [kw for kw in hits if _whole_word(kw, text)]
        out[gap] = {"variant_to": v["key"],
                    "keyword": (whole or hits or [None])[0],
                    "kind": "genuine" if whole else "substring"}
    return out


def _default_sources(store: Optional[str] = None) -> tuple:
    from coaches.loadout_resolver import list_variants, _load_loadouts
    from coaches.sr_user_builds import _STORE_PATH, format_for_display

    path = Path(store) if store else _STORE_PATH

    def records(champ: str) -> list:
        # A plain json load (same champions -> champion -> list of dicts walk
        # as sr_user_builds.list_for): the module reader renames an
        # unparseable store aside and fills a module cache, and this tool
        # never moves a file. Unreadable or malformed = no user builds.
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            builds = (data.get("champions") or {}).get(champ) or []
        except (OSError, ValueError, AttributeError):
            return []
        return [b for b in builds if isinstance(b, dict)]

    def curated(champ: str) -> list:
        return list_variants(champ, "aram")

    def user(champ: str) -> list:
        return [s for s in (format_for_display(r) for r in records(champ)) if s]

    def roster() -> list:
        return sorted((_load_loadouts().get("champions") or {}).keys())

    return curated, user, roster


def report(champions: Iterable[str], current: Optional[str] = None,
           curated: Optional[Callable] = None, user: Optional[Callable] = None,
           engine=None) -> list:
    """One record per champion. ``current`` None = the first chooser row
    (the default selection when no saved choice exists)."""
    if curated is None or user is None:
        d_cur, d_user, _ = _default_sources()
        curated = curated or d_cur
        user = user or d_user
    if engine is None:
        import core.aram_comp_verdict as engine
    out = []
    for champ in champions:
        rows = panel_rows(curated(champ), user(champ))
        cur = current if current is not None else (rows[0]["key"] if rows else "")
        gaps = reach(rows, cur, engine)
        # my_team includes the local cell (lcu/champ_select_shape.py
        # _team_picks over myTeam), so the champion's own primary lean
        # always supplies that damage type: a gap lacking it cannot open.
        # A curated sustain champion closes the sustain gap the same way.
        info = engine._lookup(champ)
        lean = engine._damage_lean(info) if info else None
        sustains = engine._norm(info.get("name") if info else champ) in \
            engine._SUSTAIN_NORM
        for gap, r in gaps.items():
            r["self_closes"] = (gap == "sustain" and sustains) or (
                gap in ("ap", "ad") and gap == lean)
        out.append({
            "champion": champ, "rows": len(rows), "lean": lean,
            "keys": [r["key"] for r in rows], "current": cur, "gaps": gaps,
            "genuine_gaps": sorted(g for g, r in gaps.items()
                                   if r["kind"] == "genuine"
                                   and not r["self_closes"]),
        })
    return out


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("champions", nargs="*", help="champion display names")
    ap.add_argument("--all", action="store_true",
                    help="every champion in data/champion_loadouts.json")
    ap.add_argument("--current", default=None,
                    help="the active chooser key (default: the first row)")
    ap.add_argument("--reachable-only", action="store_true",
                    help="print only champions with a genuine gap")
    ap.add_argument("--store", default=None,
                    help="user_builds.json to read (default: this checkout's)")
    args = ap.parse_args(argv)
    curated, user, roster = _default_sources(args.store)
    champs = roster() if args.all else args.champions
    if not champs:
        ap.error("name a champion or pass --all")
    recs = report(champs, args.current, curated, user)
    shown = [r for r in recs if r["genuine_gaps"]] if args.reachable_only else recs
    for r in shown:
        print(json.dumps(r, sort_keys=True))
    print(json.dumps({"summary": {
        "champions": len(recs),
        "with_2plus_rows": sum(1 for r in recs if r["rows"] >= 2),
        "genuine": sum(1 for r in recs if r["genuine_gaps"]),
        "substring_only": sum(1 for r in recs if not r["genuine_gaps"] and any(
            g["kind"] == "substring" for g in r["gaps"].values())),
    }}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
