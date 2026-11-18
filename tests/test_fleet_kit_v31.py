"""FLEET-KIT v31 (MAIN 2026-11-14 0936 ORDER to all eight, cumulative).

RC was at v30, so only the v31 items apply: a failed run's usage row gains
"cause" and its "error" reads "<cause>; rc <n>[; <detail>]" (FI-A3);
`fleet_done.py archive` also moves older STATE OBSERVED blocks and gains
`--auto`, which /done runs before its commit (FI-A15); `fleet_headless.py
agents` warns MF-4 per agent file without model / effort pins; usage_pct reads
a reset stamp in milliseconds. FLEET-COMMON is unchanged since v30. These pin
the vendored bytes, the RC acts and the kit behaviour RC leans on. Key sets are
SUBSETS, never exact. CLAUDE.md carries the RC "KIT v31" rules line naming this
guard; long form in docs/FLEET_KIT_ADOPTION.md.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "ops" / "fleet_kit"
# Kit v32 (MAIN 2026-11-16 1947 ORDER, cumulative) superseded v31 in the same
# landing commit (manifest 6359f695...899a3829d, block 6205943c...bedea5ee); the
# pins below now hold the v32 bytes (25 files, FLEET-COMMON items 17 and 18 changed).
V31_MANIFEST_SHA256 = "cede0b7c8a80ca6ece410c07b572e4ac9dabe0bf7769d9c82d692bb1858c757d"
V31_COMMON_BLOCK_SHA256 = "0dbee15df74d42c2b50747c8194c9afd0d09c8ac7e03659515b9b3df7eca40a1"
BEGIN, END = "<!-- FLEET-COMMON BEGIN -->\n", "<!-- FLEET-COMMON END -->"
ARCHIVE_AUTO = "python ops/fleet_kit/fleet_done.py archive --auto"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"rc_v31_probe_{name}", KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_rc(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text(rel):
    return (ROOT / rel).read_bytes().decode("ascii")


# ---------------------------------------------------------------- vendoring

def test_the_vendored_kit_is_the_v31_order_bytes_and_conforms():
    raw = (KIT / "MANIFEST.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V31_MANIFEST_SHA256
    man = json.loads(raw.decode("ascii"))
    assert man["version"] == 32 and len(man["files"]) == 25
    assert man["common_block_sha256"] == V31_COMMON_BLOCK_SHA256
    fh = _load("fleet_headless")
    assert (fh.KIT_VERSION, fh.KIT_PATCH) == (32, 0)
    for name, want in man["files"].items():
        assert hashlib.sha256((KIT / name).read_bytes()).hexdigest() == want, name
    assert fh.conformance(ROOT) == []


def test_the_common_block_is_the_vendored_one():
    # v31 left the block unchanged since v30; v32 changed items 17 and 18, so
    # this now pins the v32 block (re-embedded in the same landing commit).
    text = _text("CLAUDE.md")
    block = text[text.index(BEGIN) + len(BEGIN):text.index(END)]
    assert hashlib.sha256(block.encode("ascii")).hexdigest() == V31_COMMON_BLOCK_SHA256


def test_claude_md_carries_the_kit_v31_rules_line():
    text = _text("CLAUDE.md")
    rc = text[text.index(END):]
    line = next(ln for ln in rc.split("\n")
                if ln.startswith("**KIT v31 (MAIN 2026-11-14 0936, cumulative)"))
    for needle in ("`cause`", "<cause>; rc <n>", "archive --auto", "MF-4",
                   "Guard `tests/test_fleet_kit_v31.py`"):
        assert needle in line, needle
    assert rc.index("**KIT v30 (") < rc.index("**KIT v31 (")
    assert (ROOT / "CLAUDE.md").stat().st_size <= 60 * 1024
    assert "## KIT v31 (MAIN 2026-11-14 0936, cumulative)" in _text("docs/FLEET_KIT_ADOPTION.md")


# ---------------------------------------------------------------- FI-A3 cause

def test_a_failed_run_error_reads_cause_then_rc_then_detail():
    fh = _load("fleet_headless")
    assert {"usage-limit", "auth", "proxy", "tool-crash", "other"} <= set(fh.CAUSES)
    assert fh.classify_cause("", {"window": "5h"}) == "usage-limit"
    assert fh.classify_cause("") == "other"
    assert fh.cause_error("other", 1) == "other; rc 1"
    err = fh.cause_error("other", 1, "error: unknown option '--x'\n")
    assert err.startswith("other; rc 1; ") and "unknown option" in err
    # No stderr: the detail is the result text's first non-empty line.
    assert fh.cause_error("other", 2, None, "\n first line\nsecond") == "other; rc 2; first line"


def test_rc_failed_row_readers_hold_on_the_v31_error_format():
    """fleet_route reads "is there an error" plus the "unknown option" substring,
    which v31 keeps in the detail: a designed negative still passes, any other
    rc 1 still fails."""
    route = _load_rc("rc_v31_fleet_route", "ops/loop/fleet_route.py")
    fh = _load("fleet_headless")
    note = "repin-subagent-cli-unknown-designed-negative-rc1"
    base = {"note": note, "rc": 1, "is_error": None, "limit": None, "cause": "other"}
    neg = dict(base, error=fh.cause_error("other", 1, "error: unknown option '--zz'"))
    assert route.is_designed_negative(neg) and not route.row_failed(neg)
    bare = dict(base, error=fh.cause_error("other", 1))
    assert not route.is_designed_negative(bare) and route.row_failed(bare)
    plain = dict(base, note="lane-1 build", error=fh.cause_error("auth", 1, "401"))
    assert route.row_failed(plain)


# ---------------------------------------------------------------- FI-A15 archive

def _handoff(root, body):
    root.mkdir(parents=True, exist_ok=True)
    (root / "RC-NEXT-SESSION.txt").write_bytes(body.encode("ascii"))


def test_archive_moves_older_state_observed_blocks_and_keeps_the_newest(tmp_path):
    """The hand-off is newest-first, so the FIRST block in the file stays."""
    fd = _load("fleet_done")
    root = tmp_path / "tree"
    _handoff(root, "SESSION: 9\n\nSTATE OBSERVED s9\n  newest\n\n"
                   "STATE OBSERVED s8\n  mid\n\nSTATE OBSERVED s7\n  old a\n  old b\n")
    doc = fd.archive(root, apply=True, today="2026-11-15")
    assert doc["applied"] is True
    after = (root / "RC-NEXT-SESSION.txt").read_text(encoding="ascii")
    assert "STATE OBSERVED s9" in after and "newest" in after
    assert "  mid" not in after and "old a" not in after
    assert after.count("(state block ") == 2
    archived = (root / "docs" / "handoff-archive" / "RC-2026-11-15.txt").read_text(encoding="ascii")
    assert "mid" in archived and "old b" in archived


def test_archive_auto_skips_a_small_handoff(tmp_path):
    root = tmp_path / "tree"
    _handoff(root, "SESSION: 9\n\nSTATE OBSERVED s8\n  a\n\nSTATE OBSERVED s9\n  b\n")
    before = (root / "RC-NEXT-SESSION.txt").read_bytes()
    out = subprocess.run([sys.executable, str(KIT / "fleet_done.py"), "archive", "--auto",
                          "--root", str(root)], capture_output=True, text=True, timeout=60,
                         check=False)
    assert out.returncode == 0, out.stderr
    assert "archive skipped" in out.stdout
    assert (root / "RC-NEXT-SESSION.txt").read_bytes() == before


def test_done_runs_archive_auto_before_its_section_1_commit():
    done = _text("tools/done.md")
    sec1 = done.index("### 1. Auto-commit any pending changes")
    sec2 = done.index("### 2. Push")
    at = done.index(ARCHIVE_AUTO)
    assert sec1 < at < sec2
    assert done.index("reap --apply", sec1) < at < done.index("fleet_gitlock.py", sec1)


# ---------------------------------------------------------------- MF-4, ms reset

def test_agents_verb_reports_mf4_and_always_exits_zero(tmp_path):
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "verifier.md").write_text("---\nname: verifier\nmodel: sonnet\neffort: medium\n---\n",
                                        encoding="ascii")
    (agents / "builder.md").write_text("---\nname: builder\n---\n", encoding="ascii")
    out = subprocess.run([sys.executable, str(KIT / "fleet_headless.py"), "agents",
                          "--root", str(tmp_path)], capture_output=True, text=True, timeout=60,
                         check=False)
    assert out.returncode == 0, out.stderr
    warns = [ln for ln in out.stdout.splitlines() if ln.startswith("warn MF-4:")]
    assert warns and all("builder.md" in ln for ln in warns)
    assert any("model" in ln for ln in warns) and any("effort" in ln for ln in warns)


def test_reset_stamps_in_milliseconds_read_as_seconds():
    lanes = _load("fleet_lanes")
    assert lanes.reset_s(1_794_800_000_000) == 1_794_800_000.0
    assert lanes.reset_s(1_794_800_000) == 1_794_800_000.0
