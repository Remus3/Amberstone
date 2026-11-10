#!/usr/bin/env python
# arch: B1 deterministic-coaching flip-readiness report over the det shadow log | section=tools | frozen=no
"""det_coach_shadow report - the flip-readiness agreement gate for the B1
deterministic-coaching flip (the Haiku-to-ZERO north star).

``dashboard/_deterministic_coaching.py`` REPLACES the coach's native (Haiku)
A/B/C choices with deterministic DS-matchup choices whenever the latter are
non-empty, and ``core/det_coach_shadow.py`` records BOTH surfaces per coarse
game state into ``data/det_coach_shadow.jsonl`` (the largest RC shadow log,
gitignored). Before that flip is turned ON the operator needs to know: at the
ticks where the deterministic chooser fires, what was Haiku ACTUALLY deciding,
and would the deterministic verdict agree with it. This is that READ-ONLY gate.

THE DE-BIAS (mirrors the cycle-53 / item-574 false-0% fix in
tools/hz_shadow_report.py - read that file's _NON_LANING_STATE_MARKERS /
classify_verdict conventions; this tool re-uses the same normalize-then-phrase
idea). The deterministic A-choice is ALWAYS a laning-TRADE verdict (source_tag
ds-matchup: "Trade now" / "Trade even" / "All in now" / "Back off"), while the
native A-choice is overwhelmingly a MACRO/objective call (wave-tempo,
objective-*, ward-timing, win-con, gank-threat ...). A naive label-match of
det-A vs native-A would therefore report a FALSE ~0% agreement because the two
sides usually sit in DIFFERENT decision DOMAINS - the same category error
cycle-53 caught when 20/20 dead-state "WAIT RESPAWN" ticks scored a false 0%.
So we FIRST classify each side into a coarse domain (trade / build / macro) and
score:

  * HEADLINE = DOMAIN ALIGNMENT RATE - over both-present rows, the fraction
    where the native A-choice domain equals the deterministic A-choice domain
    (~always "trade"). A LOW alignment rate is the do-not-flip-blind signal:
    flipping the ds-matchup laning chooser ON would, at non-aligned ticks,
    replace a Haiku macro/objective call with a laning verdict - a downgrade.
  * WITHIN-TRADE VERDICT AGREEMENT - only over rows where BOTH A-choices are
    domain "trade", coarse-verdict exact-match (trade / farm / all_in / hold /
    back_off). Cross-domain pairs are EXCLUDED and counted as domain_divergence,
    NOT disagreement (the de-bias - they never drag the within-trade denominator
    down).
  * BUILD overlap (secondary) - where native ALSO offered a build choice, does
    the det-C ds-build item name appear in any native build label (or vice
    versa).

READ-ONLY: no engine, no network, no write. Fail-soft - a missing / empty /
malformed log yields zeroed sections, never an exception: the log is read as
BYTES one line at a time and each line is decoded on its own, so a line that is
not UTF-8, not JSON, too deeply nested for the parser or torn by a concurrent
append is skipped alone (s144 true-audit: before, one bad byte anywhere raised
UnicodeDecodeError out of the whole report). A UTF-8 BOM and CRLF endings are
accepted.

BOUNDED MEMORY: the live log is the largest RC shadow log (110 MB / 60721 rows
measured 2026-11-06). build_report streams it and keeps only the fields the
report reads (``_slim``), never the whole text, a splitlines copy or the
callouts / lead_projection payloads (669 MB peak working set before).

USAGE
    python tools/det_coach_shadow_report.py            # human summary
    python tools/det_coach_shadow_report.py --json      # machine-readable JSON
    python tools/det_coach_shadow_report.py --path X     # alternate log path
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterator, Optional

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
DEFAULT_PATH = _DATA / "det_coach_shadow.jsonl"

# Flip-readiness thresholds (do-not-flip-blind defaults). A HOLD is returned
# unless BOTH clear over a meaningful sample - intentionally conservative, this
# is a gate not an authorization.
_MIN_DOMAIN_ALIGN = 0.50
_MIN_WITHIN_TRADE = 0.70
_MIN_TRADE_SAMPLE = 50


_BOM = b"\xef\xbb\xbf"


def iter_jsonl(path: Path) -> Iterator[dict]:
    """Yield each dict row of a jsonl file, streaming (fail-soft).

    Read as bytes, one line at a time; each line is decoded on its own, so a
    non-UTF-8 line, a malformed or torn line, a line too deeply nested for the
    JSON parser (RecursionError, not a ValueError) and a non-dict row are each
    skipped alone. A missing / unreadable file, or a read error part-way, ends
    the stream - never raised. A UTF-8 BOM on the first line is dropped."""
    try:
        fh = Path(path).open("rb")  # noqa: SIM115 - closed in the finally below
    except (OSError, ValueError):  # ValueError: an embedded NUL in the path
        return
    try:
        first = True
        while True:
            try:
                raw = fh.readline()
            except OSError:
                return
            if not raw:
                return
            if first:
                first = False
                raw = raw.removeprefix(_BOM)
            try:
                line = raw.decode("utf-8").strip()
            except UnicodeDecodeError:
                continue
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if isinstance(rec, dict):
                yield rec
    finally:
        fh.close()


def load_jsonl(path: Path) -> list[dict]:
    """Read a jsonl file into a list of FULL dict rows (fail-soft to []).

    The same line rules as ``iter_jsonl``. build_report does not use this (it
    streams and slims); it stays for callers that want whole rows."""
    return list(iter_jsonl(path))


# The only row fields the report reads, and the only choice fields.
_ROW_FIELDS: tuple[str, ...] = (
    "mode", "replaced", "engine_version", "my_champion",
)
_CHOICE_FIELDS: tuple[str, ...] = ("key", "source_tag", "label")


def _slim_choices(choices):
    """A choice list reduced to the fields the report reads.

    Positions are kept (a non-dict element becomes None) so the A-choice
    fallback to element 0 is unchanged; a non-list becomes None, which is
    never both-present either way."""
    if not isinstance(choices, list):
        return None
    return [
        {k: ch[k] for k in _CHOICE_FIELDS if k in ch}
        if isinstance(ch, dict) else None
        for ch in choices
    ]


def _slim(rec: dict) -> dict:
    """A row reduced to what every summarize_* / coverage block reads; the
    report over slim rows equals the report over full rows (pinned by test)."""
    out = {k: rec[k] for k in _ROW_FIELDS if k in rec}
    out["det_choices"] = _slim_choices(rec.get("det_choices"))
    out["native_choices"] = _slim_choices(rec.get("native_choices"))
    return out


def _normalize_text(text: str) -> str:
    """Lowercase + map every non-alphanumeric char to a space + collapse runs,
    so "All-in!" and "ALL IN" both normalize to "all in"."""
    chars = [ch if ch.isalnum() else " " for ch in text.lower()]
    return " ".join("".join(chars).split())


def _has_word_start(norm: str, phrase: str) -> bool:
    """True when ``phrase`` occurs in normalized text starting at a WORD START.

    A keyword never matches mid-word ("rush" is not in "brush", "even" is not
    in "seven", "cs" is not in "tactics", "hold" is not in "threshold"), but a
    longer word still matches ("trades", "items", "buying")."""
    return (" " + phrase) in (" " + norm)


# Domain classification, keyed PRIMARILY off source_tag (empirically grounded
# against the live 22k-row log, NOT guessed). The first matching rule wins.
#   trade  - the laning-combat verdict axis (det-A is always here)
#   build  - the itemization axis (det-C ds-build; native item-* tags)
#   macro  - everything else non-empty (objective / wave / gank / ward / vision
#            / win-con / end-game / team / camp / rotate / jungle ...)
_TRADE_TAGS: frozenset = frozenset(
    {"ds-matchup", "lane-state", "lane-safety", "greedy-poke", "greed-pick"}
)
# build is matched by exact membership OR an "item" substring in the tag.
_BUILD_TAGS: frozenset = frozenset({"ds-build", "earlybuy"})

# Small label-keyword fallback, used ONLY when source_tag is missing/blank.
# Build keywords are checked first, then trade; each matches at a word start
# only (_has_word_start), never mid-word.
_LABEL_TRADE_KW: tuple[str, ...] = (
    "trade", "all in", "allin", "poke", "harass", "back off", "back away",
    "fall back", "play safe", "freeze", "farm safe",
)
_LABEL_BUILD_KW: tuple[str, ...] = ("buy", "rush", "build", "item")


def classify_domain(source_tag, label=None) -> Optional[str]:
    """Map a choice's source_tag (primary) and label (fallback) to one coarse
    domain: "trade" / "build" / "macro" - or None when both are blank /
    unclassifiable.

    source_tag is authoritative when present: a known trade tag, a known build
    tag (or any tag containing "item"), else any other non-empty tag is "macro".
    Only when source_tag is missing/blank do we fall back to label keywords; a
    label with no keyword and no tag is None."""
    tag = source_tag if isinstance(source_tag, str) else ""
    tag_norm = _normalize_text(tag) if tag else ""
    if tag_norm:
        if tag in _TRADE_TAGS:
            return "trade"
        if tag in _BUILD_TAGS or "item" in tag.lower():
            return "build"
        return "macro"
    # source_tag missing/blank - small label-keyword fallback only.
    if not label or not isinstance(label, str):
        return None
    norm = _normalize_text(label)
    if not norm:
        return None
    if any(_has_word_start(norm, kw) for kw in _LABEL_BUILD_KW):
        return "build"
    if any(_has_word_start(norm, kw) for kw in _LABEL_TRADE_KW):
        return "trade"
    return None


# Coarse trade-verdict table - multi-word phrases FIRST, then single tokens,
# the more-specific ahead of any token they contain, so "back off" never reads
# as "all in" and "farm" stays farm. First hit wins; each phrase matches at a
# word start only (_has_word_start).
# Mirrors hz_shadow_report._VERDICT_PHRASES intent on the det label vocabulary
# ("Trade now"/"Trade even"/"All in now"/"Back off").
_VERDICT_PHRASES: tuple[tuple[str, str], ...] = (
    ("back off", "back_off"),
    ("back away", "back_off"),
    ("fall back", "back_off"),
    ("play safe", "back_off"),
    ("disengage", "back_off"),
    ("all in", "all_in"),
    ("allin", "all_in"),
    ("commit", "all_in"),
    # "even" before "trade": the det "Trade even" label is a no-pressure even
    # matchup (reads as hold), so the more-specific "even" token wins; a plain
    # "Trade now" has no "even" token and still maps to trade.
    ("even", "hold"),
    ("trade", "trade"),
    ("poke", "trade"),
    ("harass", "trade"),
    ("farm", "farm"),
    ("cs", "farm"),
    ("freeze", "farm"),
    ("hold", "hold"),
    ("wait", "hold"),
)


def classify_trade_verdict(text) -> Optional[str]:
    """Map a trade-domain label to one coarse verdict: "trade" / "farm" /
    "all_in" / "hold" / "back_off" - or None when no keyword hits.

    Note the det "Trade even" label maps to ``hold`` via the "even" phrase
    (an even matchup is a no-pressure hold), matching the hz convention that an
    even verdict reads as hold."""
    if not text or not isinstance(text, str):
        return None
    norm = _normalize_text(text)
    if not norm:
        return None
    for phrase, verdict in _VERDICT_PHRASES:
        if _has_word_start(norm, phrase):
            return verdict
    return None


def _first_choice(choices) -> Optional[dict]:
    """The recommended (A) choice dict from a choice list, or None.

    Prefers an explicit key == "A"; falls back to the first dict so a list
    that omits the key still yields its lead choice."""
    if not isinstance(choices, list) or not choices:
        return None
    for ch in choices:
        if isinstance(ch, dict) and ch.get("key") == "A":
            return ch
    first = choices[0]
    return first if isinstance(first, dict) else None


def _choice_domain(choice: Optional[dict]) -> Optional[str]:
    """Domain of a single choice dict (source_tag primary, label fallback)."""
    if not isinstance(choice, dict):
        return None
    return classify_domain(choice.get("source_tag"), choice.get("label"))


def _det_build_choice(choices) -> Optional[dict]:
    """The deterministic build choice - the C-key choice if present, else any
    choice whose domain classifies to "build"."""
    if not isinstance(choices, list):
        return None
    for ch in choices:
        if isinstance(ch, dict) and ch.get("key") == "C":
            return ch
    for ch in choices:
        if isinstance(ch, dict) and _choice_domain(ch) == "build":
            return ch
    return None


# Generic build-prose words to drop before item-name overlap matching, so a
# bare "buy"/"base"/"rush" never counts as an item-name hit.
_BUILD_STOPWORDS: frozenset = frozenset({
    "buy", "the", "of", "base", "now", "rush", "build", "next", "item",
    "boots", "upgrade", "a", "to", "and", "re", "route", "back", "soon",
})


def _item_tokens(label) -> set[str]:
    """Distinct >=4-char alphabetic tokens from a build label minus generic
    build-prose stopwords - the coarse item-name fingerprint used for overlap.

    "Buy Blade of The Ruined King" -> {blade, ruined, king}; a hit on any one
    token is treated as an item-name overlap."""
    if not label or not isinstance(label, str):
        return set()
    norm = _normalize_text(label)
    return {
        tok for tok in norm.split()
        if len(tok) >= 4 and tok.isalpha() and tok not in _BUILD_STOPWORDS
    }


def _native_build_labels(choices) -> list[str]:
    """Every native choice label whose domain classifies to "build"."""
    if not isinstance(choices, list):
        return []
    out: list[str] = []
    for ch in choices:
        if isinstance(ch, dict) and _choice_domain(ch) == "build":
            lbl = ch.get("label")
            if lbl:
                out.append(str(lbl))
    return out


def _has_choice(choices) -> bool:
    """A choice LIST holding at least one choice dict. A truthy non-list ("x",
    a bare dict) or a list of non-dicts cannot be compared, so it is not a
    present surface (s144 true-audit: it used to sit in every denominator)."""
    return isinstance(choices, list) and any(
        isinstance(ch, dict) for ch in choices
    )


def _both_present(rec: dict) -> bool:
    """True when the record carries BOTH det_choices and native_choices - the
    only rows where the deterministic surface can be compared to Haiku."""
    return _has_choice(rec.get("det_choices")) and _has_choice(
        rec.get("native_choices")
    )


def _coverage_block(records: list[dict]) -> dict:
    """Total / replaced / both-present + by-mode + top-15 per-champion both-
    present + engine-version distribution. ``replaced`` counts only a real
    ``True`` (the writer stores a bool; a string "false" is not a replace)."""
    total = len(records)
    replaced = sum(1 for r in records if r.get("replaced") is True)
    both = sum(1 for r in records if _both_present(r))
    by_mode: dict[str, dict] = {}
    by_champ_both: Counter = Counter()
    engine: Counter = Counter()
    for r in records:
        mode = str(r.get("mode") or "?")
        slot = by_mode.setdefault(mode, {"total": 0, "both": 0})
        slot["total"] += 1
        engine[str(r.get("engine_version") or "?")] += 1
        if _both_present(r):
            slot["both"] += 1
            by_champ_both[str(r.get("my_champion") or "?")] += 1
    return {
        "total": total,
        "replaced": replaced,
        "both_present": both,
        "by_mode": dict(sorted(by_mode.items())),
        "by_champion_both_top15": dict(by_champ_both.most_common(15)),
        "by_engine_version": dict(sorted(engine.items())),
    }


def summarize_domain_alignment(records: list[dict]) -> dict:
    """HEADLINE - native-A-domain vs det-A-domain alignment over both-present
    rows, plus the native-A-domain distribution (how often Haiku was doing
    macro vs trade vs build) and the det-A-domain distribution."""
    both = 0
    aligned = 0
    native_domain: Counter = Counter()
    det_domain: Counter = Counter()
    unclassified_native = 0
    for rec in records:
        if not _both_present(rec):
            continue
        both += 1
        det_dom = _choice_domain(_first_choice(rec.get("det_choices")))
        nat_dom = _choice_domain(_first_choice(rec.get("native_choices")))
        det_domain[det_dom or "none"] += 1
        if nat_dom is None:
            unclassified_native += 1
            native_domain["none"] += 1
            continue
        native_domain[nat_dom] += 1
        if det_dom is not None and nat_dom == det_dom:
            aligned += 1
    return {
        "both_present": both,
        "aligned": aligned,
        "alignment_rate": round(aligned / both, 4) if both else 0.0,
        "native_domain_dist": dict(native_domain.most_common()),
        "det_domain_dist": dict(det_domain.most_common()),
        "unclassified_native_a": unclassified_native,
    }


def summarize_within_trade(records: list[dict]) -> dict:
    """WITHIN-TRADE verdict agreement - only over both-present rows where BOTH
    A-choices are domain "trade". Cross-domain pairs are EXCLUDED and counted as
    domain_divergence (the de-bias - they never enter the agreement
    denominator). unclassified = a trade-vs-trade pair where a label would not
    classify to a coarse verdict."""
    comparable = 0
    agree = 0
    domain_divergence = 0
    unclassified = 0
    by_det: Counter = Counter()
    confusion: dict[tuple[str, str], int] = {}
    for rec in records:
        if not _both_present(rec):
            continue
        det_ch = _first_choice(rec.get("det_choices"))
        nat_ch = _first_choice(rec.get("native_choices"))
        det_dom = _choice_domain(det_ch)
        nat_dom = _choice_domain(nat_ch)
        if det_dom != "trade" or nat_dom != "trade":
            domain_divergence += 1
            continue
        det_v = classify_trade_verdict(det_ch.get("label") if det_ch else None)
        nat_v = classify_trade_verdict(nat_ch.get("label") if nat_ch else None)
        if det_v is None or nat_v is None:
            unclassified += 1
            continue
        comparable += 1
        agreed = det_v == nat_v
        if agreed:
            agree += 1
        by_det[det_v] += 1
        confusion[(det_v, nat_v)] = confusion.get((det_v, nat_v), 0) + 1
    return {
        "comparable": comparable,
        "agree": agree,
        "agreement_rate": round(agree / comparable, 4) if comparable else 0.0,
        "domain_divergence": domain_divergence,
        "unclassified": unclassified,
        "by_det_verdict": dict(by_det.most_common()),
        "confusion": [
            {"det": dv, "native": nv, "n": n, "agree": dv == nv}
            for (dv, nv), n in sorted(
                confusion.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ],
    }


def summarize_build_overlap(records: list[dict]) -> dict:
    """BUILD-domain overlap (secondary) - over both-present rows where native
    ALSO offered a build choice, does the det-C ds-build item name appear in any
    native build label (or vice versa). Coarse item-token overlap, counts only.

    comparable = rows with a det build choice AND >=1 native build label;
    overlap = those whose item-token sets intersect."""
    comparable = 0
    overlap = 0
    det_build_rows = 0
    native_build_rows = 0
    for rec in records:
        if not _both_present(rec):
            continue
        det_build = _det_build_choice(rec.get("det_choices"))
        nat_labels = _native_build_labels(rec.get("native_choices"))
        if det_build is not None:
            det_build_rows += 1
        if nat_labels:
            native_build_rows += 1
        if det_build is None or not nat_labels:
            continue
        comparable += 1
        det_toks = _item_tokens(det_build.get("label"))
        nat_toks: set[str] = set()
        for lbl in nat_labels:
            nat_toks |= _item_tokens(lbl)
        if det_toks and (det_toks & nat_toks):
            overlap += 1
    return {
        "comparable": comparable,
        "overlap": overlap,
        "overlap_rate": round(overlap / comparable, 4) if comparable else 0.0,
        "det_build_rows": det_build_rows,
        "native_build_rows": native_build_rows,
    }


def _flip_hint(coverage: dict, alignment: dict, within_trade: dict) -> str:
    """A coarse human read of flip-readiness. NOT a flip authorization - the
    operator decides; this only flags the obvious not-ready states. Default is
    HOLD (do-not-flip-blind): a GO needs domain alignment >= the floor AND
    within-trade agreement >= the floor over a meaningful trade sample."""
    both = coverage.get("both_present", 0)
    if both == 0:
        return "HOLD - no both-present rows yet; play real games to accrue data"
    align = alignment.get("alignment_rate", 0.0)
    wt_rate = within_trade.get("agreement_rate", 0.0)
    wt_n = within_trade.get("comparable", 0)
    if align < _MIN_DOMAIN_ALIGN:
        return (
            f"HOLD - domain alignment {align:.0%} < {_MIN_DOMAIN_ALIGN:.0%}; "
            "Haiku is mostly making macro/objective calls at these ticks, so "
            "flipping the laning chooser ON would downgrade them"
        )
    if wt_n < _MIN_TRADE_SAMPLE:
        return (
            f"HOLD - only {wt_n} trade-vs-trade rows (< {_MIN_TRADE_SAMPLE}); "
            "within-trade agreement sample too small to judge"
        )
    if wt_rate < _MIN_WITHIN_TRADE:
        return (
            f"HOLD - within-trade agreement {wt_rate:.0%} < "
            f"{_MIN_WITHIN_TRADE:.0%} over {wt_n} rows; verdicts diverge too "
            "often to flip blind"
        )
    return (
        f"REVIEW - domain alignment {align:.0%} and within-trade agreement "
        f"{wt_rate:.0%} over {wt_n} rows both clear the floor; operator gate "
        "before any flip"
    )


def build_report(path: Path) -> dict:
    """Assemble the full det_coach_shadow report dict from the log path.

    Streams the log and keeps slim rows only (bounded memory, see module
    docstring); the result equals the summarize_* functions over full rows."""
    records = [_slim(rec) for rec in iter_jsonl(path)]
    coverage = _coverage_block(records)
    alignment = summarize_domain_alignment(records)
    within_trade = summarize_within_trade(records)
    build_overlap = summarize_build_overlap(records)
    return {
        "schema": "det_coach_shadow_report/v1",
        "coverage": coverage,
        "domain_alignment": alignment,
        "within_trade": within_trade,
        "build_overlap": build_overlap,
        "flip_ready_hint": _flip_hint(coverage, alignment, within_trade),
    }


def _out(text: str) -> None:
    """Print one human-summary line as ASCII.

    Mode / champion / engine strings
    come from the log, and a valid JSON row can carry a lone surrogate or a
    character the console code page lacks; either raised UnicodeEncodeError
    out of main (s144 true-audit). Non-ASCII is backslash-escaped instead.
    (--json output is ASCII already: json.dumps escapes it.)"""
    print(text.encode("ascii", "backslashreplace").decode("ascii"))


def _print_human(report: dict) -> None:
    cov = report.get("coverage") or {}
    al = report.get("domain_alignment") or {}
    wt = report.get("within_trade") or {}
    bo = report.get("build_overlap") or {}
    _out(
        f"[coverage] total={cov.get('total', 0)} "
        f"replaced={cov.get('replaced', 0)} "
        f"both_present={cov.get('both_present', 0)}"
    )
    if cov.get("by_mode"):
        modes = ", ".join(
            f"{m}: {s.get('both', 0)}/{s.get('total', 0)}"
            for m, s in cov["by_mode"].items()
        )
        _out(f"    by-mode (both/total): {modes}")
    if cov.get("by_engine_version"):
        eng = ", ".join(
            f"{v} x{n}" for v, n in cov["by_engine_version"].items()
        )
        _out(f"    engine: {eng}")
    if cov.get("by_champion_both_top15"):
        _out("    top champions (both-present):")
        for champ, n in cov["by_champion_both_top15"].items():
            _out(f"        {champ} x{n}")
    _out(
        f"[domain-alignment] {al.get('aligned', 0)}/"
        f"{al.get('both_present', 0)} aligned "
        f"(rate {al.get('alignment_rate', 0.0)})"
    )
    if al.get("native_domain_dist"):
        nd = ", ".join(
            f"{k} x{v}" for k, v in al["native_domain_dist"].items()
        )
        _out(f"    native-A domain: {nd}")
    if al.get("det_domain_dist"):
        dd = ", ".join(f"{k} x{v}" for k, v in al["det_domain_dist"].items())
        _out(f"    det-A domain: {dd}")
    _out(
        f"[within-trade] {wt.get('agree', 0)}/{wt.get('comparable', 0)} agree "
        f"(rate {wt.get('agreement_rate', 0.0)}), "
        f"{wt.get('domain_divergence', 0)} domain-divergence (excluded), "
        f"{wt.get('unclassified', 0)} unclassified"
    )
    mism = [c for c in (wt.get("confusion") or []) if not c["agree"]]
    for c in mism[:6]:
        _out(
            f"    MISMATCH det={c['det']} -> native={c['native']} x{c['n']}"
        )
    _out(
        f"[build-overlap] {bo.get('overlap', 0)}/{bo.get('comparable', 0)} "
        f"item-name overlap (rate {bo.get('overlap_rate', 0.0)}), "
        f"det_build_rows={bo.get('det_build_rows', 0)}, "
        f"native_build_rows={bo.get('native_build_rows', 0)}"
    )
    _out(f"hint: {report.get('flip_ready_hint')}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--path", default=str(DEFAULT_PATH))
    ap.add_argument(
        "--json", action="store_true", help="emit JSON not a summary"
    )
    args = ap.parse_args(argv)
    report = build_report(Path(args.path))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
