"""RM-447: atomic writers must not strand a ``.tmp`` on failure, and must not
derive colliding temp names for same-stem outputs.

THE DEFECT
----------
Six write-then-replace sites wrote a sibling temp file and then renamed it
over the target with no cleanup when either step raised:

    scripts/data_pipeline.py        _atomic_write_text, _write_bytes,
                                    cmd_rank_tiers
    scripts/merge_refresh_builds.py _write_json_lf
    tools/gen_state_schema.py       main
    tools/hz_mismatch_diagnose.py   write_markdown

A disk-full write or a share-locked rename left ``<name>.tmp`` behind as an
untracked file. Separately ``_atomic_write_text`` built its temp path with
``with_suffix(".tmp")``, which DROPS the real suffix, so ``a.json`` and
``a.md`` both wrote through ``a.tmp``.

HOW THE FAULT IS INJECTED (PORTABLY)
------------------------------------
No held-handle trick (see tests/test_atomic_write_fault_injection_is_portable).
The ``Path`` write methods are patched to write a PARTIAL temp file and then
raise, which is what a disk-full write actually leaves behind; the rename arm
patches ``Path.replace`` to raise for a ``.tmp`` source. Both arms count their
firings and every test asserts the fault FIRED, so a writer that routes around
the patched boundary fails loudly instead of passing vacuously. Nothing here
depends on the host OS.

Every path is redirected into ``tmp_path``; no network, no real repo file.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

import scripts.data_pipeline as dp
import scripts.merge_refresh_builds as mrb
import tools.gen_state_schema as gss
import tools.hz_mismatch_diagnose as hmd

from tests._replace_faults import scoped_path_fault

_REAL_WRITE_BYTES = pathlib.Path.write_bytes


class _Fault:
    def __init__(self) -> None:
        self.fired = 0


# RM-464: a ``.tmp`` NAME is not a scope - every atomic writer in the tree
# writes a ``*.tmp`` scratch, so a class-level patch keyed on the suffix alone
# faulted any such write anywhere in the process. Both arms are now scoped to
# ``tmp_path`` by scoped_path_fault (armed control outside it); the ``.tmp``
# check still selects WHICH in-scope write fails. ``expect_fire=False`` because
# each test asserts ``fault.fired`` itself and a writer uses only one of
# write_bytes / write_text.

@pytest.fixture
def write_fails(tmp_path):
    """A temp-file write lands HALF its payload on disk, then raises."""
    fault = _Fault()

    def _write_bytes(real, self, data):
        if self.name.endswith(".tmp"):
            _REAL_WRITE_BYTES(self, data[: max(1, len(data) // 2)])
            fault.fired += 1
            raise OSError(28, "No space left on device (injected)")
        return real(self, data)

    def _write_text(real, self, data, *args, **kwargs):
        if self.name.endswith(".tmp"):
            _REAL_WRITE_BYTES(self, data[: max(1, len(data) // 2)].encode("utf-8"))
            fault.fired += 1
            raise OSError(28, "No space left on device (injected)")
        return real(self, data, *args, **kwargs)

    with scoped_path_fault("write_bytes", tmp_path, _write_bytes, expect_fire=False), \
            scoped_path_fault("write_text", tmp_path, _write_text, expect_fire=False):
        yield fault


@pytest.fixture
def replace_fails(tmp_path):
    """The temp write succeeds; renaming it over the target raises."""
    fault = _Fault()

    def _replace(real, self, target):
        if self.name.endswith(".tmp"):
            fault.fired += 1
            raise PermissionError(5, "Access is denied (injected)")
        return real(self, target)

    with scoped_path_fault("replace", tmp_path, _replace, expect_fire=False):
        yield fault


@pytest.fixture(params=["write", "replace"])
def fault(request):
    return request.getfixturevalue(f"{request.param}_fails")


def _assert_clean_failure(excinfo, fault, directory, target, original: bytes):
    assert fault.fired >= 1, "injected fault never fired - test would be vacuous"
    assert isinstance(excinfo.value, OSError)
    leftovers = sorted(p.name for p in directory.iterdir() if p.name.endswith(".tmp"))
    assert leftovers == [], f"stranded temp files: {leftovers}"
    assert target.read_bytes() == original, "target must be untouched on failure"


_ORIGINAL = b'{"previous": true}\n'


# -- failure path: no stranded temp, error propagates, target intact -------------

def test_data_pipeline_atomic_write_text_cleans_up(tmp_path, fault):
    target = tmp_path / "ddragon_items.json"
    target.write_bytes(_ORIGINAL)
    with pytest.raises(OSError) as excinfo:
        dp._atomic_write_text(target, json.dumps({"new": 1}, indent=2))
    _assert_clean_failure(excinfo, fault, tmp_path, target, _ORIGINAL)


def test_data_pipeline_write_bytes_cleans_up(tmp_path, fault):
    target = tmp_path / "icon.png"
    target.write_bytes(_ORIGINAL)
    with pytest.raises(OSError) as excinfo:
        dp._write_bytes(target, b"\x89PNG" * 64)
    _assert_clean_failure(excinfo, fault, tmp_path, target, _ORIGINAL)


def test_data_pipeline_rank_tiers_cleans_up(tmp_path, monkeypatch, fault):
    rt = tmp_path / "rank_tiers"
    rt.mkdir()
    seed = rt / "rank_tier_averages.seed.json"
    live = rt / "rank_tier_averages.json"
    _REAL_WRITE_BYTES(seed, json.dumps({"schema": 1, "patch": "1.1.1", "tiers": {}}).encode())
    live.write_bytes(_ORIGINAL)
    monkeypatch.setattr(dp, "RANK_TIERS_DIR", rt)
    monkeypatch.setattr(dp, "RANK_TIERS_SEED", seed)
    monkeypatch.setattr(dp, "RANK_TIERS_LIVE", live)
    monkeypatch.setattr(dp, "_get_live_version", lambda: "99.1.1")
    with pytest.raises(OSError) as excinfo:
        dp.cmd_rank_tiers(force=True)
    _assert_clean_failure(excinfo, fault, rt, live, _ORIGINAL)


def test_merge_refresh_builds_write_json_lf_cleans_up(tmp_path, fault):
    target = tmp_path / "aram_champion_builds.json"
    target.write_bytes(_ORIGINAL)
    with pytest.raises(OSError) as excinfo:
        mrb._write_json_lf(target, {"Ahri": {"core": ["Luden's Echo"]}})
    _assert_clean_failure(excinfo, fault, tmp_path, target, _ORIGINAL)


def test_gen_state_schema_main_cleans_up(tmp_path, monkeypatch, fault):
    out = tmp_path / "state_schema.js"
    out.write_bytes(_ORIGINAL)
    monkeypatch.setattr(gss, "ROOT", tmp_path)
    monkeypatch.setattr(gss, "OUTPUT", out)
    monkeypatch.setattr(gss, "_generate", lambda: "export const X = 1;\n" * 8)
    monkeypatch.setattr(sys, "argv", ["gen_state_schema.py"])
    with pytest.raises(OSError) as excinfo:
        gss.main()
    _assert_clean_failure(excinfo, fault, tmp_path, out, _ORIGINAL)


def test_hz_mismatch_write_markdown_cleans_up(tmp_path, monkeypatch, fault):
    target = tmp_path / "report.md"
    target.write_bytes(_ORIGINAL)
    monkeypatch.setattr(hmd, "render_markdown", lambda report: "# report\n\nbody\n")
    with pytest.raises(OSError) as excinfo:
        hmd.write_markdown({}, target)
    _assert_clean_failure(excinfo, fault, tmp_path, target, _ORIGINAL)


# -- temp naming: same stem, different suffix -> distinct temp paths --------------

@pytest.fixture
def temp_spy(monkeypatch):
    seen: list[pathlib.Path] = []

    def _write_bytes(self, data):
        if self.name.endswith(".tmp"):
            seen.append(self)
        return _REAL_WRITE_BYTES(self, data)

    monkeypatch.setattr(pathlib.Path, "write_bytes", _write_bytes)
    return seen


_PATH_WRITERS = [
    ("data_pipeline._atomic_write_text", lambda p: dp._atomic_write_text(p, "x\n")),
    ("data_pipeline._write_bytes", lambda p: dp._write_bytes(p, b"x\n")),
    ("merge_refresh_builds._write_json_lf", lambda p: mrb._write_json_lf(p, {"x": 1})),
]


@pytest.mark.parametrize("writer", [w for _, w in _PATH_WRITERS],
                         ids=[name for name, _ in _PATH_WRITERS])
def test_same_stem_outputs_get_distinct_temp_paths(tmp_path, temp_spy, writer):
    writer(tmp_path / "a.json")
    writer(tmp_path / "a.md")
    assert [p.name for p in temp_spy] == ["a.json.tmp", "a.md.tmp"]
    assert all(p.parent == tmp_path for p in temp_spy), "temp must share the target dir"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json", "a.md"]


def test_hz_write_markdown_temp_keeps_full_name(tmp_path, monkeypatch, temp_spy):
    monkeypatch.setattr(hmd, "render_markdown", lambda report: "# r\n")
    hmd.write_markdown({}, tmp_path / "a.md")
    hmd.write_markdown({}, tmp_path / "a.txt")
    assert [p.name for p in temp_spy] == ["a.md.tmp", "a.txt.tmp"]


# -- success path: bytes unchanged ----------------------------------------------

def test_success_path_bytes_are_lf_and_exact(tmp_path):
    target = tmp_path / "a.json"
    dp._atomic_write_text(target, '{\n  "a": 1\n}')
    assert target.read_bytes() == b'{\n  "a": 1\n}'
    mrb._write_json_lf(tmp_path / "b.json", {"a": 1})
    assert (tmp_path / "b.json").read_bytes() == b'{\n  "a": 1\n}'
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json", "b.json"]
