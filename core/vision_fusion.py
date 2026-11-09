# arch: confidence-weighted partial-read fusion of Live Client + CV reads | section=core | frozen=no
"""core.vision_fusion - R126 Slice B confidence-weighted partial-read fusion.

Merges Live-Client :2999 exact state (high trust) with vision/OCR reads
(confidence-weighted) into one best-effort game-state estimate, per
docs/NO_LLM_PRECOMPUTE_PLAN.md ("Fuse Live Client API (high trust) +
CV reads (confidence-weighted) into a single ... partial-read layer";
"Confidence thresholds for the fusion layer - when to trust CV over a stale
API read"). This is the DISTINCT general HUD-STATE partial-read fusion;
core/district_fusion.py is the sibling ZOI-district presence fusion (do not
conflate). It is the fail-soft/never-raises precedent this module mirrors.

Trust model per field, over union(live_client, cv_reads):
  - api_gap field: Live Client STRUCTURALLY cannot provide it (e.g. Arena
    augment cards - no capture-free API). CV is authoritative; a present LC
    value is ignored. A gap field that CV did not read is simply absent.
  - fresh, non-gap, in live_client: LC is exact - confidence 1.0.
  - stale, non-gap, in live_client: if CV also read it AND the CV confidence
    clears CV_OVERRIDE_STALE_THRESHOLD AND the CV value passes the
    is_plausible_cv gate, CV wins; else the stale LC read is kept at
    STALE_LIVECLIENT_CONF (0.5) rather than dropped (always emit SOMETHING -
    graceful degradation). A CV read rejected by the gate is tagged
    cv_implausible:<field> in _notes.
  - non-gap, only in cv_reads: CV fallback at its confidence.

CV reads carry NO per-field score today - core/vision_routing.read_or_escalate
returns a plain {field: value} dict - so CV confidence here is a HEURISTIC
assignment (CV_DEFAULT_CONF). A caller that has measured template-match /
OCR scores may pass them via the cv_confidence map.

Output contract: {field: {"value": v, "source": "liveclient"|"cv",
"confidence": float}} plus a "_notes": [str, ...] provenance key. Pure,
dependency-free, stateless. Never raises: any catastrophic failure degrades
to {"_notes": ["fusion_error"]}; None inputs coerce to {}.

Hostile-input contract (s144 true-audit cycle 192). CV values come from OCR
or a Sonnet JSON reply, and json.loads accepts NaN, Infinity and unbounded
integers, so the layer treats every input as untrusted:
  - a NaN, infinite or float-overflowing numeric CV read is implausible (no
    HUD ever shows one), so it can never beat a stale Live Client value; a
    non-finite or overflowing Live Client anchor counts as no anchor.
  - a confidence is always a finite float in [0, 1]; a NaN, bool or
    unreadable score is CV_DEFAULT_CONF, an overflowing one clamps, and a
    non-Mapping cv_confidence is ignored rather than voiding the whole read.
  - live_client / cv_reads may be any Mapping and are snapshotted into plain
    dicts; any other non-None value is ignored and noted.
  - api_gap_fields is a set of field names: a bare str is ONE name (never a
    substring set), unhashable members are skipped, and a non-iterable or
    over-long (> MAX_GAP_FIELDS) value is ignored and noted.
  - live_stale is stale only for True, a non-zero finite-or-infinite number
    or a "true" / "1" / "yes" / "on" string; "false", NaN or a raising
    __bool__ read fresh.
  - "_notes" is reserved for provenance and is never fused as a field, and a
    field whose key cannot be labelled is dropped alone (note field_error).
"""
from __future__ import annotations

import itertools
import math
from collections.abc import Mapping

#: Live Client :2999 is exact ground truth for a field it reports.
LIVECLIENT_CONF = 1.0
#: A Live Client read flagged stale (poll frozen / snapshot aged) keeps this
#: reduced trust when no CV read is available to override it.
STALE_LIVECLIENT_CONF = 0.5
#: Heuristic confidence for a CV/OCR read with no measured per-field score.
CV_DEFAULT_CONF = 0.7
#: A CV read must meet or clear this confidence to override a stale LC read.
CV_OVERRIDE_STALE_THRESHOLD = 0.6

# -- RM-01 Lane E B-01: CV plausibility gate ---------------------------------
# Confidence alone is NOT enough to let CV beat a known-good Live Client value.
# Measured over data/fusion_shadow.jsonl (230 real-game records, 2026-07-18 ->
# 2026-07-24): 41 of 41 cv_override_stale decisions - i.e. every override the
# layer has ever made - were the field `gold` with a CV value of literally 1
# beating a Live Client gold of 87 / 913 / 6423 / 8703 / 12761 / 30410. The
# CV read is a mis-read (the vision relay answers a TFT-shaped prompt in every
# mode, so a non-board frame degrades to a single junk numeric), but the fusion
# layer is the trust arbiter and must be robust to it: per the shipped safety
# doctrine a wrong precompute is worse than a Haiku call. The gate is applied
# ONLY to the contested stale-override branch - the fresh-LC, api_gap and
# cv-only fallback paths emit exactly what they emitted before.

#: Fields whose in-game value only ever increases: a CV read strictly below the
#: last known Live Client value is a mis-read, not a state change. `gold` is
#: deliberately absent - currentGold drops on every purchase.
MONOTONIC_NONDECREASING_FIELDS = frozenset({"level", "cs"})

#: Hard plausible ranges for numeric HUD fields, mirroring the bounds in
#: core.vision_routing.DEFAULT_VALIDATORS. A field absent here is not
#: range-checked (the gate defaults open).
PLAUSIBLE_RANGES = {
    "gold": (0, 99999),
    "level": (1, 18),
    "cs": (0, 1000),
}

#: A CV read diverging from the Live Client anchor by this factor or more is an
#: order-of-magnitude mis-read (8703 vs 1 is a factor of 8703).
CV_ORDER_OF_MAGNITUDE_FACTOR = 10.0

#: The divergence ratio is only meaningful once one side is this large; below
#: it a real early-game swing (3 gold -> 40 gold) would trip a pure ratio test.
CV_DIVERGENCE_ABS_FLOOR = 50.0

#: The provenance key of the output; never fused as a field.
NOTES_KEY = "_notes"

#: Upper bound on api_gap_fields members read from an arbitrary iterable, so
#: an unbounded iterator cannot hang the vision tick (the atlas has a handful).
MAX_GAP_FIELDS = 256

#: String spellings of a true live_stale flag (compared stripped, lower-case).
_TRUE_STRINGS = frozenset({"1", "true", "yes", "on"})


def _numeric(v):
    """Return ``v`` as an exact float when it is a real numeric, else None.

    bool is a subclass of int - augment_select True/False must never be run
    through the numeric divergence rules, so bools are rejected here. The
    value is read through float.__float__ / int.__float__, so a numeric
    subclass cannot redirect the conversion, and an int beyond float range
    is +/-inf rather than an OverflowError. The result may be NaN or
    infinite; callers decide what a non-finite value means.
    """
    if isinstance(v, bool):
        return None
    if isinstance(v, float):
        return float.__float__(v)
    if isinstance(v, int):
        try:
            return int.__float__(v)
        except OverflowError:
            return math.inf if int.__gt__(v, 0) else -math.inf
    return None


def _field_key(field):
    """An exact-str copy of a str field (overrides cannot forge a match)."""
    return str.__str__(field) if isinstance(field, str) else field


def _label(field) -> str:
    """The provenance label of a field key; raises only on an unprintable key."""
    if isinstance(field, str):
        return str.__str__(field)
    return str(field)


def _flag(value) -> bool:
    """Read a live_stale flag strictly (see the module hostile-input contract)."""
    if value is None or isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        return str.__str__(value).strip().lower() in _TRUE_STRINGS
    num = _numeric(value)
    if num is not None:
        return not math.isnan(num) and num != 0.0
    try:
        return bool(value)
    except Exception:  # noqa: BLE001 - an unreadable flag reads fresh
        return False


def _snapshot(mapping, name, notes):
    """A plain-dict copy of a Mapping input; anything else is {} (noted)."""
    if mapping is None:
        return {}
    if isinstance(mapping, Mapping):
        try:
            return dict(mapping)
        except Exception:  # noqa: BLE001 - unreadable input degrades to {}
            pass
    notes.append(name + "_ignored")
    return {}


def _gap_set(api_gap_fields, notes):
    """Normalize api_gap_fields to a frozenset of hashable field names."""
    if api_gap_fields is None:
        return frozenset()
    if isinstance(api_gap_fields, str):
        return frozenset({str.__str__(api_gap_fields)})
    try:
        members = list(itertools.islice(iter(api_gap_fields), MAX_GAP_FIELDS + 1))
    except Exception:  # noqa: BLE001 - non-iterable / raising iterator
        members = None
    if members is None or len(members) > MAX_GAP_FIELDS:
        notes.append("api_gap_fields_ignored")
        return frozenset()
    out = set()
    for member in members:
        try:
            out.add(_field_key(member))
        except TypeError:
            continue
    return frozenset(out)


def is_plausible_cv(field, cv_value, lc_value=None) -> bool:
    """Is ``cv_value`` a believable read for ``field`` given the LC anchor?

    Fail-soft and DEFAULTS OPEN: anything the gate cannot judge (unknown
    field, non-numeric pair, missing anchor, any internal error) is reported
    plausible, so the gate can never silently swallow a field it does not
    understand. Four rules, each independently sufficient to reject:

      0. finite     - a numeric CV read that is NaN, infinite or beyond float
         range is never a HUD value (json.loads yields all three).
      1. hard range - the value is outside PLAUSIBLE_RANGES[field].
      2. monotonic  - field is monotonic non-decreasing and the CV read sits
         strictly below the Live Client anchor.
      3. divergence - CV and LC differ by CV_ORDER_OF_MAGNITUDE_FACTOR or
         more, once either side clears CV_DIVERGENCE_ABS_FLOOR. A numeric LC
         anchor paired with a non-numeric CV read is a parse miss and is
         rejected by the same rule.

    A non-finite or overflowing LC anchor is treated as no anchor, so only
    rules 0 and 1 apply.
    """
    try:
        key = _field_key(field)
        cv = _numeric(cv_value)
        if cv is not None and not math.isfinite(cv):
            return False
        lo_hi = PLAUSIBLE_RANGES.get(key)
        if cv is not None and lo_hi is not None and not lo_hi[0] <= cv <= lo_hi[1]:
            return False

        lc = _numeric(lc_value)
        if lc is None or not math.isfinite(lc):
            return True
        if cv is None:
            # Numeric anchor paired with a non-numeric CV read: a parse miss.
            return False

        if key in MONOTONIC_NONDECREASING_FIELDS and cv < lc:
            return False

        hi = max(abs(cv), abs(lc))
        lo = min(abs(cv), abs(lc))
        return not (hi >= CV_DIVERGENCE_ABS_FLOOR
                    and hi / max(lo, 1.0) >= CV_ORDER_OF_MAGNITUDE_FACTOR)
    except Exception:  # noqa: BLE001 - fail-soft: an unjudgeable read is open
        return True


def _cv_conf(field, cv_confidence):
    """CV confidence for ``field``, clamped to [0, 1].

    Uses the caller-supplied measured score when present; otherwise the
    heuristic CV_DEFAULT_CONF. Fail-soft: a non-Mapping map, a bool, NaN or
    unreadable score degrades to the default rather than raising, and an
    overflowing score clamps, so the result is always finite.
    """
    if not isinstance(cv_confidence, Mapping):
        return CV_DEFAULT_CONF
    try:
        if field not in cv_confidence:
            return CV_DEFAULT_CONF
        raw = cv_confidence[field]
        if isinstance(raw, bool):
            return CV_DEFAULT_CONF
        v = _numeric(raw)
        if v is None:
            v = float(str.__str__(raw) if isinstance(raw, str) else raw)
    except Exception:  # noqa: BLE001 - an unreadable score is the default
        return CV_DEFAULT_CONF
    if math.isnan(v):
        return CV_DEFAULT_CONF
    return min(max(v, 0.0), 1.0)


def fuse_reads(
    live_client: dict,
    cv_reads: dict,
    *,
    api_gap_fields=frozenset(),
    live_stale: bool = False,
    cv_confidence: dict | None = None,
) -> dict:
    """Fuse Live Client exact state with confidence-weighted CV reads.

    Args:
        live_client: {field: value} exact reads from Live Client :2999.
        cv_reads: {field: value} vision/OCR reads (no per-field score).
        api_gap_fields: fields Live Client structurally cannot provide; CV is
            authoritative for these and any LC value is ignored.
        live_stale: when True the Live Client snapshot is aged - a
            confident CV read may override it (see CV_OVERRIDE_STALE_THRESHOLD).
        cv_confidence: optional {field: score} measured CV confidences; a
            field absent here defaults to CV_DEFAULT_CONF.

    Returns:
        {field: {"value", "source", "confidence"}} plus a "_notes" list of
        provenance tags. Never raises; catastrophic failure -> {"_notes":
        ["fusion_error"]}.
    """
    try:
        notes: list = []
        live_client = _snapshot(live_client, "live_client", notes)
        cv_reads = _snapshot(cv_reads, "cv_reads", notes)
        gap = _gap_set(api_gap_fields, notes)
        stale = _flag(live_stale)

        # union(live_client, cv_reads) preserving first-seen order (LC first).
        fields = list(dict.fromkeys(itertools.chain(live_client, cv_reads)))

        result: dict = {}
        for f in fields:
            try:
                label = _label(f)
                if isinstance(f, str) and label == NOTES_KEY:
                    notes.append("reserved_field:" + NOTES_KEY)
                    continue
                entry, note = _fuse_field(
                    f, live_client, cv_reads, gap, stale, cv_confidence,
                    label, notes,
                )
            except Exception:  # noqa: BLE001 - one bad field drops alone
                notes.append("field_error")
                continue
            if entry is not None:
                result[f] = entry
                notes.append(note)

        result[NOTES_KEY] = notes
        return result
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return {NOTES_KEY: ["fusion_error"]}


def _fuse_field(f, live_client, cv_reads, gap, stale, cv_confidence, label,
                notes):
    """Decide one field: return (entry or None, provenance note)."""
    in_lc = f in live_client
    in_cv = f in cv_reads

    if _field_key(f) in gap:
        # Structural API gap: CV authoritative, LC ignored entirely.
        # A gap field CV did not read is simply not emitted.
        if not in_cv:
            return None, None
        return ({"value": cv_reads[f], "source": "cv",
                 "confidence": _cv_conf(f, cv_confidence)},
                "cv_gap:" + label)

    if in_lc and not stale:
        return ({"value": live_client[f], "source": "liveclient",
                 "confidence": LIVECLIENT_CONF},
                "lc_exact:" + label)

    if in_lc:
        conf = _cv_conf(f, cv_confidence) if in_cv else 0.0
        contested = in_cv and conf >= CV_OVERRIDE_STALE_THRESHOLD
        # B-01 gate: confidence alone must not let an implausible CV read
        # beat a known-good LC value. Evaluated through the module attribute
        # so a monkeypatched gate is honored; a gate that raises degrades to
        # "plausible" (fail-soft, never-raises).
        plausible = True
        if contested:
            try:
                plausible = bool(is_plausible_cv(f, cv_reads[f], live_client[f]))
            except Exception:  # noqa: BLE001 - gate must never raise
                plausible = True
            if not plausible:
                notes.append("cv_implausible:" + label)
        if contested and plausible:
            return ({"value": cv_reads[f], "source": "cv", "confidence": conf},
                    "cv_override_stale:" + label)
        return ({"value": live_client[f], "source": "liveclient",
                 "confidence": STALE_LIVECLIENT_CONF},
                "lc_stale:" + label)

    # non-gap, only in cv_reads.
    return ({"value": cv_reads[f], "source": "cv",
             "confidence": _cv_conf(f, cv_confidence)},
            "cv_fallback:" + label)


def fuse_with_atlas(live_client, cv_reads, **kw) -> dict:
    """Convenience wrapper that sources api_gap_fields from the region atlas.

    LAZILY imports core.vision_region_atlas inside the function (fail-soft: if
    the atlas is absent or errors, api_gap_fields degrades to frozenset()) so
    this module stays decoupled and standalone-testable. Any api_gap_fields
    passed in kw is dropped in favor of the atlas value.
    """
    try:
        from core import vision_region_atlas
        gap = vision_region_atlas.api_gap_fields()
    except Exception:  # noqa: BLE001 - atlas optional; degrade to no gaps
        gap = frozenset()
    kw.pop("api_gap_fields", None)
    return fuse_reads(live_client, cv_reads, api_gap_fields=gap, **kw)
