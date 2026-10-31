"""Guard: three more DS engine modules cite by symbol or row, not line (ae).

Measured 2026-10-31 at ENGINE 1.290.0, re-deriving the RM-1053 residue
filed by cycle 124:

- ``_ability_wiki_damage_registry.py`` cited the extractor as
  ``(``:108-110``)`` for the wiki host and endpoint. Line 108 is now a
  comment; the values are ``WIKI_HOST`` and ``WIKI_API`` (the sibling cite in
  ``_ability_wiki_form_damage.py`` was fixed the same way by guard u).
- ``_passive_flat_mitigation_overrides.py`` cited "its docstring lines 64-69"
  of ``_passive_mitigation_overrides.py``. That range still resolves, but
  nothing fenced it: it is the PER-INSTANCE FLAT-AMOUNT bullet under
  "Documented EXCLUSIONS" in that module docstring.
- ``_passive_damage_overrides.py`` (the Mordekaiser Darkness Rise entry) cited
  ``docs/DS_SWEEP_TRACKER.md:839``. That line is now a batch26 roll-up; the
  numbers sit in the tracker's Mordekaiser row, and the quoted text was a
  paraphrase, not the row's words.

Not taken: ``server.py``'s ``OPEN_ITEMS_REVIEW_2026-07-25.md:451-457`` cite.
It points into a dated, never-edited archive and was ruled to stay by the
RM-46 route-plumb guard.

The tests below pin the rewritten prose and the facts it restates.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
EXTRACTOR = REPO / "tools" / "daemon_slayer_wiki_ability_extract.py"
TRACKER = REPO / "docs" / "DS_SWEEP_TRACKER.md"

_LINE_CITE = re.compile(
    r"(?<![\w.])\w+\.(?:py|md|json):\d|(?<![\w.]):\d|\blines? \d"
)
# Ratio notation ("1%:2%") and the DS port are not line cites.
_NOT_A_CITE = re.compile(r"%:\d|(?<!\w):8860\b")

TARGETS = {
    "_ability_wiki_damage_registry.py": (
        "endpoint ``tools/daemon_slayer_wiki_ability_extract.py`` builds as "
        "``WIKI_API`` from ``WIKI_HOST``.",
    ),
    "_passive_flat_mitigation_overrides.py": (
        "registry deliberately EXCLUDED (the PER-INSTANCE FLAT-AMOUNT bullet "
        'under "Documented EXCLUSIONS" in its module docstring) the '
        "survivability class",
    ),
    "_passive_damage_overrides.py": (
        "The Mordekaiser row of docs/DS_SWEEP_TRACKER.md records the same "
        "numbers (5 (+30% AP) (+1-5% of target MAXIMUM health) per second, "
        "as 8 ticks/sec at 0.125s), so the two AGREE",
    ),
}

OLD_SHAPES = (
    "(``:108-110``). The raw ``|leveling`` line is quoted verbatim beside every",
    "registry deliberately EXCLUDED (its docstring lines 64-69) the survivability",
    '# docs/DS_SWEEP_TRACKER.md:839 records the same numbers ("5 + 30% AP +',
)


def _flat(text: str) -> str:
    return " ".join(text.replace("#", " ").split())


def _hits(text: str) -> list[str]:
    return [
        f"{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(_NOT_A_CITE.sub("", line))
    ]


def test_pattern_matches_the_old_shapes():
    for sample in OLD_SHAPES:
        assert _LINE_CITE.search(_NOT_A_CITE.sub("", sample)), sample
    for phrases in TARGETS.values():
        for sample in phrases:
            assert not _LINE_CITE.search(_NOT_A_CITE.sub("", sample)), sample
    for sample in ("Renata P Leverage (1%:2% level", "a live ``:8860`` at"):
        assert not _LINE_CITE.search(_NOT_A_CITE.sub("", sample)), sample


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    hits = _hits((DS / name).read_text(encoding="utf-8"))
    assert not hits, f"{name}: cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    flat = _flat((DS / name).read_text(encoding="utf-8"))
    for phrase in TARGETS[name]:
        assert phrase in flat, f"{name}: {phrase}"


def test_extractor_constants_are_as_cited():
    tree = ast.parse(EXTRACTOR.read_text(encoding="utf-8"))
    assigns = {
        t.id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name)
    }
    assert ast.literal_eval(assigns["WIKI_HOST"]) == (
        "https://wiki.leagueoflegends.com"
    )
    assert ast.unparse(assigns["WIKI_API"]) == "WIKI_HOST + '/en-us/api.php'"


def test_percent_registry_excludes_the_flat_class():
    tree = ast.parse(
        (DS / "_passive_mitigation_overrides.py").read_text(encoding="utf-8")
    )
    doc = " ".join((ast.get_docstring(tree) or "").split())
    excl = doc[doc.index("Documented EXCLUSIONS"):]
    bullet = excl[excl.index("- PER-INSTANCE FLAT-AMOUNT"):]
    bullet = bullet[:bullet.index("- DR PERCENT NOT IN EFFECTS TEXT")]
    for name in ("Fizz P", "Amumu E", "Leona W"):
        assert name in bullet, name


def test_tracker_mordekaiser_row_carries_the_numbers():
    rows = [
        line
        for line in TRACKER.read_text(encoding="utf-8").splitlines()
        if line.startswith("- **Mordekaiser** - ")
    ]
    assert len(rows) == 1
    row = rows[0].replace("**", "")
    assert (
        "5 (+30% AP) (+1-5% of target MAXIMUM health) per second as "
        "8 ticks/sec at 0.125s"
    ) in row
