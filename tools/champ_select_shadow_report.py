#!/usr/bin/env python
# arch: champ-select pick-advisor shadow agreement report (flip-readiness gate) | section=tools | frozen=no
"""Champ-select shadow-validation report - the flip-readiness gate for the last
champ-select Haiku call (coaches/champ_select_coach.coach_pick).

core.champ_select_shadow (-> data/champ_select_shadow.jsonl) records, once per
distinct pick state, BOTH sides side by side WITHOUT changing any live output:
the ``native`` block (what live Haiku actually said) and the ``deterministic``
block (what core.champ_select_advisor_deterministic.advise_pick WOULD have
said), each carrying the same four advice fields advice / swap / summoners /
watchout, alongside the pick state itself (my_champion / my_team / their_team /
bench / queue_id / is_aram / engine_version).

Before the pick advisor is flipped off Haiku, the operator needs an honest
per-field read of how often the two sides already agree. This is the ARAM /
Arena sibling of tools/aram_shadow_report.py + tools/arena_shadow_report.py and
measures four columns, each with its OWN comparability rule so an empty side is
never scored as a disagreement:

  * summoners - exact spell-pair SET equality. Both sides are parsed into a set
    of canonical spell tokens ("Flash + Heal" and "Heal and Flash" are the same
    set), so ordering and separator style never manufacture a mismatch. A row is
    comparable only when BOTH sides parse to a non-empty set. Free prose that
    names a third spell ("Flash + Ignite over Heal") parses to three tokens and
    will read as a mismatch - an honest, visible limitation, not a silent one.

  * watchout - champion-name OVERLAP scored against the record's own
    ``their_team``. Each side's free text is scanned for the enemy names that
    record actually carries, so the two sides are compared on WHO they named,
    never on phrasing. A row is comparable only when the roster is non-empty and
    both sides name at least one enemy.

  * swap - SWAP / KEEP classification plus the target champion resolved off the
    record's ``bench``. ARAM-GATED: the bench only exists in ARAM, so non-ARAM
    rows carry no swap decision at all and are routed to ``gated_out_non_aram``
    instead of being scored as agreement. Both sides silent = a real KEEP/KEEP
    agreement, so every ARAM row is comparable.

  * advice - ordered keyword-class agreement (variant / swap / dodge / keep /
    pick / ban) over the one-line headline, plus the per-field ``field_presence``
    silent-gap diagnostic that aram_shadow_report carries. advice is the HEADLINE
    axis: it is the coarse pick verdict, so it drives ``state``.

DEGRADED-STATE EXCLUSION - the Haiku path emits user-facing placeholders that
are not advice at all: "(no champion locked yet)", "(champ-select coach
disabled)", "(API key missing - coach disabled)", "(coaching paused -
retrying)". Scoring those against a real deterministic recommendation floods the
gate with false rows - the same lesson aram_shadow_report learned from its
cycle-53 "WAIT RESPAWN" false-0%. Authority is the NATIVE advice string (the
deterministic side is never degraded), and degraded rows are excluded from every
summary and counted once in coverage.

MIN_SAMPLE gate - below MIN_SAMPLE comparable ADVICE rows the state reads
"awaiting_accrual"; at or above it the advice agreement rate is compared against
FLIP_GATE for a "ready" / "not_ready" read. That is NOT a flip authorization -
the operator decides; this only flags the obvious not-ready states.

This is a READ-ONLY report (no engine, no network, no write). Fail-soft: a
missing / empty / malformed log, a record missing either side, or a non-dict
record all yield a zeroed section, never an exception.

USAGE
    python tools/champ_select_shadow_report.py            # human summary
    python tools/champ_select_shadow_report.py --json     # machine-readable
    python tools/champ_select_shadow_report.py --path X --min-sample N
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = _ROOT / "data" / "champ_select_shadow.jsonl"

# Byte-identical to core.champ_select_shadow._ADVICE_KEYS - the four advice
# fields both sides of every record carry. Duplicated rather than imported so
# this report stays a standalone read-only tool with no core import.
_FIELDS: tuple[str, ...] = ("advice", "swap", "summoners", "watchout")

# Agreement floor a field must clear before a flip is even discussable - the
# same 70% bar tools/aram_shadow_report.py uses.
FLIP_GATE = 0.70

# Champ-select POSTs are deduped per distinct pick state, so one game yields a
# handful of rows at most; the floor mirrors arena_shadow_report.MIN_SAMPLE.
MIN_SAMPLE = 20


def load_jsonl(path) -> list[dict]:
    """Read a jsonl file into a list of dicts (fail-soft to []).

    A missing file, an unreadable path, or any malformed / non-dict LINE is
    skipped, never raised - the same robustness core.champ_select_shadow itself
    promises. json decodes unicode transparently, so Haiku free-text glyphs in
    the live log load fine even though this tool's own source stays 7-bit
    ASCII."""
    out: list[dict] = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


# ---------------------------------------------------------------- primitives


def _norm(text) -> str:
    """Lowercase + map every non-alphanumeric char to a space + collapse runs,
    so "Kai'Sa", "KAI SA" and "kai-sa" all normalize to "kai sa"."""
    if not isinstance(text, str):
        return ""
    chars = [ch if ch.isalnum() else " " for ch in text.lower()]
    return " ".join("".join(chars).split())


def _has_phrase(norm: str, phrase: str) -> bool:
    """Token-boundary containment. Padding both sides with a space is what keeps
    "ban" out of "banner" and "lock" out of "locked" - a raw substring test
    misclassifies those."""
    return f" {phrase} " in f" {norm} "


def _get(rec, key, default=None):
    """One top-level record field, tolerating a non-dict record."""
    if not isinstance(rec, dict):
        return default
    return rec.get(key, default)


def _side(rec, side: str) -> dict:
    """The native / deterministic sub-block, or {} when absent or malformed."""
    value = _get(rec, side)
    return value if isinstance(value, dict) else {}


def _field(rec, side: str, field: str):
    """One advice field off one side, or None when the side or field is absent."""
    return _side(rec, side).get(field)


def _roster(rec, key: str) -> list[str]:
    """A pick-state name list (their_team / bench) as clean strings, [] on any
    absent or malformed value."""
    raw = _get(rec, key)
    if not isinstance(raw, list):
        return []
    return [str(c).strip() for c in raw if c and str(c).strip()]


def _is_present(value) -> bool:
    """True when a field value is meaningfully populated. A blank / whitespace
    string, an empty list/dict, or None all read as absent."""
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    if value is None:
        return False
    return bool(value)


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _confusion(pairs: dict) -> list[dict]:
    """A (det, native) -> n tally as a sorted, JSON-safe list (most frequent
    first, then by key) - the same shape the ARAM / Arena reports emit."""
    return [
        {"deterministic": dv, "native": nv, "n": n, "agree": dv == nv}
        for (dv, nv), n in sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


# ------------------------------------------------------- degraded-state gate

# Native placeholders that are a coach STATE, not pick advice - every one is a
# literal from coaches/champ_select_coach.py (the "(no champion locked yet)" /
# "(champ-select coach disabled)" / "(API key missing - coach disabled)" /
# "(coaching paused - retrying)" strings). Normalized, token-boundary matched.
_DEGRADED_MARKERS: tuple[str, ...] = (
    "no champion locked",
    "coach disabled",
    "coaching disabled",
    "coaching paused",
    "api key missing",
)


def is_degraded(rec) -> bool:
    """True when this row is a degraded / placeholder coach state rather than a
    real pick recommendation, and must be routed OUT of every agreement sample.

    Authority is the NATIVE advice string - the deterministic advisor has no
    degraded mode (it returns the empty shape, which reads as absent, not as a
    placeholder), so a deterministic-side marker must never gate a row out."""
    norm = _norm(_field(rec, "native", "advice"))
    return any(_has_phrase(norm, m) for m in _DEGRADED_MARKERS)


def _scorable(records) -> list:
    """Every record that is not a degraded coach state."""
    return [rec for rec in records if not is_degraded(rec)]


# ------------------------------------------------------ column 1: summoners

# Canonical summoner-spell vocabulary. Keys are the tokens either side may
# write, values the canonical name a set is built from - Snowball and Mark are
# the same ARAM spell under two names, TP is the universal Teleport shorthand.
_SPELL_ALIASES: dict[str, str] = {
    "flash": "flash",
    "heal": "heal",
    "barrier": "barrier",
    "ignite": "ignite",
    "exhaust": "exhaust",
    "ghost": "ghost",
    "cleanse": "cleanse",
    "teleport": "teleport",
    "tp": "teleport",
    "smite": "smite",
    "clarity": "clarity",
    "mark": "mark",
    "snowball": "mark",
}


def parse_summoners(text) -> frozenset:
    """Parse a summoner-spell line into a canonical spell SET.

    "Flash + Heal", "flash/ignite", "Heal and Flash" all reduce to a set, so
    ordering and separator style never manufacture a mismatch. Tokens outside
    the vocabulary are dropped; an empty result means the side is unparseable
    (excluded from the comparable sample rather than scored as a mismatch)."""
    norm = _norm(text)
    if not norm:
        return frozenset()
    return frozenset(
        _SPELL_ALIASES[tok] for tok in norm.split() if tok in _SPELL_ALIASES
    )


def _spell_label(spells: frozenset) -> str:
    return "+".join(sorted(spells)) if spells else "-"


def summarize_summoners(records) -> dict:
    """Native-vs-deterministic summoner agreement by exact spell-pair SET
    equality over the scorable sample. Comparable only when BOTH sides parse to
    a non-empty set; a one-sided parse is a coverage gap, not a disagreement."""
    comparable = agree = 0
    det_only = native_only = both_unparsed = 0
    pairs: dict[tuple[str, str], int] = {}
    for rec in _scorable(records):
        det = parse_summoners(_field(rec, "deterministic", "summoners"))
        native = parse_summoners(_field(rec, "native", "summoners"))
        if det and native:
            comparable += 1
            if det == native:
                agree += 1
            key = (_spell_label(det), _spell_label(native))
            pairs[key] = pairs.get(key, 0) + 1
        elif det and not native:
            det_only += 1
        elif native and not det:
            native_only += 1
        else:
            both_unparsed += 1
    return {
        "comparable": comparable,
        "agree": agree,
        "agreement_rate": _rate(agree, comparable),
        "det_only_parsed": det_only,
        "native_only_parsed": native_only,
        "both_unparsed": both_unparsed,
        "confusion": _confusion(pairs),
    }


# -------------------------------------------------------- column 2: watchout


def extract_watchout_names(text, roster) -> frozenset:
    """The set of ROSTER champions this free-text watchout line actually names.

    Both the text and each roster name go through the same normalizer, so
    "Kai'Sa" in the record matches "Kai'Sa will out-range you" and the
    multi-word "Lee Sin" matches as one token run. Scoring against the record's
    own their_team is what makes the two sides comparable on WHO they named
    rather than on phrasing."""
    norm = _norm(text)
    if not norm:
        return frozenset()
    named = set()
    for name in roster or []:
        key = _norm(name)
        if key and _has_phrase(norm, key):
            named.add(name)
    return frozenset(named)


def _name_label(names: frozenset) -> str:
    return "|".join(sorted(names)) if names else "-"


def summarize_watchout(records) -> dict:
    """Native-vs-deterministic watchout agreement by enemy-name overlap.

    A row is comparable only when the record carries a non-empty their_team AND
    both sides name at least one of those enemies. Rows with no roster at all
    are counted into ``no_roster`` and never scored (there is nothing to name)."""
    comparable = agree = 0
    det_only = native_only = both_unnamed = no_roster = 0
    pairs: dict[tuple[str, str], int] = {}
    for rec in _scorable(records):
        roster = _roster(rec, "their_team")
        if not roster:
            no_roster += 1
            continue
        det = extract_watchout_names(_field(rec, "deterministic", "watchout"), roster)
        native = extract_watchout_names(_field(rec, "native", "watchout"), roster)
        if det and native:
            comparable += 1
            if det == native:
                agree += 1
            key = (_name_label(det), _name_label(native))
            pairs[key] = pairs.get(key, 0) + 1
        elif det and not native:
            det_only += 1
        elif native and not det:
            native_only += 1
        else:
            both_unnamed += 1
    return {
        "comparable": comparable,
        "agree": agree,
        "agreement_rate": _rate(agree, comparable),
        "det_only_named": det_only,
        "native_only_named": native_only,
        "both_unnamed": both_unnamed,
        "no_roster": no_roster,
        "confusion": _confusion(pairs),
    }


# ------------------------------------------------------------ column 3: swap

# Phrases that mean "no bench swap". The deterministic side writes "" for keep
# and the Haiku path already maps a literal "none" to "", but Haiku prose can
# still arrive as "no swap needed" - normalize all of them to one KEEP verdict.
_SWAP_KEEP_MARKERS: tuple[str, ...] = (
    "none",
    "no swap",
    "no bench swap",
    "nothing",
    "keep",
    "stay",
    "n a",
)


def classify_swap(text, bench) -> tuple:
    """Classify one side's swap field into (class, target).

    ("KEEP", None) when the side is silent or says no-swap; ("SWAP", champion)
    when a bench champion is named; ("SWAP", None) when a swap is asserted but
    no bench name resolves - which is a real, visible disagreement against a
    concrete target, not a silent pass."""
    norm = _norm(text)
    if not norm:
        return ("KEEP", None)
    if any(_has_phrase(norm, m) for m in _SWAP_KEEP_MARKERS):
        return ("KEEP", None)
    for name in bench or []:
        key = _norm(name)
        if key and _has_phrase(norm, key):
            return ("SWAP", name)
    return ("SWAP", None)


def _swap_label(pair: tuple) -> str:
    cls, target = pair
    if cls != "SWAP":
        return cls
    return f"SWAP:{target}" if target else "SWAP:?"


def summarize_swap(records) -> dict:
    """Native-vs-deterministic bench-swap agreement over ARAM rows only.

    The bench exists only in ARAM, so a non-ARAM row carries no swap decision to
    compare and is routed to ``gated_out_non_aram`` rather than scored as a free
    KEEP/KEEP agreement (which would inflate the rate). Every ARAM row IS
    comparable - both sides silent is a genuine KEEP/KEEP agreement.
    ``class_agree`` scores the coarse SWAP-vs-KEEP call alone; ``target_agree``
    scores only the rows where both sides swap to the SAME named champion."""
    comparable = agree = class_agree = target_agree = 0
    gated_out = no_bench = 0
    by_class: dict[str, int] = {}
    pairs: dict[tuple[str, str], int] = {}
    for rec in _scorable(records):
        if not bool(_get(rec, "is_aram")):
            gated_out += 1
            continue
        bench = _roster(rec, "bench")
        if not bench:
            no_bench += 1
        det = classify_swap(_field(rec, "deterministic", "swap"), bench)
        native = classify_swap(_field(rec, "native", "swap"), bench)
        comparable += 1
        if det == native:
            agree += 1
        if det[0] == native[0]:
            class_agree += 1
        if det[0] == "SWAP" and det[1] and det[1] == native[1]:
            target_agree += 1
        by_class[det[0]] = by_class.get(det[0], 0) + 1
        key = (_swap_label(det), _swap_label(native))
        pairs[key] = pairs.get(key, 0) + 1
    return {
        "comparable": comparable,
        "agree": agree,
        "agreement_rate": _rate(agree, comparable),
        "class_agree": class_agree,
        "class_agreement_rate": _rate(class_agree, comparable),
        "target_agree": target_agree,
        "gated_out_non_aram": gated_out,
        "no_bench": no_bench,
        "by_deterministic_class": dict(sorted(by_class.items())),
        "confusion": _confusion(pairs),
    }


# ---------------------------------------------------------- column 4: advice

# Ordered pick-verdict table - multi-word phrases FIRST, then the single tokens
# with the more-specific ahead of anything they contain. "shift build" must beat
# "stay" because the deterministic variant line is literally "Stay <champ>,
# shift build - ..." (core.champ_select_advisor_deterministic) and its verdict is
# VARIANT, not keep. First phrase that hits wins - deterministic by construction.
_ADVICE_PHRASES: tuple[tuple[str, str], ...] = (
    ("shift build", "variant"),
    ("different build", "variant"),
    ("swap to", "swap"),
    ("bench swap", "swap"),
    ("swap", "swap"),
    ("dodge", "dodge"),
    ("stay", "keep"),
    ("keep", "keep"),
    ("lock in", "keep"),
    ("lock", "keep"),
    ("first pick", "pick"),
    ("pick", "pick"),
    ("ban", "ban"),
)


def classify_advice(text) -> Optional[str]:
    """Map a one-line pick headline (deterministic or Haiku prose) to one coarse
    verdict: "variant" / "swap" / "dodge" / "keep" / "pick" / "ban" - or None
    when no keyword hits or the text is a degraded coach placeholder."""
    norm = _norm(text)
    if not norm:
        return None
    if any(_has_phrase(norm, m) for m in _DEGRADED_MARKERS):
        return None
    for phrase, verdict in _ADVICE_PHRASES:
        if _has_phrase(norm, phrase):
            return verdict
    return None


def summarize_advice(records) -> dict:
    """HEADLINE axis - native-vs-deterministic pick-verdict agreement.

    Degraded rows are excluded first (counted into ``degraded_excluded``). A row
    is comparable only when BOTH headlines classify. ``det_only_classified`` is
    the flip-risk case inverted (the deterministic side spoke and Haiku did not);
    ``native_only_classified`` is the real flip risk - Haiku called a verdict the
    deterministic advisor has no answer for."""
    comparable = agree = 0
    det_only = native_only = both_unclassified = degraded = 0
    by_det: dict[str, int] = {}
    by_native: dict[str, dict] = {}
    pairs: dict[tuple[str, str], int] = {}
    for rec in records:
        if is_degraded(rec):
            degraded += 1
            continue
        dv = classify_advice(_field(rec, "deterministic", "advice"))
        nv = classify_advice(_field(rec, "native", "advice"))
        if dv is not None and nv is not None:
            comparable += 1
            agreed = dv == nv
            if agreed:
                agree += 1
            by_det[dv] = by_det.get(dv, 0) + 1
            slot = by_native.setdefault(nv, {"n": 0, "agree": 0})
            slot["n"] += 1
            if agreed:
                slot["agree"] += 1
            pairs[(dv, nv)] = pairs.get((dv, nv), 0) + 1
        elif dv is not None:
            det_only += 1
        elif nv is not None:
            native_only += 1
        else:
            both_unclassified += 1
    return {
        "comparable": comparable,
        "agree": agree,
        "agreement_rate": _rate(agree, comparable),
        "by_deterministic": dict(sorted(by_det.items())),
        "by_native": dict(sorted(by_native.items())),
        "det_only_classified": det_only,
        "native_only_classified": native_only,
        "both_unclassified": both_unclassified,
        "degraded_excluded": degraded,
        "confusion": _confusion(pairs),
    }


# ---------------------------------------------------- presence + coverage


def summarize_field_presence(records) -> dict:
    """Per-field both / det_only / native_only / neither counts over scorable
    rows - the silent-gap diagnostic. A field the deterministic advisor always
    leaves empty while Haiku always fills it never shows up in an agreement rate
    (it is never comparable); it shows up HERE as a native_only column."""
    out: dict[str, dict] = {
        field: {"both": 0, "det_only": 0, "native_only": 0, "neither": 0}
        for field in _FIELDS
    }
    for rec in _scorable(records):
        for field in _FIELDS:
            dp = _is_present(_field(rec, "deterministic", field))
            np_ = _is_present(_field(rec, "native", field))
            slot = out[field]
            if dp and np_:
                slot["both"] += 1
            elif dp:
                slot["det_only"] += 1
            elif np_:
                slot["native_only"] += 1
            else:
                slot["neither"] += 1
    return out


def summarize_coverage(records) -> dict:
    """Row counts + pick-state breadth. ``degraded`` and ``scorable`` partition
    ``total`` exactly once; ``aram`` and ``non_aram`` partition ``scorable``
    (so ``non_aram`` equals the swap column's ``gated_out_non_aram``). Champion
    and queue breadth are read over scorable rows - the sample that is scored."""
    champs = set()
    queues = set()
    degraded = aram = non_aram = 0
    for rec in records:
        if is_degraded(rec):
            degraded += 1
            continue
        if bool(_get(rec, "is_aram")):
            aram += 1
        else:
            non_aram += 1
        champ = _get(rec, "my_champion")
        if isinstance(champ, str) and champ.strip():
            champs.add(champ.strip())
        queue = _get(rec, "queue_id")
        if queue is not None:
            queues.add(str(queue))
    return {
        "total": len(records),
        "degraded": degraded,
        "scorable": len(records) - degraded,
        "aram": aram,
        "non_aram": non_aram,
        "distinct_champions": len(champs),
        "distinct_queues": len(queues),
    }


# ------------------------------------------------------------- flip verdict


def _state_and_hint(coverage: dict, advice: dict, min_sample: int) -> tuple:
    """The coarse flip-readiness state + a human hint, gated on the HEADLINE
    advice column. NOT a flip authorization - the operator decides; this only
    flags the obvious not-ready states."""
    comparable = advice.get("comparable", 0)
    if coverage.get("total", 0) == 0:
        return ("awaiting_accrual",
                "no shadow data yet - play real champ-select rounds to accrue "
                "coverage")
    if comparable < min_sample:
        return ("awaiting_accrual",
                f"awaiting accrual ({comparable}/{min_sample} comparable advice "
                "rows) - keep playing before any flip read (operator gate)")
    rate = advice.get("agreement_rate", 0.0)
    pct = round(100 * rate)
    if rate >= FLIP_GATE:
        return ("ready",
                f"advice agreement {pct}% over {comparable} comparable rows "
                f"(>={round(100 * FLIP_GATE)}% gate MET) - NOT a flip "
                "authorization (operator gate; review the per-field columns "
                "and the native_only gaps first)")
    return ("not_ready",
            f"advice agreement {pct}% over {comparable} comparable rows - "
            f"below the {round(100 * FLIP_GATE)}% gate; do not flip")


def build_report(path, min_sample: int = MIN_SAMPLE) -> dict:
    """Assemble the full champ-select shadow report dict from one log path."""
    records = load_jsonl(path)
    coverage = summarize_coverage(records)
    advice = summarize_advice(records)
    state, hint = _state_and_hint(coverage, advice, min_sample)
    return {
        "schema": "champ_select_shadow_report/v1",
        "path": str(path),
        "min_sample": min_sample,
        "flip_gate": FLIP_GATE,
        "headline_field": "advice",
        "coverage": coverage,
        "agreement": {
            "advice": advice,
            "swap": summarize_swap(records),
            "summoners": summarize_summoners(records),
            "watchout": summarize_watchout(records),
        },
        "field_presence": summarize_field_presence(records),
        "flip_hint": hint,
        "state": state,
    }


def _print_human(report: dict) -> None:
    cov = report.get("coverage") or {}
    agr = report.get("agreement") or {}
    print(f"[champ-select shadow] {cov.get('total', 0)} rows, "
          f"{cov.get('scorable', 0)} scorable, "
          f"{cov.get('degraded', 0)} degraded")
    print(f"    pick states: {cov.get('aram', 0)} ARAM, "
          f"{cov.get('non_aram', 0)} non-ARAM, "
          f"{cov.get('distinct_champions', 0)} champs, "
          f"{cov.get('distinct_queues', 0)} queues")
    for field in _FIELDS:
        slot = agr.get(field) or {}
        print(f"    {field}: {slot.get('agree', 0)}/"
              f"{slot.get('comparable', 0)} "
              f"({slot.get('agreement_rate', 0.0)}) comparable")
    swap = agr.get("swap") or {}
    print(f"    swap gate: {swap.get('gated_out_non_aram', 0)} non-ARAM rows "
          f"gated out, {swap.get('no_bench', 0)} ARAM rows with no bench, "
          f"class agreement {swap.get('class_agree', 0)}/"
          f"{swap.get('comparable', 0)}")
    print("    [field_presence]")
    fp = report.get("field_presence") or {}
    for field in _FIELDS:
        slot = fp.get(field) or {}
        print(f"        {field}: both={slot.get('both', 0)} "
              f"det_only={slot.get('det_only', 0)} "
              f"native_only={slot.get('native_only', 0)} "
              f"neither={slot.get('neither', 0)}")
    for field in _FIELDS:
        mism = [c for c in ((agr.get(field) or {}).get("confusion") or [])
                if not c["agree"]]
        for c in mism[:3]:
            print(f"    MISMATCH {field}: det={c['deterministic']} -> "
                  f"native={c['native']} x{c['n']}")
    print(f"state: {report.get('state')} - {report.get('flip_hint')}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--path", default=str(DEFAULT_PATH),
                    help="shadow jsonl path (default data/champ_select_shadow.jsonl)")
    ap.add_argument("--json", action="store_true", help="emit JSON not a summary")
    ap.add_argument("--min-sample", type=int, default=MIN_SAMPLE,
                    help=f"comparable advice rows gate (default {MIN_SAMPLE})")
    args = ap.parse_args(argv)
    report = build_report(Path(args.path), min_sample=args.min_sample)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
