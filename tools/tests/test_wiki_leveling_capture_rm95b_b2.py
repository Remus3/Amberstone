# arch: offline tests for the RM-95b B2 leveling*_raw capture + apiname/slot join key | section=tools-tests | frozen=no
"""Offline unit tests for the RM-95b B2 half of the wiki ability extractor.

NO network. Canned wikitext only; ``extract`` is driven through its
``_module_text=`` / ``_batch_fn=`` seams exactly as
``test_wiki_ability_extract.py`` does.

Two things are under test:

* ``_block_param`` - the brace-depth reader that captures a MULTI-LINE param.
  ``_param_re`` stops at end-of-line, which silently truncates a wrapped
  ``{{st|Label|Value|...}}`` payload; every regression here is a truncation.
* the ``apiname`` + ``slot`` join key, without which a sidecar record cannot be
  matched to an ``AbilitiesSnapshot`` form (the snapshot keys on apiname +
  P/Q/W/E/R; the sidecar map key is ``display/ability_name``).

The additive contract matters as much as the capture: a page with NO leveling
param must produce a record byte-identical to the pre-change one.
"""
from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import daemon_slayer_wiki_ability_extract as W  # noqa: E402


# --------------------------------------------------------------------------- fixtures
# Shaped on the real Locke Q wikitext (quoted verbatim in
# agents/daemon_slayer/_ability_wiki_damage_registry.py): a leveling payload that
# WRAPS across lines, carries nested {{ap|..}} / {{as|..}} wrappers, and is
# followed by further params that must NOT be swallowed.
MULTILINE = (
    "{{Data Ability\n"
    "|name = Ritual Nails\n"
    "|cooldown = {{ap|9 to 5}}\n"
    "|leveling  = {{st|Magic Damage per Nail|{{ap|50 to 82}} "
    "{{as|(+ 20% AP)}}\n"
    "  |Maximum Nail Damage|{{ap|150 to 246}} {{as|(+ 60% AP)}}}}\n"
    "|targeting = Direction\n"
    "|damagetype = magic\n"
    "}}\n"
)

# A page with numbered variants AND a deliberately empty base leveling param.
NUMBERED = (
    "{{Data Ability\n"
    "|name = Cultivation\n"
    "|leveling =\n"
    "|leveling2 = {{st|Bonus Damage|{{ap|10 to 30}}}}\n"
    "|leveling3 = {{st|One Stack Bonus|{{fd|12.5}}}}\n"
    "|silence = true\n"
    "}}\n"
)

# The control: no leveling param anywhere. Must stay byte-identical.
NO_LEVELING = (
    "{{Data Ability\n"
    "|name = Flash Frost\n"
    "|static = true\n"
    "|cooldown = {{ap|12 to 8}}\n"
    "|effect radius = 100\n"
    "}}\n"
)


def _page(title: str, wikitext: str, pid: int) -> dict:
    return {
        "pageid": pid,
        "title": title,
        "revisions": [{"slots": {"main": {"*": wikitext}}}],
    }


def _query_response(pages: list[dict]) -> dict:
    return {"query": {"pages": {str(p.get("pageid", i)): p
                                for i, p in enumerate(pages)}}}


_MODULE = (
    "return {\n"
    '  ["Anivia"] = {\n'
    '    ["id"] = 34,\n    ["apiname"] = "Anivia",\n'
    '    ["skill_i"] = {[1] = "Rebirth"},\n'
    '    ["skill_q"] = {[1] = "Flash Frost"},\n'
    "  },\n"
    '  ["Locke"] = {\n'
    '    ["id"] = 911,\n    ["apiname"] = "Locke",\n'
    '    ["skill_q"] = {[1] = "Ritual Nails"},\n'
    "  },\n"
    "}\n"
)


# --------------------------------------------------------------------------- _block_param
class TestBlockParam:
    def test_captures_across_a_line_break(self):
        """The whole {{st|..}} payload, not just its first line."""
        v = W._block_param(MULTILINE, "leveling")
        assert v is not None
        # both label/value pairs survived the wrap
        assert "Magic Damage per Nail" in v
        assert "Maximum Nail Damage" in v
        assert "{{ap|150 to 246}}" in v
        assert v.endswith("}}")

    def test_line_anchored_regex_would_have_truncated(self):
        """Anti-tautology: prove _param_re is INSUFFICIENT for this param.

        If this ever passes with the two values equal, _block_param has silently
        degraded back to line-anchored behaviour and the test above is vacuous.
        """
        line_only = W._first_param(MULTILINE, W._param_re("leveling"))
        block = W._block_param(MULTILINE, "leveling")
        assert line_only is not None and block is not None
        assert "Maximum Nail Damage" not in line_only
        assert len(block) > len(line_only)

    def test_does_not_swallow_the_next_param(self):
        v = W._block_param(MULTILINE, "leveling")
        assert "targeting" not in v
        assert "damagetype" not in v

    def test_whitespace_collapsed_to_single_spaces(self):
        v = W._block_param(MULTILINE, "leveling")
        assert "\n" not in v
        assert "  " not in v

    def test_absent_param_is_none(self):
        assert W._block_param(NO_LEVELING, "leveling") is None

    def test_empty_param_is_none(self):
        assert W._block_param(NUMBERED, "leveling") is None

    def test_numbered_variants_are_addressed_separately(self):
        assert W._block_param(NUMBERED, "leveling2") == \
            "{{st|Bonus Damage|{{ap|10 to 30}}}}"
        assert W._block_param(NUMBERED, "leveling3") == \
            "{{st|One Stack Bonus|{{fd|12.5}}}}"

    def test_base_name_does_not_match_a_numbered_variant(self):
        """``leveling`` must not capture ``leveling2``'s value.

        The digit sits between the name and the ``=`` so the pattern cannot
        match - the same property _param_re documents. NUMBERED's own base
        param is empty, so a leak would surface as a non-None value.
        """
        assert W._block_param(NUMBERED, "leveling") is None

    def test_none_and_empty_wikitext_are_safe(self):
        assert W._block_param("", "leveling") is None
        assert W._block_param(None, "leveling") is None  # type: ignore[arg-type]


# --------------------------------------------------------------------------- _parse_ability_page
class TestParseEmitsLeveling:
    def test_multiline_lands_as_leveling_raw(self):
        rec = W._parse_ability_page(MULTILINE)
        assert "leveling_raw" in rec
        assert "Maximum Nail Damage" in rec["leveling_raw"]

    def test_numbered_land_as_their_own_keys(self):
        rec = W._parse_ability_page(NUMBERED)
        assert "leveling_raw" not in rec  # empty -> omitted
        assert "leveling2_raw" in rec
        assert "leveling3_raw" in rec

    def test_no_leveling_page_is_byte_identical_to_pre_change(self):
        """The additive contract: absent param -> record unchanged.

        The expected dict is the FULL pre-change record for this page, written
        out literally rather than derived, so a future edit that adds a new
        always-on key fails here.
        """
        rec = W._parse_ability_page(NO_LEVELING)
        assert rec == {
            "static": True,
            "cooldown_raw": "{{ap|12 to 8}}",
            "effect_radius_raw": "100",
        }

    def test_existing_families_still_parse_alongside_leveling(self):
        rec = W._parse_ability_page(MULTILINE)
        assert rec["cooldown_raw"] == "{{ap|9 to 5}}"
        rec2 = W._parse_ability_page(NUMBERED)
        assert rec2["silence"] is True


# --------------------------------------------------------------------------- join key
class TestJoinKey:
    def test_slot_letter_map_covers_every_wiki_slot(self):
        assert set(W._SLOT_LETTER) == set(W._SKILL_SLOTS)
        assert W._SLOT_LETTER["i"] == "P"  # wiki "inherent" -> snapshot "P"

    def test_build_titles_wrapper_still_returns_triples(self):
        skills = W._parse_champion_skills(_MODULE)
        triples = W._build_titles(skills, None)
        assert triples, "fixture produced no titles"
        assert all(len(t) == 3 for t in triples)

    def test_index_carries_apiname_and_slot(self):
        skills = W._parse_champion_skills(_MODULE)
        rows = W._build_title_index(skills, None)
        assert all(len(r) == 4 for r in rows)
        by_name = {r[3]: r for r in rows}
        assert by_name["Rebirth"][0] == "Anivia"
        assert by_name["Rebirth"][1] == "P"
        assert by_name["Flash Frost"][1] == "Q"
        assert by_name["Ritual Nails"][0] == "Locke"
        assert by_name["Ritual Nails"][1] == "Q"

    def test_wrapper_and_index_agree_on_content_and_order(self):
        skills = W._parse_champion_skills(_MODULE)
        rows = W._build_title_index(skills, None)
        assert W._build_titles(skills, None) == \
            [(a, d, n) for a, _s, d, n in rows]


# --------------------------------------------------------------------------- end to end
class TestExtractEndToEnd:
    def _run(self, monkeypatch):
        monkeypatch.setattr(W, "_load_champion_apinames",
                            lambda p: {"Anivia", "Locke"})

        def fake_batch(titles):
            pages = []
            for n, t in enumerate(titles):
                if t.endswith("/Ritual Nails"):
                    pages.append(_page(t, MULTILINE, n + 1))
                elif t.endswith("/Flash Frost"):
                    pages.append(_page(t, NO_LEVELING, n + 1))
                else:
                    pages.append(_page(t, NUMBERED, n + 1))
            return _query_response(pages)

        return W.extract("16.14.1", sleep_s=0, limit=None, verbose=False,
                         _module_text=_MODULE, _batch_fn=fake_batch)

    def test_records_carry_identity(self, monkeypatch):
        out = self._run(monkeypatch)
        rec = out["abilities"]["Locke/Ritual Nails"]
        assert rec["apiname"] == "Locke"
        assert rec["slot"] == "Q"

    def test_leveling_reaches_the_payload(self, monkeypatch):
        out = self._run(monkeypatch)
        rec = out["abilities"]["Locke/Ritual Nails"]
        assert "Maximum Nail Damage" in rec["leveling_raw"]

    def test_with_leveling_counter_is_reported(self, monkeypatch):
        out = self._run(monkeypatch)
        # Ritual Nails (leveling) + Rebirth (NUMBERED -> leveling2/3); Flash
        # Frost has none.
        assert out["_with_leveling"] == 2
        assert out["_ability_count"] == 3

    def test_no_leveling_record_gains_only_the_identity_keys(self, monkeypatch):
        out = self._run(monkeypatch)
        rec = out["abilities"]["Anivia/Flash Frost"]
        assert rec == {
            "static": True,
            "cooldown_raw": "{{ap|12 to 8}}",
            "effect_radius_raw": "100",
            "apiname": "Anivia",
            "slot": "Q",
        }


# --------------------------------------------------------------------------- hygiene
def test_module_source_is_ascii():
    """Repo hard rule: 7-bit ASCII authored content, no em/en dashes."""
    for p in (_TOOLS / "daemon_slayer_wiki_ability_extract.py",
              Path(__file__)):
        raw = p.read_bytes()
        assert raw.decode("utf-8").isascii(), f"{p.name} carries non-ASCII"
