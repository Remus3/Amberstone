"""Guard: the R190 kit magic-pen catalog test cites by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0 (cited -> line before this edit).
test_kit_magic_pen_catalog_r190.py rests its "kit pen is a separate axis"
argument on one line cite that had drifted: ``effects.effective_target_mr``
at ``effects.py:631`` -> a def at 929. A cite that resolves today rots on
the next insert above it, so it goes.

The tests below pin the claim itself: ``effective_target_mr`` takes only a
target MR and an iterable of ``ItemEffect`` objects - no champion id, no
kit lane - so a new parameter turns this red rather than leaving the
prose stale.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from agents.daemon_slayer import effects

REPO = Path(__file__).resolve().parent.parent
TARGET = (
    REPO / "agents" / "daemon_slayer" / "tests" / "test_kit_magic_pen_catalog_r190.py"
)
# ``effects.py:631``. Not the port shape ``:8860``, which is no cite.
_LINE_CITE = re.compile(r"\w\.(?:py|md):\d|\bat line \d")


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_pattern_matches_the_rotted_shape():
    assert _LINE_CITE.search("``ItemEffect`` objects (effects.py:631). There is")
    for sample in (
        "``ItemEffect`` objects (``effects.effective_target_mr``). There is",
        "DS ``:8860`` serves the main checkout",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_target():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(_source(TARGET).splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_target_names_the_symbol():
    assert "effects.effective_target_mr(target_mr, effects)" in _source(TARGET)


def test_effective_target_mr_takes_only_mr_and_item_effects():
    sig = inspect.signature(effects.effective_target_mr)
    assert list(sig.parameters) == ["target_mr", "effects"], sig
    annotation = str(sig.parameters["effects"].annotation)
    assert "ItemEffect" in annotation, annotation
