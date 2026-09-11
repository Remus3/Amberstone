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
    commit 80bb813f - was cut. The LINE budget, not the byte budget, was
    the wrong knob.

So the plan is now head + TAIL with the cut stamped between them, and the
ledger is digested per ITEM (a bounded head slice of each item line) so the
same 8,000 bytes carry ~26 item ids instead of one. Total component budget
is UNCHANGED - this is a reallocation, not a raise.
"""
from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent


@pytest.fixture()
def lc():
    return importlib.import_module("ops.loop.loop_controller")


def _seed_directive_chain(ctl: Path, n: int = 12) -> None:
    """Seed the issued-directive chain the director context embeds.

    build_director_context reads up to 12 records, and a live run carries them
    from cycle 2 onward (~2KB). The stdin overflow this module now guards is
    only reproducible with the chain PRESENT, so a fixture that omits it
    measures a body the director never actually sends.
    """
    recs = [
        {"cycle": i, "title": f"seeded directive unit {i} - {'t' * 90}",
         "sha_after": f"{i:040x}", "verdict": "CLEAN"}
        for i in range(1, n + 1)
    ]
    ctl.mkdir(parents=True, exist_ok=True)
    (ctl / "directive_history.jsonl").write_text(
        "\n".join(json.dumps(r) for r in recs), encoding="utf-8")


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
    assert lc.ADJ_STDIN_CAP <= 60_000, (
        f"ADJ_STDIN_CAP={lc.ADJ_STDIN_CAP} exceeds the 2026-07-03 "
        "measured-safe ceiling (79,911 bytes -> empty stdout)"
    )


def test_component_caps_fit_inside_stdin_cap(lc):
    """The three component caps plus ~16KB of template/digest/chain overhead
    (measured: 79,911-byte payload with 64,000 bytes of component caps) must
    compose UNDER the stdin backstop, or every director call gets the
    middle-cut marker instead of clean component truncation."""
    overhead = 16_000
    total = lc.PLAN_CTX_CAP + lc.LEDGER_CTX_CAP + lc.ROADMAP_CTX_CAP + overhead
    assert total <= lc.ADJ_STDIN_CAP, (
        f"component caps + overhead = {total} > ADJ_STDIN_CAP {lc.ADJ_STDIN_CAP}"
    )


def test_plan_head_and_tail_reallocate_the_same_total_budget(lc):
    """The 2026-07-27 tail fix must be a REALLOCATION, not a raise: gemini's
    empty-stdout ceiling is the reason PLAN_CTX_CAP exists at all, so the head
    slice plus the tail slice have to sum back to the unchanged 24,000."""
    assert lc.PLAN_CTX_CAP == 24_000, "plan budget was raised, not reallocated"
    assert lc.PLAN_CTX_HEAD < lc.PLAN_CTX_CAP, "head slice must leave room for a tail"
    assert lc.PLAN_CTX_HEAD > 0, "the plan's own instructions live at the head"


def test_director_context_fits_adjudicator_stdin(lc, tmp_path):
    """2026-07-02: gemini CLI returns silent EMPTY stdout above ~80KB stdin
    (80KB delivered, 160KB empty - measured). The assembled context plus the
    prompt template must stay inside the proven-safe stdin budget even when
    the plan, ledger AND roadmap are all pathologically bloated.

    2026-07-27 RETARGET. This measured the CONTEXT against
    ``ADJ_STDIN_CAP - 8_000``, a hardcoded GUESS at the overhead of the two
    components it excluded - the prompt template and the operator brief. Both
    outgrew the guess (template 12,726 bytes, brief 5,273), so the real stdin
    ran 62,919 bytes while this assertion read green at 48,054 <= 52,000. The
    budget is now DERIVED from the assembled body, so template growth can no
    longer hide behind a magic number.
    """
    _seed(tmp_path, plan_bytes=400_000, ledger_line_bytes=3_000, roadmap_bytes=150_000)
    _seed_directive_chain(tmp_path)
    body = lc.build_director_body({}, "", root=tmp_path, ctl=tmp_path)
    assert len(body) <= lc.ADJ_STDIN_CAP, (
        f"assembled director body is {len(body)} bytes - exceeds "
        f"ADJ_STDIN_CAP {lc.ADJ_STDIN_CAP}"
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


# --- 2026-09-11: the row-survives guard above is a fire alarm that rings once
# --- the house is gone - it goes red only AFTER the newest row has already
# --- fallen out of the director's window, at which point the cheapest repair
# --- (relocate a findings block) has to happen under a red suite. Every cycle
# --- appends a row AND a findings block, but the findings land AFTER the rows,
# --- so the newest row drifts toward EOF by roughly one findings block per
# --- cycle while the row itself barely moves. A HEADROOM bound trips while
# --- there is still room to act. 4000 bytes is about one findings block, so
# --- this reds one cycle early rather than one cycle late.
_TAIL_HEADROOM_BYTES = 4_000


def test_real_orchestration_plan_newest_row_keeps_tail_headroom(lc):
    """Measured on the live plan, like its sibling above, but bounding the
    MARGIN rather than the bare fact of survival.

    The tail boundary is DERIVED - from PLAN_CTX_CAP, PLAN_CTX_HEAD and the
    length of the marker the helper actually emits - rather than pinned at the
    15,888 it happens to equal today. A literal would rot silently the moment
    either constant moved, leaving this asserting against a window the
    controller no longer uses.
    """
    plan = _REPO / "docs" / "ORCHESTRATION_PLAN.md"
    assert plan.exists(), f"tracked doc missing from the checkout: {plan}"
    text = plan.read_text(encoding="utf-8", errors="replace")
    rows = re.findall(r"^\| (R\d+) \|", text, re.M)
    assert rows, "no | R<n> | rows found - the plan row shape changed"
    newest = rows[-1]

    capped = lc.cap_bytes_head_tail(
        text, lc.PLAN_CTX_CAP, "ORCHESTRATION_PLAN", lc.PLAN_CTX_HEAD
    )
    if len(text) <= lc.PLAN_CTX_CAP:
        # Not a vacuous pass: below the cap the helper returns the text
        # unchanged, so the WHOLE plan reaches the director and there is no
        # tail boundary to have headroom against. The live plan is ~397KB, so
        # this branch is unreachable today and is here to fail loudly with the
        # reason if the plan is ever cut down to size.
        assert text in capped, "sub-cap plan must pass through verbatim"
        return
    marker = re.search(
        r"\n\.\.\.\[ORCHESTRATION_PLAN truncated at \d+ bytes[^\]]*\]\.\.\.\n", capped
    )
    assert marker, (
        "cap_bytes_head_tail truncated the plan but emitted no recognisable "
        "marker - the marker text changed and this guard can no longer locate "
        "the head/tail split"
    )
    tail_bytes = len(capped) - marker.end()
    from_eof = len(text) - text.rindex(f"| {newest} |")
    headroom = tail_bytes - from_eof

    assert headroom >= _TAIL_HEADROOM_BYTES, (
        f"the plan's newest row {newest} sits {from_eof} bytes from EOF against "
        f"a {tail_bytes}-byte director tail window, leaving {headroom} bytes of "
        f"headroom - under the {_TAIL_HEADROOM_BYTES} required. Relocate the "
        "OLDEST findings block out of docs/ORCHESTRATION_PLAN.md into "
        "docs/ORCHESTRATION_PLAN_HISTORY.md, verbatim. Do NOT raise "
        "PLAN_CTX_CAP, shrink the new row, or relax this bound: the cap exists "
        "because the director CLI returns silent-empty on an oversized stdin, "
        "so buying tail with cap trades one starvation mode for the other."
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


# --- 2026-07-27: the WHOLE stdin, not just its components -------------------
# --- Every cap above bounds one COMPONENT. Nothing bounded their SUM plus the
# --- prompt template plus the operator brief, so cap_stdin's blind 60/40
# --- middle cut fired on every live cycle. Measured on the real repo: a
# --- 62,919-byte body against ADJ_STDIN_CAP 60,000, and the 2,919 bytes it
# --- discarded were exactly the ALREADY-COMPLETED DIGEST header and the whole
# --- RECENT COMMITS block - the literal refutation of the duplicate directive
# --- the director kept re-emitting. Measured against the REAL docs, which are
# --- tracked, so a skip guard here could only ever be always-pass.

_COMMITS_MARKER = "--- RECENT COMMITS (newest first) ---"
_DIGEST_MARKER = "=== ALREADY-COMPLETED DIGEST"


def _real_body(lc, ctl: Path) -> str:
    """The exact stdin a live director cycle sends: real docs, real commits,
    and a populated directive chain."""
    _seed_directive_chain(ctl)
    return lc.build_director_body({}, "", root=_REPO, ctl=ctl)


def test_real_director_body_fits_adjudicator_stdin(lc, tmp_path):
    """The assembled stdin must fit the cap on its own, so the blind backstop
    never runs. cap_stdin returns its argument UNCHANGED below the limit, so
    identity is the assertion that the backstop did not fire."""
    body = _real_body(lc, tmp_path)
    assert len(body) <= lc.ADJ_STDIN_CAP, (
        f"director stdin is {len(body)} bytes against ADJ_STDIN_CAP "
        f"{lc.ADJ_STDIN_CAP} - cap_stdin will blind-cut the middle"
    )
    assert lc.cap_stdin(body) is body, "cap_stdin still fired on a normal body"


def test_real_recent_commits_block_survives_the_stdin_cap(lc, tmp_path):
    """The commit log is the cheapest and most current proof of what already
    shipped. It sat in the middle of the body, which is precisely the region
    cap_stdin sacrifices."""
    capped = lc.cap_stdin(_real_body(lc, tmp_path))
    assert _COMMITS_MARKER in capped, (
        "the RECENT COMMITS block was cut from the director stdin - the "
        "director cannot refute a duplicate it is never shown"
    )


def test_real_completed_digest_header_survives_the_stdin_cap(lc, tmp_path):
    """The header is what tells the director the block beneath it is DONE
    work. Losing it silently downgrades the digest to unlabelled prose."""
    capped = lc.cap_stdin(_real_body(lc, tmp_path))
    assert _DIGEST_MARKER in capped, (
        "the ALREADY-COMPLETED DIGEST header was cut from the director stdin"
    )


def test_overflow_is_repaid_out_of_the_plan_slice(lc, tmp_path):
    """The plan is the ONLY expendable component - it is a work menu, and both
    its head and tail slices survive a smaller budget. The digest is evidence,
    so it must never be the thing that shrinks. The stamped truncation marker
    names the budget actually applied, so it reports which component paid.

    DETERMINISM FIX 2026-07-27. This used to take the ambient _real_body and
    hope it overflowed, which made the CHECKOUT an uncontrolled input: the same
    commit read green on Legion and red on the ubuntu nightly, because the live
    margin was measured at 996 bytes and LF-vs-CRLF alone moves the assembled
    body by more than that. When nothing overflows the plan is never repaid, so
    its marker stamps the full cap and `< PLAN_CTX_CAP` fails for a reason that
    has nothing to do with the repayment mechanism.

    The overflow is therefore DRIVEN. LAST AUDIT is an uncapped component -
    build_director_context embeds the auditor verdict verbatim, which is exactly
    how a real REGRESS body inflates a cycle - so padding it past the stdin
    ceiling exercises the real production path on every platform. The pad is
    sized from the measured baseline rather than pinned, so it cannot rot into a
    literal that stops overflowing when the docs shrink."""
    _seed_directive_chain(tmp_path)
    baseline = lc.build_director_body({}, "", root=_REPO, ctl=tmp_path)
    pad = max(lc.ADJ_STDIN_CAP - len(baseline), 0) + 4_096
    audit = "AUDIT-PAD-MARKER " + "p" * pad
    body = lc.build_director_body({}, audit, root=_REPO, ctl=tmp_path)
    assert "AUDIT-PAD-MARKER" in body, "the driven overflow never reached the body"

    applied = re.search(r"\[ORCHESTRATION_PLAN truncated at (\d+) bytes", body)
    assert applied, "the plan carries no truncation marker to attribute the cut to"
    assert int(applied.group(1)) < lc.PLAN_CTX_CAP, (
        f"plan budget stayed at {applied.group(1)} - the overflow was repaid "
        "out of some other component"
    )
    for marker in (_COMMITS_MARKER, _DIGEST_MARKER,
                   "--- DIRECTIVES ALREADY ISSUED THIS RUN"):
        assert marker in body, f"digest component {marker!r} was sacrificed"


def test_plan_cap_floor_keeps_head_and_tail(lc):
    """A floor stops the repayment from starving the plan to nothing, and it
    must stay above PLAN_CTX_HEAD or the tail slice - where the newest queue
    rows live - is what the floor silently deletes."""
    assert lc.PLAN_CTX_MIN > lc.PLAN_CTX_HEAD, (
        "the floor must leave room for the plan TAIL, not just the head"
    )
    assert lc.PLAN_CTX_MIN < lc.PLAN_CTX_CAP


def test_explicit_plan_cap_shrinks_only_the_plan(lc, tmp_path):
    """The injectable plan_cap is the mechanism the overflow path uses."""
    small = lc.build_director_context({}, "", root=_REPO, ctl=tmp_path,
                                      plan_cap=lc.PLAN_CTX_MIN)
    big = lc.build_director_context({}, "", root=_REPO, ctl=tmp_path)
    assert len(small) < len(big)
    assert len(big) - len(small) == lc.PLAN_CTX_CAP - lc.PLAN_CTX_MIN
    for marker in (_COMMITS_MARKER, _DIGEST_MARKER):
        assert marker in small


def test_escalation_survives_a_context_rebuild(lc, tmp_path):
    """The escalation file is CONSUMED on read. If the overflow rebuild popped
    it a second time the question would vanish from the very body it was
    raised for - the failure mode that made the pop the body assembler's job."""
    _seed_directive_chain(tmp_path)
    (tmp_path / "gemini_ask.txt").write_text("ESCALATION-MARKER-Q", encoding="utf-8")
    body = lc.build_director_body({}, "", root=_REPO, ctl=tmp_path)
    assert "ESCALATION-MARKER-Q" in body, "the rebuild swallowed the escalation"
    assert not (tmp_path / "gemini_ask.txt").exists(), "escalation not consumed"


# --- 2026-07-27 slice 2: the operator brief is STATIC background policy -----
# --- It was appended after the LAST AUDIT body with a bare blank line and no
# --- header, so 5,273 bytes of standing prose read as the tail of this
# --- cycle's audit - i.e. as a work order the director should act on now.

def test_operator_brief_is_labelled_and_not_attributed_to_last_audit(lc, tmp_path):
    """The brief this asserts on is the one the controller actually loads, so
    the assertion below doubles as a guard on CFG RESOLUTION. It was red on the
    ubuntu nightly and green on Legion because the controller defaulted to an
    absolute C: config path: off that one host CFG resolved to {}, the brief
    read as empty, and the labelling behaviour was never exercised at all.
    ops/loop/config.json is TRACKED, so an empty directive_suffix is the thing
    under test being broken - never an absent environment capability - which is
    why this stays an assert rather than a skip (tests/test_skip_condition_
    hygiene.py fails any skip gated on a tracked artifact)."""
    suffix = lc.CFG.get("directive_suffix", "")
    assert suffix, "config.json lost directive_suffix - this test needs it non-empty"
    ctx = lc.build_director_context({}, "AUDIT-BODY-MARKER", root=_REPO, ctl=tmp_path)

    assert lc.DIRECTIVE_SUFFIX_HEADER in ctx, "the operator brief carries no header"
    audit_at = ctx.index("=== LAST AUDIT")
    hdr_at = ctx.index(lc.DIRECTIVE_SUFFIX_HEADER)
    assert hdr_at > audit_at, "the brief must follow the LAST AUDIT section"

    between = ctx[audit_at:hdr_at]
    assert "AUDIT-BODY-MARKER" in between, "the audit body moved out of its section"
    assert suffix not in between, "the brief still sits INSIDE the LAST AUDIT body"
    assert ctx.index(suffix, hdr_at) >= hdr_at + len(lc.DIRECTIVE_SUFFIX_HEADER), (
        "the brief must start after its header, not before it"
    )


def test_operator_brief_header_states_the_digest_overrides_it(lc):
    """The header has one job: stop STATIC prose outranking the digest."""
    hdr = lc.DIRECTIVE_SUFFIX_HEADER
    assert hdr.startswith("=== ") and hdr.endswith(" ==="), "not a section boundary"
    assert "OPERATOR STANDING BRIEF" in hdr
    assert "NOT this cycle's work order" in hdr
    assert "ALREADY-COMPLETED DIGEST OVERRIDES it" in hdr
    assert hdr.isascii(), "7-bit ASCII only"
