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
  * every gated pytest call runs `-n 8 --dist loadfile`;
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
_PYTEST = re.compile(r"-m pytest\b")
_GATED = re.compile(r'fleet_suite_gate\.py"? run --owner <id> -- (?P<cmd>[^`]*)')


def _text(name: str) -> str:
    return (TOOLS / name).read_bytes().decode("utf-8")


def _args_after(line: str, end: int) -> str:
    """The rest of the command: up to the closing backtick, else end of line."""
    rest = line[end:]
    tick = rest.find("`")
    return rest if tick == -1 else rest[:tick]


def _names_a_test_file(args: str) -> bool:
    return any(tok.endswith(".py") or "::" in tok for tok in args.split())


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
            if f"{GATE} run" not in line[:m.start()] and f'{GATE}" run' not in line[:m.start()]:
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
                if "-n 8" not in cmd or "--dist loadfile" not in cmd:
                    bad.append(f"tools/{name}:{n}: {cmd.strip()[:140]}")
    assert seen >= 8, f"only {seen} gated pytest calls found - the sweep went blind"
    assert not bad, "gated suite without -n 8 --dist loadfile:\n" + "\n".join(bad)


def test_the_detector_catches_a_serial_whole_suite():
    # Positive control on the predicate itself, so an always-green sweep fails.
    line = 'run `"py.exe" -m pytest tests/ -q -n 8` from the root'
    m = _PYTEST.search(line)
    args = _args_after(line, m.end())
    assert not _names_a_test_file(args) and not _is_collect_only(args)
    assert _names_a_test_file(" tests/test_x.py -q")
    assert _is_collect_only(" tests --collect-only -q")


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
