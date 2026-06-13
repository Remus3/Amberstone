# arch: P2 cycle-14 slice-B regression tests for DS upstream extractors | section=tests | frozen=no
"""Regression tests for DEEP_AUDIT_CHARTER P2 cycle 14 slice B (DS upstream
EXTRACTORS - ddragon/cdragon/wiki -> Daemon Slayer data).

NO network: every test feeds the pure parse/resolve helpers inline strings.

FIX-NOW covered here:
  * NaN/inf guard at the wiki scalar parse choke point. A wiki getter
    (action=expandtemplates) or a recharge param can return a non-numeric
    token like "inf" / "nan" / "Infinity"; ``float()`` parses those to a
    non-finite float, and ``json.dumps`` then emits a BARE ``NaN`` /
    ``Infinity`` token - invalid JSON for strict parsers + JS ``JSON.parse``,
    and silently re-accepted by the extractor's own ``json.loads`` on the next
    run (a poisoned sidecar). The parse choke points must reject non-finite
    values (return None) so the value falls through to the next fill tier.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import daemon_slayer_wiki_ability_extract as A  # noqa: E402
import daemon_slayer_wiki_stats_extract as W  # noqa: E402


# --------------------------------------------------------------------------- wiki_stats _parse_scalar
class TestWikiStatsParseScalarRejectsNonFinite:
    """``_parse_scalar`` is the single choke point for every wiki scalar (the
    raw-module path AND the getter-fallback path). A getter can return arbitrary
    wikitext; "inf"/"nan"/"Infinity" must NOT become a non-finite cast time /
    missile speed written into the sidecar."""

    def test_inf_rejected(self):
        assert W._parse_scalar("inf") is None

    def test_negative_inf_rejected(self):
        assert W._parse_scalar("-inf") is None

    def test_nan_rejected(self):
        assert W._parse_scalar("nan") is None

    def test_infinity_word_rejected(self):
        assert W._parse_scalar("Infinity") is None

    def test_finite_still_parses(self):
        # The fix must not perturb the normal numeric path.
        assert W._parse_scalar("0.30000001192093") is not None
        assert abs(W._parse_scalar("0.30000001192093") - 0.3) < 1e-6
        assert W._parse_scalar("2500") == 2500.0

    def test_compound_separator_still_parses(self):
        # feasibility doc 1g: compound get returns trailing "||"
        assert abs(W._parse_scalar("0.30000001192093||") - 0.3) < 1e-6


# --------------------------------------------------------------------------- wiki_ability _resolve_recharge
class TestWikiAbilityRechargeRejectsNonFinite:
    """``_resolve_recharge`` bare-number fallback does ``float(s)`` on verbatim
    wiki markup; "inf"/"nan" must not become a non-finite recharge_ranks."""

    def test_inf_rejected(self):
        assert A._resolve_recharge("inf") is None

    def test_nan_rejected(self):
        assert A._resolve_recharge("nan") is None

    def test_infinity_word_rejected(self):
        assert A._resolve_recharge("Infinity") is None

    def test_bare_number_still_resolves(self):
        assert A._resolve_recharge("20") == 20.0

    def test_ap_wrapper_still_resolves(self):
        ranks = A._resolve_recharge("{{ap|35 to 25}}")
        assert ranks == [35.0, 32.5, 30.0, 27.5, 25.0]

    def test_fd_wrapper_still_resolves(self):
        assert A._resolve_recharge("{{fd|0.25}}") == 0.25

    def test_empty_returns_none(self):
        assert A._resolve_recharge("") is None
        assert A._resolve_recharge("   ") is None


# --------------------------------------------------------------------------- end-to-end: no bare NaN token reaches a sidecar
class TestNoBareNonFiniteTokenSerialized:
    """A resolved value that fed json.dumps would emit a bare NaN/Infinity token
    (invalid JSON). With the guards, the poison value never reaches the payload
    so a strict json.loads round-trip succeeds."""

    def test_parsed_scalar_never_serializes_bare_token(self):
        # Simulate a getter returning a poison token; _parse_scalar must drop it.
        v = W._parse_scalar("inf")
        payload = {"attack_cast_time": v}
        # allow_nan=False is what a strict / JS-compatible serializer enforces.
        text = json.dumps(payload, allow_nan=False)
        assert "Infinity" not in text and "NaN" not in text

    def test_recharge_never_serializes_bare_token(self):
        v = A._resolve_recharge("nan")
        payload = {"recharge_ranks": v}
        text = json.dumps(payload, allow_nan=False)
        assert "NaN" not in text and "Infinity" not in text
