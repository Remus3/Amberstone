"""FLEET-KIT v15 (MAIN 2026-10-09 2055 ORDER; suite-gate durations and short
lane, stray gate drift, spawn child foreground only): the tree-side half of
the adoption.

The kit bytes are pinned by tests/test_fleet_kit_conformance.py (manifest +
FLEET-COMMON block) and by tests/test_lane_progress_v7.py (version + file
set). This file pins what the ORDER's section 3 asks RC to check around them:
  * step 1: the vendored MANIFEST.json is the ORDER's section-1 bytes, and
    the five changed files carry the v15 behaviour (durations + lane in the
    suite gate, UnicodeError beside OSError in the four .git link readers);
  * step 2: the FLEET-COMMON block is unchanged and conformance() == [];
  * step 3 (drift g): no file named fleet_suite_gate.py sits anywhere in the
    tree (tracked or untracked-unignored) except ops/fleet_kit/, the inbound
    note folders exempt;
  * step 4: every RC headless spawn reaches the kit's child_env, which now
    sets CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 (the one RC test that pinned
    the exact set of keys a spawn adds carries the new key), and no headless
    child prompt asks for background work;
  * step 5: FLEET_SIDECAR_ROOT stays pinned to "" for the suite.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "ops" / "fleet_kit"

# The ORDER's section-1 hashes (verified against MAIN's committed outbox copy
# at adoption, LEDGER).
V15_MANIFEST_SHA256 = "8b20a75b6952356145a22f240db1399b70e6c16cccdcc333fc50bb8a2b3f463c"
COMMON_BLOCK_SHA256 = "fb6c129a73d1e1d8bee60367b4f4f74d39bb4051bdef0f56afd24d88e9a6f02b"
BG_OFF = "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"
FAKE_URL = "http://127.0.0.1:9"

# Every prompt RC hands to a headless child (lane workers, the loop director /
# auditor / drain waves, the inbox responder). A v15 child runs with
# background tasks off, so none of them may ask for background work.
CHILD_PROMPT_GLOBS = (
    "tools/headless-*.md",
    "ops/loop/director_prompt.md",
    "ops/loop/auditor_prompt.md",
    "ops/loop/prompts/*.md",
    "tools/inbox_responder_prompt.py",
)
_BG_ASK = re.compile(
    r"run_in_background|\b(?:run|runs|running|go|goes|send|sends|dispatch\w*|launch\w*|"
    r"start\w*|put|kick\w*)\b[^.\n]{0,40}\b(?:in|to|into) the background\b",
    re.IGNORECASE)


def _load(name):
    spec = importlib.util.spec_from_file_location(
        f"rc_v15_probe_{name}", KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text(rel):
    return (ROOT / rel).read_bytes().decode("ascii").replace("\r\n", "\n")


# ---------------------------------------------------------------- step 1

def test_the_vendored_manifest_is_the_v15_order_bytes():
    raw = (KIT / "MANIFEST.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V15_MANIFEST_SHA256
    man = json.loads(raw.decode("ascii"))
    assert man["version"] == 15
    assert _load("fleet_headless").KIT_VERSION == 15
    for name, want in man["files"].items():
        assert hashlib.sha256((KIT / name).read_bytes()).hexdigest() == want, name


def test_the_suite_gate_records_durations_and_offers_the_short_lane(tmp_path):
    gate = _load("fleet_suite_gate")
    assert gate.DURATIONS == "durations.jsonl"
    assert (gate.LANE_MAX_S, gate.LANE_OVERRUN_S) == (120.0, 240.0)
    assert (gate.LANE_MIN_RUNS, gate.LANE_WINDOW) == (3, 5)
    # The lane is inside MAX_SLOTS: RC's default 2 regular slots leave room.
    assert gate.lane_index(gate.DEFAULT_SLOTS) == gate.DEFAULT_SLOTS
    assert gate.lane_index(gate.MAX_SLOTS) is None
    # Eligibility needs LANE_MIN_RUNS records with a median hold <= LANE_MAX_S.
    tree, chash = "rc-probe", gate.cmd_hash(["python", "-m", "pytest", "tests/x.py"])
    assert gate.lane_eligible(tmp_path, tree, chash) is False
    for hold in (30.0, 200.0, 40.0):
        gate.record(tmp_path, {"tree": tree, "cmd": chash, "hold_s": hold})
    assert gate.median_hold(tmp_path, tree, chash) == 40.0
    assert gate.lane_eligible(tmp_path, tree, chash) is True
    # A write failure never raises (a FILE where the state dir should be).
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="ascii")
    gate.record(blocker, {"tree": tree})


def test_a_non_utf8_git_link_file_falls_back_in_all_four_readers(tmp_path):
    # RC 1925 (a): each reader caught OSError only, so a link file holding
    # invalid UTF-8 raised UnicodeDecodeError. v15 takes the existing fallback.
    top = tmp_path / "wt"
    top.mkdir()
    (top / ".git").write_bytes(b"gitdir: \xff\xfe\n")
    assert _load("fleet_claims")._gitdir_of(top) is None
    assert _load("fleet_identity")._main_checkout(top) == top
    assert _load("fleet_headless").main_checkout(top) == top
    assert _load("fleet_lanes").main_tree(top) == top


# ---------------------------------------------------------------- step 2

def test_the_common_block_is_unchanged_and_conformance_is_clean():
    man = json.loads((KIT / "MANIFEST.json").read_bytes().decode("ascii"))
    assert man["common_block_sha256"] == COMMON_BLOCK_SHA256
    lines = _text("CLAUDE.md").split("\n")
    assert lines.count("<!-- FLEET-COMMON BEGIN -->") == 1
    assert lines.count("<!-- FLEET-COMMON END -->") == 1
    assert _load("fleet_headless").conformance(ROOT) == []


# ---------------------------------------------------------------- step 3

def test_no_stray_suite_gate_copy_in_the_tree():
    # Drift (g): tracked OR untracked-unignored, so the index alone is not
    # enough; git enumerates both without walking ignored trees on disk.
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others",
         "--exclude-standard", "--", ":(glob)**/fleet_suite_gate.py"],
        capture_output=True, check=True).stdout.decode("utf-8")
    hits = sorted({p for p in out.split("\0") if p})
    # Anchor: an empty enumeration would pass, so the kit copy must be seen.
    assert "ops/fleet_kit/fleet_suite_gate.py" in hits, hits
    stray = [p for p in hits if p != "ops/fleet_kit/fleet_suite_gate.py"
             and not p.startswith("moon_sync_inbox/")]
    assert stray == [], f"non-kit fleet_suite_gate.py copies (drift g): {stray}"


# ---------------------------------------------------------------- step 4

def test_the_route_child_env_runs_foreground_only():
    from ops.loop import fleet_route
    k = fleet_route.kit()
    assert k.BG_OFF_ENV == BG_OFF
    env = k.child_env(FAKE_URL, parent={"PATH": "x", BG_OFF: "0"})
    assert env[BG_OFF] == "1", "a parent value never re-enables background tasks"
    assert env["FLEET_SUBAGENT_FIRST"] == "off"


def test_every_kit_spawn_carries_the_foreground_switch(tmp_path, monkeypatch):
    # End to end through RC's route (ops/loop/fleet_route.spawn -> kit spawn);
    # the conftest forwards the kit's launch to subprocess.run with the fake
    # claude image (same seam as tests/test_kit_v10_spawn_routes.py).
    from ops.loop import fleet_route
    calls = []

    def fake_run(argv, **kw):
        calls.append((list(argv), kw))
        return subprocess.CompletedProcess(args=argv, returncode=0,
                                           stdout='{"result": "done"}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv(BG_OFF, "0")
    fleet_route.spawn("T", caller="t-v15", root=tmp_path)
    (_argv, kw), = [(a, k) for a, k in calls if a and a[0] == "claude-fake.exe"]
    assert kw["env"][BG_OFF] == "1"
    assert kw["env"]["FLEET_SUBAGENT_FIRST"] == "off"


def test_the_exact_spawn_key_pin_names_the_foreground_switch():
    src = _text("tests/test_supervisor_ephemeral_auth_env.py")
    assert '"CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"' in src


def test_no_headless_child_prompt_asks_for_background_work():
    files = sorted({p for g in CHILD_PROMPT_GLOBS for p in ROOT.glob(g) if p.is_file()})
    assert len(files) >= 10, "the prompt set shrank; an empty sweep would pass"
    asks = []
    for p in files:
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if _BG_ASK.search(line):
                asks.append(f"{p.relative_to(ROOT).as_posix()}:{n}: {line.strip()[:100]}")
    assert asks == [], "a v15 child runs foreground only (KIT-15):\n" + "\n".join(asks)


def test_the_background_ask_matcher_is_not_vacuous():
    assert _BG_ASK.search("A LONG-RUNNING command goes to the background WITH A CAP")
    assert _BG_ASK.search("call Bash with run_in_background: true")
    assert not _BG_ASK.search("A backgrounded pytest that straddles a docs edit")
    assert not _BG_ASK.search("getComputedStyle(el).backgroundColor")


# ---------------------------------------------------------------- step 5

def test_the_suite_still_pins_the_sidecar_variable_off():
    assert os.environ.get("FLEET_SIDECAR_ROOT") == ""
