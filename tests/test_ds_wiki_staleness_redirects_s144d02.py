"""RM-955: the staleness checker read a wiki ``#REDIRECT`` page as if it were
the ability's Data page.

``run()`` asks the wiki for ``Template:Data <stem>/<Meraki form name>``. When the
wiki has renamed an ability it keeps the old title as a bare redirect
(``#REDIRECT [[Template:Data <stem>/<new name>]]``), and the query API returns
that one line as the page text. ``compare_ability`` then parsed no cooldown and
no labels from it, so every stored label landed in ``skipped_labels`` as "label
absent from live wiki page" with ``wiki_labels: []`` - a relabel diagnosis for
what is really a rename - and an ability with no stored base labels vanished
with no record at all. RM-954 (the extractor half) measured 134 such pages in
the 16.21.1 wiki sidecar.

The fix follows ONE hop: the targets are fetched and compared, and every row
read through a redirect names it in ``wiki_redirect`` (as an alias row names
``wiki_label``), because a redirect is the wiki's judgement that two titles are
the same ability, not a measurement. A redirect that could not be followed (a
missing target, or a second hop) is a ``skipped_pages`` row, never a label skip.

Fixtures are synthetic, in the shape of ``champion_abilities.json`` and the
live Data template (copied from ``tests/test_ds_wiki_staleness_check.py``).
"""
from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import ds_wiki_staleness_check as M  # noqa: E402

# Live Data-template shape; stored base 65..245 disagrees with live 75..255.
BRAMBLE_WIKI = (
    "|leveling     = {{st|Magic Damage|{{ap|75 to 255}} {{as|(+ 40% AP)}}}}\n"
    "|cooldown     = {{ap|7 to 5}}\n"
    "|damagetype   = Magic\n"
)
BRAMBLE_WIKI_RELABELLED = BRAMBLE_WIKI.replace(
    "{{st|Magic Damage|", "{{st|Magic Damage Per Hit|"
)

OLD = "Template:Data Maokai/Bramble Smash"
NEW = "Template:Data Maokai/Bramble Slam"
THIRD = "Template:Data Maokai/Bramble Strike"


def _redirect(title: str) -> str:
    return "#REDIRECT [[" + title + "]]\n"


BRAMBLE_MERAKI = [
    {
        "key": "Q",
        "name": "Bramble Smash",
        "form_index": 0,
        "cooldown": [7.0, 6.5, 6.0, 5.5, 5.0],
        "damage_blocks": [
            {
                "attribute": "Magic Damage",
                "attribute_kind": "damage",
                "base": [65.0, 110.0, 155.0, 200.0, 245.0],
                "ap_pct": [40.0] * 5,
            }
        ],
    }
]

# No base labels at all: before the fix a redirect here left NO record.
SAPLING_MERAKI = [
    {
        "key": "E",
        "name": "Sapling Toss",
        "form_index": 0,
        "cooldown": [14.0, 13.0, 12.0, 11.0, 10.0],
        "damage_blocks": [],
    }
]


def _stub_run(monkeypatch, wiki_by_title, meraki=None):
    """Drive ``run()`` with no network; ``fetch_pages`` answers per title and
    records every call so the number of wiki round trips is asserted too."""
    calls: list[list[str]] = []

    def fake_fetch(titles):
        calls.append(list(titles))
        return {t: wiki_by_title[t] for t in titles if t in wiki_by_title}

    monkeypatch.setattr(
        M, "_load_abilities",
        lambda patch: {"meraki_content_patch": "25.15",
                       "data": {"Maokai": meraki or {"Q": BRAMBLE_MERAKI}}},
    )
    monkeypatch.setattr(M, "_load_champion_names", lambda patch: {})
    monkeypatch.setattr(M, "fetch_pages", fake_fetch)
    return calls


# ------------------------------------------------------------- compare_champion


def test_redirect_page_is_a_page_skip_not_a_label_skip():
    pages: list = []
    labels: list = []
    findings = M.compare_champion(
        "Maokai", {"Q": BRAMBLE_MERAKI}, {"Bramble Smash": _redirect(NEW)},
        skipped_pages=pages, skipped_labels=labels,
    )
    assert findings == []
    assert labels == [], "a redirect is a rename, not a relabel"
    assert [(p["champion"], p["ability"], p["name"]) for p in pages] == [
        ("Maokai", "Q", "Bramble Smash")
    ]
    assert pages[0]["wiki_redirect"] == "Maokai/Bramble Slam"
    assert "redirect" in pages[0]["reason"]


def test_redirect_page_is_recorded_even_with_no_stored_labels():
    """The silent case: no base labels meant no skipped_labels row either."""
    pages: list = []
    M.compare_champion(
        "Maokai", {"E": SAPLING_MERAKI}, {"Sapling Toss": _redirect(NEW)},
        skipped_pages=pages,
    )
    assert [p["name"] for p in pages] == ["Sapling Toss"]


def test_mid_text_redirect_word_is_not_a_redirect():
    """Negative control: only a leading ``#REDIRECT`` makes a page a redirect."""
    pages: list = []
    findings = M.compare_champion(
        "Maokai", {"Q": BRAMBLE_MERAKI},
        {"Bramble Smash": BRAMBLE_WIKI + "<!-- #REDIRECT [[" + NEW + "]] -->\n"},
        skipped_pages=pages,
    )
    assert pages == []
    assert {f["field"] for f in findings} == {"base:Magic Damage"}


# ------------------------------------------------------------- run(): one hop


def test_run_follows_one_redirect_hop_and_compares_the_target(monkeypatch):
    calls = _stub_run(monkeypatch, {OLD: _redirect(NEW), NEW: BRAMBLE_WIKI})
    rep = M.run("16.21.1")

    assert calls == [[OLD], [NEW]]
    assert rep["stale_champions"] == ["Maokai"]
    assert rep["_skipped_pages"] == 0
    assert rep["_skipped_labels"] == 0
    rows = rep["findings"]
    assert [r["field"] for r in rows] == ["base:Magic Damage"]
    assert rows[0]["wiki"] == [75.0, 255.0]
    assert rows[0]["wiki_redirect"] == "Maokai/Bramble Slam"


def test_run_label_skip_through_a_redirect_names_it(monkeypatch):
    _stub_run(monkeypatch, {OLD: _redirect(NEW), NEW: BRAMBLE_WIKI_RELABELLED})
    rep = M.run("16.21.1")

    assert rep["_skipped_labels"] == 1
    assert rep["skipped_labels"][0]["label"] == "Magic Damage"
    assert rep["skipped_labels"][0]["wiki_redirect"] == "Maokai/Bramble Slam"


def test_run_does_not_refetch_a_target_it_already_has(monkeypatch):
    """Both titles requested in the first batch: no second round trip."""
    meraki = {
        "Q": BRAMBLE_MERAKI,
        "W": [dict(BRAMBLE_MERAKI[0], key="W", name="Bramble Slam")],
    }
    calls = _stub_run(
        monkeypatch, {OLD: _redirect(NEW), NEW: BRAMBLE_WIKI}, meraki=meraki
    )
    rep = M.run("16.21.1")

    assert len(calls) == 1
    by_ability = {r["ability"]: r for r in rep["findings"]}
    assert by_ability["Q"]["wiki_redirect"] == "Maokai/Bramble Slam"
    assert "wiki_redirect" not in by_ability["W"]


def test_run_missing_redirect_target_is_a_page_skip(monkeypatch):
    calls = _stub_run(monkeypatch, {OLD: _redirect(NEW)})
    rep = M.run("16.21.1")

    assert calls == [[OLD], [NEW]]
    assert rep["findings"] == []
    assert rep["_skipped_labels"] == 0
    assert rep["_skipped_pages"] == 1
    assert rep["skipped_pages"][0]["wiki_redirect"] == "Maokai/Bramble Slam"
    assert rep["skipped_champions"] == ["Maokai"]


def test_run_follows_exactly_one_hop(monkeypatch):
    """A double redirect is recorded at its second target, not chased."""
    calls = _stub_run(
        monkeypatch,
        {OLD: _redirect(NEW), NEW: _redirect(THIRD), THIRD: BRAMBLE_WIKI},
    )
    rep = M.run("16.21.1")

    assert calls == [[OLD], [NEW]]
    assert rep["findings"] == []
    assert rep["_skipped_labels"] == 0
    assert rep["_skipped_pages"] == 1
    assert rep["skipped_pages"][0]["wiki_redirect"] == "Maokai/Bramble Strike"


def test_run_plain_page_carries_no_redirect_marker(monkeypatch):
    """Negative control: the ordinary path is untouched."""
    calls = _stub_run(monkeypatch, {OLD: BRAMBLE_WIKI})
    rep = M.run("16.21.1")

    assert calls == [[OLD]]
    assert rep["stale_champions"] == ["Maokai"]
    assert all("wiki_redirect" not in r for r in rep["findings"])


def test_report_note_documents_the_redirect_rule(monkeypatch):
    _stub_run(monkeypatch, {OLD: BRAMBLE_WIKI})
    assert "wiki_redirect" in M.run("16.21.1")["_note"]
