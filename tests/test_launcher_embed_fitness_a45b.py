"""A45b (s146): the shell launcher's embedded-runtime fitness agrees with
tools/build_python_embed.py.

The blocker: a `--profile dev` launch of rc-shell resolved
`<checkout>/python-embed/python.exe` (a hand-made Python 3.11.9 runtime from
April, no build stamp, missing websockets / psutil / numpy / cv2 / httpx)
before the canonical dev interpreter, so after the section-5 cutover every RC
service would have run on it. `rc-shell/src/launcher.js` now uses a
python-embed only when `embedFitness` passes: the folder's EMBED_STAMP.json
names the SHA-256 of this root's requirements.txt.

This test drives the REAL launcher.js under node against a tmp tree that
`build_python_embed.verify_embed_dir` (the Python authority for "fits this
tree") accepts, then breaks the tree two ways and checks both sides refuse
it - so the JS gate cannot drift from the stamp the builder writes. Nothing
here pins source text, and nothing touches the live checkout.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import build_python_embed as bpe

REPO = Path(__file__).resolve().parent.parent
LAUNCHER = REPO / "rc-shell" / "src" / "launcher.js"
_SCRIPT = ("const l=require(process.argv[1]);"
           "process.stdout.write(JSON.stringify(l.embedFitness({root:process.argv[2]})));")


def _fitness(root: Path) -> dict:
    node = shutil.which("node")
    if not node:  # pragma: no cover - node is present on Legion and in CI
        pytest.skip("node not on PATH")
    res = subprocess.run([node, "-e", _SCRIPT, str(LAUNCHER), str(root)],
                         capture_output=True, text=True, cwd=str(REPO), timeout=30)
    assert res.returncode == 0, f"node failed: {res.stderr.strip()}"
    return json.loads(res.stdout)


def _fit_tree(root: Path) -> Path:
    """A python-embed/ that verify_embed_dir accepts against root/requirements.txt."""
    pin = bpe.PINS[bpe.DEFAULT_VERSION]
    lock = root / "requirements.txt"
    lock.write_bytes((REPO / "requirements.txt").read_bytes())
    embed = root / "python-embed"
    (embed / "Lib" / "site-packages").mkdir(parents=True)
    for name in ("python.exe", "pythonw.exe"):
        (embed / name).write_bytes(b"")
    (embed / pin.pth_name).write_text("python314.zip\n.\nLib\\site-packages\n..\nimport site\n",
                                      encoding="utf-8")
    stamp = {"tool": "tools/build_python_embed.py",
             "cpython": {"version": pin.version, "sha256": pin.sha256},
             "requirements_sha256": bpe.sha256_file(lock)}
    (embed / bpe.STAMP_NAME).write_text(json.dumps(stamp), encoding="utf-8")
    assert bpe.verify_embed_dir(embed, requirements=lock) == []
    return embed


def test_a_tree_the_builder_calls_fit_is_fit_for_the_launcher(tmp_path):
    _fit_tree(tmp_path)
    assert _fitness(tmp_path) == {"fit": True, "reason": "ok"}


def test_a_changed_lock_is_stale_for_both(tmp_path):
    embed = _fit_tree(tmp_path)
    lock = tmp_path / "requirements.txt"
    lock.write_bytes(lock.read_bytes() + b"websockets==99.0\n")
    problems = bpe.verify_embed_dir(embed, requirements=lock)
    assert any("different requirements.txt" in p for p in problems), problems
    assert _fitness(tmp_path) == {"fit": False, "reason": "stale-lock"}


def test_an_unstamped_runtime_is_refused_by_both(tmp_path):
    """The s146 shape: a hand-made runtime with no EMBED_STAMP.json."""
    embed = _fit_tree(tmp_path)
    (embed / bpe.STAMP_NAME).unlink()
    problems = bpe.verify_embed_dir(embed, requirements=tmp_path / "requirements.txt")
    assert problems and "not built by this tool" in problems[0], problems
    assert _fitness(tmp_path) == {"fit": False, "reason": "no-stamp"}
