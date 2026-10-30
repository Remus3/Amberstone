"""Guard: the RM-330 roster-key test cites its two canonicalizers by symbol (aa).

Measured 2026-10-30 at ENGINE 1.290.0, re-deriving the RM-1053 "DS test
lines" residue with guard v's pattern over agents/daemon_slayer/tests. The
``test_roster_key_id_only_contract_rm330.py`` docstring cited its two
client-side canonicalizers by bare line number, and both had drifted:

- ``core/archetype_picks.canonical_champion_id`` was cited at ``:400`` (the
  def now opens further down);
- ``core/daemon_slayer_client._canon_champ_key`` was cited at ``:2103`` (the
  def now opens far further down).

The docstring also called them two independent canonicalizers, but the
second reuses the first (a lazy import of ``canonical_champion_id``) rather
than carrying its own alias dict. The tests below pin the cites, that
correction, and the facts the docstring restates, by symbol.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from core import archetype_picks, daemon_slayer_client

REPO = Path(__file__).resolve().parent.parent
TARGET = (
    REPO / "agents" / "daemon_slayer" / "tests"
    / "test_roster_key_id_only_contract_rm330.py"
)
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|(?<![\w.]):\d|\blines? \d")
_NOT_A_CITE = re.compile(r"\[:\d+\]|(?<!\w):8860\b|%:\d+%|-lines? (?=\d)")

SYMBOLS = (
    "``core/archetype_picks.canonical_champion_id``, written to bridge "
    "Live Client display names to the engine's canonical-id registries",
    "``core/daemon_slayer_client._canon_champ_key`` (RM-95), which reuses "
    "the first rather than carrying its own alias dict",
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_pattern_matches_the_old_shapes():
    for sample in (
        "``core/archetype_picks.canonical_champion_id`` (:400), written to",
        "``core/daemon_slayer_client._canon_champ_key`` (RM-95, :2103).",
    ):
        assert _LINE_CITE.search(_NOT_A_CITE.sub("", sample)), sample
    for sample in SYMBOLS:
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left():
    text = TARGET.read_text(encoding="utf-8")
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(_NOT_A_CITE.sub("", line))
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_names_the_symbols():
    flat = _flat(TARGET.read_text(encoding="utf-8"))
    for symbol in SYMBOLS:
        assert symbol in flat, symbol


def test_canonical_champion_id_bridges_display_names():
    doc = _flat(inspect.getdoc(archetype_picks.canonical_champion_id) or "")
    assert (
        "to bridge Live Client display names to the DS engine's "
        "canonical-id registries"
    ) in doc


def test_canon_champ_key_reuses_canonical_champion_id():
    src = _flat(inspect.getsource(daemon_slayer_client._canon_champ_key))
    assert "(RM-95)" in src
    assert "from core.archetype_picks import canonical_champion_id" in src
    assert "resolved = canonical_champion_id(s) or s" in src
