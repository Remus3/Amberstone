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
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ops.loop import executor

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "ops" / "loop" / "config.json"

# Measured 2026-08-01. Re-measure the canary on any change to this pin.
PINNED_CLI = "2.1.220"
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
    out = subprocess.run([claude, "--version"], capture_output=True, text=True,
                         check=False, timeout=60).stdout.strip()
    assert PINNED_CLI in out, (
        f"CLI moved to {out!r} from the pinned {PINNED_CLI}. "
        f"{FLAG} is UNDOCUMENTED - re-run the canary before trusting it: spawn a "
        "subagent with a secret codeword in the appended prompt, then run the "
        "SAME prompt without the flag and confirm the codeword does NOT appear. "
        "Update PINNED_CLI only after that negative control passes.")
