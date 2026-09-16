"""Gate 6's name grammar, parametrised over the CHANNEL.md grammar table.

RM five-way-arm criterion (d). Gate 6 used to hardcode one regex while
`docs/CHANNEL.md` separately recorded, in prose, what RC's gate 6 does for each
observed filename variant. Nothing bound the two, so either could move alone.

These arms bind them. The code table is
`tools.inbox_responder_runner.NAME_GRAMMAR_TABLE`; the doc table is the one
inside section 6 of `docs/CHANNEL.md`, located here by HEADER TEXT rather than
by line number.

WHAT THIS IS NOT. It is not a widening. Every disposition ships exactly as the
doc records it today - Variant A, Variant B and Variant C all REFUSE - because
the doc is byte-pinned in five repositories and flipping a cell is a
CHANNEL_VERSION 2 joint re-pin, which is five operator acts and not one slice's.
The parametrisation buys a one-cell edit under a guard instead of a regex
rewrite with a doc that silently disagrees.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import tools.inbox_responder_runner as runner  # noqa: E402
from tools import sibling_name_sweep as sweep  # noqa: E402

CHANNEL_DOC = "docs/CHANNEL.md"

# The one environment capability any arm here may skip on.
_GIT = shutil.which("git")


# ---------------------------------------------------------------------------
# The FROZEN old predicate: gate 6's name half exactly as it stood at
# 502d0f130, written out here rather than imported, so the identity arm below
# compares two independent implementations instead of re-calling the new one.
# ---------------------------------------------------------------------------

_FROZEN_NOTE_NAME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}-\d{4}-from-[A-Z]{2,4}-[A-Za-z0-9._-]{1,160}\.md$"
)
_FROZEN_NOTE_NAME_MAX = 200


def _frozen_name_grammar_bad(name: str) -> bool:
    """`name-grammar` is appended when this is True. Frozen copy of 502d0f130."""
    return (
        not name.isascii()
        or len(name) > _FROZEN_NOTE_NAME_MAX
        or not _FROZEN_NOTE_NAME_RE.fullmatch(name)
    )


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

_TOPIC_160 = "t" * 160
_TOPIC_161 = "t" * 161
_TOPIC_201 = "t" * 201

SYNTHETIC_NAMES = (
    # The four doc rows, restated here so the corpus covers them even when the
    # doc parse is what is broken.
    "2026-09-15-0930-from-RC-FYI-example-topic.md",
    "2026-09-15-from-RC-FYI-example-topic.md",
    "from-RC-2026-09-15-0930-FYI-example-topic.md",
    "2026-09-15-0930-from-RC-FYI-example-topic.txt",
    # Topic-group edges: 160 admits, 161 refuses, 201 refuses on the group
    # BEFORE the length cap can matter.
    f"2026-09-15-0930-from-RC-{_TOPIC_160}.md",
    f"2026-09-15-0930-from-RC-{_TOPIC_161}.md",
    f"2026-09-15-0930-from-RC-{_TOPIC_201}.md",
    # Empty topic.
    "2026-09-15-0930-from-RC-.md",
    # Sender-code length and case.
    "2026-09-15-0930-from-R-topic.md",
    "2026-09-15-0930-from-ABCD-topic.md",
    "2026-09-15-0930-from-ABCDE-topic.md",
    "2026-09-15-0930-from-rc-topic.md",
    # Date and time group shapes.
    "2026-09-15-093-from-RC-topic.md",
    "2026-09-15-09300-from-RC-topic.md",
    "26-09-15-0930-from-RC-topic.md",
    "2026-9-15-0930-from-RC-topic.md",
    "2026-09-15-0930-from-RC-topic.MD",
    "2026-09-15-0930-from-RC-topic",
    "2026-09-15-0930-from-RC-topic.md.txt",
    # Separator and whitespace shapes.
    "2026-09-15-0930-from-RC topic.md",
    " 2026-09-15-0930-from-RC-topic.md",
    "2026-09-15-0930-from-RC-topic.md ",
    "2026-09-15-0930-fromRC-topic.md",
    # Non-ASCII, including a lone surrogate of the shape NTFS permits.
    "2026-09-15-0930-from-RC-t\\u00f6pic.md",
    "2026-09-15-0930-from-RC-topic\\u2014dash.md",
    "2026-09-15-0930-from-RC-topic\udc80.md",
    # Over the OUTER cap on a name that is otherwise well shaped except the
    # topic group, which is what actually refuses it.
    f"2026-09-15-0930-from-RC-{'a' * 220}.md",
    # Directory and payload shapes seen beside the notes.
    "responder_held",
    "a-directory-name",
    "BOUNCE-2026-09-15-0930-from-RC-topic.md.txt",
    # RC's own reply shape, which siblings parse as from RC.
    "2026-09-15-0930-from-RC-RESPONDER-re-0123456789ab.md",
    # Degenerate.
    "",
    ".md",
    "-",
)


# ---------------------------------------------------------------------------
# The FROZEN half of the corpus, captured from the live channel and checked in.
#
# WHY FROZEN AND NOT HARVESTED. `moon_sync_inbox/` is GITIGNORED, so it exists
# exactly where somebody created it: populated in the primary tree, ABSENT in
# every worktree and in CI. A corpus read from it is a property of WHICH
# CHECKOUT RAN THE TEST, not of the repository - same bytes, same commit,
# opposite verdict. RC's default working shape is parallel agents in isolated
# worktrees, so that is the normal case here, not a corner.
#
# WHY SHAPES AND NOT THE NAMES THEMSELVES. This repository is PUBLIC, and the
# live names are channel traffic: `docs/CHANNEL.md` section 6 says in its own
# words that its examples are synthetic and that no live note name appears
# there. MEASURED before deciding, with RC's own armed `tools/sibling_name_sweep`
# over the 358 live names read on Legion at 502d0f130: TWO of them trip the
# sweep. Checking the names in verbatim would have published those two.
#
# So each live name is projected to a SHAPE: every digit becomes `0`, every
# lowercase letter `a`, every uppercase letter `A`, and every other character -
# each `-`, `.`, `_`, the literal `from`, the extension - is kept in place. The
# projection is VERDICT-FAITHFUL BY MEASUREMENT, not by argument: over all 358
# live names, `_frozen_name_grammar_bad(name) == _frozen_name_grammar_bad(
# shape)` for every one, 0 divergences. Content is erased; every property gate
# 6 can see - length, character class, separator positions, code case and
# length, extension - is preserved exactly.
#
# The 358 names projected to 353 distinct shapes; what is checked in is every
# REFUSED shape (46, the interesting half) plus one ADMITTED shape per distinct
# (length, sender-code) pair (134), so every observed length is represented.
FROZEN_LIVE_SHAPES = (
    "0000-00-00-0000-from-AA-00-aa-00-aaaaaaaaa-aaaa-aaaa-aaa-aa-aaaaa-aaaa-aaa-aaaaa.md",
    "0000-00-00-0000-from-AA-0000-0000-aaaaaaaa-aaa-a-aaaa-aaaaaaaaaa.md",
    "0000-00-00-0000-from-AA-0000-0000-aaaaaaaa-aaa-a-aaaaaaaaaa.md",
    "0000-00-00-0000-from-AA-0000-0000-aaaaaaaa-aaa-aaa-aaaa-aaaaa-aaaa-aaa-aaaaa-aa.md",
    "0000-00-00-0000-from-AA-0000-0000-aaaaaaaa-aaa-aaaaa-aaaaaaaaaa.md",
    "0000-00-00-0000-from-AA-A-AA-A-AA-AAAA-aa-aaaaa-aaa-aaaaaaaa-aaaaaaaaaaaa-aaa-aaa-00-aaaaaaaa-aaaaaa-aaa-aa-AAA-aaa-aaaaaa-aaaaaa.md",
    "0000-00-00-0000-from-AA-A0-0-AAAAAAAA-aaaa-aaaaaa-aaa-aaa-aaaaaaaaaaa-aa-aaaaaaaaa.md",
    "0000-00-00-0000-from-AA-A0-aaa-aaaaaaaa-aa-0000-00-00-aaa-aaaaaaaa-from-aaa-aa-aaa-aaaaaaa-aaaaaaaaa.md",
    "0000-00-00-0000-from-AA-AA-A0-0-aaa-aaaaaaaa-aaaaa-aaaaaaa-aaaaaaaaaaaaa-aa-aaaaa-aaaaaaaaaaaa-aaaa-aa-aaaaaaaaa-aaaa-aaa-aaaaaaaaa-aa-aaaaa-aaaaaa.md",
    "0000-00-00-0000-from-AA-AA-AAAAA-AA-AAA-AAAA-aa-aaaaaaaa-aaaaaaaaaaa-a-aaaaaaaa-aaaa-aaaa-aaa-aaaaaaaa-aaaaa-aaaaaa-aaaaaa-aaaa-aaa-aaaaaaaa.md",
    "0000-00-00-0000-from-AA-AA-aaa-aaa-aaa-aaaaaaa-aaaa-aaa-aaa-aaa-aaaaaaaaaa-aa-aaa-aaaa-aaaaa-aa-aaa-aaa-aaaa-aaaaaaaa.md",
    "0000-00-00-0000-from-AA-AAA-000a0aa000aa-aaaaaaa-aa-a0-aaaaaaaaaaa-aaa-aaaaaaa-a0-aa-aaaaaaa.md",
    "0000-00-00-0000-from-AA-AAA-0a0aa000a000-AAAAAAAAAA-aaa-aaa-0-aaaaaaa-aaa-aaaaaaaa-aa-a-aaaaaaaa-aaa-aa-aaaaa-aa-a-aaaaaaa-aaaaaaaa.md",
    "0000-00-00-0000-from-AA-AAA-AAA-AAAAAAAAAA-AAAAAA-AAA-AAAAAAAAAAA-AAAA-aa-AA-aa-AAA-aaaaaaa-AAA-00-aaaa.md",
    "0000-00-00-0000-from-AA-AAA-AAAAA-AAA-AAAAAAAAA-aaa-aaaa-aaaaaaaaa-aaa-aaa-aaaaaaaaa.md",
    "0000-00-00-0000-from-AA-AAA-AAAAA-aaaa-aaaaa-aaaaaaaaaaaaaaaaaaa-aa-a0-0-aaaa-aaaaa-0-aaaaaa-aaa-aaaaaa-aaaaaaa.md",
    "0000-00-00-0000-from-AA-AAA-AAAAAA-00-aaaa-aaa-aaaaaa-aaa-aaa-aaa-aaaaa-aaaaaaa-aaaaaaaaaa-aaaaaaa-aa-aaaa-aaaaaa.md",
    "0000-00-00-0000-from-AA-AAA-a-aaaaaa-aaaaa-aa-aaa-aaaa-aa-aaa-aaaa-aaa-aaaaaaa.md",
    "0000-00-00-0000-from-AA-AAA-aa-aaa-aaaaaaaa-aaaaa-aaaa-AA-aaaaaaaaaa-aa-A0-A0-A0-aaa-A0-aaaaaaa-aaa-aaa-aaaaaaaa-aaaaa-aa-aaaa.md",
    "0000-00-00-0000-from-AA-AAA-aa-aaaaa-aaaaaaaaa-AA-aa-a-aaaaaaa-aaa-aaa-aaaaaa-aaaa-aaaaaaaa-aaaa-aaaaaa-aaa-aaaaaa.md",
    "0000-00-00-0000-from-AA-AAA-aaaa-aaaaaa-aaaa-aaaaa-aaa-aaaaaaaaa-aaaaaa-aaa-aaaaaaaaa.md",
    "0000-00-00-0000-from-AA-AAA-aaaa-aaaaaaaaa-aaaaaaa-aaaaaaaaaa-aaa-aa-aaaaaaa-aa-aaaaa-aa-aaaaaaaaa.md",
    "0000-00-00-0000-from-AA-AAA-aaaaaa-aa-aaaaaa-aaaaaa-aaa-aaa-aaaa-aaaaaaa-aaaaaaa-aa-aaaaaaaaa-aa-aaaaaaaa-aaa-aaaaaa.md",
    "0000-00-00-0000-from-AA-AAA-aaaaaaaa-aaaaaa-aaaaa-aa-aaaaaaaa-aaaaaaaaaaa.md",
    "0000-00-00-0000-from-AA-AAA-aaaaaaaaa-aaa-aaaaaaa-aaaa-aaaaaa-0-aaaa-aaa-aaaaaaaaa-aa-a-aaaaa-aaaa-aaa-aa-aaaaaaaa-aaa-aaa-aaaaaaa-aaaaaa.md",
    "0000-00-00-0000-from-AA-AAA-aaaaaaaaaa-aa-aaaaaa-0-0-aaa-aaaaaaa-aa-aa-aaaaaaa-aaaaaaa-aaaaa-aaa-aaaa-aaaa.md",
    "0000-00-00-0000-from-AA-AAA-aaaaaaaaaa-aaa-aaaaaaaaaaaa-aaaaaaaaa-from-aaa-aaaaaaa-aaaa.md",
    "0000-00-00-0000-from-AA-AAAAA-A0-aaa-aaaaaa-0-aaaaaa-00a-aaa-aaa-aaaa-aaaaaaaaa-aa-aaaaaaaaaaa.md",
    "0000-00-00-0000-from-AA-AAAAA-AAAA.md",
    "0000-00-00-0000-from-AA-AAAAA-AAAAA-AAAAAA-aa-aaaa-AA-aaaa-aaa-aaaaaaaaaa-aaaaaaa-aaa-aaa-AAAAAA-aaaaa-aaa-AAAAAAAA.md",
    "0000-00-00-0000-from-AA-AAAAA-aa-aaaaa-aaaaaaaaa-aaa-aaaaaa-aa-aaa-aaaaaaa-aaa-aaa-aaaa-aaaaa.md",
    "0000-00-00-0000-from-AA-AAAAAA-0a0aa000a000-aa-aaaaaa-aaaaaa-aaa-aaaa-aaaaaaa-aaaaaaaa-aaa-aaaaaa-aaa-aaaa-aaaa-aaaa-aaa-aaaaa-aaaa-aaaa.md",
    "0000-00-00-0000-from-AA-AAAAAA-0a0aa000a000-aaa-aaaaaaaa-aaaa-aaaa-aaaa-aaa-aaaaa-aaa-aaaaaaa-aaaaa-aa-aaaa.md",
    "0000-00-00-0000-from-AA-AAAAAA-0a0aa000a000-aaaa-aaaaaaaa-aaaaaaaaa-aaa-aaaa-aaa-aaaaaa-aaa-aaaa-aaa-aaa.md",
    "0000-00-00-0000-from-AA-AAAAAA-a00a00a000aa-aa-aaaa-aaaaaa-aaaaa-aaaaa-aaa-aa-aaaa-aaaaaa-aaaaaaaa-aaaaaaaaaa-aa-aaaa-aa-0a0aa000a000.md",
    "0000-00-00-0000-from-AA-AAAAAA-aaa-aaaaaaaaaa-aaaa-aaa-aaaa-aaaaaa-aaa-aaa-aaaa-aaa-aaaaaaa.md",
    "0000-00-00-0000-from-AA-AAAAAA-aaaaa-aaaa-aaa-aaaaaaa-aaaa-aaaaa-aaa-aaaaaa.md",
    "0000-00-00-0000-from-AA-AAAAAA-aaaaa-aaaa-aaaaaaaa-aaaaa-aaaaaaaaaaa-aa-aaaaaaaa-aa-aaaaa.md",
    "0000-00-00-0000-from-AA-AAAAAA-aaaaaa-aa-aaaaaa-aaaaaa-aa-aaa-aaaa-aaa-aaaaaa-0-aaaaaaaa-aa-aaa-aaaaa.md",
    "0000-00-00-0000-from-AA-AAAAAA-aaaaaaa-aaaaaaa-aaa-aaaaaaa-aaaaa-aaa-aaaa-aaaa-AAAA.md",
    "0000-00-00-0000-from-AA-AAAAAA-aaaaaaaa-a0-a0-aaaaaaa-aaaa-aaa-aaaaaaaa.md",
    "0000-00-00-0000-from-AA-AAAAAA-aaaaaaaa-aaaaa-aaaaaa-aaaaaa-aaaa-aaaa-aaaa.md",
    "0000-00-00-0000-from-AA-AAAAAA-aaaaaaaa-aaaaa-aaaaaaa-aaa-aaaaa-aaaaa.md",
    "0000-00-00-0000-from-AA-AAAAAAA-a0-aaaaaaaa-aaaaaaaaa-aaa-aaaaaaa-aaaaaa.md",
    "0000-00-00-0000-from-AA-AAAAAAA-aaa-aaaa-aaaa-aaaa-aaaaaaaaaa-aaaaaaa-aa-aaa-AA-aaa-aa-aaaaa-aaa.md",
    "0000-00-00-0000-from-AA-AAAAAAA-aaaa-aaaaaa-aaa-aaaa-aaaaaa-aaa-aaaa-aaa-aaaa-aaaaaaa-aaaa-aa-aa-aaaaaaa-aaaa.md",
    "0000-00-00-0000-from-AA-AAAAAAA-aaaaaaa-a0-aa-aaaaaaa-aaaa-aa-aaaaaaaaaaa-aaa-aa-aaaa-aaa-aaaaaaaaa.md",
    "0000-00-00-0000-from-AA-AAAAAAAA-aaa-aaaa-aaa-aaa-aaaaaaa-aaaa-aaa-aaa-aaaaaa-aaa-aaaaaaaaaa-aaaaa-aaa-aaaaa.md",
    "0000-00-00-0000-from-AA-AAAAAAAA-aaaaa-aaaaaaa-aaa-aaaaa-aa-aaaa-aaaaa.md",
    "0000-00-00-0000-from-AA-AAAAAAAAA-aa-0a00aa0000a0.md",
    "0000-00-00-0000-from-AA-AAAAAAAAAA-0-aaaaa-aaaaa-aaaaaaaaa-aa-aaa-aaa-aaaaaaaaaa-aaaa-aaa-aaa-aaaa-aaaaa-aaaaaaaa-aaaa-aaa-aaaaaaa.md",
    "0000-00-00-0000-from-AA-AAAAAAAAAA-aa-aa-aaaaaa-aaa-aaaa-aaaaa-aaa-aa-aaa-aaaaaaa-aaa-aaaa-aaaaaaaa-aaaaa.md",
    "0000-00-00-0000-from-AA-AAAAAAAAAA-aa-aaa-aaa.md",
    "0000-00-00-0000-from-AA-AAAAAAAAAA-aa-aaaaaa-a-aaaaaaaaa-aaaa-aaa-aaa-aaaaaa-aaa-aaaaaaaaaaa-aa-aaaa-aaa-aaaaa.md",
    "0000-00-00-0000-from-AA-AAAAAAAAAA-aaa-A0-aaaa-aaaa-aaa-aaaaaaa-aaa-aaa-aaaa-aaaa.md",
    "0000-00-00-0000-from-AA-AAAAAAAAAA-aaa-aa-aaa-aaaaa-aaaaaaaa-aa-AAAAAAAAA-aa-aa-aaaaaa-aaa-aaaa.md",
    "0000-00-00-0000-from-AA-AAAAAAAAAA-aaa-aaa-aaaaa-aaaaa-aaaaaaa-aaaa-aaaa-aaaaaaaaa-aaaaaaaa-aaa-a-aaaa-aaaa-aaaaaaaaaa.md",
    "0000-00-00-0000-from-AA-AAAAAAAAAA-aaa-aaaaaaaaa-aaaaaa-aa-aaaaaaa-aaaaaaa-aaa-aaaaaaaaa.md",
    "0000-00-00-0000-from-AA-AAAAAAAAAA-aaaaa-aaaa-aaaaaa-aaaaaa-aaaaaa-aaaaaaaa-aaaaaaaaaa.md",
    "0000-00-00-0000-from-AA-AAAAAAAAAA-aaaaaa-aaa-aaaaaaa-aaaa-aaa-aaaaaaaaa-aa-aaaaaaaaaa-aaaaa-aaaa.md",
    "0000-00-00-0000-from-AA-AAAAAAAAAA-aaaaaa-aaaaa.md",
    "0000-00-00-0000-from-AA-a0-aaaaa-0-aaa-0a.md",
    "0000-00-00-0000-from-AA-aa-AAAAAAAA-aaa-aaaaaaa-aa-aaa-0000-aaaa-aa-aaaaaaaaa-aaa-aaaaaaaaa-aaaa-aaa-AA-aaaaaaaa.md",
    "0000-00-00-0000-from-AA-aa-aaa-aaaa-aaaa-aaaa-aa-AA-aaa-aaaa-aaaa-aa-aaaaaa-aaaa-aaaaa-aa-aa-aaa-a-aaaa-aaa-aaa-aaaaaaaaaa-aaaaa.md",
    "0000-00-00-0000-from-AA-aa-aaaaa-aa-aaaaaa-AA-aaa-AAAAAAAAA-aaaaaaa-aaa-aaaaaa-aaaaa-aaaaaaa-aa-AAAAAAAAAAAAA-aaa-aaaa-aa-aaa-aaaaaaa-aaa-aaaa.md",
    "0000-00-00-0000-from-AA-aa000-aaaa-aaa-aaaaa.md",
    "0000-00-00-0000-from-AA-aaa-AAAAA-aaaaaa-aaaaa-aaaa-aaaaaa-aaaaaaaaa.md",
    "0000-00-00-0000-from-AA-aaa-aaa-aaaa-0-0-aaaaa-aaa-aaaa-aaa-aaaaaaaaa-aa-aaa-aaaaa-aaa-aaa-aaaaaaaa-aa-aaaaaaaaaa-aa-aaa-aaa-aaaaaaaaaa.md",
    "0000-00-00-0000-from-AA-aaa-aaa-aaaaa-aa-aaa-aaa-aaaaa.md",
    "0000-00-00-0000-from-AA-aaa-aaaa-aaaaa-aaa-aaaa-aaa-AAA-AAAAAAA-aaa-aaa-aaaaaaaaaa-aaa-aaaaa-aaaaa-aaa-aaaaa-aa-aaaaaaa-aaaa.md",
    "0000-00-00-0000-from-AA-aaa-aaaaa-aaaaa.md",
    "0000-00-00-0000-from-AA-aaaa-aaaa-aaaaaa-aaaaaaa-aaa-aaa.md",
    "0000-00-00-0000-from-AA-aaaa-aaaaa-aaa-aaa-aa-aaaa-aaaaaa.md",
    "0000-00-00-0000-from-AA-aaaa-aaaaa-aaa-aaaa-AA-aaaa-aa-0-0-000.md",
    "0000-00-00-0000-from-AA-aaaa-aaaaa-aaa.md",
    "0000-00-00-0000-from-AA-aaaa-aaaaa-aaaaaaaaa-aaa-aaaa-aa-aaa-aa-aaaaaaa-aaaa.md",
    "0000-00-00-0000-from-AA-aaaa-aaaaa-aaaaaaaaaaa.md",
    "0000-00-00-0000-from-AA-aaaa-aaaaaaa-0-aa-aaaaa-aaaa-aaaaaaaaaa-aa-aaaa-aaaaa-aaa-aaa-aaaaaa-aaaa-aaa-aaaaaaa-aaaaaa-aa-aaaa-aaaaaaa.md",
    "0000-00-00-0000-from-AA-aaaa-aaaaaaaaa-aaa-aaaaa.md",
    "0000-00-00-0000-from-AA-aaaa-aaaaaaaaa-aaaaa-aaaa-aaaaa-aaaaaaaaa.md",
    "0000-00-00-0000-from-AA-aaaa0-aaaaaaaaaa.md",
    "0000-00-00-0000-from-AA-aaaaa-aaaa-AAAAAAA-aaa-aaaaaaaa-aaaa-aaaaaaa-aa-aaa-aaaaa-AA-aaaa-aaa-A0-aa-aaaaa-aaaa-aa-aaa-aaaa.md",
    "0000-00-00-0000-from-AA-aaaaa-aaaa-aaaaa-aaaa-aa-aa-aaaaaaa-aaaaaa.md",
    "0000-00-00-0000-from-AA-aaaaa-aaaaa-aaa-aaaa-aaaaa-aa.md",
    "0000-00-00-0000-from-AA-aaaaa-aaaaa-aaaaaaaa-aaaa-aaaaaaaa.md",
    "0000-00-00-0000-from-AA-aaaaa-aaaaa.md",
    "0000-00-00-0000-from-AA-aaaaa-aaaaaa.md",
    "0000-00-00-0000-from-AA-aaaaaa-aaa-aaaaaa-aaa-aaaa-0000.md",
    "0000-00-00-0000-from-AA-aaaaaa.md",
    "0000-00-00-0000-from-AA-aaaaaaa-aaaa-aaa-aa-aaaaaa.md",
    "0000-00-00-0000-from-AA-aaaaaaa-aaaaa-aaa-aa-aaaaaaa.md",
    "0000-00-00-0000-from-AA-aaaaaaaa-aaaaa-aaaaa-AA-aaaa-aaaa-aaaaaaaa-AAa-00-aaaaaaa-aaaaaaaaa-aaa-aaaa-aaaaaaaa-aaaaaaaaa.md",
    "0000-00-00-0000-from-AA-aaaaaaaa-aaaaa-aaaaaaa-aaaaa-aaa-aaaaa-aaaa.md",
    "0000-00-00-0000-from-AA-aaaaaaaaa-0-aaaaaaaa-aaa-aaaaaaaaa-aaaaaaa-aa-aaaaaaaa-aa-a-aaaaa-aaaaaaa-aaaaa-aaa-a-aaaaaaaa-aaaaaaaa-aaaaa-aaaaaaaa-aaa-aaaaaaa.md",
    "0000-00-00-0000-from-AA-aaaaaaaaa-aaaaaa-aa-aaa-aaaa-aaaa-aaaaaaaaa-aa-aaa-aaaaa-aaaaaaa-aaaaaaa-aa-aaa-aa-aaaa-aaa-aaa-aaa-aaaaaa-aaaa-aaaa-aaaa.md",
    "0000-00-00-0000-from-AAA-A0-aaaaaaaa-aaaa-aaaaaaaaa-aaaaa-aaaaa-aaaa-aaa-aaaa-aa-aaa-aaa-aaaa-aaaaa-aaa-aaaa.md",
    "0000-00-00-0000-from-AAA-AA-000-aaaaaaaa-aaaaaa-aaaaaaa-aaaaaaaaa-aaaa-a-aaaaaa-aaaa-aa-aaa-a-aaaa.md",
    "0000-00-00-0000-from-AAA-AA-aaaaaa-AAAAAAAA-aaa-aaaaaaaa-AA-aaa-aaaaa-aaaaa-aa-aa-aaaaa-aaa-aaa-aaaaaaaa-aaaa.md",
    "0000-00-00-0000-from-AAA-AAA-aa-aaa-aaaaaaaa-aaaaa-aaaa-aaaaa-aa-aaaaaaa-aaaa-aaa-aaaa-aaaaaaaaaaa-aa-A0-A0.md",
    "0000-00-00-0000-from-AAA-AAAAAA-0a0aa000a000-aaaa-aaaaaaaa-aaaaaaaaa-aaa-aaa-aa-aaaa-aaa-aaaaaaaaa-aaaaaaa-aaaa.md",
    "0000-00-00-0000-from-AAA-AAAAAA-a-aaaaaaa-aaaa-aaa-aaaaa-aaaaa-aaaaaaaa-aaaa-aaaaaaa.md",
    "0000-00-00-0000-from-AAA-AAAAAA-aaaaaa-aaaaaaaa-0000-aa-0000-aaaaa-aa-AA-aaaaa-aaa-aaa-aaaaaaa-aaaaa-aa-aaaaa-aaaaaaaaa.md",
    "0000-00-00-0000-from-AAA-AAAAAAA-aaa-aaaaaa-aaaaaaaa-aa-aaa-aaa-aaaa-aaa-aaaaa-aaaaaa-aaaaaaaaa-aaaaa-aa.md",
    "0000-00-00-0000-from-AAA-AAAAAAAA-AA-aaa-aaa-aaaa-aaaaaaaa-aaaaaaaa-aaaa-aaa-aaaaa-aaaa-aaaa.md",
    "0000-00-00-0000-from-AAA-AAAAAAAA-aaa-aaaaaa-aaa-aaaaaa-aaaa-aa-aaaaaa-aaa-aaaaaaaa-aaa-aa-aaaa-aaaaaaaaa-aa-aaa-aaaaaaa-aaaa.md",
    "0000-00-00-0000-from-AAA-AAAAAAAAA-AAAAAAAAAA-aaa-00-aaaaaaaa-aaaaaa-aa-aaa-aaaaaa-aaa-aa-aaa-aaa-aaaaaa-aa-aaaaaa-AAAAA.md",
    "0000-00-00-0000-from-AAA-AAAAAAAAAA-aa-aaaaaaaa-a-aaaa-aaaaa-aaaa-aaaaaaaa-aaa-aaa-aaa-aaaa-aa.md",
    "0000-00-00-0000-from-AAA-AAAAAAAAAA-aaa-aaa-aaaa-aaaa-aaa-aaa-aaaaaaaaaa-aaaaa.md",
    "0000-00-00-0000-from-AAA-AAAAAAAAAA-aaaaaaaaa-aa-aaaaaaaaa-aaa-aaaaa-aaaaaaaa-aaa-aaaaaaa.md",
    "0000-00-00-0000-from-AAA-a-aaaaaa-aaaaaaa-aaaaaa-aaaaaa-aaaaaaaa-000-aaaaa-aa-aaa-aaa-aaaaaaa-aaaaaaaaa.md",
    "0000-00-00-0000-from-AAA-aa-aaaaaa-aaaaaa.md",
    "0000-00-00-0000-from-AAA-aa-aaaaaa-aaaaaaa-aaaa-aaaaaa-aaa-aaa-aaaaa-aaaa-aaaaaaa-aaa-aaaa-aaaaaaa-aaaaaaa.md",
    "0000-00-00-0000-from-AAA-aaa-00-0-aaa-aaa-aaa-aaaaaa-aaaaaaaa-aaaaaaa-aaa-aa-aaaaaaaaa-aa-aa-aaaaaaa-aaaa-00-aaaa-aaa-aaaaaaaaa.md",
    "0000-00-00-0000-from-AAA-aaa-00-aaaa-aaa-aaaaaaa-aaaaa-aaaa-aaaa-aaa-aaa-aaaaaa-aaaa-aa-aaaaaaaaaa-aaaaaaa-a-aaaaaaaaa-aaaa.md",
    "0000-00-00-0000-from-AAA-aaa-aaa-aaaaa-aaaaaaa-aaaaaaaaaa-aaa-aaaa-0a-aaaaaaa-aaaa-aa-aaaaaaaa-aaaaa-aaaaa-aaa.md",
    "0000-00-00-0000-from-AAA-aaa-aaaaa-aa-00-0-aaa-aaaaa-aaaaa-aaaa-aa-a-aaaaa-aaa-aaa-aaaaaaa-aaaa-aaaaaaaaaaaa-aaaaa-aaaaaaaaa.md",
    "0000-00-00-0000-from-AAA-aaaa-000-aa-aaaa-aaa-aaaa-aaaaaa-aaa-aaa-aaaaa-aaa-aaaaa-aaaaaaaaa.md",
    "0000-00-00-0000-from-AAA-aaaa-a-aa-aaaaaa-aaa-a-aaa-aaaaaaa-aaaaaa-aaaaaa-aaa-aaaa-aaaa.md",
    "0000-00-00-0000-from-AAA-aaaa-aaa-aaaaaaaaa-aaaaaaaa-aaaa-aa-aaa-aaa-aaaaaa-aaaa-aaa-aaaa-aaaaaaa-aaaaaaa-aa-aaaa-aaaaaa-aa-aaaa-aaaa.md",
    "0000-00-00-0000-from-AAA-aaaa-aaaaa-aaaaaaaaaaa.md",
    "0000-00-00-0000-from-AAA-aaaa-aaaaaa-aaaaa-aaaaa-aaaa-aaaa-aaaa-aaaa-a-aaaaaaa-aaa-aaa-aaaaaaa-aaaaaaa.md",
    "0000-00-00-0000-from-AAA-aaaa-aaaaaa-aaaaaa-aaa-aaa-aaaa-aaa-aaaaaaaa-aaaaaaaaaaaaa.md",
    "0000-00-00-0000-from-AAA-aaaa-aaaaaa-aaaaaaaa-aaaaaaaa-aaa-aaaa-aaaa-aaa-aaaaaaa-aa-aaa-aaaaa.md",
    "0000-00-00-0000-from-AAA-aaaaa-aaaa-aaaaaaaa.md",
    "0000-00-00-0000-from-AAA-aaaaa-aaaaaaa-aaaaaaaa-aaaa-aaa-aaaa-aaaaa-aa-aaa-aaaaa.md",
    "0000-00-00-0000-from-AAA-aaaaa-aaaaaaaa.md",
    "0000-00-00-0000-from-AAA-aaaaaa-aaaaa-aaaaaaaa-aaaa-aaa-aaa-aaaaaaa-aaa-aaa-aaaaaa.md",
    "0000-00-00-0000-from-AAA-aaaaaaa-aaa-aaaa-aaaaaaaa-aaa-aaaa-aa-aaaa-aaaaaaa-aaaaaaaaaa-AAAA-aaaa.md",
    "0000-00-00-0000-from-AAA-aaaaaaa-aaaaaaa-aaaaaaaaa-aaaaaaaa-aaaa-aaaaa.md",
    "0000-00-00-0000-from-AAA-aaaaaaa-aaaaaaaaa-aaaa-aaaaaaaaa-aaaaaa-0-aaaaaa.md",
    "0000-00-00-0000-from-AAA-aaaaaaaa-aaa-aaaaa-aaaaaaaa-aaaa-aaaaaaaaa.md",
    "0000-00-00-0000-from-AAA-aaaaaaaaa-aaaaa-aaaa-aaaa-aaa-aaaaaaaaaaaaa-aaaaaaaa.md",
    "0000-00-00-0000-from-AAA-aaaaaaaaa-aaaaaaaaa-aaaa-aaaaaaa-aaa-aaaaaaaaa-aaa-aaaa-aaaaaaaaa.md",
    "0000-00-00-0000-from-AAA-aaaaaaaaaaa-a-aaa-aaaaa-aaaa-aaaaaa-aaaa-aaa-aaaaaa-aaa-aaaaa-aaaaa-aaaaaa-aaa-aaa-aaaaaaaa.md",
    "0000-00-00-from-AA-A00_AAAAAA_AAAAAA0.md",
    "0000-00-00-from-AA-A00_AAAAAA_AAAAAAA0AA0.md",
    "0000-00-00-from-AA-AA-AAA-aaaaa-AAAAAAAAAAA-AAAAAAA-aaaaaaa-aa-aaaaaaa-aaa-aaaa-aa-aa-aaaaaaa-aa-aaaaaa.md",
    "0000-00-00-from-AA-AA-AAAAAAA-AAA-AAAAAAAAAAA-aaa-aaaaaa-aaaaa-aaa-aaaa-aaaaaaa-aaa-aaa-aaaaaaaa-AA-aaaa-aaaa-aaaaaaaa.md",
    "0000-00-00-from-AA-AAAAA-AA-AAA-AAAAAAA-a-aaaaa-aaaa-aaaaaaa-aaaa-aaaa-aaaaaa-aaa-aaaa-aaaaaaaaa-aaaaa.md",
    "0000-00-00-from-AA-AAAAAAAAAA-aaa-aaaaaa-AA-aaaa-aa-aaaa-aaaaaaa-aaa-aaaaa.md",
    "0000-00-00-from-AA-AAAAAAAAAAAA-aaa-aaaaaa-aaaa-aa-aaaa-aaaaa-aaa-aaaaa-aaa-AA.md",
    "0000-00-00-from-AA-AAAAAAAAAAA_AAAAA.md",
    "0000-00-00-from-AA-AAAAAAAAAA_AAAAAAAA_AAA_a0_0.md",
    "0000-00-00-from-AA-AAAAAAAAAA_AAAA_AAAAA.md",
    "0000-00-00-from-AA-AAAAAAAAAA_AAAA_AAAAAAA.md",
    "0000-00-00-from-AA-AAAAAAAAAA_AAAA_AAAAAAAA.md",
    "0000-00-00-from-AA-AAAAAAAAAA_AAAA_AAAAAAAAAAA.md",
    "0000-00-00-from-AA-AAAAAAAAAA_AAAA_AAAAAAAAAAAA.md",
    "0000-00-00-from-AA-AAAAAAAAAA_AAAA_AAAA_AAAAAA.md",
    "0000-00-00-from-AA-AAAAAAAAAA_AA_AAAA.md",
    "0000-00-00-from-AA-AAAAAAAAAA_AA_AAAAAA.md",
    "0000-00-00-from-AA-AAAAAAAAA_AAA_AAAAAA.md",
    "0000-00-00-from-AA-AAAAAAA_A000_AAAAAA.md",
    "0000-00-00-from-AA-AAAAAA_AAAAA.md",
    "0000-00-00-from-AA-AAAAAA_AAA_AAAA.md",
    "0000-00-00-from-AA-AAAAAA_AAA_AAAAAA.md",
    "0000-00-00-from-AA-AAAA_AAAAAA.md",
    "0000-00-00-from-AA-AAA_AAAAA_a0_0.md",
    "0000-00-00-from-AA-AA_AAAAAAA_AAAAAAAAAA_a0.md",
    "0000-00-00-from-AA-aa-AA-aaaa-aaaaa-aa-aaa-aaa-aaaaa-aaaaaaaaaaa-aaa-aaaaaaa-aa-aaaaa-aaaa-aa-aaaaaaa-aa-a-aaaa-AA-aaa-aaa-aaaa.md",
    "0000-00-00-from-AA-aaa-aaaa-aaa-aaaaaa-aaaa-aaaaaaaaaa-aaaaaaa-aaaaaaaaa-aaa-a-aaaaa-aaaaa-aa-aaaaaa-aaa.md",
    "0000-00-00-from-AA-aaa-aaaaa-aa-aa-00-0-aaa-aaa-aaa-aaa-aaaaaa-aaa-AAAAAAA-aaaa-aa-aaaaa-aaaaaa-aa-aaaa-aa.md",
    "0000-00-00-from-AA-aaaa-aaaaaaa-aaaaaaa-aaa-aaaa-aaaaaa-aaa-aaa-aaaaa-aaaaa-aa-aaa-aaaa-aaaaaa-aa-aaaaaaaa.md",
    "0000-00-00-from-AA-aaaaa-aaa-aaaaaaaaa-aaaaaaa-aaa-aaaaaa-aaaaaa-aaaa-aaaaaa-aaaaaaaaaa.md",
    "0000-00-00-from-AA-aaaaaa-aaa-aaaa-aaaaa-aaa-aaaaaa-aaa-aaaa-aa-aaaaaaaa-aaaa-aaaa.md",
    "0000-00-00-from-AA-aaaaaaaa-aaaaaaaa-aaaaaaaaa-aaaa-aaaaaaaaa-aaaaaaaaaa-aa-aaa-aaa.md",
    "0000-00-00-from-AA-aaaaaaaaa-aa-A0-A0-aaa-a-aaaaaa-aaaaaa-aaaa-aaaa-AAAA-aaaaaa-AAA_AAA.md",
    "0000-00-00-from-AA-aaaaaaaaaa-aaaaaa",
    "0000-00-00-from-AA-aaaaaaaaaa-aaaaaaaa-aaa-aaaaa-aa-aaa-a-aaaaaaaaa-aa-aaa-aaaaaa.md",
    "AAAAAA.md",
    "AAAAAAAAA-aaaa_aaaa_aaaaaa.aa.txt",
    "_aaaa",
    "_aaaaaa",
    "aa_aaaaa_aaa_aaaaa.aa.from-aa",
    "aa_aaaaa_aaaaaa.aa.from-aa",
    "aaaaa.aa.aaaaaaaa-0aaaa",
    "aaaaaaaa.aa.from-aa",
    "from-AA-0000-00-00-0000-aaaaaaaaaa-aaa-aaa-aaaaaaaa-aaaaa-aa-aaa-aaa.md",
    "from-AA-aaaaaaaa",
    "from-AAA-aaaaaaaa",
)


def _corpus() -> list[str]:
    """Literals only. Nothing here reads a gitignored path, or any path."""
    return list(SYNTHETIC_NAMES) + list(FROZEN_LIVE_SHAPES)


# ---------------------------------------------------------------------------
# The doc table
# ---------------------------------------------------------------------------


# The table as it stands under CHANNEL_VERSION 1, EVERY CELL OF EVERY ROW.
#
# A shape summary is not a pin. A sibling tree measured exactly that on its own
# version of this arm: grading the column count, the row count, the Shape order,
# that each verdict is a member of the admit-or-refuse pair, and that column one
# is backticked let FIVE of six doc mutations through - a nonsense PRIMARY
# example, a nonsense variant example, two examples SWAPPED between rows, the
# PRIMARY verdict flipped, and all four responder columns blanked on every row.
#
# The timing argument is what makes that fatal rather than untidy. While the
# `CHANNEL_PIN` digest holds, every one of those mutations also reddens the
# digest arm, so the table cannot drift today. The blindness goes live at
# EXACTLY ONE MOMENT: a CHANNEL_VERSION 2 re-pin, when the digest is legitimately
# replaced and a hand-copied table is most likely to be mangled - which is the
# only moment this arm was ever going to be load-bearing.
_H = ("Example", "RC gate 6", "RSC", "LW", "CS", "LL", "Shape")
EXPECTED_HEADER = _H
EXPECTED_ROWS = (
    ("`2026-09-15-0930-from-RC-FYI-example-topic.md`", "ADMIT", "routes", "any entry",
     "no responder", "no responder", "PRIMARY"),
    ("`2026-09-15-from-RC-FYI-example-topic.md`", "REFUSE", "routes", "any entry",
     "no responder", "no responder", "Variant A"),
    ("`from-RC-2026-09-15-0930-FYI-example-topic.md`", "REFUSE", "zero destinations",
     "any entry", "no responder", "no responder", "Variant B"),
    ("`2026-09-15-0930-from-RC-FYI-example-topic.txt`", "REFUSE", "routes", "any entry",
     "no responder", "no responder", "Variant C"),
)


# The exact ordered verdict column. Pinned as an ORDERED LIST rather than as
# membership in the admit-or-refuse pair: membership is strictly weaker than
# order at no saving, and a third sibling's arm caught the flipped-PRIMARY
# mutation purely by having asserted order.
EXPECTED_VERDICTS = ("ADMIT", "REFUSE", "REFUSE", "REFUSE")

# The table block VERBATIM - header line, separator line, and the four data
# lines as contiguous bytes. This is the arm that REQUIRES the separator rather
# than skipping it by content: a row extractor that matches the separator's
# shape in order to skip it stays green when the separator is deleted, which is
# the same shift-by-one family as an unconditional header drop reached by a
# different route. `test_the_verbatim_block_is_the_only_guard_on_the_separator`
# asserts that no OTHER arm here covers it, so a later reader cannot assume
# something else does.
EXPECTED_TABLE_BLOCK = (
    "| Example | RC gate 6 | RSC | LW | CS | LL | Shape |",
    "|---|---|---|---|---|---|---|",
    "| `2026-09-15-0930-from-RC-FYI-example-topic.md` | ADMIT | routes | any entry "
    "| no responder | no responder | PRIMARY |",
    "| `2026-09-15-from-RC-FYI-example-topic.md` | REFUSE | routes | any entry "
    "| no responder | no responder | Variant A |",
    "| `from-RC-2026-09-15-0930-FYI-example-topic.md` | REFUSE | zero destinations "
    "| any entry | no responder | no responder | Variant B |",
    "| `2026-09-15-0930-from-RC-FYI-example-topic.txt` | REFUSE | routes | any entry "
    "| no responder | no responder | Variant C |",
)


def _doc_text() -> str:
    return (REPO_ROOT / CHANNEL_DOC).read_bytes().decode("ascii")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator(line: str) -> bool:
    cells = _cells(line)
    return bool(cells) and all(set(c) <= set("-: ") and c for c in cells)


def _table_block(text: str) -> tuple[list[str], int, int]:
    """(all lines, header index, last table line index). Located by header TEXT.

    A table whose header cannot be found returns a header index of -1, which
    every caller must treat as a FAILURE rather than as an empty agreement.
    """
    lines = text.splitlines()
    start = -1
    for index, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        lowered = [c.lower() for c in _cells(line)]
        if "example" in lowered and "rc gate 6" in lowered:
            start = index
            break
    if start < 0:
        return lines, -1, -1
    end = start
    while end + 1 < len(lines) and lines[end + 1].strip().startswith("|"):
        end += 1
    return lines, start, end


def _grade_doc_table(text: str) -> list[str]:
    """Every problem with the doc's table, or an empty list.

    Returned rather than asserted so the negative-control arms below can drive
    the SAME grading chain over a mutated doc instead of a re-implementation of
    it. ORDER IS DELIBERATE: the header, then the separator, then the ROW COUNT,
    and only then the cell-by-cell compare. A roster without its size is half a
    pin - rows go absent exactly where a count miscounts - so the count is
    asserted BEFORE any content is compared, and a wrong count short-circuits.
    """
    problems: list[str] = []
    lines, start, end = _table_block(text)
    if start < 0:
        return ["no row carries both an `Example` and an `RC gate 6` header cell"]
    # The header is IDENTIFIED BY TEXT above, never taken as "whatever row 0
    # is". That distinction is the whole of a second sibling's finding: a parser
    # that drops `rows[0]` unconditionally lets a deleted separator promote the
    # header out of the data, shift every row up by one, and a cell-for-cell
    # pin still matches. Nothing here drops a row by position.
    header = _cells(lines[start])
    if tuple(header) != tuple(EXPECTED_HEADER):
        problems.append(f"header is {header}, expected {list(EXPECTED_HEADER)}")
    body = lines[start + 1:end + 1]
    separators = [line for line in body if _is_separator(line)]
    # EXACTLY ONE, not at least one, and asserted BEFORE any content compare.
    # Deletion and DUPLICATION are both departures from exactly-one, and the
    # duplicate is the class that a shift-by-one parser reads straight past.
    if len(separators) != 1:
        problems.append(
            f"the table carries {len(separators)} separator row(s), expected exactly 1"
        )
    elif body and not _is_separator(body[0]):
        problems.append("the separator row is not directly under the header")
    if separators and len(_cells(separators[0])) != len(EXPECTED_HEADER):
        problems.append(
            f"the separator declares {len(_cells(separators[0]))} columns, expected "
            f"{len(EXPECTED_HEADER)}"
        )
    if problems:
        return problems
    body = [line for line in body if not _is_separator(line)]
    rows = [_cells(line) for line in body if line.strip().startswith("|")]
    if len(rows) != len(EXPECTED_ROWS):
        problems.append(
            f"the table carries {len(rows)} data row(s), expected {len(EXPECTED_ROWS)}"
        )
        return problems
    if problems:
        return problems
    for index, (got, want) in enumerate(zip(rows, EXPECTED_ROWS)):
        if len(got) != len(want):
            problems.append(f"row {index} has {len(got)} cells, expected {len(want)}")
            continue
        for column, (a, b) in enumerate(zip(got, want)):
            if a != b:
                problems.append(
                    f"row {index} column {EXPECTED_HEADER[column]!r} is {a!r}, "
                    f"expected {b!r}"
                )
    return problems


def _doc_grammar_table(text: str | None = None) -> tuple[bool, list[dict]]:
    """(header_found, rows as dicts keyed by the lowercased header cell)."""
    lines, start, end = _table_block(_doc_text() if text is None else text)
    if start < 0:
        return False, []
    header = [c.lower() for c in _cells(lines[start])]
    rows = []
    for line in lines[start + 1:end + 1]:
        if _is_separator(line):
            continue
        cells = _cells(line)
        if len(cells) != len(header):
            continue
        rows.append(dict(zip(header, cells)))
    return True, rows


# ---------------------------------------------------------------------------
# The six mutations a sibling measured against their own version of this arm,
# plus the ADDED-ROW case they did not test. Each returns a mutated COPY of the
# doc text - `docs/CHANNEL.md` itself is byte-pinned in five repositories and is
# never written here.
# ---------------------------------------------------------------------------


def _render(lines: list[str], start: int, end: int, block: list[str]) -> str:
    return "\n".join(lines[:start] + block + lines[end + 1:]) + "\n"


def _with_block(text: str, change) -> str:
    lines, start, end = _table_block(text)
    assert start >= 0, "the fixture doc has no table to mutate"
    block = list(lines[start:end + 1])
    return _render(lines, start, end, change(block))


def _set_cell(line: str, column: int, value: str) -> str:
    cells = _cells(line)
    cells[column] = value
    return "| " + " | ".join(cells) + " |"


def _mut_primary_example_nonsense(text: str) -> str:
    return _with_block(text, lambda b: b[:2] + [_set_cell(b[2], 0, "`nonsense-name`")] + b[3:])


def _mut_variant_example_nonsense(text: str) -> str:
    return _with_block(text, lambda b: b[:3] + [_set_cell(b[3], 0, "`nonsense-name`")] + b[4:])


def _swap_examples(block: list[str]) -> list[str]:
    a, b = _cells(block[3])[0], _cells(block[4])[0]
    return block[:3] + [_set_cell(block[3], 0, b), _set_cell(block[4], 0, a)] + block[5:]


def _mut_two_variant_examples_swapped(text: str) -> str:
    return _with_block(text, _swap_examples)


def _mut_primary_verdict_flipped(text: str) -> str:
    return _with_block(text, lambda b: b[:2] + [_set_cell(b[2], 1, "REFUSE")] + b[3:])


def _blank_responder_columns(block: list[str]) -> list[str]:
    out = list(block[:2])
    for line in block[2:]:
        for column in (2, 3, 4, 5):
            line = _set_cell(line, column, "")
        out.append(line)
    return out


def _mut_responder_columns_blanked(text: str) -> str:
    return _with_block(text, _blank_responder_columns)


def _mut_separator_deleted(text: str) -> str:
    return _with_block(text, lambda b: b[:1] + b[2:])


def _mut_separator_duplicated(text: str) -> str:
    return _with_block(text, lambda b: b[:2] + [b[1]] + b[2:])


def _mut_row_added(text: str) -> str:
    extra = (
        "| `2026-09-15-0930-from-RC-FYI-another.md` | ADMIT | routes | any entry "
        "| no responder | no responder | Variant E |"
    )
    return _with_block(text, lambda b: b + [extra])


DOC_MUTATIONS = [
    ("primary-example-nonsense", _mut_primary_example_nonsense),
    ("variant-example-nonsense", _mut_variant_example_nonsense),
    ("two-variant-examples-swapped", _mut_two_variant_examples_swapped),
    ("primary-verdict-flipped", _mut_primary_verdict_flipped),
    ("responder-columns-blanked", _mut_responder_columns_blanked),
    ("separator-row-deleted", _mut_separator_deleted),
    ("separator-row-duplicated", _mut_separator_duplicated),
    ("row-added", _mut_row_added),
]


# ---------------------------------------------------------------------------
# 1a - behaviour identity
# ---------------------------------------------------------------------------


def test_the_code_table_reproduces_the_frozen_gate6_name_predicate_exactly():
    """Behaviour identity over the whole corpus. Measured at 502d0f130.

    Corpus: 34 synthetic names covering each doc variant and each edge
    (non-ASCII including a lone surrogate, over-length, empty topic, wrong code
    length and case, .txt, a bounce, a directory name, the degenerate cases),
    plus the 180 FROZEN shapes above, projected from the 358 unique live entry
    names read across five channel inbox directories on Legion at 502d0f130.
    214 names in all, every one a literal in this file: the corpus is identical
    in the primary tree, in a worktree and in CI, because none of it is read
    from disk.
    """
    corpus = _corpus()
    # ANTI-VACUITY, pinned EXACTLY rather than floored. A floor on a corpus
    # BUILT from the same constant is a TAUTOLOGY that can never fire, and a
    # floor cannot detect GROWTH either - a name added to the set passes it by
    # construction, which is the same defect as a minimum row count on a table.
    #
    # WHAT THIS PROVES AND WHAT IT DOES NOT: it proves the corpus is exactly the
    # 214 distinct literals measured at 502d0f130 and that it exercises BOTH
    # verdicts. It does NOT prove anything about the live channel as it stands
    # today - the frozen shapes are a snapshot, and refreshing them is a
    # deliberate act with the sweep re-run, not something a test does for you.
    assert len(SYNTHETIC_NAMES) == 34
    assert len(FROZEN_LIVE_SHAPES) == 180
    assert len(corpus) == 214
    assert len(set(corpus)) == 214, "a duplicate inflated the corpus count"
    verdicts = {_frozen_name_grammar_bad(name) for name in corpus}
    assert verdicts == {True, False}, (
        "the corpus exercises only one verdict, so an identity claim over it "
        "would hold for a predicate that is constant"
    )
    for variant in runner.NAME_GRAMMAR_TABLE:
        assert variant.example in corpus, (
            f"the corpus does not carry the {variant.shape} example"
        )
    divergent = [
        name
        for name in corpus
        if _frozen_name_grammar_bad(name) != runner.name_grammar_bad(name)
    ]
    assert divergent == [], (
        f"{len(divergent)} of {len(corpus)} name(s) resolve differently under the "
        "parametrised gate than under the frozen 502d0f130 predicate; the "
        "parametrisation must be behaviour-identical, and a divergence is a "
        "defect in it, not a discovery"
    )


def test_the_inbox_is_git_ignored_which_is_why_the_corpus_is_frozen():
    """Ask whether GIT IGNORES it, never whether the path EXISTS.

    Existence is a property of the checkout - the inbox is populated in the
    primary tree and absent in every worktree - so an existence probe returns
    opposite answers for the same commit. Whether git ignores the path is a
    property of the REPOSITORY and is identical everywhere.

    THE TRAP INSIDE THE FIX. `moon_sync_inbox/` is a DIRECTORY-ONLY ignore
    pattern, and git can only tell that a BARE pathspec names a directory from a
    trailing slash on it or from the path being on disk - so `check-ignore
    moon_sync_inbox` answers from the FILESYSTEM again and reports NOT IGNORED
    in a worktree, reproducing the defect this arm exists to remove. A trailing
    slash fixes it but depends on nobody ever tidying the slash away.

    So the probe asks about a path UNDERNEATH the directory instead. A path
    under it matches a directory-only pattern whether or not anything is on
    disk, which makes this both checkout-independent and slash-independent -
    there is no slash left to forget. `--no-index` keeps the index out of it.
    The control is asserted beside it: the bare name is expected to answer from
    the filesystem, so it is NOT asserted ignored - it is only required to
    differ from a crash.

    THE SKIP GATE IS THE BINARY, not the outcome. `git` absent from PATH is an
    environment capability and the only condition this arm may skip on; a git
    that RUNS and answers wrongly must fail loudly, so no exception handler
    turns a real answer into a skip.
    """
    if _GIT is None:
        pytest.skip("git not on PATH - what git ignores is unresolvable without it")

    def _ignored(pathspec: str) -> int:
        return subprocess.run(
            [_GIT, "check-ignore", "-q", "--no-index", pathspec],
            cwd=str(REPO_ROOT), capture_output=True, timeout=30,
        ).returncode

    under = _ignored("moon_sync_inbox/a-note.md")
    assert under == 0, (
        "git does not ignore paths under `moon_sync_inbox/`; if the channel "
        "inbox became tracked, this corpus and several claims in "
        "docs/CHANNEL.md need re-reading"
    )
    assert _ignored("moon_sync_inbox") in (0, 1), "git check-ignore did not run"


def test_no_frozen_shape_carries_a_sibling_identifier():
    """The frozen corpus is checked in, and this repository is PUBLIC.

    The projection erases letters, so an identifier cannot survive it - but
    asserted rather than argued, with RC's own sweep, because two of the live
    names it was projected from DO trip that sweep. Honest about the skip: the
    needle list is gitignored, so CI measures nothing here and the pre-push hook
    is the backstop.
    """
    cfg = sweep.load_config()
    text = "\n".join(FROZEN_LIVE_SHAPES)
    assert sweep.structural_findings(text, path="CORPUS", source="TEST") == []
    if cfg.mode != sweep.MODE_ARMED:
        pytest.skip(
            f"sweep is {cfg.mode}, not {sweep.MODE_ARMED}: the gitignored needle "
            "config is absent here, so the name arm was NOT measured"
        )
    findings = sweep.scan_text(
        sweep.build_needles(cfg), cfg.codes, text, path="CORPUS", source="TEST",
    )
    assert findings == [], (
        f"{len(findings)} frozen shape(s) trip the sibling-name sweep (text "
        "deliberately not printed)"
    )


def test_note_shape_ok_itself_is_unchanged_at_the_gate_site(tmp_path):
    """The identity arm above is on the predicate; this one is on the GATE.

    A predicate that agrees while the call site reads a different one proves
    nothing, so these drive `note_shape_ok` over real files on disk.
    """
    checked = 0
    for index, name in enumerate(SYNTHETIC_NAMES):
        if not name or not name.isascii() or "/" in name or "\\" in name:
            continue
        holder = tmp_path / f"case{index}"
        holder.mkdir()
        try:
            path = holder / name
            path.write_bytes(b"body\n")
        except (OSError, ValueError):
            continue
        expected = ["name-grammar"] if _frozen_name_grammar_bad(name) else []
        assert runner.note_shape_ok(path, name) == expected, (
            f"gate 6 disagrees with the frozen predicate on {name!r}"
        )
        checked += 1
    assert checked >= 20, (
        f"only {checked} names reached the real gate; the on-disk arm went vacuous"
    )


# ---------------------------------------------------------------------------
# 1b - the code table and the doc table agree, cell for cell
# ---------------------------------------------------------------------------


def test_the_doc_grammar_table_parses_and_is_not_empty():
    """An unfindable or empty table must FAIL here, never pass vacuously."""
    found, rows = _doc_grammar_table()
    assert found, (
        f"no row in {CHANNEL_DOC} carries both an `Example` and an `RC gate 6` "
        "header cell; the parser found no table, which is a failure and not an "
        "agreement"
    )
    # EXACT, never a floor: a floor cannot detect a row being ADDED, and an
    # added row is precisely how a re-pin round grows a table nobody re-read.
    assert len(rows) == len(runner.NAME_GRAMMAR_TABLE) == len(EXPECTED_ROWS), (
        f"{CHANNEL_DOC} declares {len(rows)} grammar row(s) against "
        f"{len(runner.NAME_GRAMMAR_TABLE)} in the code table and "
        f"{len(EXPECTED_ROWS)} pinned here; all three move together or not at all"
    )


def test_the_live_doc_table_matches_the_expected_structure_cell_for_cell():
    """The whole table pinned as an explicit expected structure.

    Row count first, then every cell of every row. A CHANNEL_VERSION 2 re-pin
    that hand-copies this table and mangles a cell reddens HERE, which is the
    one moment the digest arm cannot help: at the flip the digest is legitimately
    being replaced.
    """
    problems = _grade_doc_table(_doc_text())
    assert problems == [], (
        f"{CHANNEL_DOC} grammar table drifted from the pinned structure: "
        + "; ".join(problems)
    )


def test_the_table_block_is_verbatim_contiguous_bytes():
    """Header PLUS separator PLUS rows, compared as one contiguous string.

    This is the arm that REQUIRES the separator instead of skipping it by
    content. A row extractor that recognises the separator in order to drop it
    stays green when it is deleted; an arm that compares the block as bytes
    cannot.
    """
    lines, start, end = _table_block(_doc_text())
    assert start >= 0, f"no grammar table found in {CHANNEL_DOC}"
    block = lines[start:end + 1]
    assert "\n".join(block) == "\n".join(EXPECTED_TABLE_BLOCK), (
        f"the {CHANNEL_DOC} grammar table block is not the pinned bytes; a re-pin "
        "round moves these bytes and this arm is where that has to be re-read"
    )


def test_the_verbatim_block_is_the_only_guard_on_the_separator():
    """Guard the guard: nothing ELSE here pins the separator row.

    Stated as an assertion rather than a comment so a later reader cannot
    assume some other arm is covering the separator and delete the verbatim one
    as redundant. The separator literal must appear exactly once in this
    module's own source, inside `EXPECTED_TABLE_BLOCK`.
    """
    source = Path(__file__).read_text(encoding="ascii")
    literal = "|" + "---|" * len(EXPECTED_HEADER)
    assert source.count(literal) == 1, (
        f"the separator literal appears {source.count(literal)} times in this "
        "module; the verbatim block arm is supposed to be its only pin"
    )
    assert literal in EXPECTED_TABLE_BLOCK[1]


def test_the_verdict_column_is_pinned_in_order():
    """Exact ordered list, not membership in the admit-or-refuse pair."""
    found, rows = _doc_grammar_table()
    assert found
    assert tuple(r["rc gate 6"] for r in rows) == EXPECTED_VERDICTS
    assert tuple(v.disposition for v in runner.NAME_GRAMMAR_TABLE) == EXPECTED_VERDICTS


@pytest.mark.parametrize("label,mutate", DOC_MUTATIONS, ids=[m[0] for m in DOC_MUTATIONS])
def test_each_known_doc_mutation_is_caught(label, mutate):
    """Negative controls, eight of them. A pin nothing can violate is not a pin.

    Six came from one sibling tree, five of which their own arm PASSED. The
    seventh, SEPARATOR DUPLICATION, came from a second tree that caught the
    other six and was blind to this one - both it and deletion are departures
    from EXACTLY ONE separator, which is why one assertion closes both. The
    eighth, an ADDED row, is caught by the EXACT row count; a minimum-count
    floor passes it by construction, which is why no floor is used here.

    Each must be caught by the structural chain AND change the verbatim block,
    so neither guard is carrying the other.
    """
    original = _doc_text()
    mutated = mutate(original)
    assert mutated != original, f"{label} did not change the doc text"
    problems = _grade_doc_table(mutated)
    assert problems != [], (
        f"the {label} mutation passed the table pin unnoticed; the arm is blind "
        "to exactly the damage a re-pin round would do"
    )
    lines, start, end = _table_block(mutated)
    block = lines[start:end + 1] if start >= 0 else []
    assert "\n".join(block) != "\n".join(EXPECTED_TABLE_BLOCK), (
        f"the {label} mutation left the verbatim block identical"
    )


def test_every_doc_row_matches_the_code_table_cell_for_cell():
    found, rows = _doc_grammar_table()
    assert found and rows, "the doc grammar table did not parse"
    by_shape = {v.shape: v for v in runner.NAME_GRAMMAR_TABLE}
    assert {r["shape"] for r in rows} == set(by_shape), (
        f"the doc names shapes {sorted(r['shape'] for r in rows)} and the code "
        f"table names {sorted(by_shape)}; neither side may add or drop a row alone"
    )
    for row in rows:
        variant = by_shape[row["shape"]]
        doc_example = row["example"].strip("`")
        assert variant.example == doc_example, (
            f"{row['shape']}: the doc's example is {doc_example!r} and the code "
            f"table's is {variant.example!r}"
        )
        assert variant.disposition == row["rc gate 6"].strip().upper(), (
            f"{row['shape']}: the doc says RC gate 6 would "
            f"{row['rc gate 6']} {doc_example!r}, the code table says "
            f"{variant.disposition}"
        )
        assert runner.name_grammar_verdict(doc_example) == variant.disposition, (
            f"{row['shape']}: the live verdict for {doc_example!r} is "
            f"{runner.name_grammar_verdict(doc_example)}, not the "
            f"{variant.disposition} both tables declare"
        )


# ---------------------------------------------------------------------------
# 1c - Variant B stays refused
# ---------------------------------------------------------------------------


def test_variant_b_the_code_first_form_is_refused():
    """FORBIDDEN in the doc, and silently undeliverable at one sibling.

    Mutating the Variant B cell to ADMIT must redden this arm - that is what
    makes the cell a guarded one-cell edit rather than a free one.
    """
    variant = {v.shape: v for v in runner.NAME_GRAMMAR_TABLE}["Variant B"]
    assert variant.disposition == runner.GRAMMAR_REFUSE
    for name in (
        variant.example,
        "from-RC-2026-09-15-0930-topic.md",
        "from-RSC-2026-09-15-0930-REVIEW-0123456789ab-topic.md",
    ):
        assert variant.pattern.fullmatch(name), (
            f"{name!r} is not even matched by the Variant B pattern, so this arm "
            "would stay green under any disposition"
        )
        assert runner.name_grammar_verdict(name) == runner.GRAMMAR_REFUSE
        assert runner.name_grammar_bad(name) is True
        assert runner.NOTE_NAME_RE.fullmatch(name) is None


# ---------------------------------------------------------------------------
# 1d - the length cap stays the OUTER bound
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "variant", runner.NAME_GRAMMAR_TABLE, ids=lambda v: v.shape.replace(" ", "-")
)
def test_every_variant_composes_inside_note_name_max(variant):
    """The property the constants comment reasons about, per variant.

    The longest name any variant can accept is shorter than `NOTE_NAME_MAX`, so
    the grammar refuses before the cap ever can - which is what keeps the cap
    the OUTER bound instead of a second, conflicting one. Checked for every row
    in the table so a widened pattern cannot quietly cross it.
    """
    longest = variant.longest_name()
    assert variant.pattern.fullmatch(longest), (
        f"{variant.shape}: the composed longest name is not accepted by its own "
        "pattern, so the bound below measures nothing"
    )
    assert len(longest) <= runner.NOTE_NAME_MAX, (
        f"{variant.shape}: composes to {len(longest)} characters against "
        f"NOTE_NAME_MAX {runner.NOTE_NAME_MAX}; the cap is no longer the outer bound"
    )
    over = variant.longest_name(topic_len=161)
    assert variant.pattern.fullmatch(over) is None, (
        f"{variant.shape}: a 161-character topic is still accepted, so the topic "
        "group is not what refuses first"
    )
    assert len(over) <= runner.NOTE_NAME_MAX, (
        f"{variant.shape}: the first name its own group refuses is already over "
        "the cap, so the two bounds have swapped order"
    )
