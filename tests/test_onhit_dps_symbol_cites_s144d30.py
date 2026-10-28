"""Guard: no tracked .py file cites ``onhit_dps.py`` by line number (RM-1050).

Measured 2026-10-28 at ENGINE 1.290.0 over the 19 ``onhit_dps.py:<n>`` cites in
tracked .py files. The 8 ``:494-496`` / ``:501-504`` contract cites (burst.py,
ehp.py, rank.py, _rank_mage.py) named lines that now hold the
``OnhitDpsRankedItem(...)`` row construction, ``kit_conversion.py`` cited
``:505`` for a ``"SpellDamage" in tags`` test now at :525 and ``:316-329`` for
``_onhit_ap_axis`` now at :336, and ``:143`` / ``:369`` / ``:434`` / ``:456``
were each off by 1 to 104 lines. Only ``:315-324`` still overlapped its
comment block, and ``test_onhit_dps.py:90-96`` still named its test but
described a shape that test lost on 2026-07-18. A line cite into a file other
commits keep editing resolves to SOME line forever, so it never fails loudly;
it just points at the wrong code. The fix is to cite by symbol
(``rank_items_by_onhit``, ``_coherence_key``, ``_onhit_ap_axis``,
``compute_onhit_dps``) and this guard keeps a new line cite from creeping back.

Scope: tracked ``*.py`` files only. ``agents/daemon_slayer/CHANGELOG.md`` and
the docs ledgers are dated records whose line cites were true when written;
they are not swept.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests import _repo_walk

REPO = Path(__file__).resolve().parent.parent
ONHIT = REPO / "agents" / "daemon_slayer" / "onhit_dps.py"

# Matches ``onhit_dps.py:494`` and ``test_onhit_dps.py:90`` alike; both name a
# file whose line numbers move under the citer.
_LINE_CITE = re.compile(r"onhit_dps\.py:\d")

# The symbols the replacement cites name. If one is renamed the prose that
# cites it goes stale the same way a line cite does, so pin them here.
_CITED_SYMBOLS = (
    "def compute_onhit_dps(",
    "def rank_items_by_onhit(",
    "def _onhit_ap_axis(",
    "def _coherence_key(",
    'or "SpellDamage" in tags or',
    "ap_ad_coherence: float = 0.0,",
    "if len(current_ids) >= slot_count:",
    "onhit_dps=ability_dps + auto_dps,",
)


def _offenders() -> list[str]:
    hits: list[str] = []
    for path in _repo_walk.iter_repo_files(REPO, ("*.py",)):
        if path.resolve() == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if _LINE_CITE.search(line):
                rel = _repo_walk.relative_posix(path, REPO)
                hits.append(f"{rel}:{lineno}: {line.strip()}")
    return hits


def test_walk_is_not_vacuous():
    files = {p.resolve() for p in _repo_walk.iter_repo_files(REPO, ("*.py",))}
    assert ONHIT.resolve() in files
    assert len(files) > 500


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "(onhit_dps.py:494-496)",
        "``onhit_dps.py:505``",
        "test_onhit_dps.py:90-96",
        "agents/daemon_slayer/onhit_dps.py:434",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in ("onhit_dps.py", "onhit_dps.rank_items_by_onhit", "onhit_dps.py's"):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_number_cites_into_onhit_dps():
    offenders = _offenders()
    assert offenders == [], (
        "cite onhit_dps.py by symbol, not by line number:\n  "
        + "\n  ".join(offenders)
    )


def test_cited_symbols_exist():
    text = ONHIT.read_text(encoding="utf-8")
    missing = [s for s in _CITED_SYMBOLS if s not in text]
    assert missing == [], f"symbols cited by name are gone from onhit_dps.py: {missing}"
