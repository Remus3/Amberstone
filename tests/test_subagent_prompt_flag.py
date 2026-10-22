"""RM-137 - subagent prompt inheritance via --append-subagent-system-prompt.

The flag is UNDOCUMENTED: absent from `claude --help` on the pinned CLI version,
accepted by the binary, and PROVEN to propagate into a spawned subagent by canary
with a negative control (LEDGER 1147). Two failure modes this file exists to
catch, both SILENT:

  1. the CLI changes and the flag stops delivering anything - the launcher keeps
     working and the rules just stop arriving (exactly how the headless-hook rule
     stayed false in CLAUDE.md for months);
  2. the wire becomes inert - the constant survives but nothing passes it, which
     is the settable-but-arithmetically-dead shape of
     reference_ds_route_seam_transport_vs_flag.

This file does NOT re-prove propagation. That needs a live spawn; it is a manual
canary and the failure message says so.

REAL CLI (RM-684): test_cli_version_still_matches_the_pin execs the installed
`claude --version` (no session, no API call; it skips when the CLI is absent or
not runnable). Never include this module in a fake-only pass (LEDGER 1684); it
stays IN the gated whole suite, where its tripwire is the point.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ops.loop import executor

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "ops" / "loop" / "config.json"

# Measured 2026-08-01; re-measured 2026-09-01 on 2.1.251 after Legion's CLI
# upgraded 2.1.220 -> 2.1.251. Canary + negative control BOTH passed: a codeword
# placed only in --append-subagent-system-prompt reached a spawned subagent, and
# the same prompt without the flag did not carry it. Re-measure on any change.
#
# RE-MEASURED 2026-10-01 on 2.1.285 (NOW-5). THREE controls, all passing, which
# is one more than the 2026-09-01 round ran:
#   1. CANARY: a codeword placed only in --append-subagent-system-prompt came
#      back inside a spawned subagent's own hand-back body. Proven to be a REAL
#      spawn by a stream-json run showing a single `Agent` tool_use and the
#      subagent reporting `tool_uses: 0` - so the codeword came from its system
#      prompt, not from a file read or a parent relay.
#   2. NEGATIVE CONTROL: the byte-identical invocation WITHOUT the flag returned
#      NO-CANARY and the codeword appears zero times in the transcript.
#   3. TOP-LEVEL LEAK CONTROL (new this round): flag present, NO spawn, top
#      level asked to read its OWN system prompt -> NO-CANARY. This closes the
#      ambiguity the header warns about, where a canary could be satisfied by
#      the parent reading its own prompt rather than by propagation.
# Still UNDOCUMENTED on 2.1.285: a `subagent` grep of `claude --help` returns
# only `--forward-subagent-text`, and the binary still accepts the flag (exit 0,
# against exit 1 for a genuinely unknown option). Re-measure on any change - do
# NOT bump this constant without re-running all three controls, because a bump
# alone converts a live wire-check into a constant that proves nothing.
#
# RE-MEASURED 2026-10-12 on 2.1.296 (RM-684, session 111). All three controls
# re-run BEFORE the bump, each a real `claude -p` started through the fleet
# kit's spawn() (URL from ops/loop/headless_env, stream-json via log_path),
# sonnet / effort low, one random codeword placed only in the flag value:
#   0. UNKNOWN-OPTION control: `--definitely-not-a-flag` -> exit 1, "unknown
#      option"; the canary run with the real flag -> exit 0.
#   1. CANARY: one top-level `Agent` tool_use, the codeword absent from its
#      input, the subagent's totalToolUseCount 0, and the codeword came back
#      first in the subagent's hand-back -> final result CANARY=<codeword>.
#   2. NEGATIVE CONTROL: byte-identical prompt, no flag, same real spawn shape
#      -> NO-CANARY, codeword count 0 in the stream.
#   3. TOP-LEVEL LEAK CONTROL: flag present, no spawn, top level reads its OWN
#      prompt -> NO-CANARY, codeword count 0.
# Still UNDOCUMENTED on 2.1.296: a `subagent` grep of `claude --help` returns
# only `--forward-subagent-text`. Before the bump this test failed on
# '2.1.296 (Claude Code)' against 2.1.285, so the tripwire still fires.
#
# RE-MEASURED 2026-10-19 on 2.1.304 (F1, session 124). The same RM-684 harness
# (four real `claude -p` runs through the fleet kit's spawn(), sonnet / effort
# low, a FRESH random codeword placed only in the flag value; the stream-json
# init of each of the three model runs (1-3) reports claude_code_version
# 2.1.304, while run 0 exits at argv parsing with an empty stream) re-run
# BEFORE the bump:
#   0. UNKNOWN-OPTION control: `--definitely-not-a-flag` -> exit 1, "unknown
#      option"; the canary run with the real flag -> exit 0.
#   1. CANARY: one top-level `Agent` tool_use, the codeword absent from its
#      input, the subagent's totalToolUseCount 0, and the codeword's FIRST
#      appearance in the stream is the subagent's completion (its
#      task_notification summary, then its hand-back) -> final result
#      CANARY=<codeword>.
#   2. NEGATIVE CONTROL: byte-identical prompt, no flag, same real spawn shape
#      -> NO-CANARY, codeword count 0 in the stream.
#   3. TOP-LEVEL LEAK CONTROL: flag present, no spawn, top level reads its OWN
#      prompt -> NO-CANARY, codeword count 0.
# Still UNDOCUMENTED on 2.1.304: a `subagent` grep of `claude --help` returns
# only `--forward-subagent-text`. Before the bump this test failed on
# '2.1.304 (Claude Code)' against 2.1.296, so the tripwire still fires.
#
# RE-MEASURED 2026-10-20 on 2.1.305 (session 125, after the CLI auto-updated
# 2.1.304 -> 2.1.305 and this test went red in the gated suite, LEDGER 1748).
# The same RM-684 harness (four real `claude -p` runs through the fleet kit's
# spawn(), sonnet / effort low, a FRESH random codeword placed only in the
# flag value; the stream-json init of each of runs 1-3 reports
# claude_code_version 2.1.305, while run 0 exits at argv parsing with an empty
# stream) re-run BEFORE the bump:
#   0. UNKNOWN-OPTION control: `--definitely-not-a-flag` -> exit 1, "unknown
#      option"; the canary run with the real flag -> exit 0.
#   1. CANARY: one top-level `Agent` tool_use, the codeword absent from its
#      input, the subagent's totalToolUseCount 0, and the codeword's FIRST
#      appearance in the stream is the subagent's completion (its
#      task_notification summary, then its hand-back) -> final result
#      CANARY=<codeword>.
#   2. NEGATIVE CONTROL: byte-identical prompt, no flag, same real spawn shape
#      -> NO-CANARY, codeword count 0 in the stream.
#   3. TOP-LEVEL LEAK CONTROL: flag present, no spawn, top level reads its OWN
#      prompt -> NO-CANARY, codeword count 0.
# Still UNDOCUMENTED on 2.1.305: a `subagent` grep of `claude --help` returns
# only `--forward-subagent-text` (the whole --help text is byte-identical to
# 2.1.304's). Before the bump this test failed on '2.1.305 (Claude Code)'
# against 2.1.304, so the tripwire still fires.
#
# RE-MEASURED 2026-10-22 on 2.1.308 (session 126, after the CLI auto-updated
# 2.1.305 -> 2.1.308 and this test went red in the s126 gated suite). The same
# RM-684 harness (four real `claude -p` runs through the fleet kit's spawn(),
# sonnet / effort low, a FRESH random codeword placed only in the flag value;
# the stream-json init of each of runs 1-3 reports claude_code_version
# 2.1.308, while run 0 exits at argv parsing with an empty stream) re-run
# BEFORE the bump:
#   0. UNKNOWN-OPTION control: `--definitely-not-a-flag` -> exit 1, "unknown
#      option"; the canary run with the real flag -> exit 0.
#   1. CANARY: one top-level `Agent` tool_use, the codeword absent from its
#      input, the subagent's totalToolUseCount 0, and the codeword's FIRST
#      appearance in the stream is the subagent's completion (its
#      task_notification summary, then its hand-back) -> final result
#      CANARY=<codeword>.
#   2. NEGATIVE CONTROL: byte-identical prompt, no flag, same real spawn shape
#      -> NO-CANARY, codeword count 0 in the stream.
#   3. TOP-LEVEL LEAK CONTROL: flag present, no spawn, top level reads its OWN
#      prompt -> NO-CANARY, codeword count 0.
# Still UNDOCUMENTED on 2.1.308: a `subagent` grep of `claude --help` returns
# only `--forward-subagent-text` (the whole --help text is byte-identical to
# 2.1.305's). Before the bump this test failed on '2.1.308 (Claude Code)'
# against 2.1.305, so the tripwire still fires.
#
# RE-MEASURED 2026-10-22 on 2.1.309 (slice W2-F, after the CLI auto-updated
# 2.1.308 -> 2.1.309 and this test went red in the gated suite on main
# 915300765). The same RM-684 harness (four real `claude -p` runs through the
# fleet kit's spawn(), sonnet / effort low, a FRESH random codeword placed only
# in the flag value; the stream-json init of each of runs 1-3 reports
# claude_code_version 2.1.309, while run 0 exits at argv parsing with an empty
# stream; one kit usage line per run) re-run BEFORE the bump:
#   0. UNKNOWN-OPTION control: `--definitely-not-a-flag` -> exit 1, "unknown
#      option"; the canary run with the real flag -> exit 0.
#   1. CANARY: one top-level `Agent` tool_use, the codeword absent from its
#      input, the subagent's totalToolUseCount 0, and the codeword's FIRST
#      appearance in the stream is the subagent's completion (its
#      task_notification summary, then its hand-back) -> final result
#      CANARY=<codeword>.
#   2. NEGATIVE CONTROL: byte-identical prompt, no flag, same real spawn shape
#      -> NO-CANARY, codeword count 0 in the stream.
#   3. TOP-LEVEL LEAK CONTROL: flag present, no spawn, top level reads its OWN
#      prompt -> NO-CANARY, codeword count 0.
# Still UNDOCUMENTED on 2.1.309: a `subagent` grep of `claude --help` returns
# only `--forward-subagent-text` (the whole --help text is byte-identical to
# 2.1.305's, as 2.1.308's was). Before the bump this test failed on
# '2.1.309 (Claude Code)' against 2.1.308, so the tripwire still fires.
PINNED_CLI = "2.1.309"
FLAG = "--append-subagent-system-prompt"


def _build(tmp_path, **over):
    cfg = {"channel": "sdk", "repo_root": str(tmp_path), "cycle_deadline_sec": 60}
    cfg.update(over)
    return executor.build(cfg, tmp_path, log=lambda m: None, stop=lambda m: None,
                          awrite=lambda p, t: None)


def test_flag_is_passed_when_the_prompt_is_configured(tmp_path):
    argv = _build(tmp_path, subagent_prompt="RULES").build_argv(1)
    assert argv[argv.index(FLAG) + 1] == "RULES"


def test_flag_is_absent_when_unconfigured(tmp_path):
    assert FLAG not in _build(tmp_path).build_argv(1)


def test_empty_prompt_does_not_pass_a_bare_flag(tmp_path):
    assert FLAG not in _build(tmp_path, subagent_prompt="  ").build_argv(1)


def test_payload_is_ascii_and_small():
    rules = executor.SUBAGENT_STANDING_RULES
    assert rules.isascii(), "7-bit ASCII only - repo-wide hard rule"
    assert 0 < len(rules) <= 400, (
        f"{len(rules)} chars - this is a per-spawn token cost on every lane; "
        "keep it short, do not paste CLAUDE.md")


def test_the_wire_is_not_inert_the_live_config_actually_carries_it():
    """Non-vacuity: a constant nothing passes is a settable-but-dead seam."""
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert cfg.get("subagent_prompt", "").strip(), (
        "ops/loop/config.json must carry subagent_prompt or RM-137 is inert")
    assert cfg["subagent_prompt"] == executor.SUBAGENT_STANDING_RULES, (
        "config.json has drifted from executor.SUBAGENT_STANDING_RULES")


def test_cli_version_still_matches_the_pin():
    claude = shutil.which("claude.cmd") or shutil.which("claude")
    if not claude:
        pytest.skip("claude CLI not on PATH")
    proc = subprocess.run([claude, "--version"], capture_output=True, text=True,
                          check=False, timeout=60)
    out = proc.stdout.strip()
    # A launcher ON PATH is not the same capability as a WORKING CLI, and
    # conflating them made this assert a false version-drift alarm. Measured
    # 2026-08-29 on Legion: the `claude.cmd` shim resolves, but the native
    # binary is not installed, so the process exits 1 with an empty stdout and
    # "Error: claude native binary not installed." on stderr. That read as
    # `CLI moved to '' from the pinned 2.1.220` - which names the wrong defect
    # and points at a canary re-run that cannot be performed, because there is
    # no working CLI to spawn a subagent with.
    #
    # An unusable CLI is an absent ENVIRONMENT CAPABILITY, so it skips, the
    # same class as the not-on-PATH branch above. Version DRIFT - a CLI that
    # runs and reports a different number - still fails loudly below, which is
    # the signal this file exists for.
    if proc.returncode != 0 or not out:
        pytest.skip(
            f"claude CLI at {claude} is not runnable (exit {proc.returncode}, "
            f"stdout empty); stderr: {proc.stderr.strip().splitlines()[:1]}"
        )
    assert PINNED_CLI in out, (
        f"CLI moved to {out!r} from the pinned {PINNED_CLI}. "
        f"{FLAG} is UNDOCUMENTED - re-run the canary before trusting it: spawn a "
        "subagent with a secret codeword in the appended prompt, then run the "
        "SAME prompt without the flag and confirm the codeword does NOT appear. "
        "Update PINNED_CLI only after that negative control passes.")
