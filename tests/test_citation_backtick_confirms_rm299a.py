"""RM-299a: a citation whose symbol is not backticked is graded UNCHECKED -
it proves the line NUMBER is in range and nothing about what is on it.

docs/RC2_QA_CONSOLIDATED.md rows that already NAMED their symbol now backtick
it. Two moved to CONFIRMED (`shouldPulse`, `statusFor`); backticking also
exposed three stale line numbers, two of which were re-derived to the
definition line (`normScaleFactor` 306 -> 356, `MinIntervalGuard`
143 -> 198). UNCHECKED is deliberately NOT made a hard failure here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.citation_audit as ca  # noqa: E402

DOC = "docs/RC2_QA_CONSOLIDATED.md"
NOW_CONFIRMED = {"overlay_priority.js:113": "shouldPulse",
                 "status.js:43": "statusFor"}


@pytest.fixture(scope="module")
def doc_cites():
    return [c for c in ca.audit(ROOT) if c.doc == DOC]


def test_previously_unchecked_rows_now_confirm(doc_cites):
    for raw, sym in NOW_CONFIRMED.items():
        hits = [c for c in doc_cites if c.raw == raw]
        assert hits, raw
        assert hits[0].status == "RESOLVES"
        assert hits[0].detail == "CONFIRMED", (raw, hits[0].detail)
        assert sym in hits[0].claim_tokens


def test_un_backticking_drops_the_claim_token():
    """Mutation: strip the backticks again and the row has no claim token,
    which is exactly what grades it UNCHECKED."""
    text = (ROOT / DOC).read_text(encoding="utf-8")
    lines = text.splitlines()
    mutated = [ln.replace("`", "") if any(r in ln for r in NOW_CONFIRMED) else ln
               for ln in lines]
    for raw in NOW_CONFIRMED:
        for cites, src in ((ca.extract_citations(text, DOC), lines),
                           (ca.extract_citations("\n".join(mutated), DOC), mutated)):
            c = next(c for c in cites if c.raw == raw)
            toks = ca._claim_tokens(src, c)
            if src is lines:
                assert toks, raw
            else:
                assert not toks, (raw, toks)
