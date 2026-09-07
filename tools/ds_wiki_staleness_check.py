"""RM-81: flag champions whose stored Meraki ability data predates a rework.

WHY THIS EXISTS
---------------
`data/daemon_slayer/<patch>/champion_abilities.json` is sourced from Meraki's
frozen ``latest`` endpoint, pinned at content patch 25.15 (see
``daemon_slayer_abilities_extract._EXPECTED_MERAKI_CONTENT_PATCH``) while the
live game runs ~11 patches ahead. The freeze itself is deliberate and logged,
and ``upstream_drift_check`` already tracks the field, so this module does NOT
re-discover that. What was uncovered is the DOWNSTREAM cost: a champion that is
PRESENT in the map still returns ``champion_has_ability_data() -> True``, so the
RM-79 kit-less guard stays quiet while the stored values describe a champion who
no longer exists.

The existing CDragon drift report (`cdragon_ratio_drift.json`) is RATIO-only -
its 1,046 rows cover ap_pct / total_ad_pct / caster_max_hp_pct / bonus_ad_pct
and contain zero ``base`` and zero ``cooldown`` rows - so it structurally cannot
see the two fields that carry the real evidence. This module closes that gap
using ONLY the wiki source the repo already reads, so it neither needs
CommunityDragon nor touches the ``prefer_cdragon_ratios`` cutover - which is
default-ON and live (``abilities.py`` ``load(prefer_cdragon_ratios=True)`` since
item 320 / ENGINE 1.119.0), NOT default-off as this file previously claimed.

TWO MODES, because they answer different questions
--------------------------------------------------
``--recent`` (cheap, 1 API call, meant for a daily task) reads
Special:RecentChanges for ``Template:Data <Champion>/<Ability>`` edits and
re-checks only those champions. It is a FORWARD watchdog: it stops NEW drift
from accumulating silently. It cannot find old drift, because the feed only
reaches back ~30 days while the Meraki pin is ~11 patches old.

``--full`` (~18 batched requests) sweeps every champion and is what surfaces the
drift already banked - the RM-81 discovery cases (Maokai, Mel) live here.

CONSERVATIVE BY DESIGN
----------------------
A finding is emitted only when BOTH sides carry a parseable value for the SAME
labelled quantity, compared at its first/last rank endpoints. Wiki damage labels
that do not match a Meraki ``attribute`` verbatim are skipped rather than
guessed at, so the report under-reports rather than crying wolf: an editorial
wiki edit ("fixed typo") moves no number and therefore produces no finding.

The one exception is ``_LABEL_ALIASES`` (RM-220), a hand-cited, exact,
champion-scoped table of stored spellings the live page publishes under
different wording for the same quantity. It is deliberately tiny, every entry
names the live page it was read off, and a row it produces carries
``wiki_label`` so an aliased comparison is never mistaken for a verbatim one.

Usage:
    python tools/ds_wiki_staleness_check.py --full [--patch 16.14.1] [--write]
    python tools/ds_wiki_staleness_check.py --recent [--days 7] [--write]
    python tools/ds_wiki_staleness_check.py --full --json
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from daemon_slayer_wiki_ability_extract import (  # noqa: E402
    DATA_DIR,
    HEADER_UA,
    WIKI_API,
    _AP_WRAPPER_RE,
    _fetch,
    _MAX_TITLES_PER_BATCH,
    _TEMPLATE_PREFIX,
)

REPORT_NAME = "ability_staleness.json"

# Endpoint equality tolerance. Wiki values are authored to at most 2 decimals;
# Meraki stores floats, so exact equality would flag pure representation noise.
_TOL = 1e-2

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_ST_RE = re.compile(r"\{\{\s*st\s*\|", re.IGNORECASE)
# Deliberately LOCAL rather than the imported `_AP_WRAPPER_RE`, which pins bare
# `[0-9.]+` endpoints. The extractor that owns that regex feeds the engine, so
# widening it there would be a Tier-2 change to a data producer; this reader
# only needs the looser capture for itself.
_AP_OPEN_RE = re.compile(r"\{\{\s*ap\s*\|", re.IGNORECASE)
_TO_SPLIT_RE = re.compile(r"\s+to\s+", re.IGNORECASE)
# `round=2` / `fd=1` - a RENDERING hint, not a rank (RM-220).
_NAMED_PARAM_RE = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=")
# `110 6` - the endpoint, then the ability's RANK COUNT (RM-220). Bounded to two
# digits: no ability has 100 ranks, and an unbounded tail would let a genuine
# trailing number be eaten.
_RANK_COUNT_SUFFIX_RE = re.compile(r"^(?P<expr>.*\S)\s+\d{1,2}$")
_ARITH_CHARS_RE = re.compile(r"[0-9.+\-*/() ]+")
# `{{ii|Death's Daughter}}` inside a LABEL - the stored side reads it as plain
# text, so the wrapper has to be flattened before the two can ever match.
_LABEL_TEMPLATE_RE = re.compile(r"\{\{\s*[a-z]+\s*\|([^{}|]*)\}\}", re.IGNORECASE)
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

# RM-220(B): exact, champion-scoped label aliases. NOT a vocabulary table.
#
# RM-218 was REFUTED as a blanket vocabulary gap, and this must not become one
# by increments. Each entry is one stored spelling that a single CITED live page
# publishes under different wording for the SAME quantity - nothing else
# qualifies, and three nearby residue cases show why the bar is that high:
#
#   * Ekko Q stores one ``Magic Damage`` where the live page publishes BOTH
#     ``Initial Magic Damage`` and ``Return Magic Damage``. A one-to-many split
#     has no single correct target, so it stays unaliased.
#   * Cho'Gath R stores ``Champion True Damage`` while the live page's only
#     PARSEABLE true-damage label used to be ``Non-Champion True Damage`` (1200
#     flat) - which reads like an alias and is a different quantity. That one
#     dissolved on its own: the missing label was the enumerated
#     ``{{ap|300|475|650}}`` form, and RM-220(A) reads it, so an exact match now
#     exists and no alias is needed.
#   * Briar Q stores ``Magic Damage`` where the live page publishes ``Physical
#     Damage`` and ``Resistances Reduction``. Binding those would assert the
#     damage TYPE never changed, which is itself the drift.
#
# Matching is EXACT on the whole stored label and scoped to the champion, never
# fuzzy and never substring: ``Magic Damage`` is itself an unmatched stored
# label, and a substring rule would bind it to ``Magic Damage Per Tick`` and
# compare a per-tick number against a total.
_LABEL_ALIASES: dict[tuple[str, str], str] = {
    # Template:Data Ahri/Fox-Fire, fetched 2026-09-04 at 16.15.1, |leveling2:
    #   {{st|Primary Magic Damage|{{ap|40 to 120}} {{as|(+ 40% AP)}}
    #       |Subsequent Magic Damage|{{ap|40*0.4 to 120*0.4}} ...}}
    # Stored: Initial Flame 40..120 (agrees), Subsequent Flame 12..36 against a
    # live 16..48 - the second flame moved from 30 to 40 percent of the first,
    # so this alias converts a discarded skip into the finding it always was.
    ("Ahri", "Initial Flame Magic Damage"): "Primary Magic Damage",
    ("Ahri", "Subsequent Flame Magic Damage"): "Subsequent Magic Damage",
}


_VARDEFINE_RE = re.compile(r"\{\{#vardefine:\s*([A-Za-z0-9_]+)\s*\|([^}|]*)\}\}")
_VARREF_RE = re.compile(r"\{\{#var:\s*([A-Za-z0-9_]+)\s*(?:\|[^}]*)?\}\}")


def _strip_comments(raw: str) -> str:
    return _COMMENT_RE.sub("", raw or "")


def resolve_wiki_vars(wikitext: str) -> str:
    """Inline ``{{#vardefine:name|value}}`` values into ``{{#var:name}}`` refs.

    Several Data pages hoist their numbers into MediaWiki variables at the top of
    the page and reference them indirectly, so the leveling line contains no
    literal digits (Garen's R is ``{{ap|{{#var:b1}} to {{#var:b3}}}}``). Without
    this the whole page silently yields no findings - a measured recall miss:
    Riot's 26.14 notes cut Garen's R from 150/250/350 to 125/200/275 and the
    detector saw nothing.

    The definitions live on the same page, so this needs no extra API call. A
    reference with no matching definition is left as-is, which then fails to
    parse as a number and correctly produces no finding rather than a guess.
    """
    text = wikitext or ""
    varmap = {m.group(1): m.group(2).strip() for m in _VARDEFINE_RE.finditer(text)}
    if not varmap:
        return text
    return _VARREF_RE.sub(
        lambda m: varmap.get(m.group(1), m.group(0)), text
    )


def parse_param(wikitext: str, name: str) -> Optional[str]:
    """Return the raw value of a leading-pipe template param, or None.

    Data templates author one param per line (``|cooldown     = {{ap|7 to 5}}``),
    so a line-anchored match is both sufficient and safe - it cannot run into the
    next param the way a greedy scan would.
    """
    pat = re.compile(
        r"^\|\s*" + re.escape(name) + r"\s*=\s*(.*)$",
        re.IGNORECASE | re.MULTILINE,
    )
    text = resolve_wiki_vars(wikitext or "")
    m = pat.search(text)
    if not m:
        return None
    return _strip_comments(m.group(1)).strip() or None


def parse_endpoints(raw: Optional[str]) -> Optional[tuple[float, float]]:
    """``{{ap|X to Y}}`` -> (X, Y); a bare number -> (N, N); else None.

    Endpoints rather than the full interpolated array on purpose: ``{{ap|}}``
    is a LINEAR macro, but real per-rank values are occasionally non-linear
    (Mel W is 38/35/33/29/26, not the 38/35/32/29/26 a linear expansion gives),
    so comparing interiors would manufacture false findings. First and last rank
    are exact on both sides.

    THREE MORE AUTHORED FORMS (RM-220). A single ``X to Y`` regex reached only
    part of the corpus: at 16.15.1, 27 skipped-label rows across 14 champions
    carried an EMPTY live-label list, meaning the page parsed to no labelled
    quantity whatsoever. The cause was never vocabulary, it was that ``{{ap|}}``
    is authored four ways, so the body is now brace-balanced and split on its
    OWN pipes instead:

      * ``{{ap|35 to 110 6}}`` (Jayce W) - the trailing 6 is his rank count. The
        old non-greedy tail backtracked across the space, captured ``110 6`` and
        died in ``_arith``, taking the whole page's labels with it.
      * ``{{ap|150|275|400}}`` (Nocturne R, Cho'Gath R) - enumerated ranks, no
        ``to`` anywhere. First and last positional are the endpoints.
      * ``{{ap|(50/12)*3 to (150/12)*3|round=2}}`` (Rumble Q) - ``round=`` is a
        rendering hint sitting between the endpoint and the closing braces.

    The scan takes the first ``{{ap|`` that PARSES rather than the first one it
    finds, which is what keeps a widened parser from stealing a match the old
    regex would have skipped past - Nocturne's cooldown is
    ``{{tt|{{ap|140 to 90}}|note}}`` and must still read 140..90.
    """
    s = _strip_comments(raw or "").strip()
    if not s:
        return None
    for body in _ap_bodies(s):
        pts = _ap_endpoints(body)
        if pts is not None:
            return pts
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return (v, v)


def _ap_bodies(text: str) -> list[str]:
    """Every ``{{ap|...}}`` body in ``text``, brace-balanced, in page order.

    Balanced rather than regex-terminated because a body legitimately contains
    nested templates - Rumble Q authors its endpoints as ``{{#var:q_b1}}``, and
    an unresolved ``{{#var:}}`` must not truncate the body at its own ``}}``.
    An unterminated wrapper yields nothing rather than a guess.
    """
    out: list[str] = []
    for m in _AP_OPEN_RE.finditer(text):
        i = m.end()
        depth = 1
        while i < len(text) and depth:
            if text.startswith("{{", i):
                depth += 1
                i += 2
            elif text.startswith("}}", i):
                depth -= 1
                i += 2
            else:
                i += 1
        if depth == 0:
            out.append(text[m.end(): i - 2])
    return out


def _ap_endpoints(body: str) -> Optional[tuple[float, float]]:
    """First/last endpoint of one ``{{ap|}}`` body, or None (RM-220)."""
    parts = [p.strip() for p in _top_level_parts(body)]
    parts = [p for p in parts if p and not _NAMED_PARAM_RE.match(p)]
    if not parts:
        return None
    if len(parts) > 1:
        lo, hi = _arith(parts[0]), _arith(parts[-1])
        return None if lo is None or hi is None else (lo, hi)
    halves = _TO_SPLIT_RE.split(parts[0], maxsplit=1)
    if len(halves) == 2:
        lo, hi = _endpoint(halves[0]), _endpoint(halves[1])
        return None if lo is None or hi is None else (lo, hi)
    only = _endpoint(parts[0])
    return None if only is None else (only, only)


def _endpoint(expr: str) -> Optional[float]:
    """One endpoint, tolerating the rank count the wiki appends to it (RM-220).

    Order matters and is the whole safety argument: the arithmetic walk runs
    FIRST, so a settled expression like ``100*12+100*3`` is never reinterpreted.
    The suffix strip only fires on input that already failed to parse, and
    ``N M`` is never valid arithmetic, so it cannot reach a working parse.
    """
    s = (expr or "").strip()
    val = _arith(s)
    if val is not None:
        return val
    m = _RANK_COUNT_SUFFIX_RE.match(s)
    return _arith(m.group("expr")) if m else None


def _arith(expr: Optional[str]) -> Optional[float]:
    """Evaluate a literal arithmetic endpoint, or None (RM-218).

    Wiki endpoints are not always bare numbers: Alistar's Trample is
    ``{{ap|80/10 to 200/10}}`` (per-tick), Gangplank's R is
    ``{{ap|40*12+40*3 to 100*12+100*3}}``. Refusing those dropped the whole
    LABEL, which is why two champions parsed to no labels at all.

    This is a whitelist walk, not an evaluator: numeric literals and
    ``+ - * /`` only, so a name, call, attribute or power cannot be reached.
    Anything else returns None and the label goes on counting itself as a skip.
    """
    s = (expr or "").strip()
    if not s or not _ARITH_CHARS_RE.fullmatch(s):
        return None
    try:
        tree = ast.parse(s, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None
    return _arith_node(tree.body)


def _arith_node(node: ast.AST) -> Optional[float]:
    if isinstance(node, ast.Constant):
        return float(node.value) if isinstance(node.value, (int, float)) else None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        val = _arith_node(node.operand)
        if val is None:
            return None
        return val if isinstance(node.op, ast.UAdd) else -val
    if isinstance(node, ast.BinOp):
        left, right = _arith_node(node.left), _arith_node(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return None if right == 0 else left / right
    return None


def _st_blocks(wikitext: str) -> list[str]:
    """Return each ``{{st|...}}`` block body, brace-balanced."""
    out: list[str] = []
    text = resolve_wiki_vars(_strip_comments(wikitext or ""))
    for m in _ST_RE.finditer(text):
        i = m.end()
        depth = 1
        while i < len(text) and depth:
            if text.startswith("{{", i):
                depth += 1
                i += 2
            elif text.startswith("}}", i):
                depth -= 1
                i += 2
            else:
                i += 1
        out.append(text[m.end(): i - 2])
    return out


def parse_leveling_bases(wikitext: str) -> dict[str, tuple[float, float]]:
    """Map each labelled damage line to its BASE endpoints.

    ``{{st|Magic Damage|{{ap|75 to 255}} {{as|(+ 40% AP)}}}}`` -> the base is the
    value BEFORE the first ``{{as|`` wrapper. The ``{{as|}}`` wrappers hold the
    scaling terms, so cutting there is what keeps a ratio like
    ``{{ap|2 to 4}}% of maximum health`` from being read as the base.
    """
    out: dict[str, tuple[float, float]] = {}
    for block in _st_blocks(wikitext):
        parts = _top_level_parts(block)
        for i in range(0, len(parts) - 1, 2):
            label = _flatten_label(parts[i])
            head = re.split(
                r"\{\{\s*as\s*\|", parts[i + 1], maxsplit=1, flags=re.IGNORECASE
            )[0]
            pts = parse_endpoints(head.strip())
            if label and pts is not None:
                out.setdefault(label, pts)
    return out


def _top_level_parts(body: str) -> list[str]:
    """Split an ``{{st|}}`` body on its OWN pipes, ignoring nested templates.

    An ``{{st|}}`` block may carry several label/value pairs -
    ``{{st|Magic Damage Per Tick|{{ap|...}}|Total Magic Damage|{{ap|...}}}}`` -
    and reading only the first pair is what made RM-218 look like a vocabulary
    gap: the "missing" label was on the page all along, one pipe further in.
    """
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    i = 0
    while i < len(body):
        if body.startswith("{{", i):
            depth += 1
            buf.append("{{")
            i += 2
        elif body.startswith("}}", i):
            depth = max(0, depth - 1)
            buf.append("}}")
            i += 2
        elif body[i] == "|" and depth == 0:
            parts.append("".join(buf))
            buf = []
            i += 1
        else:
            buf.append(body[i])
            i += 1
    parts.append("".join(buf))
    return parts


def _flatten_label(raw: str) -> str:
    """``True Damage with {{ii|Death's Daughter}}`` -> the plain stored spelling."""
    s = raw or ""
    for _ in range(4):
        nxt = _LABEL_TEMPLATE_RE.sub(lambda m: m.group(1), s)
        if nxt == s:
            break
        s = nxt
    return re.sub(r"\s+", " ", s).strip()


def _floats(seq: Any) -> Optional[list[float]]:
    """Coerce a stored numeric array to floats, or None if it is not one."""
    if not isinstance(seq, (list, tuple)) or not seq:
        return None
    try:
        return [float(x) for x in seq]
    except (TypeError, ValueError):
        return None


def rank_series(
    vals: list[float], cooldown: Any = None
) -> tuple[list[float], Optional[dict[str, Any]]]:
    """Cut a concatenated per-level tail off a per-rank ``base`` series.

    Some stored ``base`` arrays are an N-entry rank series CONCATENATED with a
    per-level series, so ``vals[-1]`` is a level-scaled number rather than the
    max-rank base. Mordekaiser Q stores
    ``[80, 117.6, 155.3, 192.9, 230.6, 13.2, ... 45.0]`` - reading 45.0 as the
    rank-5 base makes this report cry 389% where the true delta is 4.6%, and
    those inflated rows are the loudest in the whole sweep, so the bug does not
    merely add noise, it actively mis-prioritises which champions to re-source.

    The tell is an INTERNAL DROP, not an end-to-end decrease: base damage never
    falls as rank rises, so the first index where the series decreases is where
    the foreign tail begins. End-to-end (``vals[-1] < vals[0]``) is NOT
    sufficient - measured on 16.14.1 it catches only 6 of the 11 concatenated
    arrays, missing Malzahar W, whose ranks run 17 to 39 and whose tail then
    climbs to 64.5.

    ``len(cooldown)`` deliberately does NOT drive the index. Measured on
    16.14.1 it is wrong three separate ways:
      - Aurelion Sol Q stores 4 base entries against 5 cooldowns, so
        ``vals[len(cooldown) - 1]`` raises IndexError and kills the sweep;
      - Sona Q/W, Nidalee Q, Karma W and Heimerdinger E store a rank-invariant
        1-entry cooldown, so ``vals[0]`` would report the RANK-1 value as the
        max-rank endpoint (Sona Q 190 read as 50) and manufacture 8 false rows;
      - Shen Q stores a legitimate 18-entry PER-LEVEL base (10 to 40 based on
        level) that carries no rank series at all and must not be cut.
    It is carried in the marker instead, as corroboration a human can eyeball.
    """
    for i in range(1, len(vals)):
        if vals[i] < vals[i - 1] - _TOL:
            cd = cooldown if isinstance(cooldown, (list, tuple)) else None
            return vals[:i], {
                "reason": "concatenated_per_level_tail",
                "kept_ranks": i,
                "stored_len": len(vals),
                "cooldown_ranks": len(cd) if cd else None,
                "dropped_tail": [round(v, 4) for v in vals[i:]],
            }
    return vals, None


def meraki_endpoints(entry: dict[str, Any]) -> dict[str, Any]:
    """Endpoints for one Meraki ability form: cooldown plus each based block.

    ``base`` arrays pass through ``rank_series`` first, so a concatenated
    per-level tail cannot masquerade as the max-rank value. Cooldown arrays
    deliberately do NOT: a per-level passive cooldown legitimately DECREASES
    (Maokai's Sap Magic runs 30 at level 1 down to 20 at level 18), so applying
    the drop rule there would truncate real data.
    """
    cooldown = entry.get("cooldown")

    def _ends(seq: Any) -> Optional[tuple[float, float]]:
        vals = _floats(seq)
        if vals is None:
            return None
        return (vals[0], vals[-1])

    bases: dict[str, tuple[float, float]] = {}
    suspect: dict[str, dict[str, Any]] = {}
    for blk in entry.get("damage_blocks") or []:
        if not isinstance(blk, dict):
            continue
        attr = blk.get("attribute")
        vals = _floats(blk.get("base"))
        if not attr or vals is None:
            continue
        attr = str(attr)
        if attr in bases:
            continue
        kept, marker = rank_series(vals, cooldown)
        bases[attr] = (kept[0], kept[-1])
        if marker:
            suspect[attr] = marker
    return {"cooldown": _ends(cooldown), "bases": bases, "shape_suspect": suspect}


def _differs(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return abs(a[0] - b[0]) > _TOL or abs(a[1] - b[1]) > _TOL


def compare_ability(
    champion: str,
    slot: str,
    entry: dict[str, Any],
    wikitext: str,
    skipped_labels: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Compare one stored ability form against its live wiki Data page.

    A stored damage label with no counterpart on the live page cannot be
    compared - the wiki relabels damage lines on reworks. That is not an error
    and the sweep keeps going, but it is LOST COVERAGE, so pass
    ``skipped_labels`` to have each miss appended rather than dropped (RM-216).

    A miss falls back to ``_LABEL_ALIASES`` exactly once, by whole-label lookup
    scoped to the champion (RM-220). When that fires, the row carries
    ``wiki_label`` naming the live label it was actually compared against, so an
    aliased finding is never mistaken for a verbatim one.
    """
    findings: list[dict[str, Any]] = []
    mine = meraki_endpoints(entry)

    wiki_cd = parse_endpoints(parse_param(wikitext, "cooldown"))
    if mine["cooldown"] and wiki_cd and _differs(mine["cooldown"], wiki_cd):
        findings.append(
            {
                "champion": champion,
                "ability": slot,
                "name": entry.get("name"),
                "field": "cooldown",
                "meraki": list(mine["cooldown"]),
                "wiki": list(wiki_cd),
            }
        )

    wiki_bases = parse_leveling_bases(wikitext)
    suspect = mine.get("shape_suspect") or {}
    for attr, pts in mine["bases"].items():
        live = wiki_bases.get(attr)
        alias = None
        if not live:
            alias = _LABEL_ALIASES.get((champion, attr))
            live = wiki_bases.get(alias) if alias else None
            if not live:
                alias = None
        if not live:
            if skipped_labels is not None:
                skipped_labels.append(
                    {
                        "champion": champion,
                        "ability": slot,
                        "name": entry.get("name"),
                        "label": attr,
                        "reason": "label absent from live wiki page",
                        "wiki_labels": sorted(wiki_bases),
                    }
                )
            continue
        if _differs(pts, live):
            row = {
                "champion": champion,
                "ability": slot,
                "name": entry.get("name"),
                "field": "base:" + attr,
                "meraki": list(pts),
                "wiki": list(live),
            }
            if alias:
                # An alias is a JUDGEMENT, not a measurement, so the row names
                # the live label it was compared against and a reader can
                # re-check it without re-deriving the table.
                row["wiki_label"] = alias
            if attr in suspect:
                row["SHAPE_SUSPECT"] = suspect[attr]
            findings.append(row)
    return findings


def compare_champion(
    champion: str,
    meraki_champ: dict[str, Any],
    wiki_by_name: dict[str, str],
    skipped_pages: Optional[list[dict[str, Any]]] = None,
    skipped_labels: Optional[list[dict[str, Any]]] = None,
    stems: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Compare every stored ability of one champion, matched by ability NAME.

    The match is by name, so a wiki page RENAME (ability renamed on a rework)
    leaves the stored ability with no page and nothing to compare. Pass
    ``skipped_pages`` to have that recorded instead of silently dropping the
    ability - and, when it is the champion's only one, the champion (RM-216).
    """
    findings: list[dict[str, Any]] = []
    for slot, forms in (meraki_champ or {}).items():
        if not isinstance(forms, list) or not forms:
            continue
        entry = forms[0]
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "")
        page = wiki_by_name.get(name)
        if not page:
            if skipped_pages is not None:
                skipped_pages.append(
                    {
                        "champion": champion,
                        "ability": slot,
                        "name": name,
                        "reason": "no live wiki page for this ability name",
                        "tried": list(stems or [champion]),
                    }
                )
            continue
        findings.extend(
            compare_ability(champion, slot, entry, page, skipped_labels=skipped_labels)
        )
    return findings


def champions_from_titles(titles: Iterable[str]) -> set[str]:
    """``Template:Data Master Yi/Alpha Strike`` -> ``{"Master Yi"}``."""
    out: set[str] = set()
    for t in titles or []:
        s = str(t)
        if not s.startswith(_TEMPLATE_PREFIX):
            continue
        rest = s[len(_TEMPLATE_PREFIX):]
        champ = rest.split("/", 1)[0].strip()
        if champ:
            out.add(champ)
    return out


# --------------------------------------------------------------------------- network

def fetch_recent_titles(days: int = 7, limit: int = 500) -> list[str]:
    """Template-namespace RecentChanges titles, newest first."""
    q = {
        "action": "query",
        "list": "recentchanges",
        "rcnamespace": "10",
        "rclimit": str(limit),
        "rcprop": "title|timestamp",
        "rctype": "edit|new",
        "format": "json",
    }
    if days:
        q["rcend"] = _iso_days_ago(days)
    doc = json.loads(_fetch(WIKI_API + "?" + urllib.parse.urlencode(q)))
    return [r.get("title", "") for r in doc.get("query", {}).get("recentchanges", [])]


def _iso_days_ago(days: int) -> str:
    now = datetime.now(timezone.utc).timestamp() - days * 86400
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_pages(titles: list[str]) -> dict[str, str]:
    """Batched ``action=query`` page fetch -> {title: wikitext}."""
    out: dict[str, str] = {}
    for i in range(0, len(titles), _MAX_TITLES_PER_BATCH):
        batch = titles[i: i + _MAX_TITLES_PER_BATCH]
        q = {
            "action": "query",
            "prop": "revisions",
            "rvslots": "main",
            "rvprop": "content",
            "titles": "|".join(batch),
            "format": "json",
        }
        doc = json.loads(_fetch(WIKI_API + "?" + urllib.parse.urlencode(q)))
        for page in (doc.get("query", {}).get("pages", {}) or {}).values():
            revs = page.get("revisions") or []
            if not revs:
                continue
            content = (revs[0].get("slots", {}).get("main", {}) or {}).get("*")
            if content:
                out[page.get("title", "")] = content
    return out


# --------------------------------------------------------------------------- driver

def _load_abilities(patch: str) -> dict[str, Any]:
    return json.loads(
        (DATA_DIR / patch / "champion_abilities.json").read_text(encoding="utf-8")
    )


def _load_champion_names(patch: str) -> dict[str, str]:
    """``{ddragon_key: display_name}`` from the same patch dir, or ``{}``.

    A missing or malformed bulk degrades to key-only titles rather than
    aborting the sweep - the names are an accuracy improvement, not a
    precondition.
    """
    try:
        doc = json.loads(
            (DATA_DIR / patch / "champions.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    for key, entry in (doc.get("data") or {}).items():
        name = (entry or {}).get("name")
        if name:
            out[str(key)] = str(name)
    return out


def wiki_title_stems(champion: str, names: dict[str, str]) -> list[str]:
    """Every spelling a champion's Data pages might be titled under (RM-219).

    `champion_abilities.json` is keyed by DDragon key (`MonkeyKing`) while the
    wiki titles by display name (`Wukong`), so the key alone found nothing for
    20 champions. Both are returned rather than the display name alone: the
    wiki also serves `Template:Data Nunu/...` for a champion whose display name
    is `Nunu & Willump`, so REPLACING the key would trade one silent miss for
    another. Order is key first, then display name, and duplicates collapse.
    """
    stems = [champion]
    display = names.get(champion)
    if display and display != champion:
        stems.append(display)
    return stems


def _titles_for(
    champion: str,
    champ_data: dict[str, Any],
    names: Optional[dict[str, str]] = None,
) -> list[str]:
    abilities = []
    for forms in (champ_data or {}).values():
        if isinstance(forms, list) and forms and isinstance(forms[0], dict):
            n = forms[0].get("name")
            if n:
                abilities.append(str(n))
    return [
        f"{_TEMPLATE_PREFIX}{stem}/{n}"
        for stem in wiki_title_stems(champion, names or {})
        for n in dict.fromkeys(abilities)
    ]


def run(patch: str, champions: Optional[set[str]] = None) -> dict[str, Any]:
    doc = _load_abilities(patch)
    data = doc.get("data", {})
    names = _load_champion_names(patch)
    targets = sorted(c for c in data if champions is None or c in champions)

    titles: list[str] = []
    for champ in targets:
        titles.extend(_titles_for(champ, data[champ], names))
    pages = fetch_pages(titles) if titles else {}

    findings: list[dict[str, Any]] = []
    skipped_pages: list[dict[str, Any]] = []
    skipped_labels: list[dict[str, Any]] = []
    for champ in targets:
        by_name = {}
        stems = wiki_title_stems(champ, names)
        for stem in stems:
            prefix = _TEMPLATE_PREFIX + stem + "/"
            for title, text in pages.items():
                if title.startswith(prefix):
                    by_name.setdefault(title[len(prefix):], text)
        findings.extend(
            compare_champion(
                champ, data[champ], by_name, stems=stems,
                skipped_pages=skipped_pages, skipped_labels=skipped_labels,
            )
        )

    stale = sorted({f["champion"] for f in findings})
    return {
        "_patch": patch,
        "_generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_meraki_content_patch": doc.get("meraki_content_patch"),
        "_source": "wiki.leagueoflegends.com Template:Data <Champion>/<Ability>",
        "_note": (
            "RM-81 staleness report. A row means the STORED Meraki value and the "
            "LIVE wiki value disagree at the first/last rank endpoint for the same "
            "labelled quantity. Conservative: unmatched damage labels are skipped, "
            "so this UNDER-reports. Absence of a champion is not proof of currency "
            "- if it was skipped rather than compared it is named in "
            "skipped_champions, so a shrinking stale set can be read as "
            "convergence or as lost coverage without a live wiki fetch (RM-216)."
        ),
        "_checked_champions": len(targets),
        "_pages_fetched": len(pages),
        "_skipped_pages": len(skipped_pages),
        "_skipped_labels": len(skipped_labels),
        "stale_champions": stale,
        "skipped_champions": _skipped_champions(skipped_pages, skipped_labels),
        "skipped_pages": skipped_pages,
        "skipped_labels": skipped_labels,
        "findings": findings,
    }


def _skipped_champions(*rows: Iterable[dict[str, Any]]) -> list[str]:
    out: set[str] = set()
    for group in rows:
        out.update(str(r.get("champion")) for r in group or [])
    return sorted(out)


def write_report(
    report: dict[str, Any],
    patch: str,
    checked: Optional[set[str]] = None,
) -> Path:
    """Atomically write the staleness report, merging when the run was PARTIAL.

    ``checked=None`` means a full sweep, which replaces the report wholesale.
    ``checked={...}`` means only those champions were re-examined, so prior
    findings for everyone else are carried forward - otherwise a ``--recent``
    pass over a handful of champions would erase what ``--full`` established and
    silently mark the rest of the roster current.
    """
    out = DATA_DIR / patch / REPORT_NAME
    merged = dict(report)
    if checked is not None and out.exists():
        try:
            prior = json.loads(out.read_text(encoding="utf-8"))
            kept = [
                f for f in (prior.get("findings") or [])
                if f.get("champion") not in checked
            ]
            merged["findings"] = kept + list(report.get("findings") or [])
            merged["stale_champions"] = sorted(
                {f["champion"] for f in merged["findings"]}
            )
            for key in ("skipped_pages", "skipped_labels"):
                carried = [
                    s for s in (prior.get(key) or [])
                    if s.get("champion") not in checked
                ]
                merged[key] = carried + list(report.get(key) or [])
            merged["_skipped_pages"] = len(merged["skipped_pages"])
            merged["_skipped_labels"] = len(merged["skipped_labels"])
            merged["skipped_champions"] = _skipped_champions(
                merged["skipped_pages"], merged["skipped_labels"]
            )
            merged["_mode"] = "recent+merged"
        except (OSError, ValueError, AttributeError, KeyError):
            merged = dict(report)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, indent=1), encoding="utf-8")
    tmp.replace(out)
    return out


def _current_patch() -> str:
    """Newest patch dir, ordered numerically.

    ``data/daemon_slayer/`` also holds non-version dirs (``laning_scenarios``),
    so filter to X.Y.Z and sort on the numeric tuple - a lexical sort would put
    ``16.9.1`` after ``16.14.1``.
    """
    versions = [p.name for p in DATA_DIR.iterdir() if p.is_dir() and _VERSION_RE.match(p.name)]
    if not versions:
        raise RuntimeError(f"no patch directories under {DATA_DIR}")
    return max(versions, key=lambda v: tuple(int(x) for x in v.split(".")))


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--full", action="store_true", help="sweep every champion")
    mode.add_argument(
        "--recent", action="store_true", help="only champions edited on the wiki"
    )
    ap.add_argument("--patch", default=None)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--write", action="store_true", help="write the report JSON")
    ap.add_argument("--json", action="store_true", help="print the full report")
    args = ap.parse_args(argv)

    patch = args.patch or _current_patch()
    champions = None
    if args.recent:
        champions = champions_from_titles(fetch_recent_titles(days=args.days))
        print(f"recent-changes candidates ({args.days}d): {len(champions)}")
        if not champions:
            print("no Data-template edits in window - nothing to re-check")
            return 0

    report = run(patch, champions)

    if args.write:
        print(f"wrote {write_report(report, patch, checked=champions)}")

    if args.json:
        print(json.dumps(report, indent=1))
    else:
        print(
            f"patch={report['_patch']} meraki={report['_meraki_content_patch']} "
            f"checked={report['_checked_champions']} "
            f"pages={report['_pages_fetched']} "
            f"stale={len(report['stale_champions'])} "
            f"findings={len(report['findings'])} "
            f"skipped_pages={report.get('_skipped_pages', 0)} "
            f"skipped_labels={report.get('_skipped_labels', 0)}"
        )
        for row in report.get("skipped_pages") or []:
            print(
                f"  SKIP-PAGE {row['champion']} {row['ability']} "
                f"'{row['name']}': {row['reason']}"
            )
        for row in report.get("skipped_labels") or []:
            print(
                f"  SKIP-LABEL {row['champion']} {row['ability']} "
                f"'{row['label']}': live labels {row['wiki_labels']}"
            )
        for champ in report["stale_champions"]:
            rows = [f for f in report["findings"] if f["champion"] == champ]
            detail = ", ".join(
                f"{r['ability']} {r['field']} {r['meraki']}->{r['wiki']}" for r in rows
            )
            print(f"  STALE {champ}: {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
