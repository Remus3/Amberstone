"""RM-258 residual: tools/build_python_embed.py writes through core.polled_json.

Two hand-rolled swaps used to live in the embedded-runtime builder (PKG-4):
`_atomic_write_text` (the rewritten python3XX._pth and EMBED_STAMP.json)
wrote a fixed `<name>.tmp` scratch derived from the destination and renamed it
with a bare `Path.replace`, and `fetch_embed_zip` streamed the download into a
fixed `<zip>.part` and renamed that the same way: no fsync, no WinError 5
retry. Both now hand their bytes to `core.polled_json.atomic_write_bytes`
(per-writer scratch, fsync, bounded retry, scratch removed on failure). The
download is still bounded by EMBED_ZIP_MAX_BYTES and still hash-checked
BEFORE a byte reaches the cache, so a mismatch keeps nothing.

Every path lives under tmp_path; no network, no pip.
"""
from __future__ import annotations

import ast
import hashlib
import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import polled_json  # noqa: E402
from tools import build_python_embed as bpe  # noqa: E402

_TOOL = _ROOT / "tools" / "build_python_embed.py"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("python.exe", b"MZ synthetic")
        zf.writestr("python314._pth", "python314.zip\n.\n")
    return buf.getvalue()


@pytest.fixture
def pin_and_data():
    data = _zip_bytes()
    pin = bpe.EmbedPin(
        version="3.14.4",
        url="https://www.python.org/ftp/python/3.14.4/python-3.14.4-embeddable-amd64.zip",
        sha256=hashlib.sha256(data).hexdigest(),
    )
    return pin, data


def _opener(data: bytes):
    def opener(url, timeout=None):
        return _Resp(data)
    return opener


@pytest.fixture
def spy(monkeypatch):
    calls = []
    real = polled_json.atomic_write_bytes

    def _spy(path, data):
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", _spy)
    return calls


def _litter(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir()
                  if p.name.endswith((".tmp", ".part")))


def _deny_every_rename(monkeypatch):
    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))


def test_pth_rewrite_routes_through_polled_json_as_lf(tmp_path, spy, pin_and_data):
    pin, _ = pin_and_data
    pth = tmp_path / pin.pth_name
    pth.write_bytes(b"python314.zip\r\n.\r\n")

    lines = bpe.configure_pth(tmp_path, pin)

    assert [p for p, _ in spy] == [pth]
    on_disk = pth.read_bytes()
    assert on_disk == spy[0][1] == ("\n".join(lines) + "\n").encode("utf-8")
    assert b"\r" not in on_disk
    assert _litter(tmp_path) == []


def test_download_routes_through_polled_json_and_leaves_no_part(
        tmp_path, spy, pin_and_data):
    pin, data = pin_and_data
    cache = tmp_path / "cache"

    got = bpe.fetch_embed_zip(pin, cache, opener=_opener(data))

    assert spy == [(got, data)]
    assert got.read_bytes() == data
    assert _litter(cache) == []


def test_hash_mismatch_writes_nothing(tmp_path, spy, pin_and_data):
    pin, data = pin_and_data
    cache = tmp_path / "cache"

    with pytest.raises(bpe.EmbedError):
        bpe.fetch_embed_zip(pin, cache, opener=_opener(data + b"tampered"))

    assert spy == []
    assert list(cache.iterdir()) == []


def test_oversized_download_writes_nothing(tmp_path, spy, pin_and_data, monkeypatch):
    pin, data = pin_and_data
    cache = tmp_path / "cache"
    monkeypatch.setattr(bpe, "EMBED_ZIP_MAX_BYTES", len(data) - 1)

    with pytest.raises(bpe.EmbedError, match="exceeded"):
        bpe.fetch_embed_zip(pin, cache, opener=_opener(data))

    assert spy == []
    assert list(cache.iterdir()) == []


def test_refused_rename_keeps_the_prior_pth_and_leaves_no_scratch(
        tmp_path, monkeypatch, pin_and_data):
    pin, _ = pin_and_data
    pth = tmp_path / pin.pth_name
    before = b"python314.zip\n.\n"
    pth.write_bytes(before)
    _deny_every_rename(monkeypatch)

    with pytest.raises(PermissionError):
        bpe.configure_pth(tmp_path, pin)

    assert pth.read_bytes() == before
    assert _litter(tmp_path) == []


def test_refused_cache_write_is_an_embed_error_and_leaves_no_scratch(
        tmp_path, monkeypatch, pin_and_data):
    pin, data = pin_and_data
    cache = tmp_path / "cache"
    _deny_every_rename(monkeypatch)

    with pytest.raises(bpe.EmbedError):
        bpe.fetch_embed_zip(pin, cache, opener=_opener(data))

    assert list(cache.iterdir()) == []


def test_tool_has_no_hand_rolled_swap():
    src = _TOOL.read_text(encoding="utf-8")
    tree = ast.parse(src)
    renames = [n.lineno for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr in ("replace", "rename")
               and not (n.args and isinstance(n.args[0], ast.Constant)
                        and isinstance(n.args[0].value, str))]
    assert renames == [], renames
    assert ".part" not in src
    assert 'name + ".tmp"' not in src


def test_script_mode_imports_core_from_a_foreign_cwd(tmp_path):
    # Script mode puts tools/ (not the repo root) first on sys.path; the
    # writer must still resolve core/ with no PYTHONPATH from any cwd.
    out = tmp_path / "out" / "x.txt"
    code = ("import sys; sys.path[:0] = [sys.argv[1]]; "
            "import build_python_embed as b; "
            "b._atomic_write_text(__import__('pathlib').Path(sys.argv[2]), 'a\\nb\\n')")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [sys.executable, "-c", code, str(_TOOL.parent), str(out)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
        check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert proc.returncode == 0, proc.stderr
    assert out.read_bytes() == b"a\nb\n"
    assert _litter(out.parent) == []
