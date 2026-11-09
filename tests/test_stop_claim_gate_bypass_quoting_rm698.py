"""RM-698: hook-bypass counting in tools/stop_claim_gate.py, quoting blind spots.

Before the fix every bypass check ran EV_BYPASS plus `\\bgit\\b` over the
noise-stripped command, and `strip_command_noise` blanks every quoted span:
(a) MISS - a bypass inside a quoted shell script (`bash -c "..."`,
    `sh -c '...'`, `pwsh -Command "..."`) stripped to the bare launcher and
    was never counted;
(b) FALSE HIT - `--no-verify` text that was not an option of a git statement
    (an escaped-quote script argument, another statement's argument) was
    counted because SOME statement of the command named git.

(a) is fixed: each launcher script is judged as a nested command, so the gate
only ever counts MORE. (b) is NOT narrowed, by decision (2026-11-08): six
verifier rounds each found a real, executed hook bypass that a narrowing
stopped counting (variables, quoting, braces, arrays, `set --`, functions,
grouped pipes, `printf -v`, `-OutVariable`, `$_`, `@(...)`). Alternatives
measured and refuted: a per-statement "flag after the git word" rule with
variable tracking (rounds 1-5), and sparing only INERT output / search
statements (round 6). A false hit costs one advisory line; a false miss hides
a hook bypass. The filed false hits are pinned below as STILL counted, so a
later narrowing is a deliberate, visible change. Reverses if: the gate gains a real shell parser with measured
coverage, or false hook_bypass findings on ordinary commands matter in a real
session.

The three call sites, each pinned here with the filed probe strings:
  1. the Stop-time scan in `audit` (main-session check 5, `hook_bypass`);
  2. `_note_bypass` (sub-agent evidence, `subagent_hook_bypass`);
  3. `_bypass_targets` (where each bypassing git statement acts).
"""
from __future__ import annotations

import shlex

import pytest

from tools import stop_claim_gate as gate

MISSES = [
    'bash -c "cd RC && git push --no-verify"',
    "bash -c 'git push --no-verify'",
    'pwsh -Command "git push --no-verify"',
]
# The filed (b) strings: decided to stay counted (see the module docstring).
FALSE_HITS = [
    'python -c "x = \\"--no-verify\\""; git status',
    "rg --pattern=--no-verify . ; git status",
]

# Siblings of the same root, beyond the five filed strings.
MORE_MISSES = [
    "sh -c 'git commit --no-verify -m x'",
    'powershell -Command "git push --no-verify"',
    'powershell.exe -NoProfile -Command "git push --no-verify"',
    '"tools/PowerShell 7/pwsh.exe" -c "git push --no-verify"',
    "bash -lc 'git push --no-verify'",
    "/usr/bin/bash -c 'git -c core.hooksPath=/dev/null commit -m x'",
    'pwsh -Command "bash -c \'git push --no-verify\'"',
    "bash -c 'cd x; git push --no-verify' && echo done",
    '& pwsh -Command "git push --no-verify"',
    "bash -o pipefail -c 'git push --no-verify'",
    "bash +O extglob -ec 'git push --no-verify'",
    "bash +x -c 'git push --no-verify'",
    # Round-6 flag routes, inside a launcher script.
    "sh -c '{ echo --no-verify; } | xargs git push'",
    "bash -c 'printf -v F -- --no-verify; git push $F'",
    'pwsh -Command "Write-Output --no-verify -OutVariable v; git push $v"',
    'pwsh -Command "git push @(echo x; echo --no-verify)"',
    # A PowerShell path ending in a backslash, then a launcher (raw reading).
    "Set-Location ..\\repo\\\nbash -c 'git push --no-verify'",
]
# Same class as the filed (b) strings, also decided to stay counted.
MORE_FALSE_HITS = [
    "echo --no-verify && git status",
    "git status; echo --no-verify",
    "git log -1; Write-Output --no-verify",
    "grep -rn -- --no-verify docs/ ; git log -1",
    "echo --no-gpg-sign; git log",
    "git log | Select-String --no-verify",
    "(echo --no-verify); git status",
    "python -c 'import os' --no-verify; git push",
]
# Must be counted before and after: plain git bypass shapes.
STILL_COUNTED = [
    "git commit --no-verify -m wip",
    "git -c core.hooksPath= commit -m x",
    "cd tools; git push --no-verify origin main",
    "G=git; $G push --no-verify",
    "echo $(git commit --no-verify -m x)",
    '"tools/Git Portable/cmd/git.exe" push --no-verify',
    # Line continuations keep ONE statement (verifier probe, RM-698 round 1).
    "git commit \\\n  --no-verify -m x",
    "git commit -m x \\\r\n --no-gpg-sign",
    "git \\\n -c core.hooksPath=/dev/null commit",
    "git commit `\n  --no-verify",
    "git push `\r\n --no-verify",
    "bash -c 'git commit \\\n --no-verify'",
    # A PowerShell path ending in a backslash is not a continuation (round 2).
    "Set-Location ..\\repo\\\ngit push --no-verify",
    "Set-Location ..\\repo\\\r\ngit push --no-verify",
    "cd ..\\repo\\\ngit commit --no-verify -m x",
    # An UNQUOTED variable value is still the flag (the old rule counted it).
    "F=--no-verify; git commit $F -m x",
    # A PowerShell assignment RUNS the git command it assigns from (round 3).
    "$out = git push --no-verify 2>&1",
    "$out=git push --no-verify",
    "$null = git push --no-verify",
    "$r = (git commit --no-verify -m x)",
    "$out = git commit --no-verify -m x 2>&1 | Out-String",
    # git reached through a variable that names it (round 3).
    '$git = "git"; & $git push --no-verify',
    "G='tools/Git Portable/cmd/git.exe'; \"$G\" push --no-verify",
    # A flag held in an unquoted assignment, passed quoted or braced (round 4).
    'F=--no-verify; git push "$F"',
    'F=--no-verify; git push "$F" origin',
    'F=--no-verify\ngit push "$F"',
    'F=--no-verify; git push "${F}"',
    "F=--no-verify; git push ${F}",
    "F=--no-verify; git push origin ${F}",
    'F=--no-verify; git commit -m x "$F"',
    "{ git push --no-verify; }",
    "(cd x && git commit --no-verify -m x)",
    # Every way a flag reaches git from another statement keeps the old count
    # (round 5: tracking the flag leaked; only INERT statements are spared).
    'F=--no-verify; git push "${F:-x}"',
    'F=--no-verify; G="$F"; git push $G',
    'ARGS=(--no-verify); git push "${ARGS[@]}"',
    'set -- --no-verify; git push "$@"',
    "if true; then F=--no-verify; fi; git push $F",
    "for f in --no-verify; do git push $f; done",
    "declare F=--no-verify; git push $F",
    'f() { git push "$@"; }; f --no-verify',
    "echo --no-verify | xargs git push",
    "echo --no-verify | git status",
    "echo --no-verify > args.txt; git push $(cat args.txt)",
    "echo core.hooksPath=/dev/null >> .git/config; git push",
    "git push `echo --no-verify`",
    # An inert head is spared only on every condition (mutation round).
    "echo --no-verify; F=--no-verify; git push $F",
    # Real bypasses whose flag sits in an echo-like statement (rounds 5-6:
    # each was lost by a narrowing that was measured and refuted).
    "git push $(echo x; echo --no-verify)",
    "echo --no-verify > args.lst; xargs -a args.lst git push",
    "python ops/fleet_kit/fleet_gitlock.py run --owner x -- git commit --no-verify -m x",
    "python tools/wrap.py git push --no-verify",
    "{ echo --no-verify; } | xargs git push",
    "(echo --no-verify; true) | xargs git push",
    "echo --no-verify \\\n| xargs git push",
    "printf -v F -- --no-verify; git push $F",
    "echo --no-verify; git push $_",
    "Write-Output --no-verify -OutVariable v; git push $v",
    "echo --no-verify -ov v; git push $v",
    "git push @(echo x; echo --no-verify)",
    "git push (& { echo --no-verify })",
    # Glued by quotes: only the STRIPPED text matches (round 7).
    'git -c core.hooksPath""=/dev/null commit -m x',
    "git -c core.hooksPath''=/dev/null commit -m x",
]
# Must stay uncounted before and after: the bypass is data, not an option.
STILL_NOT_COUNTED = [
    'git commit -m "mention --no-verify in the message"',
    "git status",
    "cat <<'EOF'\ngit push --no-verify\nEOF",
    "bash -c 'echo --no-verify'; git status",
    "bash -c 'git status'",
    "bash script.sh -c 'git push --no-verify'",
    "bash -- -c 'git push --no-verify'",
    # Quoted data reached through a variable is data (round 2).
    "$msg = @'\nfix(tools): RM-698 count --no-verify\n'@\ngit commit -m $msg",
    "$msg = 'docs: mention --no-verify'; git commit -m $msg",
    "MSG='docs: mention --no-verify'; git commit -m \"$MSG\"",
    "$s = 'git push --no-verify'; Write-Output $s",
    "$pat = '--no-verify'; git log --grep $pat",
    "$m = 'git commit --no-verify'; echo --no-verify $m",
    "$m = 'git commit --no-verify'; Write-Output $m",
    # What follows -File is the script's own arguments (round 3).
    'pwsh -File run.ps1 -Command "git push --no-verify"',
    'powershell -f run.ps1 -c "git push --no-verify"',
    # Literal text inside double quotes is still data (round 4).
    'F=x; git commit -m "$F --no-verify"',
    'git commit -m "${HOME} --no-verify"',
]


def _audit_checks(command):
    ev = {"texts": [], "bash": [command], "edited": [], "runs": [],
          "agent_results": []}
    return {f["check"] for f in gate.audit(ev)}


def _noted(command, name="bash"):
    found = {"bypass": []}
    gate._note_bypass(found, ("toolu_x", name, {"command": command}), None)
    return [c for c, _cwd, _tid in found["bypass"]]


# ---------------------------------------------------------------- site 1


@pytest.mark.parametrize("command", MISSES + MORE_MISSES + STILL_COUNTED)
def test_audit_counts_a_bypass_including_one_inside_a_quoted_script(command):
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", STILL_NOT_COUNTED)
def test_audit_does_not_count_bypass_text_that_is_quoted_data(command):
    assert "hook_bypass" not in _audit_checks(command)


@pytest.mark.parametrize("command", FALSE_HITS + MORE_FALSE_HITS)
def test_audit_keeps_counting_a_flag_in_another_statement_by_decision(command):
    """(b) not narrowed: see the module docstring for the decision."""
    assert "hook_bypass" in _audit_checks(command)


def test_audit_keeps_the_stripped_command_as_the_finding_quote():
    """The finding text is unchanged: the noise-stripped command, as before,
    so the per-session seen set does not re-report old findings."""
    command = "git commit --no-verify -m wip"
    finding = next(f for f in gate.audit({"texts": [], "bash": [command],
                                          "edited": [], "runs": [],
                                          "agent_results": []})
                   if f["check"] == "hook_bypass")
    assert finding["quote"] == gate.strip_command_noise(command)


# ---------------------------------------------------------------- site 2


@pytest.mark.parametrize("command", MISSES + MORE_MISSES + STILL_COUNTED)
def test_note_bypass_records_a_bypass_including_one_inside_a_quoted_script(command):
    assert _noted(command) == [command]
    assert _noted(command, name="powershell") == [command]


@pytest.mark.parametrize("command", STILL_NOT_COUNTED)
def test_note_bypass_ignores_bypass_text_that_is_quoted_data(command):
    assert _noted(command) == []


@pytest.mark.parametrize("command", FALSE_HITS + MORE_FALSE_HITS)
def test_note_bypass_keeps_a_flag_in_another_statement_by_decision(command):
    assert _noted(command) == [command]


def test_note_bypass_ignores_other_tools():
    assert _noted("git commit --no-verify -m x", name="read") == []


# ---------------------------------------------------------------- site 3


def test_a_quoted_script_bypass_is_placed_by_the_cd_inside_it(tmp_path):
    inner = tmp_path / "inner"
    command = f"bash -c 'cd \"{inner.as_posix()}\" && git push --no-verify'"
    assert gate._bypass_targets(command, str(tmp_path / "outer")) == [inner.as_posix()]


def test_a_quoted_script_bypass_with_a_relative_cd_joins_the_outer_cwd(tmp_path):
    command = MISSES[0]
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [
        tmp_path.as_posix() + "/RC"]


def test_a_cd_inside_a_quoted_script_does_not_move_the_outer_statement(tmp_path):
    command = ("bash -c 'cd elsewhere && git status' && "
               "git commit --no-verify -m x")
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [tmp_path.as_posix()]


def test_a_variable_set_inside_a_quoted_script_does_not_leak_out(tmp_path):
    inner = tmp_path / "inner"
    command = (f"bash -c 'D={inner.as_posix()}' && cd \"$D\" && "
               "git commit --no-verify -m x")
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [None]


def test_a_continued_git_statement_is_placed_by_the_cd_before_it(tmp_path):
    inner = tmp_path / "inner"
    command = f'cd "{inner.as_posix()}" && git commit \\\n  --no-verify -m x'
    # The joined reading places it; None stays because the pre-RM-698 walk
    # placed nothing here and failed closed (the targets only ever grow).
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [inner.as_posix(), None]


def test_a_powershell_path_ending_in_a_backslash_still_places_the_git_line(tmp_path):
    inner = tmp_path.as_posix() + "/inner\\"
    command = "Set-Location " + inner + "\ngit push --no-verify"
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [inner]


def test_a_quoted_variable_still_places_a_cd_into_it(tmp_path):
    inner = tmp_path / "inner"
    command = f"D='{inner.as_posix()}'; cd \"$D\" && git commit --no-verify -m x"
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [inner.as_posix()]


def test_an_assigning_git_statement_is_placed_by_its_own_dash_c(tmp_path):
    inner = tmp_path / "inner"
    command = f'$out = git -C "{inner.as_posix()}" push --no-verify'
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [inner.as_posix(), None]


def test_a_flagged_command_with_no_placeable_statement_fails_closed(tmp_path):
    assert gate._bypass_targets("F=--no-verify; git push $F", tmp_path.as_posix()) == [None]


def test_a_pwsh_command_bypass_is_placed_at_the_outer_cwd(tmp_path):
    assert gate._bypass_targets(MISSES[2], tmp_path.as_posix()) == [tmp_path.as_posix()]


@pytest.mark.parametrize("command", STILL_NOT_COUNTED)
def test_a_command_with_no_bypass_has_no_target(command, tmp_path):
    """Nothing to place: no fail-closed [None] for a command with no bypass,
    so the target walk agrees with _note_bypass by construction."""
    assert gate._bypass_targets(command, tmp_path.as_posix()) == []
    assert gate._bypass_hits_rc(command, tmp_path.as_posix(), "rc-common") is False


@pytest.mark.parametrize("command", FALSE_HITS)
def test_a_kept_false_hit_fails_closed_to_an_unplaced_target(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [None]


def test_an_over_long_command_still_fails_closed(tmp_path):
    command = "git commit --no-verify -m x; " + "echo x; " * gate.COMMAND_PARSE_MAX
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [None]
    assert _noted(command) == [command]
    assert "hook_bypass" in _audit_checks(command)


def test_an_over_long_command_without_git_is_not_counted():
    command = "echo --no-verify; " + "echo x; " * gate.COMMAND_PARSE_MAX
    assert _noted(command) == []


def test_nested_launchers_stop_at_the_depth_cap_but_still_count():
    """A script nested past the cap fails closed: a bypass flag and a git
    word anywhere in the RAW script count (stripping would blank it)."""
    command = "git commit --no-verify -m x"
    for _ in range(gate.BYPASS_NEST_MAX + 2):
        command = "bash -c " + shlex.quote(command)
    assert _noted(command) == [command]


def test_nested_launchers_past_the_cap_still_need_a_git_word():
    command = "echo --no-verify"
    for _ in range(gate.BYPASS_NEST_MAX + 2):
        command = "bash -c " + shlex.quote(command)
    assert _noted(command) == []


def test_a_quote_glued_over_long_bypass_still_counts():
    """The old rule decides first, even past COMMAND_PARSE_MAX (round 7)."""
    command = ('git -c core.hooksPath""=/dev/null commit -m x; '
               + "echo x; " * gate.COMMAND_PARSE_MAX)
    assert _noted(command) == [command]
    assert "hook_bypass" in _audit_checks(command)


def test_a_new_placement_outside_rc_does_not_hide_an_unplaced_bypass(tmp_path):
    """Round 8: HEAD counted both (its walk placed nothing, so [None]); a
    placement the new walk adds outside RC must not take that away."""
    out = (tmp_path / "out").as_posix()
    root = gate.ROOT.as_posix()
    rc = gate._git_common_dir(gate.ROOT)
    assert rc is not None
    first = f'A=git B=--no-verify; cd "{root}"; $A push $B'
    assert None in gate._bypass_targets(first, out)
    assert gate._bypass_hits_rc(first, out, rc)
    second = (f"F=--no-verify; bash -c 'cd {out}; git push --no-verify'; "
              "git push $F")
    assert gate._bypass_targets(second, root) == [out, None]
    assert gate._bypass_hits_rc(second, root, rc)


def test_a_launcher_only_bypass_outside_rc_is_placed_outside(tmp_path):
    """No old-rule count to keep, so the launcher walk alone places it."""
    out = (tmp_path / "out").as_posix()
    command = f"bash -c 'cd {out} && git push --no-verify'"
    assert gate._bypass_targets(command, gate.ROOT.as_posix()) == [out]


def test_a_launcher_bypass_no_statement_can_place_fails_closed(tmp_path):
    command = "bash -c 'F=--no-verify; git push $F'"
    assert _noted(command) == [command]
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [None]
