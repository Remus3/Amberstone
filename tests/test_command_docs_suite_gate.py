"""Whole suites in the slash-command docs run ONLY through the kit's suite gate,
in parallel, and the docs carry ONE tier table (MAIN kit-v13 ORDER section 2,
PERF-AUDIT items 3 and 4, 2026-10-09).

Measured by MAIN 2026-10-08: the local dual suite is 27m22s serial against
2m24s at `-n 8 --dist loadfile`, so a serial whole suite held the machine-wide
suite slot (FLEET-COMMON 16c) for ~45 minutes instead of ~3-4. tools/done.md
still called xdist "NOT yet adopted" although its six blocking failures were
fixed on 2026-07-27 (the ci.yml `check` job comment records it), and several
lane docs ran serial or ungated whole suites. Pinned here:

  * every LOCAL whole-suite command in a command doc - written `-m pytest`
    naming no test file and not a `--collect-only` count - sits inside a
    `fleet_suite_gate.py run` call on the same line;
  * every gated pytest call runs `-n 8 --dist loadfile`, and caps xdist
    worker restarts with `--max-worker-restart=0` (RM-754: after a
    `--timeout` kill, `--dist loadfile` hands the crashed test to every
    replacement worker, 1 + 4 x n times by default, so one hung test can hold
    a worker for hours while the rest sit idle; the CI half and the
    "not in pytest.ini" half live in tests/test_xdist_worker_restart_cap_rm754.py);
  * the stale "NOT yet adopted" xdist block is gone from tools/done.md;
  * exactly one TIER TABLE exists across tools/*.md, in tools/done.md, and it
    says what each tier runs, that Tier-2 runs once by the merger at -n 8 and
    that the verifier re-runs only cited tests plus collect-only counts.

Scope note: a bare `pytest ...` span (no `-m`) in these docs is a citation of
CI's own command (`.github/workflows/ci.yml`), not a local run, and is not
matched. Local commands in every command doc use the `python -m pytest` form.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

# The 23 slash-command docs (same anchored set as tests/test_skill_dispatch_v10.py).
COMMANDS = (
    "RC2-Continue.md", "directed-headless-upgrade.md", "done.md",
    "game-monitor.md", "headless-ds.md", "headless-gated.md",
    "headless-queue.md", "headless-repo.md", "headless-research.md",
    "headless-true-audit.md", "headless-uiux.md", "headless-upgrade.md",
    "live-gated-drain.md", "orchestrated-run.md", "overlay-build-continue.md",
    "repo-insights.md", "root-cause-fix.md", "section-j-dispatch.md",
    "ship-batch.md", "sync-all-md.md", "test-driven-development.md",
    "test-first-autopilot.md", "weekly-hygiene.md",
)

TIER_TABLE_HEAD = "**TIER TABLE"
GATE = "fleet_suite_gate.py"
RESTART_CAP = "--max-worker-restart=0"
_PYTEST = re.compile(r"-m pytest\b")
_GATED = re.compile(r'fleet_suite_gate\.py"? run --owner <id> -- (?P<cmd>[^`]*)')
# Shell chain operators: a gate covers its own command only (RM-1103). A
# single `&` between two commands chains too (cmd.exe, RM-1104 (a)). One that
# opens a span or follows another operator (PowerShell's call operator, `; &`)
# has no whitespace of its own before it, and one inside a token (`2>&1`) none
# around it, so neither splits.
_CHAIN = re.compile(r"\s*(?:&&|\|\||;|\|)\s*|\s+&\s+")
# Options whose value names a file the run SKIPS (RM-1103); the
# `--opt=value` form is one token, `--opt value` two.
_SKIP_OPTS = ("--ignore", "--ignore-glob", "--deselect")
_TIER_FLAGS = (re.compile(r"(?:^|\s)-n(?:\s*|=)8(?=\s|$)"),
               re.compile(r"(?:^|\s)--dist(?:\s+|=)loadfile(?=\s|$)"))


def _text(name: str) -> str:
    return (TOOLS / name).read_bytes().decode("utf-8")


def _args_after(line: str, end: int) -> str:
    """The rest of the command: up to the closing backtick, else end of line."""
    rest = line[end:]
    tick = rest.find("`")
    return rest if tick == -1 else rest[:tick]


def _cited_tokens(args: str):
    """The tokens minus every --ignore / --deselect option and its value: those
    name a file the run SKIPS, not one it cites (RM-1103)."""
    skip_next = False
    for tok in args.split():
        if skip_next:
            skip_next = False
        elif tok in _SKIP_OPTS:
            skip_next = True
        elif not tok.startswith(tuple(f"{opt}=" for opt in _SKIP_OPTS)):
            yield tok


def _names_a_test_file(args: str) -> bool:
    return any(tok.endswith(".py") or "::" in tok for tok in _cited_tokens(args))


def _has_tier_table_flags(cmd: str) -> bool:
    """`-n 8 --dist loadfile --max-worker-restart=0` as whole tokens, so `-n 80`
    or `--dist loadfilex` is not read as the TIER TABLE flags (RM-1103).
    Every spelling pytest parses the same way (`-n8`, `-n=8`, `--dist=loadfile`)
    is accepted: the guard pins what the run does, not its spelling (RM-1104
    (d)). The restart cap stays the one literal token the RM-754 guards name."""
    return (all(rx.search(cmd) for rx in _TIER_FLAGS)
            and RESTART_CAP in cmd.split())


def _gate_covers(prefix: str) -> bool:
    """The gate prefixes THIS command: it sits in the last chain segment before
    the pytest word, so `gate ... ; python -m pytest ...` is not gated."""
    seg = _CHAIN.split(prefix)[-1]
    return f"{GATE} run" in seg or f'{GATE}" run' in seg


def _is_collect_only(args: str) -> bool:
    toks = args.split()
    return "--collect-only" in toks or "--co" in toks


def _ungated_whole_suites(name: str) -> list[str]:
    bad = []
    for n, line in enumerate(_text(name).split("\n"), start=1):
        for m in _PYTEST.finditer(line):
            args = _args_after(line, m.end())
            if _names_a_test_file(args) or _is_collect_only(args):
                continue
            if not _gate_covers(line[:m.start()]):
                bad.append(f"tools/{name}:{n}: {line.strip()[:140]}")
    return bad


def test_the_command_set_is_anchored():
    missing = [f for f in COMMANDS if not (TOOLS / f).is_file()]
    assert not missing, missing


def test_no_command_doc_runs_a_whole_suite_outside_the_gate():
    bad = [hit for name in COMMANDS for hit in _ungated_whole_suites(name)]
    assert not bad, (
        "whole-suite pytest commands outside the kit suite gate "
        "(FLEET-COMMON 16c) - wrap each in `python ops/fleet_kit/fleet_suite_gate.py "
        "run --owner <id> -- ...`:\n" + "\n".join(bad))


def test_every_gated_pytest_call_runs_in_parallel():
    seen, bad = 0, []
    for name in COMMANDS:
        for n, line in enumerate(_text(name).split("\n"), start=1):
            for m in _GATED.finditer(line):
                cmd = m.group("cmd")
                if "pytest" not in cmd:
                    continue  # the RACE GUARDS block's `<suite cmd>` placeholder
                seen += 1
                if not _has_tier_table_flags(cmd):
                    bad.append(f"tools/{name}:{n}: {cmd.strip()[:140]}")
    assert seen >= 8, f"only {seen} gated pytest calls found - the sweep went blind"
    assert not bad, (f"gated suite without -n 8 --dist loadfile {RESTART_CAP}:\n"
                     + "\n".join(bad))


def test_the_detector_catches_a_serial_whole_suite():
    # Positive control on the predicate itself, so an always-green sweep fails.
    line = 'run `"py.exe" -m pytest tests/ -q -n 8` from the root'
    m = _PYTEST.search(line)
    args = _args_after(line, m.end())
    assert not _names_a_test_file(args) and not _is_collect_only(args)
    assert _names_a_test_file(" tests/test_x.py -q")
    assert _is_collect_only(" tests --collect-only -q")


def test_the_detector_closes_the_s144q34_holes(tmp_path, monkeypatch):
    # RM-1103 siblings: an --ignore / --deselect value is not a cited test
    # file, a gate covers only its own chained command, and the TIER TABLE
    # flags match as whole tokens.
    assert not _names_a_test_file(" tests -q -n 8 --ignore=tests/test_x.py")
    assert not _names_a_test_file(" tests -n 8 --deselect tests/test_x.py::t")
    assert _names_a_test_file(" tests/test_a.py -n 8 --ignore=tests/test_b.py")
    assert _has_tier_table_flags("-n 8 --dist loadfile --max-worker-restart=0")
    assert not _has_tier_table_flags("-n 80 --dist loadfile --max-worker-restart=0")
    assert not _has_tier_table_flags("-n 8 --dist loadfilex --max-worker-restart=0")
    gated = ("`python ops/fleet_kit/fleet_suite_gate.py run --owner <id> -- "
             "python -m pytest tests -q -n 8 --dist loadfile "
             "--max-worker-restart=0")
    (tmp_path / "x.md").write_bytes(
        (gated + "; python -m pytest tests -q -n 8`\n" + gated + "`\n").encode())
    monkeypatch.setattr(sys.modules[__name__], "TOOLS", tmp_path)
    assert [hit.split(":")[1] for hit in _ungated_whole_suites("x.md")] == ["1"]


def test_done_md_drops_the_stale_xdist_block():
    done = _text("done.md")
    assert "NOT yet adopted" not in done
    assert "is not trustworthy as a gate" not in done


def test_exactly_one_tier_table_and_it_lives_in_done_md():
    holders = [p.name for p in sorted(TOOLS.glob("*.md"))
               if TIER_TABLE_HEAD in p.read_bytes().decode("utf-8", "replace")]
    assert holders == ["done.md"], holders


def test_the_tier_table_says_who_runs_what():
    done = _text("done.md")
    start = done.index(TIER_TABLE_HEAD)
    table = done[start:done.index("\n\n", start)]
    for needle in ("Tier-0", "Tier-1", "Tier-2", "Verifier",
                   "ONCE", "merger", "--collect-only", "-n 8 --dist loadfile",
                   f"{GATE} run --owner <id> --"):
        assert needle in table, needle
    # The table comes before section 0, so the executor reads it first.
    assert start < done.index("### 0. Local check gate")


def test_command_docs_point_at_the_one_table():
    # Each doc that had its own whole-suite command now points at the table
    # rather than restating a suite policy of its own.
    for name in ("headless-queue.md", "headless-true-audit.md", "headless-repo.md",
                 "headless-uiux.md", "headless-upgrade.md", "headless-ds.md",
                 "directed-headless-upgrade.md", "ship-batch.md",
                 "test-first-autopilot.md", "test-driven-development.md"):
        assert "TIER TABLE" in _text(name), name


def test_a_single_ampersand_ends_the_gated_command(tmp_path, monkeypatch):
    # RM-1104 (a): cmd.exe's `a & b` chains, so the gate before `&` does not
    # cover the pytest after it; PowerShell's leading `&` call operator does
    # not split, so `& "py.exe" ...gate... -- "py.exe" -m pytest` stays gated.
    gated = ("`python ops/fleet_kit/fleet_suite_gate.py run --owner <id> -- "
             "python -m pytest tests -q -n 8 --dist loadfile "
             "--max-worker-restart=0")
    call = ('`& "py.exe" ops/fleet_kit/fleet_suite_gate.py run --owner <id> -- '
            '"py.exe" -m pytest tests -q -n 8 --dist loadfile --max-worker-restart=0`')
    (tmp_path / "x.md").write_bytes(
        (gated + " & python -m pytest tests -q -n 8`\n" + call + "\n").encode())
    monkeypatch.setattr(sys.modules[__name__], "TOOLS", tmp_path)
    assert [hit.split(":")[1] for hit in _ungated_whole_suites("x.md")] == ["1"]
