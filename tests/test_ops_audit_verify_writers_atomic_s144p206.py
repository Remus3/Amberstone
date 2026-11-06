"""Three ops/audit one-shot writers go through core.polled_json.

RM-258 residual (RM-1714): dsp10_pass2_verify.py and rf4_verify.py each
carried a private `_atomic_write` (`<dest>.json.tmp` + os.replace), and
p2w5_sweep_sliceA.py rewrote its targets through `<name>.py.tmp` + replace.
A scratch name derived from the destination alone is shared by two concurrent
runs. All three now write through core.polled_json (per-writer scratch name,
fsync, bounded retry); the bytes stay UTF-8 with LF only and no scratch is left.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ops.audit.ds_perm_swarm import dsp10_pass2_verify as dsp10
from ops.audit.ds_perm_swarm import rf4_verify as rf4

REPO_ROOT = Path(__file__).resolve().parents[1]
SWEEP = REPO_ROOT / "ops" / "audit" / "p2w5_sweep_sliceA.py"


@pytest.mark.parametrize("mod", [dsp10, rf4], ids=["dsp10", "rf4"])
def test_atomic_write_is_exact_lf_bytes_and_leaves_no_scratch(mod, tmp_path):
    dest = tmp_path / "sub" / "out.json"
    text = "line one\nline two " + chr(0xE9) + "\n"
    mod._atomic_write(dest, text)
    assert dest.read_bytes() == text.encode("utf-8")
    assert b"\r" not in dest.read_bytes()
    assert sorted(p.name for p in dest.parent.iterdir()) == ["out.json"]


@pytest.mark.parametrize("mod", [dsp10, rf4], ids=["dsp10", "rf4"])
def test_atomic_write_goes_through_polled_json(mod, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(mod, "atomic_write_text",
                        lambda p, t: seen.append((p, t)))
    mod._atomic_write(tmp_path / "out.json", "x\n")
    assert seen == [(tmp_path / "out.json", "x\n")]


def test_sweep_script_rewrites_targets_as_lf_with_no_scratch(tmp_path):
    src = SWEEP.read_text(encoding="utf-8")
    targets = src.split("TARGETS = [", 1)[1].split("]", 1)[0]
    rels = [ln.strip().strip(",").strip('"')
            for ln in targets.splitlines() if ln.strip().startswith('"')]
    assert len(rels) == 6
    for rel in rels:
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(("# a " + chr(0x2192) + " b\nx = 1\n").encode("utf-8"))
    proc = subprocess.run([sys.executable, str(SWEEP)], cwd=tmp_path,
                          capture_output=True, text=True, timeout=120,
                          check=False)
    assert proc.returncode == 0, proc.stderr
    for rel in rels:
        assert (tmp_path / rel).read_bytes() == b"# a -> b\nx = 1\n"
    leftovers = [p.name for p in tmp_path.rglob("*")
                 if p.is_file() and p.name.endswith(".tmp")]
    assert leftovers == []


def test_sweep_script_routes_through_polled_json():
    src = SWEEP.read_text(encoding="utf-8")
    assert "from core.polled_json import atomic_write_text" in src
    assert "os.replace" not in src and ".tmp" not in src
