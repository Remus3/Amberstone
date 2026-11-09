# arch: offline tests for the lolmath-wiki per-ability param sidecar extractor | section=tools-tests | frozen=no
"""Offline unit tests for ``tools/daemon_slayer_wiki_ability_extract.py``.

NO network. The ChampionData module text + the batch query fetch are injected via
the ``extract(..., _module_text=, _batch_fn=)`` test seams; ``_fetch`` /
``_fetch_batch`` are never called. 2026-05-30 (wiki ability extractor).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import daemon_slayer_wiki_ability_extract as W  # noqa: E402


# --------------------------------------------------------------------------- {{ap|X to Y}} resolver
class TestResolveAp:
    def test_canonical_five_rank(self):
        # the verbatim Teemo trap example: {{ap|35 to 25}} -> [35,32.5,30,27.5,25]
        assert W._resolve_ap("{{ap|35 to 25}}") == [35.0, 32.5, 30.0, 27.5, 25.0]

    def test_ascending_range(self):
        assert W._resolve_ap("{{ap|20 to 12}}") == [20.0, 18.0, 16.0, 14.0, 12.0]

    def test_embedded_in_markup(self):
        # ap wrapper inside a larger string (e.g. tt-wrapped cooldown)
        assert W._resolve_ap("{{tt|{{ap|4 to 2}}|note}}") == [4.0, 3.5, 3.0, 2.5, 2.0]

    def test_non_ap_returns_none(self):
        assert W._resolve_ap("none") is None
        assert W._resolve_ap("20") is None
        assert W._resolve_ap("") is None

    def test_fd_is_not_ap(self):
        assert W._resolve_ap("{{fd|0.25}}") is None


# --------------------------------------------------------------------------- {{fd|N}} resolver
class TestResolveFd:
    def test_fixed_value(self):
        assert W._resolve_fd("{{fd|0.25}}") == pytest.approx(0.25)

    def test_integer(self):
        assert W._resolve_fd("{{fd|2}}") == pytest.approx(2.0)

    def test_non_fd_returns_none(self):
        assert W._resolve_fd("{{ap|35 to 25}}") is None
        assert W._resolve_fd("none") is None
        assert W._resolve_fd("") is None


# --------------------------------------------------------------------------- recharge resolver
class TestResolveRecharge:
    def test_ap_wrapper_to_ranks(self):
        assert W._resolve_recharge("{{ap|35 to 25}}") == [35.0, 32.5, 30.0, 27.5, 25.0]

    def test_fd_wrapper_to_scalar(self):
        assert W._resolve_recharge("{{fd|0.25}}") == pytest.approx(0.25)

    def test_bare_number(self):
        # verbatim Heimer turret example: |recharge = 20
        assert W._resolve_recharge("20") == pytest.approx(20.0)

    def test_unresolvable_markup_returns_none(self):
        assert W._resolve_recharge("{{tip|cr}} variable") is None

    def test_blank_returns_none(self):
        assert W._resolve_recharge("") is None
        assert W._resolve_recharge("   ") is None


# --------------------------------------------------------------------------- CC-flag normalizer
class TestNormCcFlag:
    def test_true_variants(self):
        assert W._norm_cc_flag("true") is True
        assert W._norm_cc_flag("True") is True
        assert W._norm_cc_flag("1") is True

    def test_false_variants(self):
        assert W._norm_cc_flag("false") is False
        assert W._norm_cc_flag("False") is False
        assert W._norm_cc_flag("0") is False

    def test_special_kept_as_raw_string(self):
        # the tri-state spellshield value
        assert W._norm_cc_flag("Special") == "Special"

    def test_empty_returns_none(self):
        # an empty param (|grounded =) must be omitted, not stored as False
        assert W._norm_cc_flag("") is None
        assert W._norm_cc_flag("   ") is None


# --------------------------------------------------------------------------- title-list construction
class TestParseChampionSkills:
    SAMPLE = (
        "return {\n"
        '  ["Aatrox"] = {\n'
        '    ["id"]         = 266,\n'
        '    ["apiname"]    = "Aatrox",\n'
        '    ["skill_i"]    = {[1] = "Deathbringer Stance"},\n'
        '    ["skill_q"]    = {[1] = "The Darkin Blade", [2] = "The Darkin Blade 2"},\n'
        '    ["skill_w"]    = {[1] = "Infernal Chains"},\n'
        '    ["skill_e"]    = {[1] = "Umbral Dash"},\n'
        '    ["skill_r"]    = {[1] = "World Ender"},\n'
        '    ["stats"] = {\n'
        '      ["attack_cast_time"] = 0.3,\n'
        "    },\n"
        "  },\n"
        '  ["Kai\'Sa"] = {\n'
        '    ["id"]         = 145,\n'
        '    ["apiname"]    = "Kaisa",\n'
        '    ["skill_q"]    = {[1] = "Icathian Rain"},\n'
        '    ["skill_r"]    = {[1] = "Killer Instinct"},\n'
        "  },\n"
        "}\n"
    )

    def test_keys_by_apiname(self):
        s = W._parse_champion_skills(self.SAMPLE)
        assert set(s) == {"Aatrox", "Kaisa"}

    def test_display_is_block_key(self):
        # the wiki block key carries the apostrophe display name; apiname does not
        s = W._parse_champion_skills(self.SAMPLE)
        assert s["Aatrox"]["display"] == "Aatrox"
        assert s["Kaisa"]["display"] == "Kai'Sa"

    def test_skill_arrays_parsed(self):
        s = W._parse_champion_skills(self.SAMPLE)
        assert s["Aatrox"]["skills"]["q"] == ["The Darkin Blade", "The Darkin Blade 2"]
        assert s["Aatrox"]["skills"]["i"] == ["Deathbringer Stance"]

    def test_nested_subtable_not_a_champ(self):
        s = W._parse_champion_skills(self.SAMPLE)
        assert "stats" not in s

    def test_empty_input(self):
        assert W._parse_champion_skills("") == {}


class TestBuildTitles:
    SAMPLE = TestParseChampionSkills.SAMPLE

    def test_title_prefix_uses_display_name(self):
        skills = W._parse_champion_skills(self.SAMPLE)
        triples = W._build_titles(skills, keep_apinames=None)
        # tuple is (apiname, display, ability)
        kaisa = [t for t in triples if t[0] == "Kaisa"]
        assert ("Kaisa", "Kai'Sa", "Icathian Rain") in kaisa

    def test_slot_order_i_q_w_e_r(self):
        skills = W._parse_champion_skills(self.SAMPLE)
        triples = [t for t in W._build_titles(skills, None) if t[0] == "Aatrox"]
        abilities = [t[2] for t in triples]
        assert abilities[0] == "Deathbringer Stance"  # skill_i first
        assert abilities[1] == "The Darkin Blade"      # then skill_q[1]

    def test_keep_apinames_filters(self):
        skills = W._parse_champion_skills(self.SAMPLE)
        triples = W._build_titles(skills, keep_apinames={"Aatrox"})
        assert {t[0] for t in triples} == {"Aatrox"}

    def test_dedups_identical_display_ability(self):
        # a champ with the same name in two slots only yields one triple
        raw = (
            'return {\n  ["X"] = {\n    ["id"] = 1,\n    ["apiname"] = "X",\n'
            '    ["skill_q"] = {[1] = "Dup"},\n'
            '    ["skill_w"] = {[1] = "Dup"},\n  },\n}\n'
        )
        skills = W._parse_champion_skills(raw)
        triples = W._build_titles(skills, None)
        assert len([t for t in triples if t[2] == "Dup"]) == 1


# --------------------------------------------------------------------------- RM-787 duplicate apiname
class TestRm787PrimaryRecordWins:
    # RM-787 (RM-600 sibling): the module carries a second Kled block ("Kled &
    # Skaarl", id 240.1, SAME apiname) after the live record 240, and the parser
    # kept the LAST block per apiname. Every Template:Data "Kled & Skaarl/..."
    # page is a bare #REDIRECT, so the 16.21.1 sidecar holds 7 param-less Kled
    # records and never fetched Pocket Pistol or the Dismounted forms. Shapes
    # below are copied from the live module (fetched 2026-10-27).
    KLED_PRIMARY = (
        '  ["Kled"] = {\n'
        '    ["id"]         = 240,\n'
        '    ["apiname"]    = "Kled",\n'
        '    ["skill_i"]     = {[1] = "Skaarl the Cowardly Lizard", '
        '[2] = "Dismounted Skaarl the Cowardly Lizard"},\n'
        '    ["skill_q"]     = {[1] = "Bear Trap on a Rope", [2] = "Pocket Pistol"},\n'
        '    ["skill_w"]     = {[1] = "Violent Tendencies"},\n'
        '    ["skill_e"]     = {[1] = "Jousting", [2] = "Dismounted Jousting"},\n'
        '    ["skill_r"]     = {[1] = "Chaaaaaaaarge!!!", '
        '[2] = "Dismounted Chaaaaaaaarge!!!"},\n'
        "  },\n"
    )
    KLED_SECONDARY = (
        '  ["Kled & Skaarl"] = {\n'
        '    ["id"]         = 240.1,\n'
        '    ["apiname"]    = "Kled",\n'
        '    ["stats"] = {\n'
        '      --["aram"] = { this is pointless\n'
        '        --["dmg_dealt"] = 1.05,\n'
        "      --},\n"
        "    },\n"
        '    ["skill_i"]     = {[1] = "Skaarl the Cowardly Lizard"},\n'
        '    ["skill_q"]     = {[1] = "Bear Trap on a Rope"},\n'
        '    ["skill_w"]     = {[1] = "Violent Tendencies"},\n'
        '    ["skill_e"]     = {[1] = "Jousting", [2] = "Jousting 2"},\n'
        '    ["skill_r"]     = {[1] = "Chaaaaaaaarge!!!", [2] = "Chaaaaaaaarge!!! 2"}\n'
        "  },\n"
    )

    @staticmethod
    def _wrap(*blocks: str) -> str:
        return "-- <pre>\nreturn {\n" + "".join(blocks) + "}\n-- </pre>\n"

    def _assert_primary(self, parsed):
        kled = parsed["Kled"]
        assert kled["display"] == "Kled"
        assert kled["skills"]["q"] == ["Bear Trap on a Rope", "Pocket Pistol"]
        assert kled["skills"]["e"] == ["Jousting", "Dismounted Jousting"]

    def test_primary_kept_when_secondary_follows(self):
        # the live module order
        self._assert_primary(W._parse_champion_skills(
            self._wrap(self.KLED_PRIMARY, self.KLED_SECONDARY)))

    def test_primary_wins_when_secondary_comes_first(self):
        self._assert_primary(W._parse_champion_skills(
            self._wrap(self.KLED_SECONDARY, self.KLED_PRIMARY)))

    def test_lone_non_integer_record_still_used(self):
        # the live module has one such apiname (GnarBig); it must not vanish
        parsed = W._parse_champion_skills(self._wrap(self.KLED_SECONDARY))
        assert parsed["Kled"]["display"] == "Kled & Skaarl"

    def test_first_of_two_primary_records_kept(self):
        dup = self.KLED_PRIMARY.replace('["Kled"] = {', '["Kled Copy"] = {').replace(
            "Pocket Pistol", "Other")
        self._assert_primary(W._parse_champion_skills(
            self._wrap(self.KLED_PRIMARY, dup)))

    def test_commented_skill_array_is_not_live(self):
        raw = self._wrap(
            '  ["X"] = {\n'
            '    ["id"]      = 1,\n'
            '    ["apiname"] = "X",\n'
            '    --["skill_q"] = {[1] = "Old Name"},\n'
            '    ["skill_w"] = {[1] = "Live"}, -- ["skill_e"] = {[1] = "Gone"}\n'
            '    --[[ ["skill_r"] = {[1] = "Block Gone"}, ]]\n'
            "  },\n"
        )
        assert W._parse_champion_skills(raw)["X"]["skills"] == {"w": ["Live"]}

    def test_extract_requests_the_primary_titles(self, monkeypatch):
        monkeypatch.setattr(W, "_load_champion_apinames", lambda p: {"Kled"})
        sent: list[str] = []

        def fake_batch(titles):
            sent.extend(titles)
            return _query_response([_missing_page(t) for t in titles])

        W.extract("16.21.1", sleep_s=0, limit=None, verbose=False,
                  _module_text=self._wrap(self.KLED_PRIMARY, self.KLED_SECONDARY),
                  _batch_fn=fake_batch)
        assert len(sent) == 9
        assert all(t.startswith("Template:Data Kled/") for t in sent)
        assert "Template:Data Kled/Pocket Pistol" in sent


# --------------------------------------------------------------------------- page-param parsing
class TestParseAbilityPage:
    # Anivia Glacial Storm (verbatim params: static=1, silence=true, cooldown
    # markup, effect radius markup, cast time none).
    ANIVIA = (
        "{{Data ability\n"
        "|cast time    = none\n"
        "|effect radius= {{tip|cr|icononly = true}} {{pp|...}}\n"
        "|cooldown     = {{tt|{{ap|4 to 2}}|Starts after storm disappears}}\n"
        "|cdstart      = post-effect\n"
        "|static       = 1\n"
        "|spellshield  = False\n"
        "|silence      = true\n"
        "}}\n"
    )
    # Corki Valkyrie (grounded=True, knockdown=True, speed markup, effect radius=200).
    CORKI = (
        "{{Data ability\n"
        "|effect radius= 200\n"
        "|speed        = {{tt|650 + {{as|100% movement speed}}|Dash speed}}\n"
        "|cast time    = none\n"
        "|cooldown     = {{ap|20 to 12}}\n"
        "|spellshield  = False\n"
        "|grounded     = True\n"
        "|knockdown    = True\n"
        "}}\n"
    )
    # Teemo Noxious Trap (recharge {{ap}}, cooldown {{fd}}, spellshield Special).
    TEEMO = (
        "{{Data ability\n"
        "|effect radius    = {{tip|cr|icononly = true}} 450\n"
        "|cooldown     = {{fd|0.25}}\n"
        "|recharge     = {{ap|35 to 25}}\n"
        "|cast time    = {{fd|0.25}}\n"
        "|spellshield  = Special\n"
        "}}\n"
    )
    # Heimer turret (parry=True, callforhelp=True, recharge bare 20, EMPTY
    # grounded/knockdown params that must be omitted).
    HEIMER = (
        "{{Data ability\n"
        "|cooldown     = 1\n"
        "|recharge     = 20\n"
        "|cast time    = {{fd|0.25}}\n"
        "|spellshield  = False\n"
        "|parry        = True\n"
        "|callforhelp  = True\n"
        "|grounded     =\n"
        "|knockdown    =\n"
        "}}\n"
    )

    def test_static_flag(self):
        rec = W._parse_ability_page(self.ANIVIA)
        assert rec["static"] is True

    def test_silence_flag(self):
        rec = W._parse_ability_page(self.ANIVIA)
        assert rec["silence"] is True

    def test_spellshield_false_kept(self):
        rec = W._parse_ability_page(self.ANIVIA)
        assert rec["spellshield"] is False

    def test_cooldown_raw_kept(self):
        rec = W._parse_ability_page(self.ANIVIA)
        assert rec["cooldown_raw"] == "{{tt|{{ap|4 to 2}}|Starts after storm disappears}}"
        assert rec["cdstart_raw"] == "post-effect"

    def test_grounded_and_knockdown(self):
        rec = W._parse_ability_page(self.CORKI)
        assert rec["grounded"] is True
        assert rec["knockdown"] is True

    def test_geometry_raw_preserved(self):
        rec = W._parse_ability_page(self.CORKI)
        assert rec["effect_radius_raw"] == "200"
        assert rec["speed_raw"] == "{{tt|650 + {{as|100% movement speed}}|Dash speed}}"
        assert rec["cast_time_raw"] == "none"

    def test_recharge_ap_resolves_to_ranks(self):
        rec = W._parse_ability_page(self.TEEMO)
        assert rec["recharge_raw"] == "{{ap|35 to 25}}"
        assert rec["recharge_ranks"] == [35.0, 32.5, 30.0, 27.5, 25.0]

    def test_recharge_bare_resolves_to_scalar(self):
        rec = W._parse_ability_page(self.HEIMER)
        assert rec["recharge_raw"] == "20"
        assert rec["recharge_ranks"] == pytest.approx(20.0)

    def test_spellshield_special_tri_state(self):
        rec = W._parse_ability_page(self.TEEMO)
        assert rec["spellshield"] == "Special"

    def test_parry_and_callforhelp(self):
        rec = W._parse_ability_page(self.HEIMER)
        assert rec["parry"] is True
        assert rec["callforhelp"] is True

    def test_empty_cc_params_omitted(self):
        # Heimer has |grounded = and |knockdown = (empty) -> must NOT appear
        rec = W._parse_ability_page(self.HEIMER)
        assert "grounded" not in rec
        assert "knockdown" not in rec

    def test_absent_params_omitted(self):
        # Anivia page has no parry/terraingrace/callforhelp -> omitted
        rec = W._parse_ability_page(self.ANIVIA)
        assert "parry" not in rec
        assert "terraingrace" not in rec
        assert "callforhelp" not in rec

    def test_no_cc_duration_param_extracted(self):
        # there is no stun/root duration param; free text must not become a field
        wt = "{{Data ability\n|cooldown = 10\n}}\n* stunning them for 1.5 seconds\n"
        rec = W._parse_ability_page(wt)
        assert "stun" not in rec
        assert "duration" not in rec
        assert set(rec) == {"cooldown_raw"}


# --------------------------------------------------------------------------- extract end-to-end
def _query_response(pages: list[dict]) -> dict:
    """Build a canned MediaWiki action=query response from page dicts."""
    out = {}
    for i, pg in enumerate(pages):
        out[str(pg.get("pageid", i + 1))] = pg
    return {"batchcomplete": "", "query": {"pages": out}}


def _page(title: str, wikitext: str, pageid: int) -> dict:
    return {
        "pageid": pageid,
        "title": title,
        "revisions": [{"slots": {"main": {"contentmodel": "wikitext", "*": wikitext}}}],
    }


def _missing_page(title: str) -> dict:
    return {"ns": 0, "title": title, "missing": ""}


_MODULE = (
    "return {\n"
    '  ["Anivia"] = {\n'
    '    ["id"] = 34,\n    ["apiname"] = "Anivia",\n'
    '    ["skill_q"] = {[1] = "Flash Frost"},\n'
    '    ["skill_e"] = {[1] = "Glacial Storm"},\n'
    "  },\n"
    '  ["Corki"] = {\n'
    '    ["id"] = 42,\n    ["apiname"] = "Corki",\n'
    '    ["skill_w"] = {[1] = "Valkyrie"},\n'
    "  },\n"
    '  ["Teemo"] = {\n'
    '    ["id"] = 17,\n    ["apiname"] = "Teemo",\n'
    '    ["skill_r"] = {[1] = "Noxious Trap"},\n'
    "  },\n"
    "}\n"
)


class TestExtractEndToEnd:
    def _patch_loader(self, monkeypatch, apinames):
        monkeypatch.setattr(W, "_load_champion_apinames", lambda p: set(apinames))

    def test_happy_path_assembles_records(self, monkeypatch):
        self._patch_loader(monkeypatch, ["Anivia", "Corki", "Teemo"])

        def fake_batch(titles):
            pages = []
            for n, t in enumerate(titles):
                if t.endswith("/Glacial Storm"):
                    pages.append(_page(t, TestParseAbilityPage.ANIVIA, n + 1))
                elif t.endswith("/Valkyrie"):
                    pages.append(_page(t, TestParseAbilityPage.CORKI, n + 1))
                elif t.endswith("/Noxious Trap"):
                    pages.append(_page(t, TestParseAbilityPage.TEEMO, n + 1))
                elif t.endswith("/Flash Frost"):
                    pages.append(_missing_page(t))  # exercise a missing page
                else:
                    pages.append(_missing_page(t))
            return _query_response(pages)

        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False,
                        _module_text=_MODULE, _batch_fn=fake_batch)
        assert out["_ability_count"] == 3
        assert out["abilities"]["Anivia/Glacial Storm"]["static"] is True
        assert out["abilities"]["Corki/Valkyrie"]["knockdown"] is True
        assert out["abilities"]["Teemo/Noxious Trap"]["recharge_ranks"] == \
            [35.0, 32.5, 30.0, 27.5, 25.0]
        # the missing Flash Frost page is recorded, not parsed
        assert "Anivia/Flash Frost" in out["_missing_pages"]
        assert out["_with_static"] == 1
        assert out["_with_recharge"] == 1
        assert out["_with_cc_flags"] >= 2  # Corki + Anivia + Teemo carry CC flags

    def test_limit_caps_champs(self, monkeypatch):
        self._patch_loader(monkeypatch, ["Anivia", "Corki", "Teemo"])
        seen_titles = []

        def fake_batch(titles):
            seen_titles.extend(titles)
            return _query_response([_missing_page(t) for t in titles])

        out = W.extract("16.11.1", sleep_s=0, limit=1, verbose=False,
                        _module_text=_MODULE, _batch_fn=fake_batch)
        # limit=1 -> first apiname alphabetically (Anivia) only -> its 2 abilities
        assert all("Anivia/" in t for t in seen_titles)
        assert out["_ability_count"] == 0  # all missing here

    def test_failed_batch_is_fail_soft(self, monkeypatch):
        self._patch_loader(monkeypatch, ["Anivia"])

        def boom(titles):
            raise RuntimeError("401 blocked")

        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False,
                        _module_text=_MODULE, _batch_fn=boom)
        assert out["_ability_count"] == 0
        assert len(out["_errors"]) == 1
        assert "401 blocked" in out["_errors"][0]

    def test_zero_abilities_warns_path(self, monkeypatch):
        # all pages missing -> 0 abilities (the not-committable signal)
        self._patch_loader(monkeypatch, ["Anivia"])
        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False,
                        _module_text=_MODULE,
                        _batch_fn=lambda ts: _query_response([_missing_page(t) for t in ts]))
        assert out["_ability_count"] == 0

    def test_ascii_only_output_even_with_apostrophe_champ(self, monkeypatch):
        # Kai'Sa display name carries an apostrophe; ensure_ascii must not raise
        mod = (
            'return {\n  ["Kai\'Sa"] = {\n    ["id"] = 145,\n'
            '    ["apiname"] = "Kaisa",\n'
            '    ["skill_q"] = {[1] = "Icathian Rain"},\n  },\n}\n'
        )
        monkeypatch.setattr(W, "_load_champion_apinames", lambda p: {"Kaisa"})
        out = W.extract(
            "16.11.1", sleep_s=0, limit=None, verbose=False, _module_text=mod,
            _batch_fn=lambda ts: _query_response(
                [_page(t, "{{Data ability\n|cooldown = 10\n}}", 1) for t in ts]
            ),
        )
        assert "Kai'Sa/Icathian Rain" in out["abilities"]
        json.dumps(out, ensure_ascii=True)  # must not raise

    def test_normalized_title_skipped_gracefully(self, monkeypatch):
        # if the wiki returns a title we did not send (normalization), skip it
        self._patch_loader(monkeypatch, ["Anivia"])

        def fake_batch(titles):
            # return a page with a DIFFERENT title than any sent
            return _query_response([_page("Template:Data Other/Thing", "{{x}}", 9)])

        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False,
                        _module_text=_MODULE, _batch_fn=fake_batch)
        assert out["_ability_count"] == 0  # unrecognized title not keyed


# --------------------------------------------------------------------------- redirect pages
class TestS144D01RedirectPages:
    # RM-954: 134 of the 173 param-less records in the 16.21.1 sidecar are
    # Template:Data pages that are a bare #REDIRECT (Aatrox/The Darkin Blade 2
    # -> Aatrox/The Darkin Blade), indistinguishable from the 39 real pages that
    # carry no captured params. The target spellings below are copied from the
    # live pages (fetched 2026-10-27): underscores, %27, "Template: Data", a
    # trailing period and a trailing category link all occur.
    @pytest.mark.parametrize("wikitext,target", [
        ("#REDIRECT [[Template:Data Aatrox/The Darkin Blade]]",
         "Aatrox/The Darkin Blade"),
        ("#REDIRECT [[Template:Data_Akshan/Heroic_Swing]]", "Akshan/Heroic Swing"),
        ("#REDIRECT [[Template:Data_Kai%27Sa/Supercharge]]", "Kai'Sa/Supercharge"),
        ("#REDIRECT [[Template: Data Brand/Blaze]].", "Brand/Blaze"),
        ("#REDIRECT [[Template:Data_Annie/Summon:_Tibbers]]\n\n"
         "[[Category:Ability Redirects]]", "Annie/Summon: Tibbers"),
        ("#REDIRECT [[Template:Data_Kled/Chaaaaaaaarge!!!]]", "Kled/Chaaaaaaaarge!!!"),
        ("#redirect [[Template:Data Zed/Death Mark|label]]", "Zed/Death Mark"),
        ("#REDIRECT [[Template:Data Zed/Death Mark#Section]]", "Zed/Death Mark"),
        # a target outside Template:Data keeps its full title
        ("#REDIRECT [[Template:Other/Thing]]", "Template:Other/Thing"),
    ])
    def test_redirect_target_is_normalised(self, wikitext, target):
        assert W._redirect_target(wikitext) == target

    @pytest.mark.parametrize("wikitext", [
        TestParseAbilityPage.ANIVIA,
        "{{Data ability\n|cooldown = 10\n}}",
        # #REDIRECT that is not the first token is not a redirect page
        "{{Data ability\n|description = see #REDIRECT [[Template:Data X/Y]]\n}}",
        "",
    ])
    def test_ordinary_page_is_not_a_redirect(self, wikitext):
        assert W._redirect_target(wikitext) is None

    def test_extract_marks_redirect_record(self, monkeypatch):
        monkeypatch.setattr(W, "_load_champion_apinames",
                            lambda p: {"Anivia", "Corki", "Teemo"})

        def fake_batch(titles):
            pages = []
            for n, t in enumerate(titles):
                if t.endswith("/Flash Frost"):
                    pages.append(_page(
                        t, "#REDIRECT [[Template:Data_Anivia/Glacial_Storm]]", n + 1))
                elif t.endswith("/Glacial Storm"):
                    pages.append(_page(t, TestParseAbilityPage.ANIVIA, n + 1))
                elif t.endswith("/Valkyrie"):
                    # a real page with no captured params stays unmarked
                    pages.append(_page(t, "{{Data ability\n|champion = Corki\n}}", n + 1))
                else:
                    pages.append(_missing_page(t))
            return _query_response(pages)

        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False,
                        _module_text=_MODULE, _batch_fn=fake_batch)
        ab = out["abilities"]
        assert ab["Anivia/Flash Frost"] == {
            "redirect_to": "Anivia/Glacial Storm", "apiname": "Anivia", "slot": "Q"}
        assert "redirect_to" not in ab["Anivia/Glacial Storm"]
        assert ab["Corki/Valkyrie"] == {"apiname": "Corki", "slot": "W"}
        assert out["_with_redirect"] == 1
        # a redirect is still a fetched page: the count and the missing list hold
        assert out["_ability_count"] == 3
        assert "Anivia/Flash Frost" not in out["_missing_pages"]


# --------------------------------------------------------------------------- loader
class TestLoadChampionApinames:
    def test_reads_data_container(self, tmp_path, monkeypatch):
        monkeypatch.setattr(W, "DATA_DIR", tmp_path)
        pd = tmp_path / "16.11.1"
        pd.mkdir()
        (pd / "champion_abilities.json").write_text(
            json.dumps({"version": "16.11.1", "data": {"Ahri": {}, "Aatrox": {}}}),
            encoding="utf-8",
        )
        assert W._load_champion_apinames("16.11.1") == {"Aatrox", "Ahri"}

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(W, "DATA_DIR", tmp_path)
        with pytest.raises(SystemExit):
            W._load_champion_apinames("16.11.1")


# --------------------------------------------------------------------------- engine-independence + ASCII
class TestHygiene:
    def test_no_heavy_imports(self):
        with Path(W.__file__).open(encoding="utf-8") as fh:
            src = fh.read()
        assert "import requests" not in src
        assert "from agents" not in src
        assert "import agents" not in src

    def test_source_is_ascii(self):
        with Path(W.__file__).open(encoding="utf-8") as fh:
            data = fh.read()
        try:
            data.encode("ascii")
        except UnicodeEncodeError as e:
            pytest.fail(f"non-ascii byte in extractor: {e}")
        assert "daemon_slayer_wiki_ability" in W.__file__
