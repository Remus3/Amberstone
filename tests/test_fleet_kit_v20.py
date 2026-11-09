"""FLEET-KIT v20 (MAIN 2026-10-18 1812 ORDER; explicit headless route, 7-day
account fallback shipped disarmed, checklist ETA clock, LANE-95, v20 backlog):
the tree-side half of the adoption.

The kit bytes are pinned by tests/test_fleet_kit_conformance.py and
tests/test_fleet_kit_v15.py (manifest sha + common block). This file pins
what the ORDER's section 4 asks RC to do around them:
  * step 1: the vendored kit is v20 (23 files + MANIFEST, manifest sha from
    the ORDER's section 1);
  * step 2: the FLEET-COMMON block carries the v20 items 10 and 13 a text and
    conformance() == [];
  * step 3: v20 write_progress always writes a top-level ISO "started"; RC's
    progress writers go through the kit, and no RC test pins an exact key set
    on a progress document (grep at adoption: none needed changing).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "ops" / "fleet_kit"
# v20 patch 1 (MAIN 2026-10-19 0001 ORDER) supersedes the 1812 v20 bytes
# (manifest 9e4f9980...b09b000): outbound cap 6 -> 12, FLEET-COMMON 14 c.
# Kit v23 (MAIN 2026-10-25 1926 ORDER, cumulative v21 + v22) supersedes
# v20.1 (manifest 8017eae2...e77d4602); the v20 behaviour below still holds.
# Kit v24 (MAIN 2026-10-26 0315 ORDER) supersedes v23 (manifest
# f5d82861...11ba527c); same 23-file set.
# Kit v25 (MAIN 2026-10-27 2136 ORDER, LANE-CAP) supersedes v24 (manifest
# a41ff08e...c8804a7d); same 23-file set.
# Kit v26 (MAIN 2026-10-31 2200 ORDER, cumulative) superseded v25 (manifest
# fa04c87c...25c1bea, 23 files); the pins below now hold the v26 bytes (24 files).
# Kit v27 (MAIN 2026-10-31 2347 ORDER, cumulative) superseded v26 (manifest
# 45b5088e...6fe4edae, 24 files); the pins below now hold the v27 bytes (24 files).
# Kit v28 (MAIN 2026-11-01 0825 ORDER, cumulative) superseded v27 (manifest
# 0a90af35...68e949c1, 24 files); the pins below now hold the v28 bytes (24 files).
V20_MANIFEST_SHA256 = "343471741c03a78e29c3c08fa0af713f6576ef0b2d69843a87a497b9e52a6d93"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"rc_v20_probe_{name}", KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text(rel):
    return (ROOT / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def test_the_vendored_kit_is_the_v20_order_bytes():
    raw = (KIT / "MANIFEST.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V20_MANIFEST_SHA256
    man = json.loads(raw.decode("ascii"))
    assert man["version"] == 28
    assert len(man["files"]) == 24
    assert _load("fleet_headless").KIT_VERSION == 28
    assert _load("fleet_headless").KIT_PATCH == 0


def test_v20_1_outbound_cap_is_12_per_day_with_the_same_exempt_classes():
    fi = _load("fleet_inbox")
    assert fi.OUTBOUND_CAP == 12
    assert set(fi.EXEMPT) == {"ORDER", "FIX", "RULING"}
    text = _text("CLAUDE.md")
    assert "At most 12 outbound notes per tree per local day" in text
    assert "At most 6 outbound" not in text


def test_the_common_block_carries_the_v20_route_and_eta_clock_text():
    text = _text("CLAUDE.md")
    block = text[text.index("<!-- FLEET-COMMON BEGIN -->"):text.index("<!-- FLEET-COMMON END -->")]
    assert "~/.fleet/headless_route.json" in block
    assert "7-day usage-limit refusal" in block
    # v21 KIT-ETA-REMAIN: the running row reads "started ... Remain".
    assert "<pct>% ~<rem>m of <total>m Remain" in block
    assert _load("fleet_headless").conformance(ROOT) == []


def test_claude_md_kit_v20_line_says_who_may_arm_the_route_fallback():
    # RM-2075: the line once said RC "arms no account fallback", but on
    # 2026-11-08 the kit's own verb armed it on the operator's order
    # (LEDGER 2079). The true rule: the kit is the route file's only writer,
    # and a fallback is armed only on the operator's word.
    text = _text("CLAUDE.md")
    rc = text[text.index("<!-- FLEET-COMMON END -->"):]
    line = next(ln for ln in rc.split("\n") if ln.startswith("**KIT v20 (MAIN 2026-10-18 1812"))
    for needle in ("`~/.fleet/headless_route.json`", "only the kit writes it (never RC)",
                   "arms a fallback only on the operator's word", "LEDGER 2079",
                   "key SUBSET, never an exact set", "Guard `tests/test_fleet_kit_v20.py`"):
        assert needle in line, needle
    assert "arms no account fallback" not in text
    assert (ROOT / "CLAUDE.md").stat().st_size <= 60 * 1024


def test_v20_write_progress_adds_an_iso_started_key(tmp_path):
    fh = _load("fleet_headless")
    (tmp_path / ".git").mkdir()
    doc = fh.write_progress(tmp_path, "v20-probe", 10, "step", 60, "running")
    on_disk = json.loads(Path(doc["path"]).read_text(encoding="utf-8"))
    assert {"task", "pct", "step", "eta_s", "status", "updated", "started"} <= set(on_disk)
    assert isinstance(on_disk["started"], str) and isinstance(on_disk["updated"], str)


def test_the_checklist_helper_renders_the_eta_clock_for_a_running_row():
    cl = _load("fleet_checklist")
    t0 = 1_760_000_000
    row = cl.item("B1", "build it", "builder running", 1800, pct=25, started=t0)
    line = cl.line(row, now=t0 + 600)
    assert "25%" in line and "of" in line and "[" in line
    # A row without a start time keeps the plain ~ETA form (readers: optional).
    assert "~" in cl.line(cl.item("B2", "build it", "builder running", 240))
