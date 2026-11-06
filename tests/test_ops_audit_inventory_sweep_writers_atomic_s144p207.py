"""Three more ops/audit one-shot writers go through core.polled_json.

RM-258 residual (RM-1715): p0_inventory.py wrote P0_INVENTORY.md through
`<name>.md.tmp`, p3c24_b1b_sweep.py rewrote its targets through
`<name>.<ext>.b1btmp`, and g7_comp_harness.py wrote g7_comp_parity.json through
`<name>.json.tmp`: scratch names derived from the destination alone, shared by
two concurrent runs. All three now write through core.polled_json (per-writer
scratch name, fsync, bounded retry) with the bytes unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

from ops.audit import p0_inventory, p3c24_b1b_sweep

REPO_ROOT = Path(__file__).resolve().parents[1]
G7 = REPO_ROOT / "ops" / "audit" / "lolmath_ds_sweep" / "g7_comp_harness.py"


def test_p3c24_atomic_write_lf_normalises_eol_and_leaves_no_scratch(tmp_path):
    dest = tmp_path / "x.py"
    p3c24_b1b_sweep._atomic_write_lf(dest, "a\r\nb\rc\n" + chr(0xE9) + "\n")
    assert dest.read_bytes() == ("a\nb\nc\n" + chr(0xE9) + "\n").encode("utf-8")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.py"]


def test_p3c24_atomic_write_goes_through_polled_json(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(p3c24_b1b_sweep, "atomic_write_bytes",
                        lambda p, b: seen.append((p, b)))
    p3c24_b1b_sweep._atomic_write_lf(tmp_path / "x.py", "a\r\nb\n")
    assert seen == [(tmp_path / "x.py", b"a\nb\n")]


def test_p0_inventory_writes_md_as_lf_with_no_scratch(tmp_path, monkeypatch):
    root = tmp_path / "tree"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "f.txt").write_bytes(b"hello")
    (root / "top.py").write_bytes(b"x = 1\n")
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(p0_inventory, "ROOT", root)
    monkeypatch.setattr(p0_inventory, "OUT_DIR", out)
    assert p0_inventory.main() == 0
    md = (out / "P0_INVENTORY.md").read_bytes()
    assert md.startswith(b"# P0 baseline tree inventory\n")
    assert b"\r" not in md
    assert sorted(p.name for p in out.iterdir()) == [
        "P0_INVENTORY.md", "p0_inventory_full.csv"]


def test_p0_inventory_md_goes_through_polled_json(tmp_path, monkeypatch):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "a.txt").write_bytes(b"1")
    out = tmp_path / "out"
    out.mkdir()
    seen = []
    monkeypatch.setattr(p0_inventory, "ROOT", root)
    monkeypatch.setattr(p0_inventory, "OUT_DIR", out)
    monkeypatch.setattr(p0_inventory, "atomic_write_text",
                        lambda p, t: seen.append(p))
    assert p0_inventory.main() == 0
    assert seen == [out / "P0_INVENTORY.md"]


def test_g7_harness_routes_its_json_through_polled_json():
    src = G7.read_text(encoding="utf-8")
    assert "from core.polled_json import atomic_write_bytes" in src
    assert "atomic_write_bytes(outp, json.dumps(out, indent=2)" in src
    assert ".tmp" not in src and ".replace(outp)" not in src


def test_g7_harness_payload_bytes_match_the_old_dumps_encoding():
    """The conversion keeps json.dumps defaults (ensure_ascii), so the bytes
    equal what the old tmp.write_bytes put on disk."""
    on_disk = (G7.parent / "g7_comp_parity.json").read_bytes()
    assert b"\r" not in on_disk
    assert json.dumps(json.loads(on_disk), indent=2).encode("utf-8") == on_disk


def test_three_scripts_have_no_scratch_rename_left():
    for rel in ("ops/audit/p0_inventory.py", "ops/audit/p3c24_b1b_sweep.py"):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert ".tmp" not in src and "b1btmp" not in src, rel
        assert ".replace(md_path)" not in src and ".replace(path)" not in src, rel
