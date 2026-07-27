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
the director.

SECOND DEFECT (2026-07-27): the 2026-07-01 cap fixed the size and broke the
CONTENT. The director re-emitted an already-landed unit (the f1-phase6 inbox
apply) in cycle 11 that cycle 9 had already closed, because the evidence that
would have refuted it had been truncated away:

  - ORCHESTRATION_PLAN.md is 271,142 bytes and its closure rows are APPENDED
    AT THE END (R199 at offset 262,042, R200 at 265,191). A pure-HEAD 24,000
    byte cap is exactly backwards for this file: measured, the string
    "f1-phase6" occurs twice in the whole document and ZERO times in the
    head-24,000 slice the director actually received.
  - docs/LEDGER.md IS newest-first, so head-keeping is right there, but a
    single modern item is 5-10KB on ONE line (item 1074 alone is 10,749
    bytes), so an 8,000-byte cap over head_lines(60) delivered exactly ONE
    partial item id. Item 1073 - the row recording this exact closure and
    commit 756db42a - was cut. The LINE budget, not the byte budget, was
    the wrong knob.

So the plan is now head + TAIL with the cut stamped between them, and the
ledger is digested per ITEM (a bounded head slice of each item line) so the
same 8,000 bytes carry ~26 item ids instead of one. Total component budget
is UNCHANGED - this is a reallocation, not a raise.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent


@pytest.fixture()
def lc():
    return importlib.import_module("ops.loop.loop_controller")


def _seed(root: Path, plan_bytes: int, ledger_line_bytes: int,
          roadmap_bytes: int = 0) -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    plan_head = "| OQ99 | ui | queue-head-marker | OPEN | - |\n"
    filler = ("- 2026-01-01 finding filler " + "x" * 200 + "\n")
    body = plan_head + filler * (plan_bytes // len(filler) + 1)
    # The real plan APPENDS closure rows at the end - that is where the
    # evidence refuting a duplicate directive lives.
    body += "| R999 | slice | queue-tail-marker closure row | DONE | abc12345 |\n"
    (root / "docs" / "ORCHESTRATION_PLAN.md").write_text(body, encoding="utf-8")
    big_item = "725. DONE newest-ledger-marker " + "y" * ledger_line_bytes
    lines = [big_item] + [f"{700 - i}. DONE older item {'z' * ledger_line_bytes}" for i in range(59)]
    (root / "docs" / "LEDGER.md").write_text("\n".join(lines), encoding="utf-8")
    rm = "roadmap-head\n"
    if roadmap_bytes:
        # Mirror the real ROADMAP shape: few lines, each multi-KB.
        rm += "".join(f"- open item {'r' * 4_000}\n" for _ in range(roadmap_bytes // 4_000 + 1))
    (root / "ROADMAP.md").write_text(rm, encoding="utf-8")


def test_stdin_cap_below_measured_cli_threshold(lc):
    """2026-07-03: the gemini CLI empty-stdout threshold DRIFTS. 80KB stdin
    delivered fine on 2026-07-02, but a 79,911-byte director payload returned
    silent EMPTY on 2026-07-03 (the same payload truncated to 70,000 and
    60,000 bytes both delivered - measured live). Every director call was
    hitting cap_stdin's 80,000 ceiling, so cycles 10-32 burned directive-less.
    Pin the backstop under the worst measured ceiling with margin."""
    assert lc.GEMINI_STDIN_CAP <= 60_000, (
        f"GEMINI_STDIN_CAP={lc.GEMINI_STDIN_CAP} exceeds the 2026-07-03 "
        "measured-safe ceiling (79,911 bytes -> empty stdout)"
    )


def test_component_caps_fit_inside_stdin_cap(lc):
    """The three component caps plus ~16KB of template/digest/chain overhead
    (measured: 79,911-byte payload with 64,000 bytes of component caps) must
    compose UNDER the stdin backstop, or every director call gets the
    middle-cut marker instead of clean component truncation."""
    overhead = 16_000
    total = lc.PLAN_CTX_CAP + lc.LEDGER_CTX_CAP + lc.ROADMAP_CTX_CAP + overhead
    assert total <= lc.GEMINI_STDIN_CAP, (
        f"component caps + overhead = {total} > GEMINI_STDIN_CAP {lc.GEMINI_STDIN_CAP}"
    )


def test_plan_head_and_tail_reallocate_the_same_total_budget(lc):
    """The 2026-07-27 tail fix must be a REALLOCATION, not a raise: gemini's
    empty-stdout ceiling is the reason PLAN_CTX_CAP exists at all, so the head
    slice plus the tail slice have to sum back to the unchanged 24,000."""
    assert lc.PLAN_CTX_CAP == 24_000, "plan budget was raised, not reallocated"
    assert lc.PLAN_CTX_HEAD < lc.PLAN_CTX_CAP, "head slice must leave room for a tail"
    assert lc.PLAN_CTX_HEAD > 0, "the plan's own instructions live at the head"


def test_director_context_fits_gemini_stdin(lc, tmp_path):
    """2026-07-02: gemini CLI returns silent EMPTY stdout above ~80KB stdin
    (80KB delivered, 160KB empty - measured). The assembled context plus the
    prompt template must stay inside the proven-safe stdin budget even when
    the plan, ledger AND roadmap are all pathologically bloated."""
    _seed(tmp_path, plan_bytes=400_000, ledger_line_bytes=3_000, roadmap_bytes=150_000)
    ctx = lc.build_director_context({}, "", root=tmp_path, ctl=tmp_path)
    assert len(ctx) <= lc.GEMINI_STDIN_CAP - 8_000, (
        f"director context is {len(ctx)} bytes - exceeds the gemini stdin budget"
    )


def test_roadmap_head_kept_and_capped(lc, tmp_path):
    """ROADMAP head lines are multi-KB each; the cap keeps the TOP (highest
    priority items) and stamps the cut."""
    _seed(tmp_path, plan_bytes=2_000, ledger_line_bytes=40, roadmap_bytes=150_000)
    ctx = lc.build_director_context({}, "", root=tmp_path, ctl=tmp_path)
    assert "roadmap-head" in ctx, "ROADMAP head was cut"
    assert "ROADMAP head truncated" in ctx, "no ROADMAP truncation marker stamped"


def test_cap_stdin_passthrough_below_limit(lc):
    body = "small body"
    assert lc.cap_stdin(body, 1_000) is body


def test_cap_stdin_truncates_middle_keeps_head_and_tail(lc):
    """The gemini() backstop must keep the prompt-template HEAD and the
    directive_suffix / escalation TAIL - the middle is the expendable part."""
    body = "HEAD-MARKER " + "m" * 200_000 + " TAIL-MARKER"
    capped = lc.cap_stdin(body, 80_000)
    assert len(capped) <= 80_000
    assert capped.startswith("HEAD-MARKER")
    assert capped.endswith("TAIL-MARKER")
    assert "STDIN CAP" in capped


def test_caps_keep_the_head_and_mark_truncation(lc, tmp_path):
    """CONTRACT DELIBERATELY NARROWED 2026-07-27 - this test used to bless
    pure head-keeping for BOTH docs, and that blessing is what let the plan
    defect ship green.

    The head half of the claim is still correct and is still asserted: the
    plan's own instructions and the ledger's newest item both live at the top
    and must survive. What is no longer asserted is the IMPLIED converse -
    that keeping the head is SUFFICIENT. For a 271KB append-at-the-end plan it
    is not, and test_plan_cap_keeps_the_tail_closure_row now owns that half.
    Deleting this test instead would have dropped the head guarantee entirely,
    which is a real regression risk once the cap grew a tail slice."""
    _seed(tmp_path, plan_bytes=400_000, ledger_line_bytes=3_000)
    ctx = lc.build_director_context({}, "", root=tmp_path, ctl=tmp_path)
    assert "queue-head-marker" in ctx, "plan HEAD (queue tables) was cut"
    assert "newest-ledger-marker" in ctx, "ledger HEAD (newest item) was cut"
    assert "truncated" in ctx.lower(), "no truncation marker stamped"


def test_plan_cap_keeps_the_tail_closure_row(lc, tmp_path):
    """THE DEFECT, pinned. Closure rows are APPENDED to the plan, so the rows
    that refute a duplicate directive are the LAST bytes of the file. Under
    the pure-head cap the director never saw them and re-issued landed work."""
    _seed(tmp_path, plan_bytes=400_000, ledger_line_bytes=40)
    ctx = lc.build_director_context({}, "", root=tmp_path, ctl=tmp_path)
    assert "queue-tail-marker" in ctx, (
        "the plan's NEWEST (appended) closure row was truncated away - this is "
        "the cycle-9 / cycle-11 duplicate-directive defect"
    )


def test_plan_truncation_marker_sits_between_head_and_tail(lc, tmp_path):
    """A head slice glued straight onto a tail slice reads as continuous prose
    and the director would infer a row order that does not exist."""
    _seed(tmp_path, plan_bytes=400_000, ledger_line_bytes=40)
    ctx = lc.build_director_context({}, "", root=tmp_path, ctl=tmp_path)
    head_at = ctx.index("queue-head-marker")
    tail_at = ctx.index("queue-tail-marker")
    cut_at = ctx.index("ORCHESTRATION_PLAN truncated")
    assert head_at < cut_at < tail_at, (
        "the truncation marker must separate the head slice from the tail slice"
    )


def test_ledger_digest_delivers_many_item_ids_not_one(lc, tmp_path):
    """Modern ledger items are 5-10KB on ONE line, so an 8,000-byte cap over
    whole items yielded a single partial id and cut the very item recording
    the closure. Budget per ITEM instead: same bytes, ~26 ids."""
    _seed(tmp_path, plan_bytes=2_000, ledger_line_bytes=3_000)
    ctx = lc.build_director_context({}, "", root=tmp_path, ctl=tmp_path)
    ids = set(re.findall(r"\b(6\d\d|7\d\d)\. DONE", ctx))
    assert len(ids) >= 10, (
        f"only {len(ids)} ledger item ids survived the digest ({sorted(ids)}) - "
        "the director cannot de-dup against items it cannot see"
    )


def test_ledger_digest_respects_its_byte_budget(lc, tmp_path):
    """Per-item budgeting must not become a way to smuggle the whole ledger in.

    TIGHTENED 2026-07-27 after a verifier REFUTE. This assertion carried a
    `+ 200` slack, so it stayed GREEN over an 8,020-byte return against an
    8,000 cap: it measured "roughly the budget", not the budget. A cap that
    its own constant does not actually bound is the always-green shape this
    whole slice exists to remove, so the bound is now exact - and measured on
    the real 3MB ledger as well as on the fixture, because the fixture alone
    never reached the marker path that carried the overage."""
    _seed(tmp_path, plan_bytes=2_000, ledger_line_bytes=3_000)
    cases = {
        "fixture": (tmp_path / "docs" / "LEDGER.md").read_text(encoding="utf-8"),
        "real": (_REPO / "docs" / "LEDGER.md").read_text(encoding="utf-8", errors="replace"),
    }
    for name, text in cases.items():
        out = lc.ledger_digest(text, lc.LEDGER_ITEM_HEAD, lc.LEDGER_CTX_CAP, "LEDGER")
        assert len(out) <= lc.LEDGER_CTX_CAP, (
            f"{name} ledger digest is {len(out)} bytes - over LEDGER_CTX_CAP "
            f"{lc.LEDGER_CTX_CAP} by {len(out) - lc.LEDGER_CTX_CAP}; the truncation "
            "marker must be charged to the budget, not appended after it"
        )


def test_plan_cap_respects_its_byte_budget(lc):
    """Sibling bound for the head+tail helper, ASSERTED rather than assumed -
    the verifier asked whether it carried the same uncharged-marker defect.
    It does not: it subtracts len(marker) from the keep budget up front."""
    text = (_REPO / "docs" / "ORCHESTRATION_PLAN.md").read_text(encoding="utf-8", errors="replace")
    out = lc.cap_bytes_head_tail(text, lc.PLAN_CTX_CAP, "ORCHESTRATION_PLAN", lc.PLAN_CTX_HEAD)
    assert len(out) <= lc.PLAN_CTX_CAP, (
        f"plan cap returned {len(out)} bytes against PLAN_CTX_CAP {lc.PLAN_CTX_CAP}"
    )


def test_small_docs_pass_through_unchanged(lc, tmp_path):
    """Below the caps the context carries the docs verbatim (byte-identical
    behavior for the normal case)."""
    _seed(tmp_path, plan_bytes=2_000, ledger_line_bytes=40)
    ctx = lc.build_director_context({}, "", root=tmp_path, ctl=tmp_path)
    plan = (tmp_path / "docs" / "ORCHESTRATION_PLAN.md").read_text(encoding="utf-8")
    assert plan in ctx, "small plan must be embedded verbatim"


# --- measured against the REAL docs. Both are tracked in git, so they are
# --- present in every checkout: a skip guard here could only ever be
# --- always-pass, which is the class the 2026-07-27 skip audit removed.

def test_real_orchestration_plan_newest_row_survives(lc, tmp_path):
    """Measured on the live 271KB plan, not a fixture. The newest row id is
    DERIVED from the file rather than pinned, so this cannot rot into a
    literal that outlives the row it names."""
    plan = _REPO / "docs" / "ORCHESTRATION_PLAN.md"
    assert plan.exists(), f"tracked doc missing from the checkout: {plan}"
    text = plan.read_text(encoding="utf-8", errors="replace")
    rows = re.findall(r"^\| (R\d+) \|", text, re.M)
    assert rows, "no | R<n> | rows found - the plan row shape changed"
    newest = rows[-1]
    ctx = lc.build_director_context({}, "", root=_REPO, ctl=tmp_path)
    assert f"| {newest} |" in ctx, (
        f"the plan's newest row {newest} (offset ~{text.rindex(newest)} of "
        f"{len(text)}) did not survive the {lc.PLAN_CTX_CAP}-byte cap"
    )


def test_real_ledger_newest_items_survive(lc, tmp_path):
    """Measured on the live 3MB ledger. Before the fix exactly ONE item id
    survived; the item recording the previous cycle's closure did not."""
    ledger = _REPO / "docs" / "LEDGER.md"
    assert ledger.exists(), f"tracked doc missing from the checkout: {ledger}"
    ids = re.findall(r"^(\d{3,4})\. ", ledger.read_text(encoding="utf-8", errors="replace"), re.M)
    assert len(ids) >= 5, "fewer than 5 ledger items - the item line shape changed"
    ctx = lc.build_director_context({}, "", root=_REPO, ctl=tmp_path)
    missing = [i for i in ids[:5] if f"{i}. " not in ctx]
    assert not missing, (
        f"the 5 newest ledger items must all reach the director; missing {missing}"
    )
