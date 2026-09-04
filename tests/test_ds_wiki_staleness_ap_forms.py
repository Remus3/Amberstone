"""RM-220: the three ``{{ap|}}`` forms ``parse_endpoints`` could not read.

WHY THIS FILE EXISTS
--------------------
RM-216 made the staleness reader COUNT what it could not compare, and the count
then said what the silence never could: after RM-218 closed, a full sweep at
16.15.1 still reported ``skipped_labels=109``, and 27 of those rows carried an
EMPTY ``wiki_labels`` list - the reader parsed the page and found no labelled
quantity at all. Those 27 rows span 14 champions (Aphelios, Jayce, Nami, Nilah,
Nocturne, Ornn, Qiyana, Rumble, Sona, Udyr, Velkoz, Yasuo, Yunara, Yuumi) and
the cause is not vocabulary, it is the ENDPOINT PARSER: ``{{ap|}}`` has three
authored forms the old single regex could not reach.

Every fixture here is the VERBATIM live Data page, saved under
``tests/fixtures/wiki_staleness/`` on 2026-09-04 against patch 16.15.1, and
every stored block is copied verbatim from the committed
``data/daemon_slayer/16.15.1/champion_abilities.json``. Nothing is synthetic,
because a synthetic ``{{ap|}}`` would only prove the parser reads what this
file imagines the wiki writes.

THE THREE FORMS
---------------
* rank-count suffix - Jayce W publishes ``{{ap|35 to 110 6}}``. The trailing 6
  is his rank count (he has six ranks in a form). The old regex let its
  non-greedy tail backtrack across the space, captured ``110 6`` as the upper
  endpoint, and ``_arith`` then correctly refused it as a syntax error - so the
  whole page yielded zero labels.
* enumerated ranks - Nocturne R publishes ``{{ap|150|275|400}}``, with no
  ``to`` anywhere. The old regex required a literal ``to`` and matched nothing.
* named parameter - Rumble Q publishes
  ``{{ap|({{#var:q_b1}}/12)*3 to ({{#var:q_b5}}/12)*3|round=2}}``. The trailing
  ``|round=2`` sits between the second endpoint and the closing braces, so the
  old ``\\s*\\}\\}`` anchor never reached.

NEGATIVE CONTROLS ARE THE POINT
-------------------------------
Widening a parser is only coverage if the settled parses land unchanged, so the
plain form (Maokai Q, the original RM-81 discovery case) and the arithmetic form
(Alistar E, the RM-218 case) are pinned here to their exact prior values, whole
page label-map included. If a future widening perturbs those, this file fails
before the new form's test ever runs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_TOOLS = _ROOT / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import ds_wiki_staleness_check as M  # noqa: E402

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "wiki_staleness"


def _page(name: str) -> str:
    """Verbatim live wikitext, read as UTF-8 so a byte is never re-authored."""
    return (_FIXTURES / f"{name}.wikitext").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- fixtures

JAYCE_W_WIKI = _page("jayce_lightning_field")
NOCTURNE_R_WIKI = _page("nocturne_paranoia")
RUMBLE_Q_WIKI = _page("rumble_flamespitter")
AHRI_W_WIKI = _page("ahri_fox_fire")
CHOGATH_R_WIKI = _page("chogath_feast")
BRIAR_Q_WIKI = _page("briar_head_rush")
MAOKAI_Q_WIKI = _page("maokai_bramble_smash")
ALISTAR_E_WIKI = _page("alistar_trample")

# Stored side, verbatim from data/daemon_slayer/16.15.1/champion_abilities.json.
JAYCE_W_MERAKI = {
    "key": "W",
    "name": "Lightning Field",
    "cooldown": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
    "damage_blocks": [
        {"attribute": "Mana Restored"},
        {
            "attribute": "Magic Damage Per Tick",
            "base": [35.0, 50.0, 65.0, 80.0, 95.0, 110.0],
        },
        {
            "attribute": "Total Magic Damage",
            "base": [140.0, 200.0, 260.0, 320.0, 380.0, 440.0],
        },
    ],
}

NOCTURNE_R_MERAKI = {
    "key": "R",
    "name": "Paranoia",
    "cooldown": [140.0, 115.0, 90.0],
    "damage_blocks": [
        {"attribute": "Physical Damage", "base": [150.0, 275.0, 400.0]},
    ],
}

AHRI_W_MERAKI = {
    "key": "W",
    "name": "Fox-Fire",
    "cooldown": [10.0, 9.0, 8.0, 7.0, 6.0],
    "damage_blocks": [
        {
            "attribute": "Initial Flame Magic Damage",
            "base": [40.0, 60.0, 80.0, 100.0, 120.0],
        },
        {
            "attribute": "Subsequent Flame Magic Damage",
            "base": [12.0, 18.0, 24.0, 30.0, 36.0],
        },
        {
            "attribute": "Total Single-Target Damage",
            "base": [64.0, 96.0, 128.0, 160.0, 192.0],
        },
        {"attribute": "Increased Initial Flame Minion Damage"},
        {"attribute": "Increased Subsequent Flame Minion Damage"},
    ],
}

CHOGATH_R_MERAKI = {
    "key": "R",
    "name": "Feast",
    "cooldown": [80.0, 70.0, 60.0],
    "damage_blocks": [
        {"attribute": "Champion True Damage", "base": [300.0, 475.0, 650.0]},
        {"attribute": "Non-Champion True Damage"},
        {"attribute": "Bonus Health Per Stack"},
    ],
}

BRIAR_Q_MERAKI = {
    "key": "Q",
    "name": "Head Rush",
    "cooldown": [13.0, 12.0, 11.0, 10.0, 9.0],
    "damage_blocks": [
        {"attribute": "Magic Damage", "base": [60.0, 90.0, 120.0, 150.0, 180.0]},
        {"attribute": "Resistances Reduction"},
    ],
}


def _skips(champion: str, slot: str, entry: dict, wikitext: str):
    """Run one comparison and hand back (findings, skipped-label rows)."""
    skipped: list[dict] = []
    found = M.compare_ability(
        champion, slot, entry, wikitext, skipped_labels=skipped
    )
    return found, skipped


# ------------------------------------------------------- (A) form 1: rank-count suffix

def test_rank_count_suffix_parses_to_its_endpoints():
    """``{{ap|35 to 110 6}}`` is 35..110 over SIX ranks, not an endpoint ``110 6``."""
    assert M.parse_endpoints("{{ap|35 to 110 6}}") == (35.0, 110.0)


def test_rank_count_suffix_survives_an_arithmetic_endpoint():
    """Jayce's total is ``{{ap|35*4 to 110*4 6}}`` - suffix AND arithmetic."""
    assert M.parse_endpoints("{{ap|35*4 to 110*4 6}}") == (140.0, 440.0)


def test_rank_count_suffix_page_yields_both_labels():
    """The whole Jayce W page, which used to yield ZERO labels."""
    bases = M.parse_leveling_bases(JAYCE_W_WIKI)
    assert bases.get("Magic Damage Per Tick") == (35.0, 110.0)
    assert bases.get("Total Magic Damage") == (140.0, 440.0)


def test_rank_count_suffix_closes_its_skipped_labels():
    """Coverage gained: two stored labels stop counting themselves as lost.

    Both AGREE with the live page, so this adds a comparison and no finding -
    which is exactly the shape a widening must be able to produce. A widening
    that only ever produced findings would be indistinguishable from noise.
    """
    found, skipped = _skips("Jayce", "W", JAYCE_W_MERAKI, JAYCE_W_WIKI)
    labels = {r["label"] for r in skipped}
    assert "Magic Damage Per Tick" not in labels
    assert "Total Magic Damage" not in labels
    assert [f for f in found if f["field"].startswith("base:")] == []


# ---------------------------------------------------------- (A) form 2: enumerated ranks

def test_enumerated_ranks_take_first_and_last():
    """``{{ap|150|275|400}}`` carries no ``to`` at all."""
    assert M.parse_endpoints("{{ap|150|275|400}}") == (150.0, 400.0)


def test_enumerated_ranks_page_yields_its_label():
    bases = M.parse_leveling_bases(NOCTURNE_R_WIKI)
    assert bases.get("Physical Damage") == (150.0, 400.0)


def test_enumerated_ranks_close_a_skipped_label():
    found, skipped = _skips("Nocturne", "R", NOCTURNE_R_MERAKI, NOCTURNE_R_WIKI)
    assert [r["label"] for r in skipped] == []
    assert [f for f in found if f["field"].startswith("base:")] == []


def test_enumerated_ranks_reach_a_second_champion():
    """Cho'Gath R publishes ``{{ap|300|475|650}}`` - the form is not a one-off."""
    bases = M.parse_leveling_bases(CHOGATH_R_WIKI)
    assert bases.get("Champion True Damage") == (300.0, 650.0)


# --------------------------------------------------------- (A) form 3: named parameter

def test_named_parameter_does_not_block_the_closing_braces():
    """``|round=2`` is a rendering hint, not a rank."""
    assert M.parse_endpoints("{{ap|(50/12)*3 to (150/12)*3|round=2}}") == (12.5, 37.5)


def test_named_parameter_page_yields_its_labels():
    """Rumble Q, whose endpoints are ALSO behind ``{{#vardefine:}}`` indirection."""
    bases = M.parse_leveling_bases(RUMBLE_Q_WIKI)
    assert bases.get("Minimum Magic Damage") == (12.5, 37.5)
    assert bases.get("Maximum Magic Damage") == (62.5, 187.5)


def test_named_parameter_is_not_read_as_an_enumerated_rank():
    """``round=2`` must be dropped, never taken as the last rank's value."""
    assert M.parse_endpoints("{{ap|10 to 20|round=2}}") == (10.0, 20.0)


# --------------------------------------------------------------- NEGATIVE CONTROLS

def test_plain_form_is_unchanged():
    """The original RM-81 form. Value AND whole-page label map are pinned.

    The map is pinned WHOLE, not just the one label under test: a widening that
    invented a label would otherwise pass a per-label assertion untouched.
    These three are the values the parser produced before RM-220 landed.
    """
    assert M.parse_endpoints("{{ap|75 to 255}}") == (75.0, 255.0)
    assert M.parse_leveling_bases(MAOKAI_Q_WIKI) == {
        "Magic Damage": (75.0, 255.0),
        "Bonus Monster Damage": (150.0, 190.0),
        "Total Monster Damage": (225.0, 445.0),
    }


def test_plain_form_still_cuts_at_the_first_as_wrapper():
    """``{{ap|2 to 4}}% of maximum health`` is a RATIO and must stay out."""
    bases = M.parse_leveling_bases(MAOKAI_Q_WIKI)
    assert (2.0, 4.0) not in bases.values()


def test_arithmetic_form_is_unchanged():
    """The RM-218 forms, both directions of operator."""
    assert M.parse_endpoints("{{ap|80/10 to 200/10}}") == (8.0, 20.0)
    assert M.parse_endpoints("{{ap|40*12+40*3 to 100*12+100*3}}") == (600.0, 1500.0)


def test_arithmetic_form_page_is_unchanged():
    assert M.parse_leveling_bases(ALISTAR_E_WIKI) == {
        "Magic Damage Per Tick": (8.0, 20.0),
        "Total Magic Damage": (80.0, 200.0),
    }


def test_bare_number_and_unparseable_inputs_are_unchanged():
    assert M.parse_endpoints("40") == (40.0, 40.0)
    assert M.parse_endpoints("") is None
    assert M.parse_endpoints(None) is None
    assert M.parse_endpoints("Fixed") is None
    assert M.parse_endpoints("{{ap|Fixed to Broken}}") is None


def test_a_nested_ap_wrapper_still_resolves_to_the_outer_endpoints():
    """``cooldown = {{tt|{{ap|140 to 90}}|note}}`` - Nocturne's real shape."""
    raw = M.parse_param(NOCTURNE_R_WIKI, "cooldown")
    assert M.parse_endpoints(raw) == (140.0, 90.0)


def test_an_unterminated_ap_wrapper_is_refused_not_guessed():
    assert M.parse_endpoints("{{ap|10 to 20") is None


def test_a_bracketed_range_is_still_refused_deliberately():
    """Cho'Gath's ``Bonus Size Per Stack`` is ``{{ap|(60 to 100)/10}}`` - the
    ``to`` is INSIDE the parentheses and the ``/10`` distributes over both
    endpoints. That is a FOURTH form and RM-220 does not claim it; refusing it
    keeps the label counting itself rather than reporting 60 and a broken 100.
    """
    assert M.parse_endpoints("{{ap|(60 to 100)/10}}") is None
    assert "Bonus Size Per Stack" not in M.parse_leveling_bases(CHOGATH_R_WIKI)


def test_a_first_ap_that_cannot_parse_does_not_shadow_a_later_one():
    """The scan takes the first ``{{ap|}}`` that PARSES, not the first present,
    so widening the parser cannot cost a match the old regex reached."""
    assert M.parse_endpoints("{{ap|(60 to 100)/10}} then {{ap|9 to 5}}") == (9.0, 5.0)


@pytest.mark.parametrize(
    "raw",
    [
        "{{ap|150|275|400}}",
        "{{ap|35 to 110 6}}",
        "{{ap|(50/12)*3 to (150/12)*3|round=2}}",
        "{{ap|75 to 255}}",
    ],
)
def test_every_supported_form_returns_a_pair_of_floats(raw):
    pts = M.parse_endpoints(raw)
    assert isinstance(pts, tuple) and len(pts) == 2
    assert all(isinstance(v, float) for v in pts)


# ------------------------------------------------------------------ (B) label aliases

def test_ahri_initial_flame_binds_to_the_live_primary_wording():
    """Cited page: Template:Data Ahri/Fox-Fire, leveling2.

    Live: ``{{st|Primary Magic Damage|{{ap|40 to 120}} ...}}``
    Stored: ``Initial Flame Magic Damage`` base 40..120. Same quantity, and it
    AGREES - so this alias buys coverage without inventing a finding.
    """
    found, skipped = _skips("Ahri", "W", AHRI_W_MERAKI, AHRI_W_WIKI)
    assert "Initial Flame Magic Damage" not in {r["label"] for r in skipped}
    assert "base:Initial Flame Magic Damage" not in {f["field"] for f in found}


def test_ahri_subsequent_flame_alias_surfaces_a_real_drift():
    """Same page: ``Subsequent Magic Damage`` is ``{{ap|40*0.4 to 120*0.4}}``.

    Stored 12..36 is 30 percent of the primary flame; the live page publishes 40
    percent, so the alias converts a discarded skip into the finding it always
    was.
    """
    found, skipped = _skips("Ahri", "W", AHRI_W_MERAKI, AHRI_W_WIKI)
    assert "Subsequent Flame Magic Damage" not in {r["label"] for r in skipped}
    row = next(
        f for f in found if f["field"] == "base:Subsequent Flame Magic Damage"
    )
    assert row["meraki"] == [12.0, 36.0]
    assert row["wiki"] == [16.0, 48.0]
    assert row["wiki_label"] == "Subsequent Magic Damage"


def test_an_alias_is_recorded_on_the_row_it_produced():
    """An alias is a JUDGEMENT, so a reader must be able to see it was used."""
    found, _ = _skips("Ahri", "W", AHRI_W_MERAKI, AHRI_W_WIKI)
    aliased = [f for f in found if f.get("wiki_label")]
    assert aliased, "an aliased finding must name the live label it matched"
    for row in aliased:
        assert row["wiki_label"] != row["field"].split(":", 1)[1]


def test_a_near_miss_alias_candidate_dissolves_into_an_exact_match():
    """Cho'Gath R is the trap this row was warned about, and (A) removes it.

    Stored ``Champion True Damage`` is 300..650. Before RM-220(A) the live page
    parsed to ``Non-Champion True Damage`` (a flat 1200), ``Bonus Health Per
    Stack`` and ``Bonus Attack Range Per Stack`` - so the skip row invited an
    alias onto a genuinely DIFFERENT quantity. The real counterpart was on the
    page all along, in the enumerated ``{{ap|300|475|650}}`` form the parser
    could not read. Both labels now resolve, to different numbers, and no alias
    exists for either.
    """
    bases = M.parse_leveling_bases(CHOGATH_R_WIKI)
    assert bases["Champion True Damage"] == (300.0, 650.0)
    assert bases["Non-Champion True Damage"] == (1200.0, 1200.0)
    assert not any(c == "Chogath" for c, _ in M._LABEL_ALIASES)

    found, skipped = _skips("Chogath", "R", CHOGATH_R_MERAKI, CHOGATH_R_WIKI)
    assert [r["label"] for r in skipped] == []
    assert [f for f in found if f["field"].startswith("base:")] == []


def test_a_relabelled_damage_type_is_never_aliased():
    """Briar Q stores ``Magic Damage`` 60..180; the live page publishes
    ``Physical Damage`` 60..160 and ``Resistances Reduction``. Binding on the
    surviving damage line would silently assert the damage TYPE never changed,
    which is itself the drift this tool exists to find - so it stays skipped,
    and the skip row names both live labels for a human to adjudicate.
    """
    _, skipped = _skips("Briar", "Q", BRIAR_Q_MERAKI, BRIAR_Q_WIKI)
    row = next(r for r in skipped if r["label"] == "Magic Damage")
    assert row["wiki_labels"] == ["Physical Damage", "Resistances Reduction"]


def test_aliases_are_exact_and_champion_scoped_never_substring():
    """``Magic Damage`` is itself an unmatched stored label; a substring rule
    would bind it to ``Magic Damage Per Tick`` and compare a per-tick number
    against a total."""
    table = M._LABEL_ALIASES
    assert all(isinstance(k, tuple) and len(k) == 2 for k in table)
    for (champion, stored), live in table.items():
        assert champion and stored and live
        assert stored != live
    assert ("Briar", "Magic Damage") not in table
    assert ("Chogath", "Champion True Damage") not in table
    assert ("Ekko", "Magic Damage") not in table
    assert not any(stored in live or live in stored for (_, stored), live in table.items())


def test_the_alias_table_stays_small_and_cited():
    """A guard against the exact failure RM-218 was refuted for: growing this
    into a general vocabulary table. Every entry needs its own live page."""
    assert len(M._LABEL_ALIASES) <= 4, (
        "each alias needs its own cited live page and its own test - "
        "if this table is growing, the evidence has to grow with it"
    )


# ------------------------------------------------------------------ corpus reachability

def test_the_committed_corpus_still_carries_the_cited_stored_blocks():
    """The stored dicts above are copies, so pin them to the real file.

    A copy that silently diverges from ``champion_abilities.json`` turns every
    assertion above into a statement about this file rather than about the
    engine's data.
    """
    path = _ROOT / "data" / "daemon_slayer" / "16.15.1" / "champion_abilities.json"
    if not path.exists():
        pytest.skip("16.15.1 corpus not present in this checkout")
    data = json.loads(path.read_text(encoding="utf-8"))["data"]
    for champ, slot, copied in [
        ("Jayce", "W", JAYCE_W_MERAKI),
        ("Nocturne", "R", NOCTURNE_R_MERAKI),
        ("Ahri", "W", AHRI_W_MERAKI),
        ("Chogath", "R", CHOGATH_R_MERAKI),
        ("Briar", "Q", BRIAR_Q_MERAKI),
    ]:
        live = data[champ][slot][0]
        assert live["name"] == copied["name"]
        assert live["cooldown"] == copied["cooldown"]
        stored_bases = {
            b["attribute"]: b.get("base")
            for b in live["damage_blocks"]
            if isinstance(b, dict)
        }
        for blk in copied["damage_blocks"]:
            assert blk["attribute"] in stored_bases
            assert stored_bases[blk["attribute"]] == blk.get("base")
