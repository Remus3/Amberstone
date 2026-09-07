"""No RUNNABLE surface may hardcode a Windows account's home directory.

Adopted from Sibling-D OPS-38 (their commit ``2e567145a``), whose operator
ruled the same way and whose guard SHAPE is copied here on purpose.

WHY THIS EXISTS
---------------
``Administrator`` is the Windows BUILT-IN account name, so this was never an
identifying leak and must not be reported as one. The real cost is worse:

* **A hook or scheduled-task command naming an interpreter under one account is
  a command that does not run under another, and a command that does not run
  reports NOTHING.** Silent non-execution is the failure mode this repository
  fears most - the same class as a git hook that is present and never fires.
* A fresh clone runs under whatever account the person cloning has. This repo
  is heading for a public flip, so that is not hypothetical.

THE FIX SHAPE, AND WHY IT IS NOT A BARE INTERPRETER NAME
--------------------------------------------------------
Sibling-D parameterised its hook commands to a bare ``python`` resolved from
``PATH``. **RC cannot do that**, and the reason is written down in
``tests/test_bare_py_ban.py``: on this machine a bare launcher resolves through
PEP 514 to a pymanager runtime with no third-party packages, and a past incident
silently ran a pytest-less interpreter and zeroed the suite. So RC's answer keeps
the pin ABSOLUTE and parameterises only the account-specific prefix:

* PowerShell   ``"$env:LOCALAPPDATA\\Programs\\Python\\Python314\\python.exe"``
* cmd / batch  ``"%LOCALAPPDATA%\\Programs\\Python\\Python314\\python.exe"``
* Python code  resolved from ``os.environ`` / ``Path.home()`` at runtime

Both properties hold at once: still absolute, no longer account-specific.
``tools/moon_sync_poller.py`` was the pattern - it already resolved its state
dir this way and had a test asserting no home path is baked in.

THE GUARD'S SHAPE WAS ARRIVED AT BY REFUTATION, NOT INVENTED
------------------------------------------------------------
It matches the SHAPE of a home directory under ANY account name, never the
string this machine happens to use. A guard that only knew ``Administrator``
would pass cleanly the day someone commits a path under a different account -
which is precisely the day it matters.

ONE DELIBERATE NARROWING, MEASURED
----------------------------------
Sibling-D's pattern also matched the POSIX shapes ``/home/<name>`` and
``/Users/<name>``. Ported verbatim it produced 33 findings here that are not
paths at all: this repo serves a dashboard route whose URL begins with the same
two characters as the POSIX home prefix, and it appears across ``web/js/main.js``
and eight test modules. Those are URL routes, not home directories, and pinning
33 false positives would have made the guard a tolerated list instead of a
clean-tree requirement. RC is Windows-only (ADR-011, 1-PC on Legion), so the
POSIX branches are dropped and only the drive-letter shape is matched. This is
recorded because a caveat that lives only in a session transcript is a lie in
the artifact.

HISTORICAL RECORDS ARE FROZEN, NOT EDITED
-----------------------------------------
``docs/_archive/**`` is immutable by this repository's own rule, and the
``ops/audit/`` claim and report artifacts are dated records of what a past audit
observed - the quoted path IS the evidence. Rewriting them would destroy the
record. They are PINNED BY COUNT instead: each may carry exactly the number of
occurrences it carries today, so a NEW occurrence reddens the suite while the
record stays intact. A pin that merely TOLERATED a file would let it grow
forever.

WHAT THIS GUARD IS BLIND TO, stated here because a caveat kept out of the
artifact is a caveat nobody will read:

* It scans files git would publish - tracked, plus untracked-but-not-ignored so
  a defect is caught BEFORE it lands - and only those whose suffix is RUNNABLE
  or CONFIG (see :data:`RUNNABLE_SUFFIXES`). Prose - ``.md``, ``.txt``, ``.jsonl``
  ledgers, ``.log`` - is deliberately out of scope. A path in a document is
  stale documentation; a path in a hook command is silent non-execution, and
  only the second one is what this file was written to stop. ``docs/LEDGER.md``,
  ``docs/history_notes.md``, ``WAKEUP_NOTES.md`` and the ``tools/*.md`` ritual
  documents still carry occurrences and were deliberately not edited.
* It matches a HOME-directory shape. A machine-specific absolute path that is
  not under a home directory - a bespoke root, a mapped drive - is invisible.
* A driveless UNC share (``\\\\server\\Users\\someone``) is out of scope: the
  prefix requires a drive letter and a colon, and a UNC share has neither.
* A pinned file could lose one occurrence and gain another without the count
  moving. The pin is a growth check, not an identity check.
* It says nothing about whether a parameterised path RESOLVES. A command reading
  ``%LOCALAPPDATA%`` is clean here and still broken if that variable is unset -
  which is why :class:`TestTheParameterisedFormsActuallyResolve` exists.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Any Windows user home directory, under ANY account name. The account label
#: must not itself be a placeholder - ``%USERPROFILE%``, ``$env:LOCALAPPDATA``,
#: ``$HOME``, ``~`` and ``<user>`` are the CORRECT forms and must never be
#: reported, which is what the negative lookahead buys.
#:
#: The trailing separator or word boundary matters: without it the pattern would
#: match the bare directory ``C:\Users`` and report a sentence that merely names
#: where Windows keeps home directories.
#:
#: ``re.IGNORECASE`` because Windows paths are case-insensitive - the title-case,
#: lowercase and uppercase spellings all name ONE place, and a committed
#: lowercase path is exactly as live a defect. The lookahead is unaffected by the
#: flag on purpose: its characters are punctuation, not letters.
HOME_SHAPED = re.compile(
    r"[A-Za-z]:[\\/]Users[\\/]"
    r"(?![%$<~])"
    r"[A-Za-z0-9._~-]+"
    r"(?:[\\/]|\b)",
    re.IGNORECASE,
)

#: Suffixes whose content is EXECUTED or PARSED AS CONFIG. See the module
#: docstring for why prose is out of scope.
RUNNABLE_SUFFIXES = frozenset({
    ".py", ".ps1", ".psm1", ".cmd", ".bat", ".sh", ".mjs", ".js",
    ".json", ".xml", ".spec", ".toml", ".yml", ".yaml", ".ini", ".cfg",
})

#: Dated records of what was true on a date. The quoted path IS the evidence,
#: so these are frozen rather than edited. Raising a number here is a deliberate
#: act and belongs in the commit message.
FROZEN_HISTORICAL: dict[str, int] = {
    # docs/_archive/** is immutable by this repository's own rule - it is even
    # excluded from ripgrep searches. These two record a retired scheduled task
    # and a retired LAN bridge exactly as they were registered.
    "docs/_archive/2026-06-11_RC-VisionServer_schtask_removed.xml": 1,
    "docs/_archive/run_lan_bridge.bat": 1,
    # Dated audit artifacts: a claims file and the report produced from it. The
    # recorded suite command is the observation, not an instruction to re-run.
    "ops/audit/p2b_claims.json": 2,
    "ops/audit/p2w5_truth_gate_claims.json": 1,
    "ops/audit/p2w5_truth_gate_report.json": 1,
}

#: Files that DELIBERATELY contain home-shaped paths because the shape is their
#: SUBJECT. A guard that cannot plant its own needle cannot prove it is armed,
#: and this module would otherwise forbid the very technique it depends on.
#:
#: Pinned by COUNT for the same reason the records are: a merely tolerated file
#: grows forever, and a real leak dropped in among the fixtures would hide.
CONTROL_FIXTURES: dict[str, int] = {
    # A negative fixture: an anchored drive-letter path that the DDragon version
    # guard must REJECT. Forbidding it would forbid testing the rejection.
    "tests/test_ddragon_version_path_guard.py": 2,
    # Characterization fixture: the stop-claim gate must still read a quoted
    # absolute interpreter path as evidence of a real pytest run.
    "tests/test_stop_claim_gate.py": 1,
    # This module's own planted needles - MEASURED against a first red run, not
    # guessed. A guess of 9 went red at 7: two of the spellings this file talks
    # about in prose are written as escaped or parameterised forms that the
    # pattern correctly declines to match, and prose describing a needle is not
    # itself a needle unless it is spelled as one.
    "tests/test_no_hardcoded_home_path.py": 7,
}


def tracked_runnable_files() -> list[str]:
    """Every publishable file whose content is executed or parsed as config.

    ``git ls-files`` rather than a tree walk, and that choice is load-bearing
    twice over. It is the only enumeration that answers "what would be published
    from here", and it is inherently immune to the worktree-agent directories
    that live inside this repo during a normal session - a bare ``rglob`` from
    the repo root scans those and reports another checkout's files as this one's.

    ``--others --exclude-standard`` alongside ``--cached`` so a NEW file carrying
    a home path is red BEFORE it is committed rather than after. It costs six
    extra files today and honours ``.gitignore``, so the worktree and scratch
    directories stay excluded.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout
    rels = [p.decode("utf-8") for p in out.split(b"\0") if p]
    return sorted(r for r in rels if Path(r).suffix.lower() in RUNNABLE_SUFFIXES)


def _joined_with_line_numbers(text: str) -> tuple[str, list[int]]:
    """Collapse ``text`` by DROPPING every line break.

    Returns the joined string plus a parallel array giving, for each kept
    character, the 1-based line it came from.

    Dropped rather than replaced by a space: this repository hard-wraps prose
    near 80 columns as a bare newline with no intervening space, so a long
    space-free path can be split right at the wrap. Replacing the newline with a
    space would leave the halves separated and the match would still fail;
    dropping it reconstructs what the author typed. This can only ADD matches
    relative to a per-line scan, never remove one, because no character inside an
    existing single-line match is a newline.
    """
    kept: list[str] = []
    lines: list[int] = []
    line_no = 1
    for ch in text:
        if ch == "\n":
            line_no += 1
            continue
        kept.append(ch)
        lines.append(line_no)
    return "".join(kept), lines


def _findings_in_text(text: str) -> list[tuple[int, str]]:
    """``[(line_number, matched_text)]`` for already-read text.

    Split out from :func:`findings_in` so the line-join behaviour can be
    exercised against a constructed string with no file on disk. The reported
    line is where the match's FIRST character sits, so it is always a real
    openable line even when the match continues onto the next one.
    """
    joined, line_numbers = _joined_with_line_numbers(text)
    return [
        (line_numbers[m.start()], m.group(0))
        for m in HOME_SHAPED.finditer(joined)
    ]


def findings_in(rel: str) -> list[tuple[int, str]]:
    """``[(line_number, matched_text)]`` for one repo-relative file."""
    try:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return _findings_in_text(text)


class TestThePatternItselfIsArmed:
    """A clean result and a broken regex are the same output. Prove otherwise."""

    def test_it_fires_on_a_planted_home_path_in_either_slash_direction(self):
        planted = [
            r"C:\Users\someone\AppData\Local\Programs\Python\Python314\python.exe",
            "C:/Users/someone/AppData/Local/Programs/Python/Python314/python.exe",
        ]
        missed = [t for t in planted if not HOME_SHAPED.search(t)]
        assert not missed, f"pattern failed to fire on {missed!r}"

    def test_it_does_NOT_fire_on_the_parameterised_forms_this_repo_uses(self):
        correct = [
            r"%LOCALAPPDATA%\Programs\Python\Python314\python.exe",
            r"$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
            "$env:LOCALAPPDATA/Programs/Python/Python314/python.exe",
            r"%USERPROFILE%\Desktop",
            r"C:\Users\<user>\Desktop",
            "~/bin/python",
        ]
        wrong = [t for t in correct if HOME_SHAPED.search(t)]
        assert not wrong, f"pattern wrongly fired on the correct form(s) {wrong!r}"

    def test_it_does_not_fire_on_the_bare_users_directory(self):
        """A sentence that merely names where Windows keeps home directories is
        not a committed path, and reporting it would train readers to ignore
        this guard."""
        assert not HOME_SHAPED.search("Windows keeps home directories under C:/Users")

    def test_it_fires_case_insensitively(self):
        """Windows paths are case-insensitive, so the differently-cased
        spellings all name ONE place. A guard that only catches the title-case
        spelling lets the others through a fresh clone untouched."""
        variants = ["c:/users/someone/x", "C:/USERS/SOMEONE/X"]
        missed = [t for t in variants if not HOME_SHAPED.search(t)]
        assert not missed, f"pattern is case-blind, missed: {missed!r}"

    def test_it_still_exempts_placeholders_under_ignorecase(self):
        """A placeholder is exempt by SHAPE - the character right after the
        separator - not by the case of the account label, so an uppercase
        placeholder must stay exempt too."""
        assert not HOME_SHAPED.search(r"C:\USERS\<user>\Desktop")

    def test_it_fires_on_an_8_3_short_name(self):
        """A long or spaced account name collapses to a tilde-and-digit short
        form. The account charset already allows both, and the short form does
        not start with an excluded placeholder character."""
        assert HOME_SHAPED.search(r"C:\Users\ADMINI~1\AppData\Local\Temp")

    def test_it_fires_on_a_mixed_slash_spelling(self):
        """Each separator slot is its own character class, so the two were
        never required to match each other."""
        mixed = [r"C:/Users\someone/AppData", r"C:\Users/someone\AppData"]
        missed = [t for t in mixed if not HOME_SHAPED.search(t)]
        assert not missed, f"pattern failed to fire on {missed!r}"

    def test_it_does_NOT_fire_on_this_repo_s_own_dashboard_routes(self):
        """The MEASURED narrowing, pinned so nobody re-widens it by reflex.

        Porting the upstream pattern verbatim brought two POSIX home prefixes
        with it and produced 33 findings that are URL routes served by this
        repo's own dashboard, not paths. Re-adding those branches without
        re-measuring turns this guard into a tolerated list.
        """
        routes = ["/home/summary", "/home/session/x", "/home/panel_visibility"]
        wrong = [r for r in routes if HOME_SHAPED.search(r)]
        assert not wrong, (
            "the POSIX home branch was re-added; it collides with this repo's "
            f"own dashboard routes: {wrong!r}"
        )

    def test_it_fires_across_a_hard_wrapped_line_break(self, tmp_path, monkeypatch):
        """A line-oriented match is a claim about the file's line breaks. Prose
        here hard-wraps near 80 columns with no space at the join, so a long
        path can be split by a bare newline."""
        planted = tmp_path / "wrapped.md"
        planted.write_text(
            "The interpreter used to live under C:/Users/\n"
            "someone/AppData/Local/Programs/Python/python.exe on this box.\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            __import__(__name__, fromlist=["REPO_ROOT"]), "REPO_ROOT", tmp_path
        )
        hits = findings_in("wrapped.md")
        assert hits, "a path split by a hard line-wrap was not found"
        line_no, matched = hits[0]
        assert line_no == 1, f"expected the match attributed to line 1, got {line_no}"
        assert "someone" in matched, f"unexpected matched text: {matched!r}"


class TestNoRunnableSurfaceCarriesAHomePath:
    def test_every_tracked_runnable_file_outside_the_pinned_sets_is_clean(self):
        offenders = []
        for rel in tracked_runnable_files():
            if rel in FROZEN_HISTORICAL or rel in CONTROL_FIXTURES:
                continue
            for number, text in findings_in(rel):
                offenders.append(f"{rel}:{number} -> {text}")
        assert not offenders, (
            "tracked runnable file(s) hardcode a Windows account home directory. "
            "A fresh clone runs under a different account, and a hook or task "
            "command naming an absent interpreter reports NOTHING rather than "
            "failing loudly. Use %LOCALAPPDATA% / $env:LOCALAPPDATA / os.environ "
            "and keep the pin absolute:\n  " + "\n  ".join(offenders)
        )


class TestTheRecordsAreFrozenRatherThanTolerated:
    def test_each_frozen_record_carries_exactly_its_pinned_count(self):
        wrong = []
        for rel, expected in FROZEN_HISTORICAL.items():
            actual = len(findings_in(rel))
            if actual != expected:
                wrong.append(f"{rel}: pinned {expected}, found {actual}")
        assert not wrong, (
            "a frozen record changed its home-path count. These files record "
            "what was true on a date and are not edited - a RISE means new "
            "machine-specific content was added and should be parameterised; a "
            "FALL means a record was rewritten:\n  " + "\n  ".join(wrong)
        )

    def test_each_control_fixture_carries_exactly_its_pinned_count(self):
        wrong = []
        for rel, expected in CONTROL_FIXTURES.items():
            actual = len(findings_in(rel))
            if actual != expected:
                wrong.append(f"{rel}: pinned {expected}, found {actual}")
        assert not wrong, (
            "a control-fixture file changed its home-path count. These files may "
            "plant a needle to prove a guard is armed; they may not accumulate. A "
            "RISE means a real path may be hiding among the fixtures:\n  "
            + "\n  ".join(wrong)
        )

    def test_the_pinned_sets_name_only_files_that_exist(self):
        named = list(FROZEN_HISTORICAL) + list(CONTROL_FIXTURES)
        missing = [rel for rel in named if not (REPO_ROOT / rel).is_file()]
        assert not missing, f"pinned set names files that do not exist: {missing}"

    def test_the_two_pinned_sets_do_not_overlap(self):
        overlap = set(FROZEN_HISTORICAL) & set(CONTROL_FIXTURES)
        assert not overlap, f"a file is pinned twice, so one pin is dead: {sorted(overlap)}"

    def test_every_pinned_file_is_actually_in_scope(self):
        """A pin on an out-of-scope file is a dead pin that reads as coverage."""
        in_scope = set(tracked_runnable_files())
        stray = [
            rel for rel in list(FROZEN_HISTORICAL) + list(CONTROL_FIXTURES)
            if rel not in in_scope
        ]
        assert not stray, (
            "pinned file(s) are not tracked runnable surfaces, so their pins can "
            f"never fire: {stray}"
        )


class TestTheParameterisedFormsActuallyResolve:
    """A clean path that does not resolve is worse than a hardcoded one."""

    def test_localappdata_is_set(self):
        if os.name != "nt":
            return
        assert os.environ.get("LOCALAPPDATA"), (
            "LOCALAPPDATA is unset, so every %LOCALAPPDATA% hook command, .cmd "
            "wrapper and scheduled-task action would expand to a bare relative "
            "path and silently fail"
        )

    def test_the_parameterised_interpreter_resolves_to_a_real_file(self):
        """The pin has to stay ABSOLUTE (tests/test_bare_py_ban.py: a bare
        launcher resolves to a dep-less runtime and zeroes the suite), so what
        must hold is that expanding the variable yields an interpreter that
        exists - or that the wrappers' documented PATH fallback does."""
        if os.name != "nt":
            return
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            return
        resolved = Path(local) / "Programs" / "Python" / "Python314" / "python.exe"
        if resolved.is_file():
            return
        import shutil

        assert shutil.which("python"), (
            f"{resolved} does not exist and 'python' does not resolve on PATH, so "
            "every parameterised wrapper in this repo would silently not run"
        )


def test_this_guard_reads_the_files_it_claims_to():
    """An empty finding from an empty listing is the same output as a clean
    tree, which is the defect this whole file is written against."""
    files = tracked_runnable_files()
    assert len(files) > 100, f"tracked runnable listing looks wrong: {len(files)} files"
    assert "tools/precommit_gate.py" in files
    assert any(f.endswith(".ps1") for f in files), "no PowerShell surface enumerated"
    assert any(f.endswith(".cmd") for f in files), "no cmd wrapper enumerated"
