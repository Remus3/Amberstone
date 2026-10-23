"""RM-818 sibling sweep: the commit gate read git and ruff through the LOCALE.

Same root cause as tools/edit_lint_check.py (tests/test_edit_lint_check_cp1252_rm818.py):
tools/precommit_gate.py ran `git diff --cached`, the ruff `--version` probe
and `ruff check --output-format=json` with `text=True` and no encoding. Git
and ruff emit UTF-8 bytes whatever the console code page. Measured under a
cp1252 child (Windows, UTF-8 mode off, as .githooks/pre-commit runs from a
plain terminal): a staged U+201D (E2 80 9D; cp1252 has no 0x9D) faulted the
reader thread, the diff came back None, and the gate BLOCKED with "the gate
itself failed (AttributeError)" instead of naming the glyph; the ruff half,
handed a None stdout, parsed no findings and passed in silence. Every child
now decodes UTF-8 with errors="replace".

Source stays ASCII: every non-ASCII probe is built with chr().
"""
from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
GATE = _ROOT / "tools" / "precommit_gate.py"
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tools"))

import precommit_gate as G  # noqa: E402

from tests._module_view import bind_subprocess  # noqa: E402

_RDQUO = chr(0x201D)  # UTF-8 E2 80 9D; 0x9D is undefined in cp1252
_RUFF_IMPORTABLE = importlib.util.find_spec("ruff") is not None


def _legacy_env() -> dict:
    drop = ("PYTHONUTF8", "PYTHONIOENCODING", "LC_ALL", "LC_CTYPE", "LANG")
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update(PYTHONUTF8="0", GIT_CONFIG_NOSYSTEM="1")
    if os.name != "nt":
        env.update(LC_ALL="C", LANG="C", PYTHONCOERCECLOCALE="0")
    return env


def _staged(tmp_path: Path, name: str, text: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1"}

    def run(*args):
        subprocess.run(["git", *args], cwd=repo, capture_output=True, env=env, check=True)

    run("init", "-q", ".")
    run("config", "user.email", "gate@test")
    run("config", "user.name", "gate")
    (repo / "base.txt").write_text("base\n", encoding="ascii")
    run("add", "-A")
    run("commit", "-qm", "base")
    (repo / name).write_bytes(text.encode("utf-8"))
    run("add", name)
    return repo


def test_a_staged_smart_quote_is_named_under_a_legacy_locale(tmp_path):
    repo = _staged(tmp_path, "q.md", "say " + _RDQUO + "hi" + _RDQUO + "\n")
    probe = subprocess.run([sys.executable, "-c", "import locale; print(locale.getencoding())"],
                           capture_output=True, timeout=30, env=_legacy_env())
    encoding = probe.stdout.decode("ascii", errors="replace").strip()
    if encoding.replace("-", "").lower() in ("utf8", ""):
        pytest.skip(f"this host's legacy child still decodes {encoding or 'nothing'}")
    proc = subprocess.run([sys.executable, str(GATE)], input=b"git commit", cwd=str(repo),
                          env=_legacy_env(), capture_output=True, timeout=120)
    err = proc.stderr.decode("ascii", errors="replace")
    assert "itself failed" not in err and "Traceback" not in err, (encoding, err[-1500:])
    assert proc.returncode == 2, (encoding, proc.returncode, err[-1500:])
    assert "q.md" in err, err[-1500:]


def test_every_text_mode_child_decodes_utf8(tmp_path, monkeypatch):
    """Host-independent half: each text-mode child names its encoding, so the
    locale never decides how git's or ruff's bytes are read."""
    repo = _staged(tmp_path, "victim.py", "import os\n")
    calls = []
    real = subprocess.run

    def recording(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return real(argv, **kwargs)

    bind_subprocess(monkeypatch, G, run=recording)
    monkeypatch.chdir(repo)
    monkeypatch.setattr("sys.stdin", io.StringIO("git commit"))
    G.main()
    text_calls = [(argv, kw) for argv, kw in calls if kw.get("text")]
    assert any(argv[:2] == ["git", "diff"] for argv, _ in text_calls), calls
    if _RUFF_IMPORTABLE:
        assert any("check" in argv for argv, _ in text_calls), calls
    bad = [argv for argv, kw in text_calls
           if (kw.get("encoding"), kw.get("errors")) != ("utf-8", "replace")]
    assert not bad, bad
