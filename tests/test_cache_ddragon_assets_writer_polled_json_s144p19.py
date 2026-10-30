"""RM-1130: scripts/cache_ddragon_assets.py fetch() goes through core.polled_json.

The script downloads item and champion icons into web/data/ddragon/<ver>/img/,
the static tree the :8888 dashboard serves and the tree the RC-DDragonMirror
task (tools/ddragon_mirror_refresh.py, already on core.polled_json) writes too.
Its ``fetch`` hand-rolled the swap:

  1. a fixed ``<name>.png.tmp`` scratch derived from the destination alone, so
     this script and the mirror task writing one icon share it;
  2. a BARE ``Path.replace`` with no WinError 5 retry;
  3. no fsync before the rename, and a scratch left behind when the rename
     failed.

It now delegates to ``core.polled_json.atomic_write_bytes``. The bytes are the
downloaded body, unchanged. scripts/ sits outside the repo-wide guard
tests/test_atomic_write_guard_rm258_rm261.py (one-shot generator tree), so this
module carries its own source pin. No test touches the network: ``urlopen`` is
monkeypatched, and the transient failure is a monkeypatched ``os.replace``.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import polled_json  # noqa: E402


def _load():
    spec = importlib.util.spec_from_file_location(
        "cache_ddragon_assets_s144p19",
        ROOT / "scripts" / "cache_ddragon_assets.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


CDA = _load()

_NAME = "1001.png"
_BODY = b"\x89PNG\r\n\x1a\n-synthetic-icon-bytes-\r\n"


class _Resp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(CDA, "urlopen", lambda req, timeout=None: _Resp(_BODY))
    monkeypatch.setattr(CDA.time, "sleep", lambda _s: None)


def test_a_transient_permission_error_on_replace_is_retried(tmp_path, monkeypatch):
    target = tmp_path / _NAME
    real_replace = polled_json.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", flaky)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    assert CDA.fetch("https://example.invalid/x.png", target) is True
    assert target.read_bytes() == _BODY
    assert calls["n"] == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == [_NAME]


def test_an_exhausted_replace_leaves_no_scratch_and_no_target(tmp_path, monkeypatch):
    target = tmp_path / _NAME

    def always_denied(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json.os, "replace", always_denied)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        CDA.fetch("https://example.invalid/x.png", target)
    assert list(tmp_path.iterdir()) == []


def test_two_writes_of_one_icon_use_distinct_per_writer_scratch_names(
        tmp_path, monkeypatch):
    target = tmp_path / _NAME
    seen: list[str] = []
    real_replace = polled_json.os.replace

    def spy(src, dst):
        seen.append(pathlib.Path(src).name)
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", spy)
    assert CDA.fetch("https://example.invalid/x.png", target) is True
    target.unlink()
    assert CDA.fetch("https://example.invalid/x.png", target) is True
    assert len(seen) == 2
    assert seen[0] != seen[1]
    assert all(n.startswith(_NAME + ".") and n.endswith(".tmp")
               and n != _NAME + ".tmp" for n in seen)


def test_the_body_lands_byte_for_byte_and_the_parent_is_created(tmp_path):
    target = tmp_path / "web" / "data" / "ddragon" / "16.1.1" / "img" / "item" / _NAME
    assert CDA.fetch("https://example.invalid/x.png", target) is True
    assert target.read_bytes() == _BODY


def test_an_existing_non_empty_icon_is_skipped(tmp_path, monkeypatch):
    target = tmp_path / _NAME
    target.write_bytes(b"kept")

    def boom(*a, **k):
        raise AssertionError("fetch must not download an icon already present")

    monkeypatch.setattr(CDA, "urlopen", boom)
    assert CDA.fetch("https://example.invalid/x.png", target) is False
    assert target.read_bytes() == b"kept"


def test_the_writer_does_not_hand_roll_the_rename():
    """Source pin: fetch delegates instead of renaming itself."""
    src = (ROOT / "scripts" / "cache_ddragon_assets.py").read_text(encoding="utf-8")
    assert '".tmp"' not in src
    assert "tmp.replace(" not in src
    assert "from core.polled_json import atomic_write_bytes" in src
    assert CDA.atomic_write_bytes is polled_json.atomic_write_bytes
