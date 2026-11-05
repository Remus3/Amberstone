"""Closing guard for RM-1053: no tracked .py cites ANY DS engine module by line (RM-1053).

RM-1053 converted `<engine>.py:<n>` line cites to symbol cites one module
family at a time, each with its own ``*_s144d3x`` guard, and the repo-wide
``test_engine_line_cites_repo_wide_s144d33`` closed the three scorer modules
``ability_dps`` / ``dps`` / ``hps``. This module closes the rest: the module
list is DERIVED FROM DISK (every ``agents/daemon_slayer/*.py`` except the
package ``__init__``), so a module added later is covered with no edit here.

Measured 2026-11-04 at ENGINE 1.290.0 over every tracked ``*.py`` that
``tests/_repo_walk`` reaches, outside the dated ``*_s144d3x`` guards: 8 live
cites remained (rank, server, data_loader, cc_conditional, ability_hps and a
``_per_spell_cc`` colon cite), all in test comments. They are now symbol cites.

Two kinds of file are NOT swept, on purpose:

* the ``*_s144d3<digit>.py`` guards: each records the old cite it retired,
  dated and true when written (the repo-wide guard above counts them).
* ``_DATED_RECORDS`` below: two files that quote an old cite as DATA, with the
  exact per-file line count. The table only shrinks.

Ambiguous names: ``server.py`` is also ``dashboard/server.py`` and
``mc/server.py``. A hit with a directory prefix counts only when that prefix
ends in ``daemon_slayer/``; a bare engine-file cite with no directory counts
(it can only mean the engine in a bare comment, and none exists today).
"""
from __future__ import annotations

import functools
import re
from pathlib import Path

from tests import _repo_walk

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"

_MODULES = tuple(
    sorted((p.stem for p in DS.glob("*.py") if p.stem != "__init__"), key=len, reverse=True)
)
_ALT = "|".join(re.escape(m) for m in _MODULES)

# <path-prefix?><module>.py:<digit>   or   <module>:<2+ digits> after a dot.
_LINE_CITE = re.compile(
    r"(?<![\w/.\-])(?P<path>(?:[\w.\-]+/)*)(?P<mod>" + _ALT
    + r")\.py[`'\"]*(?::~?L?|:\s~|\s?#L)\d"
)
_DOTTED_CITE = re.compile(
    r"daemon_slayer\.(?P<mod>" + _ALT + r"):\d"
)
_WORD_CITE = re.compile(
    r"(?<![\w/.\-])(?:[\w.\-]+/)*(?:" + _ALT + r")\.py[`'\")\]]*,?\s+(?:\(\s*)?(?:around\s+|near\s+|at\s+)?(?:lines?|L|ln)\s*\.?\s*~?\d"
)

# Dated guards that record a retired cite; matched by file name.
_GUARD_NAME = re.compile(r"_s144d3\d\.py$")

# Files quoting an old cite as DATA, with the exact count of matching lines.
_DATED_RECORDS = {
    # the s144d19 guard names the cite the headless-ds doc used to carry
    "tests/test_headless_ds_doc_citations_s144d19.py": 1,
    # a fixture sample of a retired mirror path
    "tests/test_citation_drift_guard_rm171.py": 1,
}


def _line_has_cite(line: str) -> bool:
    for m in _LINE_CITE.finditer(line):
        prefix = m.group("path")
        if prefix == "" or prefix.endswith("daemon_slayer/"):
            return True
    return bool(_DOTTED_CITE.search(line) or _WORD_CITE.search(line))


@functools.lru_cache(maxsize=1)
def _hits() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in _repo_walk.iter_repo_files(REPO, ("*.py",)):
        if _GUARD_NAME.search(path.name):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        n = sum(1 for line in text.splitlines() if _line_has_cite(line))
        if n:
            counts[_repo_walk.relative_posix(path, REPO)] = n
    return counts


def test_module_list_is_derived_from_disk_and_not_vacuous():
    assert len(_MODULES) > 50, len(_MODULES)
    for name in ("rank", "server", "data_loader", "cc_conditional", "ability_hps",
                 "_per_spell_cc", "effects", "_effects_types", "_effects_data"):
        assert name in _MODULES, name
    assert "__init__" not in _MODULES
    files = {p.resolve() for p in _repo_walk.iter_repo_files(REPO, ("*.py",))}
    assert (DS / "rank.py").resolve() in files
    assert len(files) > 500, len(files)


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "(rank" + ".py:339)",
        "agents/daemon_slayer/data_loader" + ".py:133",
        "server" + ".py:636",
        "cc_conditional" + ".py:458.",
        "agents.daemon_slayer._per_spell_cc" + ":778",
        "ability_hps" + ".py lines 289-324",
        "agents/daemon_slayer/_effects_data" + ".py:3257",
        "rank" + ".py:L12",
        "`rank" + ".py`:339",
        "rank" + ".py#L339",
        "rank" + ".py (line 339)",
        "rank" + ".py around line 339",
        "rank" + ".py: ~339",
    ):
        assert _line_has_cite(sample), sample


def test_pattern_ignores_other_files_and_symbol_cites():
    for sample in (
        "dashboard/server" + ".py:35",
        "mc/server" + ".py:36",
        "`rank.py` `rank_items`",
        "rank.rank_items",
        "see rank.py",
        "SPEC:109-114",
        "_per_spell_cc._PER_SPELL_CC_DURATIONS",
        "myrank" + ".py:3",
        "the ranking.py:3 helper",
        "ehp" + ".py: 3114's HSP amps the pool",
    ):
        assert not _line_has_cite(sample), sample


def test_dated_records_exist_and_still_carry_their_count():
    hits = _hits()
    drift = {
        rel: (n, hits.get(rel, 0))
        for rel, n in _DATED_RECORDS.items()
        if hits.get(rel, 0) != n
    }
    assert drift == {}, "(recorded, now); lower the table, never raise it: " + repr(drift)


def test_no_line_cites_into_the_engine_beyond_the_dated_records():
    new = {rel: n for rel, n in _hits().items() if rel not in _DATED_RECORDS}
    assert new == {}, "cite DS engine modules by symbol, not by line: " + repr(new)
