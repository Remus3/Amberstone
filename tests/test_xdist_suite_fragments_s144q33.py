"""No living doc carries an ungated xdist whole-suite fragment (RM-1102).

Filed by the s144 queue cycle 47 verifier after RM-754: the RM-754 guard
(tests/test_command_docs_suite_gate.py) matches only the `-m pytest` form in
the 23 slash-command docs, so three xdist suite fragments sat outside it with
neither the kit suite gate (FLEET-COMMON 16c) nor `--max-worker-restart=0`:

  * docs/OPERATIONS.md, the `RC_REQUIRE_DS_ENGINE` recipe: a fenced
    `python -m pytest tests/ agents/daemon_slayer/tests/ -q -n 8` - an ungated
    whole suite with no `--dist loadfile` and no restart cap;
  * docs/OPERATIONS.md, "Rules of thumb": `pytest . -n 8` named as the
    pre-merge bar - ungated, and `pytest .` is banned by name in CLAUDE.md
    (it has deleted the live supervisor lock);
  * tools/headless-true-audit.md, wrap step 1: the shorthand `tests/ -q -n 8`,
    which has no `-m pytest` and so no guard saw it.

Pinned here, over the command docs plus the living ops docs (CLAUDE.md "Docs
map": ARCHITECTURE, OPERATIONS, API, plus README): every code span - an inline
backtick span, or one line of a fenced block - that runs xdist (`-n <x>` /
`--numprocesses`) over a suite root (it says `pytest`, or names `tests`,
`agents/daemon_slayer/tests` and the like) without naming a test file and
without being a `--collect-only` count sits inside a `fleet_suite_gate.py run`
call, and every gated call in a living ops doc carries the TIER TABLE flags
(`-n 8 --dist loadfile --max-worker-restart=0`). A bare `-n 8` span in prose
(a worker count, not a command) is not a suite and is not matched.

Out of scope: dated records (docs/_archive/, measurement docs, plans, audits,
LEDGER, ROADMAP history) quote the command that was run at the time; they are
evidence, not instructions. CLAUDE.md is the main session's file.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from tests.test_command_docs_suite_gate import COMMANDS, RESTART_CAP

ROOT = Path(__file__).resolve().parent.parent
LIVING_OPS_DOCS = ("docs/OPERATIONS.md", "docs/ARCHITECTURE.md", "docs/API.md",
                   "README.md")
SCANNED = tuple(f"tools/{name}" for name in COMMANDS) + LIVING_OPS_DOCS

GATE = "fleet_suite_gate.py"
SUITE_ROOTS = {"tests", "agents/daemon_slayer/tests", "agents/daemon_slayer",
               "tools/tests", "tests/snapshot_panels", "."}
_XDIST = re.compile(r"(?:^|\s)(?:-n\s*(?:\d+|auto|logical)|--numprocesses(?:=|\s+)\S+)(?=\s|$)")
_PYTEST_WORD = re.compile(r"\bpytest\b")
_FENCE = re.compile(r"^\s*(?:>\s*)*```")
_INLINE = re.compile(r"`([^`\n]+)`")


def _spans(rel: str):
    """Yield (line_no, span) for every inline code span and fenced code line."""
    fenced = False
    text = (ROOT / rel).read_bytes().decode("utf-8")
    for n, line in enumerate(text.split("\n"), start=1):
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            yield n, line.strip()
        else:
            for m in _INLINE.finditer(line):
                yield n, m.group(1).strip()


def _runs_xdist(span: str) -> bool:
    return bool(_XDIST.search(span))


def _names_a_suite(span: str) -> bool:
    if _PYTEST_WORD.search(span):
        return True
    return any(tok.rstrip("/") in SUITE_ROOTS or tok in SUITE_ROOTS
               for tok in span.split())


def _names_a_test_file(span: str) -> bool:
    return any(tok.endswith(".py") or "::" in tok for tok in span.split())


def _is_collect_only(span: str) -> bool:
    toks = span.split()
    return "--collect-only" in toks or "--co" in toks


def _is_gated(span: str) -> bool:
    return f"{GATE} run" in span or f'{GATE}" run' in span


def _pytest_args(span: str) -> str:
    """The arguments after the last `pytest` word, else the whole span (so the
    gate's own `fleet_suite_gate.py` path is not read as a cited test file)."""
    last = None
    for last in _PYTEST_WORD.finditer(span):
        pass
    return span if last is None else span[last.end():]


def _is_xdist_whole_suite(span: str) -> bool:
    args = _pytest_args(span)
    return (_runs_xdist(span) and _names_a_suite(span)
            and not _names_a_test_file(args) and not _is_collect_only(args))


def test_the_scanned_docs_exist():
    missing = [rel for rel in SCANNED if not (ROOT / rel).is_file()]
    assert not missing, missing


def test_no_living_doc_carries_an_ungated_xdist_suite_fragment():
    seen, bad = 0, []
    for rel in SCANNED:
        for n, span in _spans(rel):
            if not _is_xdist_whole_suite(span):
                continue
            seen += 1
            if not _is_gated(span):
                bad.append(f"{rel}:{n}: {span[:140]}")
    # The TIER TABLE command alone recurs across the command docs; a sweep that
    # matched none of it has gone blind, and an empty sweep would pass.
    assert seen >= 8, f"only {seen} xdist suite spans found - the sweep went blind"
    assert not bad, (
        "xdist whole-suite fragments outside the kit suite gate (FLEET-COMMON "
        "16c) - point at, or restate, the tools/done.md TIER TABLE command:\n"
        + "\n".join(bad))


def test_every_gated_call_in_a_living_ops_doc_carries_the_tier_table_flags():
    seen, bad = 0, []
    for rel in LIVING_OPS_DOCS:
        for n, span in _spans(rel):
            if not (_is_gated(span) and _PYTEST_WORD.search(span)):
                continue
            seen += 1
            toks = span.split()
            if ("-n 8" not in span or "--dist loadfile" not in span
                    or RESTART_CAP not in toks):
                bad.append(f"{rel}:{n}: {span[:140]}")
    assert seen >= 1, "no gated pytest call in the living ops docs - the sweep went blind"
    assert not bad, (f"gated suite without -n 8 --dist loadfile {RESTART_CAP}:\n"
                     + "\n".join(bad))


def test_the_detector_catches_each_filed_fragment():
    # Positive controls: the three filed fragments, verbatim.
    for frag in ("python -m pytest tests/ agents/daemon_slayer/tests/ -q -n 8",
                 "pytest . -n 8", "tests/ -q -n 8"):
        assert _is_xdist_whole_suite(frag) and not _is_gated(frag), frag
    assert _is_xdist_whole_suite("pytest tests --numprocesses=auto")


def test_the_detector_spares_counts_files_prose_and_the_gated_command():
    # Negative controls: a worker count in prose, a cited test file, a
    # collect-only count, a serial suite, and the gated TIER TABLE command.
    for span in ("-n 8", "-n 6", "python -m pytest tests/test_x.py -q -n 8",
                 "python -m pytest tests --collect-only -q -n 8",
                 "python -m pytest tests -q"):
        assert not _is_xdist_whole_suite(span), span
    gated = ("python ops/fleet_kit/fleet_suite_gate.py run --owner <id> -- "
             "python -m pytest tests agents/daemon_slayer/tests -q -n 8 "
             "--dist loadfile --max-worker-restart=0 --timeout=300")
    assert _is_xdist_whole_suite(gated) and _is_gated(gated)


def test_fenced_and_inline_spans_are_both_read(tmp_path, monkeypatch):
    doc = tmp_path / "docs" / "X.md"
    doc.parent.mkdir()
    doc.write_bytes(b"run `tests/ -q -n 8` now\n```powershell\n"
                    b"python -m pytest tests -q -n 8\n```\n-n 8 prose\n")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    spans = list(_spans("docs/X.md"))
    assert (1, "tests/ -q -n 8") in spans
    assert (3, "python -m pytest tests -q -n 8") in spans
    assert all(n != 5 for n, _ in spans)
