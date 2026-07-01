"""
tests/test_loop_director_context_caps.py

Loop-infra fix (2026-07-01): the director call went out with a 572KB prompt
(ORCHESTRATION_PLAN.md had grown to 380KB - a 289KB Findings log - and the
LEDGER head-60 lines were 93KB because modern ledger items are multi-KB
single lines). gemini completed with an empty body, which the controller
correctly treats as NO_WORK -> STOP - but the queue had 5 OPEN rows, so the
stop was a malfunction of input size, not a real empty queue.

Locked here: build_director_context BYTE-CAPS its two unbounded components
(the plan text and the ledger head) so doc growth can never again starve
the director. The cap keeps the HEAD of each doc - the plan's queue tables
and newest findings, the ledger's newest items - and stamps a visible
truncation marker.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture()
def lc():
    return importlib.import_module("ops.loop.loop_controller")


def _seed(root: Path, plan_bytes: int, ledger_line_bytes: int) -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    plan_head = "| OQ99 | ui | queue-head-marker | OPEN | - |\n"
    filler = ("- 2026-01-01 finding filler " + "x" * 200 + "\n")
    body = plan_head + filler * (plan_bytes // len(filler) + 1)
    (root / "docs" / "ORCHESTRATION_PLAN.md").write_text(body, encoding="utf-8")
    big_item = "725. DONE newest-ledger-marker " + "y" * ledger_line_bytes
    lines = [big_item] + [f"{700 - i}. DONE older item {'z' * ledger_line_bytes}" for i in range(59)]
    (root / "docs" / "LEDGER.md").write_text("\n".join(lines), encoding="utf-8")
    (root / "ROADMAP.md").write_text("roadmap-head\n", encoding="utf-8")


def test_director_context_is_byte_bounded(lc, tmp_path):
    """A pathologically bloated plan + ledger must not produce an unbounded
    director prompt: the assembled context stays under the hard budget."""
    _seed(tmp_path, plan_bytes=400_000, ledger_line_bytes=3_000)
    ctx = lc.build_director_context({}, "", root=tmp_path, ctl=tmp_path)
    assert len(ctx) < 260_000, (
        f"director context is {len(ctx)} bytes - the byte caps are not applied"
    )


def test_caps_keep_the_head_and_mark_truncation(lc, tmp_path):
    """The cap must keep the TOP of each doc (queue tables / newest ledger
    items live at the head) and make the cut visible to the director."""
    _seed(tmp_path, plan_bytes=400_000, ledger_line_bytes=3_000)
    ctx = lc.build_director_context({}, "", root=tmp_path, ctl=tmp_path)
    assert "queue-head-marker" in ctx, "plan HEAD (queue tables) was cut"
    assert "newest-ledger-marker" in ctx, "ledger HEAD (newest item) was cut"
    assert "truncated" in ctx.lower(), "no truncation marker stamped"


def test_small_docs_pass_through_unchanged(lc, tmp_path):
    """Below the caps the context carries the docs verbatim (byte-identical
    behavior for the normal case)."""
    _seed(tmp_path, plan_bytes=2_000, ledger_line_bytes=40)
    ctx = lc.build_director_context({}, "", root=tmp_path, ctl=tmp_path)
    plan = (tmp_path / "docs" / "ORCHESTRATION_PLAN.md").read_text(encoding="utf-8")
    assert plan in ctx, "small plan must be embedded verbatim"
