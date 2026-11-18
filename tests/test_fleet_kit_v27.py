"""FLEET-KIT v27 (MAIN 2026-10-31 2347 ORDER to all seven, cumulative: hook
launcher fast path, failed-run stderr tail, unpriced + session_id usage rows,
daily USD lane ceiling, pending ORDERs first, fleet_rewrite --range): the
tree-side half of the adoption.

The ORDER's section 5 asks RC to:
  * step 1: vendor all 24 files + MANIFEST byte-for-byte (manifest sha from
    the ORDER's section 1) and confirm conformance() == []; FLEET-COMMON.md is
    unchanged from v26, so no re-embed;
  * step 2: no settings change (the v26 launcher lines stay; only the
    launcher's bytes change) - tests/test_fleet_kit_v26.py still pins the
    wiring and the `{}` silent allow;
  * step 3: pending ORDER rows first - ops/loop/inbox_tick.py already queues
    every WORK note through the kit's enqueue_work and closes it with
    mark_work_done; v27's mark_seen also queues (deduped on note + sha256).
CLAUDE.md carries the RC "KIT v27" rules line naming this guard.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "ops" / "fleet_kit"
# Kit v28 (MAIN 2026-11-01 0825 ORDER, cumulative) superseded v27 (manifest
# 0a90af35...68e949c1, 24 files); the pins below now hold the v28 bytes (24 files).
# Kit v30 (MAIN 2026-11-12 0345 ORDER, cumulative v29 + v30) superseded v28
# (manifest 34347174...b9e52a6d93, block cacc3ca3...4e77dd0); the pins below now
# hold the v30 bytes (24 files).
# Kit v31 (MAIN 2026-11-14 0936 ORDER, cumulative) superseded v30
# (manifest d2ac4025...5714d07ea2, block unchanged); the pins below now
# hold the v31 bytes (24 files).
# Kit v32 (MAIN 2026-11-16 1947 ORDER, cumulative) superseded v31
# (manifest 6359f695...899a3829d, block 6205943c...bedea5ee); the pins below
# now hold the v32 bytes (25 files, FLEET-COMMON items 17 and 18 changed).
V27_MANIFEST_SHA256 = "cede0b7c8a80ca6ece410c07b572e4ac9dabe0bf7769d9c82d692bb1858c757d"
V27_COMMON_BLOCK_SHA256 = "0dbee15df74d42c2b50747c8194c9afd0d09c8ac7e03659515b9b3df7eca40a1"
END = "<!-- FLEET-COMMON END -->"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"rc_v27_probe_{name}", KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text(rel):
    return (ROOT / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def test_the_vendored_kit_is_the_v27_order_bytes_and_conforms():
    raw = (KIT / "MANIFEST.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V27_MANIFEST_SHA256
    man = json.loads(raw.decode("ascii"))
    assert man["version"] == 32 and len(man["files"]) == 25
    assert man["common_block_sha256"] == V27_COMMON_BLOCK_SHA256
    fh = _load("fleet_headless")
    assert (fh.KIT_VERSION, fh.KIT_PATCH) == (32, 0)
    for name, want in man["files"].items():
        assert hashlib.sha256((KIT / name).read_bytes()).hexdigest() == want, name
    assert fh.conformance(ROOT) == []


def test_the_launcher_runs_python_once_with_dash_s():
    raw = (KIT / "fleet_hook.sh").read_bytes()
    assert raw.isascii() and b"\r" not in raw
    text = raw.decode("ascii")
    assert '"$py" -S "$dir/$script" "$@" --fleet-nonce "$nonce"' in text
    assert "$(dirname" not in text and "$(date" not in text


def test_fleet_claims_has_no_module_level_subprocess():
    claims = _load("fleet_claims")
    assert not hasattr(claims, "subprocess")
    assert "runner" in claims.porcelain_paths.__code__.co_varnames


def test_usage_lines_carry_priced_and_session_id():
    fh = _load("fleet_headless")
    ok = fh.usage_line({"total_cost_usd": 1.5, "session_id": "abc"}, "RC", "n", "sonnet",
                       "low", False, 0, 1.0)
    assert ok["session_id"] == "abc" and "priced" in ok
    late = fh.usage_line({"total_cost_usd": 1.5}, "RC", "n", "sonnet", "low", False, 0, 1.0,
                         error="timeout")
    assert late["cost_usd"] is None and late["priced"] is False
    assert late["session_id"] is None


def test_the_daily_usd_ceiling_is_read_from_machine_config_only():
    lanes = _load("fleet_lanes")
    assert lanes.USD_CEIL_KEY == "daily_usd_ceiling"
    assert lanes.usd_ceiling("RC", {}) is None
    assert lanes.usd_ceiling("RC", {"daily_usd_ceiling": {"RC": 500}}) == 500
    assert lanes.usd_ceiling("rc", {"daily_usd_ceiling": {"RC": 500}}) == 500


def test_mark_seen_of_an_order_queues_it(tmp_path):
    inbox = _load("fleet_inbox")
    note = tmp_path / "2026-11-01-0000-from-MAIN-ORDER-to-RC-x.md"
    note.write_bytes(b"# From MAIN - ORDER\nORDER\nHOP: 1\n")
    d = inbox.classify(note.name, "RC", note.read_text(encoding="ascii"))
    assert d.action == inbox.WORK
    inbox.mark_seen(tmp_path, note, d)
    rows = inbox.pending_work(tmp_path)
    assert [r["note"] for r in rows] == [note.name]
    assert (tmp_path / inbox.PENDING_REL).is_file()
    first = inbox.session_start(tmp_path, tmp_path, "RC")[0]
    assert first["pending"] is True and first["note"] == note.name


def test_fleet_rewrite_takes_a_range():
    rw = _load("fleet_rewrite")
    assert rw.check_range(ROOT, None) is None
    assert callable(rw.check_range)


def test_the_suite_gate_reports_a_tree_median_hold(tmp_path):
    gate = _load("fleet_suite_gate")
    assert gate.tree_median_hold(tmp_path, "RC") == (None, 0)


def test_claude_md_carries_the_kit_v27_rules_line():
    text = _text("CLAUDE.md")
    rc = text[text.index(END):]
    line = next(ln for ln in rc.split("\n") if ln.startswith("**KIT v27 (MAIN 2026-10-31 2347"))
    for needle in ("daily_usd_ceiling", "fleet_inbox.py pending",
                   "Guard `tests/test_fleet_kit_v27.py`"):
        assert needle in line, needle
    assert (ROOT / "CLAUDE.md").stat().st_size <= 60 * 1024
