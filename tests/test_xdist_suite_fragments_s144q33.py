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

RM-1103 (the s144 queue cycle 48 verifier's five blind spots) tightened the
predicate: a `tests\\` / `./tests` root names the suite; an `--ignore` /
`--ignore-glob` / `--deselect` value is a file the run skips, not one it cites;
a fenced command continued by a trailing backtick, caret or backslash is one
span; a span is split on `;`, `&&`, `||` and `|`, so the gate covers its own
command only; and the TIER TABLE flags match as whole tokens (`-n 80` is not
`-n 8`).

RM-1104 (the s144 queue cycle 49 verifier's four residues): a single `&`
between two commands chains (cmd.exe) while a leading `&` (PowerShell's call
operator) does not; the gate counts only where it prefixes the run; `-n=8` and
`-n8` run xdist; and the TIER TABLE flags accept every spelling pytest parses
the same way (`-n8`, `-n=8`, `--dist=loadfile`), pinned by a test.

RM-1106 (the s144 queue cycle 54 verifier): bash's `|&` is one chain
operator, so `x|&tests/ -q -n 8` reads its suite root `tests/`, not `&tests/`.

Out of scope: dated records (docs/_archive/, measurement docs, plans, audits,
LEDGER, ROADMAP history) quote the command that was run at the time; they are
evidence, not instructions. CLAUDE.md is the main session's file.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from tests.test_command_docs_suite_gate import (
    _CHAIN,
    COMMANDS,
    RESTART_CAP,
    _has_tier_table_flags,
    _names_a_test_file,
)

ROOT = Path(__file__).resolve().parent.parent
LIVING_OPS_DOCS = ("docs/OPERATIONS.md", "docs/ARCHITECTURE.md", "docs/API.md",
                   "README.md")
SCANNED = tuple(f"tools/{name}" for name in COMMANDS) + LIVING_OPS_DOCS

GATE = "fleet_suite_gate.py"
SUITE_ROOTS = {"tests", "agents/daemon_slayer/tests", "agents/daemon_slayer",
               "tools/tests", "tests/snapshot_panels", "."}
# `-n 8`, `-n8` and `-n=8` all run xdist (RM-1104 (c)).
_XDIST = re.compile(r"(?:^|\s)(?:-n(?:\s*|=)(?:\d+|auto|logical)"
                    r"|--numprocesses(?:=|\s+)\S+)(?=\s|$)")
_PYTEST_WORD = re.compile(r"\bpytest\b")
_FENCE = re.compile(r"^\s*(?:>\s*)*```")
_INLINE = re.compile(r"`([^`\n]+)`")
# A fenced line ending in a PowerShell backtick, a cmd caret or a shell
# backslash continues on the next line (RM-1103 (c)).
_CONTINUED = re.compile(r"\s[`^\\]$")
# The chain split (d), the --ignore / --deselect skip (b) and the whole-token
# TIER TABLE flags (e) are the RM-754 guard's own predicates, imported above.


def _spans(rel: str):
    """Yield (line_no, span) for every inline code span and fenced code line;
    a continued fenced command is one span, numbered by its first line."""
    fenced, held, start = False, "", 0
    text = (ROOT / rel).read_bytes().decode("utf-8")
    for n, line in enumerate(text.split("\n"), start=1):
        if _FENCE.match(line):
            if held:
                yield start, held
            fenced, held = not fenced, ""
            continue
        if fenced:
            part = line.strip()
            if not held:
                start = n
            held = f"{held} {part}".strip()
            if _CONTINUED.search(" " + held):
                held = held[:-1].rstrip()
                continue
            yield start, held
            held = ""
        else:
            for m in _INLINE.finditer(line):
                yield n, m.group(1).strip()
    if held:
        yield start, held


def _runs_xdist(span: str) -> bool:
    return bool(_XDIST.search(span))


def _root(tok: str) -> str:
    """`tests\\`, `./tests/` and `.\\tests` all name the root `tests`."""
    tok = tok.replace("\\", "/")
    while tok.startswith("./"):
        tok = tok[2:]
    return tok.rstrip("/") or "."


def _names_a_suite(span: str) -> bool:
    if _PYTEST_WORD.search(span):
        return True
    return any(_root(tok) in SUITE_ROOTS for tok in span.split())


def _is_collect_only(span: str) -> bool:
    toks = span.split()
    return "--collect-only" in toks or "--co" in toks


def _is_gated(span: str) -> bool:
    """The gate PREFIXES the run: it sits before the first `pytest` word (else
    the first xdist flag), so a gate named after the run - a trailing comment,
    an argument - does not gate it (RM-1104 (b))."""
    run = _PYTEST_WORD.search(span) or _XDIST.search(span)
    head = span if run is None else span[:run.start()]
    return f"{GATE} run" in head or f'{GATE}" run' in head


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


def _segments(span: str) -> list[str]:
    return [seg for seg in _CHAIN.split(span) if seg]


def _suite_segments(span: str) -> list[str]:
    return [seg for seg in _segments(span) if _is_xdist_whole_suite(seg)]


def _ungated_suite_segments(span: str) -> list[str]:
    return [seg for seg in _suite_segments(span) if not _is_gated(seg)]


def test_the_scanned_docs_exist():
    missing = [rel for rel in SCANNED if not (ROOT / rel).is_file()]
    assert not missing, missing


def test_no_living_doc_carries_an_ungated_xdist_suite_fragment():
    seen, bad = 0, []
    for rel in SCANNED:
        for n, span in _spans(rel):
            seen += len(_suite_segments(span))
            bad.extend(f"{rel}:{n}: {seg[:140]}"
                       for seg in _ungated_suite_segments(span))
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
            if not _has_tier_table_flags(span):
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


def test_a_backslash_or_dot_slash_suite_root_is_a_suite():
    # RM-1103 (a): a Windows `tests\` or a `./tests` root names the suite.
    for frag in ("tests\\ -q -n 8", ".\\tests -n 8", "./tests -q -n 8",
                 "./tests/ agents\\daemon_slayer\\tests -n 4"):
        assert _is_xdist_whole_suite(frag) and not _is_gated(frag), frag


def test_an_ignore_or_deselect_value_is_not_a_cited_test_file():
    # RM-1103 (b): a whole suite that skips one file still runs the suite.
    for frag in ("python -m pytest tests -n 8 --ignore=tests/test_x.py",
                 "python -m pytest tests -n 8 --ignore tests/test_x.py",
                 "python -m pytest tests -n 8 --deselect tests/test_x.py::test_y",
                 "python -m pytest tests -n 8 --deselect=tests/test_x.py::test_y",
                 "python -m pytest tests -n 8 --ignore-glob=tests/test_x*.py"):
        assert _is_xdist_whole_suite(frag), frag
    # A cited file next to an --ignore value is still a slice.
    assert not _is_xdist_whole_suite(
        "python -m pytest tests/test_a.py -n 8 --ignore=tests/test_b.py")


def test_a_continued_fenced_command_is_read_as_one_span(tmp_path, monkeypatch):
    # RM-1103 (c): PowerShell backtick, cmd caret and shell backslash
    # continuations join with the next fenced line.
    doc = tmp_path / "docs" / "X.md"
    doc.parent.mkdir()
    doc.write_bytes(b"```powershell\npython -m pytest tests `\n  -q -n 8\n"
                    b"python -m pytest tests ^\n  -n 8\n"
                    b"python -m pytest tests \\\n  -n 8\n```\n")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    hits = [(n, s) for n, s in _spans("docs/X.md") if _ungated_suite_segments(s)]
    assert [n for n, _ in hits] == [2, 4, 6], hits


def test_a_gate_does_not_cover_a_chained_ungated_suite():
    # RM-1103 (d): the gate covers its own command, not the next one.
    gated = ("python ops/fleet_kit/fleet_suite_gate.py run --owner <id> -- "
             "python -m pytest tests -q -n 8 --dist loadfile "
             "--max-worker-restart=0")
    for sep in ("; ", " && ", " || ", " | "):
        assert _ungated_suite_segments(gated + sep + "python -m pytest tests -n 8"), sep
    assert not _ungated_suite_segments(gated)
    assert not _ungated_suite_segments("cd <repo> && " + gated)


def test_the_tier_table_flags_are_matched_as_whole_tokens():
    # RM-1103 (e): `-n 80` and `--dist loadfilex` are not the TIER TABLE flags.
    ok = "-q -n 8 --dist loadfile --max-worker-restart=0"
    assert _has_tier_table_flags(ok)
    for bad in ("-q -n 80 --dist loadfile --max-worker-restart=0",
                "-q -n 8 --dist loadfilex --max-worker-restart=0",
                "-q -n 8 --dist loadscope --max-worker-restart=0",
                "-q -n 8 --dist loadfile"):
        assert not _has_tier_table_flags(bad), bad


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


def test_a_single_ampersand_chains_but_a_call_operator_does_not():
    # RM-1104 (a): cmd.exe's `a & b` runs b after a, so a gate before a
    # single `&` does not cover the suite after it; PowerShell's leading `&`
    # call operator (`& "py.exe" -m pytest`, also after `;`) is not a chain.
    gated = ("python ops/fleet_kit/fleet_suite_gate.py run --owner <id> -- "
             "python -m pytest tests -q -n 8 --dist loadfile "
             "--max-worker-restart=0")
    assert _ungated_suite_segments(gated + " & python -m pytest tests -n 8")
    call = ('& "py.exe" ops/fleet_kit/fleet_suite_gate.py run --owner <id> -- '
            '"py.exe" -m pytest tests -q -n 8 --dist loadfile --max-worker-restart=0')
    assert _segments(call) == [call]
    assert not _ungated_suite_segments(call)
    assert not _ungated_suite_segments("cd <repo>; " + call)
    assert _segments('cd <repo>; & "py.exe" -V') == ["cd <repo>", '& "py.exe" -V']
    # `2>&1` and `&&` are not single-ampersand chains.
    assert _segments("a 2>&1 && b") == ["a 2>&1", "b"]


def test_a_suite_after_a_pipe_ampersand_is_still_a_suite():
    # RM-1106: `x |& <cmd>` classifies <cmd> as if it stood alone. Before,
    # `x|&tests/ -q -n 8` left the token `&tests/`, which names no suite root.
    gated = ("python ops/fleet_kit/fleet_suite_gate.py run --owner <id> -- "
             "python -m pytest tests -q -n 8 --dist loadfile "
             "--max-worker-restart=0")
    for cmd in ("tests/ -q -n 8", "python -m pytest tests -n 8", "pytest . -n 8"):
        assert _ungated_suite_segments(cmd)
        for sep in (" |& ", "|&", " |&", "|& "):
            assert _ungated_suite_segments("x" + sep + cmd) == [cmd], (sep, cmd)
    for sep in (" |& ", "|&"):
        assert _suite_segments("x" + sep + gated) == [gated], sep
        assert not _ungated_suite_segments("x" + sep + gated), sep


def test_the_gate_must_precede_the_suite_it_covers():
    # RM-1104 (b): a gate named AFTER the run (a trailing comment, an
    # argument) does not gate the run; the gate prefixes the command. The
    # quoted form is the reachable one: a bare `...gate.py` token reads as a
    # cited test file and already makes the span a slice.
    for frag in ('python -m pytest tests -n 8 # "ops/fleet_kit/fleet_suite_gate.py" run',
                 'python -m pytest tests -n 8 --ignore=x "fleet_suite_gate.py" run',
                 'tests/ -q -n 8 then "fleet_suite_gate.py" run'):
        assert _is_xdist_whole_suite(frag) and not _is_gated(frag), frag
    assert _is_gated('& "py.exe" ops/fleet_kit/fleet_suite_gate.py" run --owner <id> '
                     '-- "py.exe" -m pytest tests -n 8')


def test_every_argparse_spelling_of_n_runs_xdist():
    # RM-1104 (c): pytest parses `-n=8` and `-n8` as `-n 8`.
    for frag in ("python -m pytest tests -n=8", "python -m pytest tests -n8",
                 "tests/ -q -n=auto", "pytest . --numprocesses 4"):
        assert _is_xdist_whole_suite(frag) and not _is_gated(frag), frag
    for prose in ("-name", "--no-header", "-nx"):
        assert not _runs_xdist(prose), prose


def test_the_tier_table_flags_accept_each_argparse_spelling():
    # RM-1104 (d), the choice pinned: the guard pins what the run DOES, so
    # every spelling pytest parses identically to `-n 8 --dist loadfile` is
    # accepted; a different value is not. `--max-worker-restart=0` stays the
    # one literal token the RM-754 guards and the TIER TABLE name.
    for ok in ("-n8 --dist loadfile --max-worker-restart=0",
               "-n=8 --dist loadfile --max-worker-restart=0",
               "-n 8 --dist=loadfile --max-worker-restart=0"):
        assert _has_tier_table_flags(ok), ok
    for bad in ("-n=80 --dist loadfile --max-worker-restart=0",
                "-n8 --dist=loadscope --max-worker-restart=0",
                "-n 8 --dist loadfile --max-worker-restart 0"):
        assert not _has_tier_table_flags(bad), bad
