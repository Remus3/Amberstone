"""Guard (RM-958): the cc_conditional midpoint and per-entry counts stay true.

Measured 2026-10-27:

* ``docs/DAEMON_SLAYER.md`` says cc_conditional ships "13 operator-tunable
  midpoints". That was correct but unguarded (the RM-957 verifier's gap):
  ``_DEFAULT_CONDITION_PROBABILITY`` has 13 keys, one per ``COND_*`` tag.
* The ``cc_conditional`` module docstring told the operator they could tune
  "the 10 per-tag probability midpoints AND the 28 per-entry
  probabilities". Both counts were wave-1 era: the module now carries 13
  tag midpoints, and any of the 73 registry entries (primary through a
  ``<champion>:<spell>`` key, form sidecar through
  ``<champion>:<spell>:<form>``) takes a per-entry override.

Every count is checked against the live module, not against a literal here.
ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import re
from pathlib import Path

from agents.daemon_slayer import cc_conditional

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "docs" / "DAEMON_SLAYER.md"


def _tags() -> set[str]:
    return {
        getattr(cc_conditional, name)
        for name in dir(cc_conditional)
        if name.startswith("COND_")
    }


def test_every_condition_tag_has_exactly_one_midpoint():
    assert set(cc_conditional._DEFAULT_CONDITION_PROBABILITY) == _tags()


def test_every_midpoint_is_a_probability():
    for tag, p in cc_conditional._DEFAULT_CONDITION_PROBABILITY.items():
        assert 0.0 <= p <= 1.0, tag


def test_ds_doc_midpoint_count_matches_the_live_module():
    text = _DOC.read_text(encoding="utf-8")
    m = re.search(r"\+ (\d+) operator-tunable midpoints", text)
    assert m, "the cc_conditional bullet lost its midpoint count"
    assert int(m.group(1)) == len(cc_conditional._DEFAULT_CONDITION_PROBABILITY)


def test_module_docstring_counts_match_the_live_module():
    doc = cc_conditional.__doc__ or ""
    flat = " ".join(doc.split())
    for m in re.finditer(r"(\d+) per-tag (?:probability )?midpoints", flat):
        assert int(m.group(1)) == len(
            cc_conditional._DEFAULT_CONDITION_PROBABILITY
        ), m.group(0)
    for m in re.finditer(r"(\d+) per-entry probabilities", flat):
        assert int(m.group(1)) == cc_conditional.REGISTRY_TOTAL_ENTRIES, m.group(0)


def test_module_docstring_names_both_override_key_shapes():
    flat = " ".join((cc_conditional.__doc__ or "").split())
    assert "``_DEFAULT_CONDITION_PROBABILITY``" in flat
    assert "``<champion>:<spell>``" in flat
    assert "``<champion>:<spell>:<form>``" in flat
