# arch: confidence-weighted partial-read fusion of Live Client + CV reads | section=core | frozen=no
"""core.vision_fusion - R126 Slice B confidence-weighted partial-read fusion.

Merges Live-Client :2999 exact state (high trust) with vision/OCR reads
(confidence-weighted) into one best-effort game-state estimate, per
docs/NO_LLM_PRECOMPUTE_PLAN.md:159-163 ("Fuse Live Client API (high trust) +
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
"""
from __future__ import annotations

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


def _numeric(v):
    """Return ``v`` as a float when it is a real numeric, else None.

    bool is a subclass of int - augment_select True/False must never be run
    through the numeric divergence rules, so bools are rejected here.
    """
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def is_plausible_cv(field, cv_value, lc_value=None) -> bool:
    """Is ``cv_value`` a believable read for ``field`` given the LC anchor?

    Fail-soft and DEFAULTS OPEN: anything the gate cannot judge (unknown
    field, non-numeric pair, missing anchor, any internal error) is reported
    plausible, so the gate can never silently swallow a field it does not
    understand. Three rules, each independently sufficient to reject:

      1. hard range - the value is outside PLAUSIBLE_RANGES[field].
      2. monotonic  - field is monotonic non-decreasing and the CV read sits
         strictly below the Live Client anchor.
      3. divergence - CV and LC differ by CV_ORDER_OF_MAGNITUDE_FACTOR or
         more, once either side clears CV_DIVERGENCE_ABS_FLOOR. A numeric LC
         anchor paired with a non-numeric CV read is a parse miss and is
         rejected by the same rule.
    """
    try:
        cv = _numeric(cv_value)
        lo_hi = PLAUSIBLE_RANGES.get(field)
        if cv is not None and lo_hi is not None:
            if cv < lo_hi[0] or cv > lo_hi[1]:
                return False

        lc = _numeric(lc_value)
        if lc is None:
            return True
        if cv is None:
            # Numeric anchor paired with a non-numeric CV read: a parse miss.
            return False

        if field in MONOTONIC_NONDECREASING_FIELDS and cv < lc:
            return False

        hi = max(abs(cv), abs(lc))
        lo = min(abs(cv), abs(lc))
        if hi >= CV_DIVERGENCE_ABS_FLOOR:
            if hi / max(lo, 1.0) >= CV_ORDER_OF_MAGNITUDE_FACTOR:
                return False
        return True
    except Exception:  # noqa: BLE001 - fail-soft: an unjudgeable read is open
        return True


def _cv_conf(field, cv_confidence):
    """CV confidence for ``field``, clamped to [0, 1].

    Uses the caller-supplied measured score when present; otherwise the
    heuristic CV_DEFAULT_CONF. Fail-soft: any non-numeric score degrades to
    the default rather than raising.
    """
    if cv_confidence and field in cv_confidence:
        try:
            v = float(cv_confidence[field])
        except (TypeError, ValueError):
            return CV_DEFAULT_CONF
        if v < 0.0:
            return 0.0
        if v > 1.0:
            return 1.0
        return v
    return CV_DEFAULT_CONF


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
        live_client = live_client if isinstance(live_client, dict) else {}
        cv_reads = cv_reads if isinstance(cv_reads, dict) else {}
        if api_gap_fields is None:
            api_gap_fields = frozenset()

        # union(live_client, cv_reads) preserving first-seen order (LC first).
        seen = set()
        fields = []
        for f in list(live_client) + list(cv_reads):
            if f not in seen:
                seen.add(f)
                fields.append(f)

        result: dict = {}
        notes: list = []
        for f in fields:
            in_lc = f in live_client
            in_cv = f in cv_reads

            if f in api_gap_fields:
                # Structural API gap: CV authoritative, LC ignored entirely.
                # A gap field CV did not read is simply not emitted.
                if in_cv:
                    result[f] = {
                        "value": cv_reads[f],
                        "source": "cv",
                        "confidence": _cv_conf(f, cv_confidence),
                    }
                    notes.append("cv_gap:" + str(f))
                continue

            if in_lc and not live_stale:
                result[f] = {
                    "value": live_client[f],
                    "source": "liveclient",
                    "confidence": LIVECLIENT_CONF,
                }
                notes.append("lc_exact:" + str(f))
            elif in_lc and live_stale:
                conf = _cv_conf(f, cv_confidence) if in_cv else 0.0
                # B-01 gate: confidence alone must not let an implausible CV
                # read beat a known-good LC value. Evaluated through the module
                # attribute so a monkeypatched gate is honored; a gate that
                # raises degrades to "plausible" (fail-soft, never-raises).
                plausible = True
                if in_cv and conf >= CV_OVERRIDE_STALE_THRESHOLD:
                    try:
                        plausible = bool(
                            is_plausible_cv(f, cv_reads[f], live_client[f])
                        )
                    except Exception:  # noqa: BLE001 - gate must never raise
                        plausible = True
                    if not plausible:
                        notes.append("cv_implausible:" + str(f))
                if in_cv and conf >= CV_OVERRIDE_STALE_THRESHOLD and plausible:
                    result[f] = {
                        "value": cv_reads[f],
                        "source": "cv",
                        "confidence": conf,
                    }
                    notes.append("cv_override_stale:" + str(f))
                else:
                    result[f] = {
                        "value": live_client[f],
                        "source": "liveclient",
                        "confidence": STALE_LIVECLIENT_CONF,
                    }
                    notes.append("lc_stale:" + str(f))
            else:
                # non-gap, only in cv_reads.
                result[f] = {
                    "value": cv_reads[f],
                    "source": "cv",
                    "confidence": _cv_conf(f, cv_confidence),
                }
                notes.append("cv_fallback:" + str(f))

        result["_notes"] = notes
        return result
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return {"_notes": ["fusion_error"]}


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
