"""ops/loop/config.json carries config, not history prose (MAIN kit-v13 ORDER
section 2, PERF-AUDIT item 9, 2026-10-09).

The file had grown to ~19 KB, ~13 KB of it `_note` / `_RETIRED` prose that every
reader of the loop config paid for and no consumer read. The prose moved,
verbatim, to docs/LOOP_CONFIG_NOTES.md; config.json keeps one short `_notes`
pointer. Pinned here:
  * no note prose regrows in config.json (any `_`-prefixed key other than the
    pointer, at any depth, fails);
  * every relocated note has a heading in the doc, and its load-bearing
    sentences survived the move;
  * every key a consumer reads is still there with a usable type - the
    consumers are ops/loop/loop_controller.py (CFG), ops/loop/adjudicator.py
    (claude_adjudicator), ops/loop/run_lane.ps1 (executor_model /
    executor_effort), tools/inbox_responder_runner.py (max_concurrent_lanes),
    tools/inbox_responder_spawn.py (executor_cmd) and the dashboard loop routes
    (max_cycles, transcript_dir, session_jsonl).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "ops" / "loop" / "config.json"
DOC = ROOT / "docs" / "LOOP_CONFIG_NOTES.md"

POINTER_KEY = "_notes"

# Every prose key that left config.json, as a dotted path.
RELOCATED = (
    "_max_concurrent_lanes_note",
    "_directive_suffix_RETIRED_20260726",
    "_channel_note",
    "_channel_posture_note",
    "_executor_effort_note",
    "_cycle_budget_note",
    "_adjudicator_vendor_note",
    "claude_adjudicator._note",
    "_subagent_prompt_note",
)

# One sentence per note that a reader acts on; each must survive the move.
LOAD_BEARING = (
    "MUST equal the value in the other two projects' configs",
    "3 must NOT be lowered to 2 to match",
    "ROLLBACK IS THIS ONE KEY: set it back to 'ahk'.",
    "On this channel the git hooks are the ONLY commit gate",
    "The kit accepts only low, medium, high, xhigh, max",
    "read it as relative effort, never as spend.",
    "There is therefore NO one-key rollback any more",
    "so the old cmd key was dead and is removed",
    "Must stay byte-equal to ops/loop/executor.SUBAGENT_STANDING_RULES",
    "Do not restore it.",
)


def _config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _underscore_keys(obj, prefix=""):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if k.startswith("_"):
                out.append(path)
            out += _underscore_keys(v, path)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _underscore_keys(v, f"{prefix}[{i}]")
    return out


def test_config_carries_no_note_prose():
    keys = _underscore_keys(_config())
    assert POINTER_KEY in keys, "the pointer to the notes doc is gone"
    stray = [k for k in keys if k != POINTER_KEY]
    assert not stray, (
        f"note prose regrew in ops/loop/config.json: {stray}. Put it in "
        f"docs/LOOP_CONFIG_NOTES.md under the key's heading instead.")


def test_the_pointer_is_one_short_line_naming_the_doc():
    value = _config()[POINTER_KEY]
    assert isinstance(value, str) and "docs/LOOP_CONFIG_NOTES.md" in value
    assert len(value) <= 200


def test_config_stays_small():
    # Measured 19303 bytes before the move, 5873 after; the directive_suffix
    # brief is live config and stays. A regrowth past 8 KB is prose creeping back.
    assert len(CONFIG.read_bytes()) < 8192


def test_every_relocated_note_has_a_heading_with_a_body():
    text = DOC.read_text(encoding="utf-8")
    for key in RELOCATED:
        head = f"## `{key}`"
        assert head in text, f"{key} has no heading in {DOC.name}"
        body = text.split(head, 1)[1].split("\n## ", 1)[0].strip()
        assert len(body) > 80, f"{key} heading has no note body"


def test_load_bearing_sentences_survived_the_move():
    text = " ".join(DOC.read_text(encoding="utf-8").split())
    missing = [s for s in LOAD_BEARING if s not in text]
    assert not missing, f"lost in the move: {missing}"


def test_relocated_keys_are_absent_from_config():
    cfg = _config()
    for dotted in RELOCATED:
        node = cfg
        parts = dotted.split(".")
        for p in parts[:-1]:
            node = node.get(p, {})
        assert parts[-1] not in node, f"{dotted} is still in config.json"


def test_consumers_still_find_their_keys():
    cfg = _config()
    for key in ("repo_root", "control_dir", "executor_cmd", "transcript_dir",
                "executor_model", "executor_effort", "adjudicator", "channel",
                "claude_window_title", "session_jsonl", "subagent_prompt"):
        assert isinstance(cfg.get(key), str), key
    for key in ("max_cycles", "cycle_deadline_sec", "poll_sec", "max_concurrent_lanes"):
        assert isinstance(cfg.get(key), int) and not isinstance(cfg.get(key), bool), key
    for key in ("dry_run", "ignore_no_progress", "clear_each_cycle"):
        assert isinstance(cfg.get(key), bool), key
    assert cfg["channel"] in ("sdk", "ahk")
    assert isinstance(cfg.get("directive_suffix"), str) and len(cfg["directive_suffix"]) > 500
    adj = cfg.get("claude_adjudicator")
    assert isinstance(adj, dict) and adj.get("model") and adj.get("timeout_sec")
    prices = cfg.get("price_per_mtok")
    for tier in ("opus", "sonnet", "haiku", "default"):
        assert set(prices[tier]) == {"input", "output", "cache_write", "cache_read"}, tier


def test_the_doc_is_ascii_and_lf():
    data = DOC.read_bytes()
    assert data.isascii()
    assert b"\r\n" not in data
