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
V20_MANIFEST_SHA256 = "f5d82861cce3f5c2d565495dbd3a8cceff3b9d895117a2f6f9d4c83f11ba527c"


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
    assert man["version"] == 23
    assert len(man["files"]) == 23
    assert _load("fleet_headless").KIT_VERSION == 23
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
