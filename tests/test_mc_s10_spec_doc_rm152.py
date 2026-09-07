"""RM-152 spec-doc half: the Mission Control S10 plan must not ship the defect.

WHY THIS IS ITS OWN MODULE AND NOT PART OF
``tests/test_body_read_timeout_rm152.py``.

That module stands up real ``ThreadingHTTPServer`` instances and drives full
POST round-trips through ``dashboard._handler``, so importing it pulls in the
whole route registry (and transitively ``portalocker``, ``anthropic`` and the
rest of the runtime stack). This assertion, by contrast, only reads a tracked
``.md`` off disk.

``tools/md_guard_selector.py`` selects a test module when it names a tracked
``.md``, and ``.github/workflows/docs-guards.yml`` runs the selected set under
a DELIBERATELY minimal install (pytest / pytest-asyncio / pytest-timeout /
pyyaml / pydantic - no runtime stack). Co-housing the two concerns therefore
dragged 17 HTTP round-trip tests into a job that cannot import the registry:
on ``e30eda36`` the POST dispatch raised ``ModuleNotFoundError: No module
named 'portalocker'`` through ``dashboard/_dispatch.py`` ``_gather_post()``,
no response was recorded, and
``TestLegitimateDashboardClientsSurvive::test_a_normal_post_is_unaffected``
failed with ``IndexError`` on an empty response list. Widening the docs-guards
install would defeat the point of that job, so the split runs the other way:
this module imports nothing beyond the standard library and is the only one of
the pair the selector picks.

The assertion itself is unchanged and deliberate. The unimplemented S10 spec
carries the same ``rfile.read(n) if n else b""`` body read; left alone it ships
this bug a fourth time (vision_server, dashboard, daemon_slayer, then :8895).
"""
from __future__ import annotations

from pathlib import Path


def test_mission_control_plan_does_not_ship_the_defect() -> None:
    """Read off disk, not restated."""
    plan = (Path(__file__).resolve().parents[1] / "docs" / "superpowers" /
            "plans" / "2026-07-31-mission-control-s10-decouple.md")
    assert plan.exists(), f"plan moved: {plan}"
    src = plan.read_text(encoding="utf-8")
    assert 'self.rfile.read(n) if n else b""' not in src, (
        "the S10 spec still tells its implementer to read the declared body "
        "with no deadline - RM-152 all over again on :8895")
    assert "_BODY_READ_TIMEOUT_S" in src, \
        "the spec must carry the deadline it is expected to implement"
