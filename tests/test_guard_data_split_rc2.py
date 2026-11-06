"""MAIN ORDER item RC-2: the split guard data fails loudly, never passes empty.

Would an empty enumeration pass? Each loader case below answers no on a real
copy of the tree's data under tmp_path: no areas declared, a missing area file,
an empty area file, an undeclared file, a duplicate row and a row in the wrong
area all raise. Declaration and listing order change nothing.

Data under test: tests/guard_data/web_live_half/ and tests/guard_data/atomic_write/.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests import guard_data
from tests.guard_data import GuardDataError, atomic_write, web_live_half
from tests.test_atomic_write_guard_rm258_rm261 import (
    _EXCLUDED_PREFIXES,
    _RUNTIME_TOOLS,
    _TOOLS_UNCLASSIFIED,
    SANCTIONED,
)
from tests.test_web_ascii_sweep import _LIVE_HALF_ROWS
from tools import ci_impact_selector as sel

_REPO = Path(__file__).resolve().parent.parent
_LOADERS = {"web_live_half": web_live_half, "atomic_write": atomic_write}


def _copy(tmp_path: Path, name: str) -> Path:
    target = tmp_path / name
    shutil.copytree(_LOADERS[name].HERE, target,
                    ignore=shutil.ignore_patterns("__pycache__", "__init__.py"))
    return target


@pytest.fixture(params=sorted(_LOADERS))
def data(request, tmp_path):
    """(loader module, a real copy of its data)."""
    return _LOADERS[request.param], _copy(tmp_path, request.param)


def _an_area(mod) -> str:
    return sorted(mod.AREAS)[0]


def test_a_real_copy_loads_the_same_rows_as_the_tree(data):
    mod, copy = data
    assert mod.load(copy) == mod.load()


def test_no_declared_area_fails(data):
    mod, copy = data
    with pytest.raises(GuardDataError, match="no areas declared"):
        mod.load(copy, areas={})


def test_an_empty_data_directory_fails(data, tmp_path):
    mod, _copy_dir = data
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(GuardDataError, match="missing"):
        mod.load(empty)


def test_a_missing_data_directory_fails(data, tmp_path):
    mod, _copy_dir = data
    with pytest.raises(GuardDataError, match="missing"):
        mod.load(tmp_path / "absent")


def test_a_missing_area_file_fails(data):
    mod, copy = data
    (copy / (_an_area(mod) + mod.SUFFIX)).unlink()
    with pytest.raises(GuardDataError, match="missing"):
        mod.load(copy)


@pytest.mark.parametrize("body", [b"", b"# only a comment\n"])
def test_an_area_file_with_no_rows_fails(data, body):
    mod, copy = data
    (copy / (_an_area(mod) + mod.SUFFIX)).write_bytes(body)
    with pytest.raises(GuardDataError):
        mod.load(copy)


def test_an_empty_literal_area_fails(tmp_path):
    copy = _copy(tmp_path, "atomic_write")
    (copy / "runtime_tools.py").write_bytes(b"ROWS = {'tools/x.py'}\n")
    atomic_write.load(copy)
    (copy / "runtime_tools.py").write_bytes(b"ROWS = set()\n")
    with pytest.raises(GuardDataError):
        atomic_write.load(copy)
    (copy / "runtime_tools.py").write_bytes(b"ROWS = {}\n")
    with pytest.raises(GuardDataError):
        atomic_write.load(copy)


@pytest.mark.parametrize("name", ["zz_new_area.txt", "zz_new_area.py", "zz_new_area.json"])
def test_a_data_file_no_area_declares_fails(data, name):
    mod, copy = data
    (copy / name).write_bytes(b"ROWS = {'tools/x.py'}\n")
    with pytest.raises(GuardDataError, match="no loader reads"):
        mod.load(copy)


def test_a_subdirectory_of_data_fails(data):
    mod, copy = data
    (copy / "nested").mkdir()
    with pytest.raises(GuardDataError, match="unexpected directory"):
        mod.load(copy)


def test_listing_and_declaration_order_change_nothing(data, monkeypatch):
    mod, copy = data
    want = mod.load(copy)
    real = guard_data._list_dir
    monkeypatch.setattr(guard_data, "_list_dir", lambda d: sorted(real(d), reverse=True))
    assert mod.load(copy) == want
    assert mod.load(copy, areas=dict(reversed(list(mod.AREAS.items())))) == want


def test_every_guard_directory_is_declared():
    found = {p.name for p in guard_data.ROOT.iterdir()
             if p.is_dir() and p.name != "__pycache__"}
    assert found == set(guard_data.GUARDS) == set(_LOADERS)
    loose = {p.name for p in guard_data.ROOT.iterdir()
             if p.is_file() and p.name != "__init__.py"}
    assert loose == set()


# web_live_half rows.

_HEX = "a" * 64


def _web_row(rel: str, digest: str = _HEX) -> bytes:
    return f"{digest}  {rel}\n".encode()


def test_web_real_data_is_not_a_trivial_set():
    rows = web_live_half.load()
    assert rows == _LIVE_HALF_ROWS
    for anchor in ("web/js/main.js", "web/css/panels/header.css", "web/index.html"):
        assert anchor in rows
    for stem, prefix in web_live_half.AREAS.items():
        assert any(web_live_half.area_for(rel) == stem for rel in rows), stem
        assert prefix.startswith("web/")


@pytest.mark.parametrize("rel, area", [
    ("web/js/main.js", "js_main"),
    ("web/js/panels/champ_select.js", "js_champ_select"),
    ("web/js/panels/dev.js", "js_panels"),
    ("web/js/other.js", "js_other"),
    ("web/css/panels/header.css", "css_header"),
    ("web/css/panels/home.css", "css_panels"),
    ("web/css/tokens.css", "css_other"),
    ("web/a_new_dir/x.js", "web_other"),
])
def test_web_area_is_the_longest_prefix_whatever_the_declared_order(rel, area):
    assert web_live_half.area_for(rel) == area
    flipped = dict(reversed(list(web_live_half.AREAS.items())))
    assert web_live_half.area_for(rel, flipped) == area


def test_web_row_outside_web_has_no_area():
    with pytest.raises(GuardDataError):
        web_live_half.area_for("core/polled_json.py")


def test_web_row_in_the_wrong_area_fails(tmp_path):
    copy = _copy(tmp_path, "web_live_half")
    (copy / "js_lib.txt").write_bytes(_web_row("web/js/main.js"))
    with pytest.raises(GuardDataError, match="belongs in area"):
        web_live_half.load(copy)


def test_web_duplicate_row_fails(tmp_path):
    copy = _copy(tmp_path, "web_live_half")
    row = _web_row("web/js/lib/zz_dup.js")
    (copy / "js_lib.txt").write_bytes(row + row)
    with pytest.raises(GuardDataError, match="duplicate"):
        web_live_half.load(copy)


@pytest.mark.parametrize("body", [
    b"not a row\n",
    b"abc  web/js/lib/x.js\n",
    _web_row("web/js/lib/x.js").replace(b"\n", b"\r\n"),
    _web_row("web/js/lib/x\xe9.js"),
])
def test_web_malformed_row_fails(tmp_path, body):
    copy = _copy(tmp_path, "web_live_half")
    (copy / "js_lib.txt").write_bytes(body)
    with pytest.raises(GuardDataError):
        web_live_half.load(copy)


def test_web_drift_names_each_kind_of_difference():
    pinned = {"web/a.js": _HEX, "web/gone.js": _HEX, "web/same.js": _HEX}
    actual = {"web/a.js": "b" * 64, "web/new.js": _HEX, "web/same.js": _HEX}
    assert web_live_half.drift_lines(actual, pinned) == [
        "no row (new source): web/new.js",
        "stale row (source gone): web/gone.js",
        "live half changed: web/a.js",
    ]
    assert web_live_half.drift_lines({}, pinned) != []
    assert web_live_half.drift_lines(pinned, pinned) == []


def test_web_render_round_trips_the_real_files(tmp_path):
    rows = web_live_half.load()
    for stem in web_live_half.AREAS:
        path = web_live_half.HERE / (stem + web_live_half.SUFFIX)
        assert web_live_half.render_area(stem, rows) == path.read_bytes(), stem
    target = tmp_path / "out"
    target.mkdir()
    assert len(web_live_half.write_areas(rows, target)) == len(web_live_half.AREAS)
    assert web_live_half.load(target) == rows
    assert web_live_half.write_areas(rows, target) == []


def test_web_render_refuses_an_area_with_no_rows():
    with pytest.raises(GuardDataError):
        web_live_half.render_area("js_main", {"web/js/lib/x.js": _HEX})


# atomic_write rows.

def test_atomic_guard_reads_the_real_rows():
    real = atomic_write.load()
    assert real.sanctioned == SANCTIONED
    assert real.runtime_tools == _RUNTIME_TOOLS
    assert real.tools_unclassified == _TOOLS_UNCLASSIFIED
    assert real.excluded_prefixes == _EXCLUDED_PREFIXES
    assert ("core/polled_json.py", "_replace_with_retry") in SANCTIONED
    assert ("ops/launcher/service_host.py", "HostLog.write") in SANCTIONED
    assert ("tools/shadow_archive_split.py", "_swap_in") in SANCTIONED
    assert "tools/lcu_agent.py" in _RUNTIME_TOOLS
    assert "ops/fleet_kit/" in _EXCLUDED_PREFIXES


def test_atomic_duplicate_inside_one_literal_fails(tmp_path):
    copy = _copy(tmp_path, "atomic_write")
    (copy / "runtime_tools.py").write_bytes(b"ROWS = {'tools/a.py', 'tools/a.py'}\n")
    with pytest.raises(GuardDataError, match="duplicate"):
        atomic_write.load(copy)


def test_atomic_duplicate_across_areas_fails(tmp_path):
    copy = _copy(tmp_path, "atomic_write")
    row = b"ROWS = {('core/x.py', 'f'): 'why'}\n"
    (copy / "sanctioned_core.py").write_bytes(row)
    areas = {**atomic_write.AREAS, "sanctioned_two": (atomic_write.SANCTIONED, "core/")}
    (copy / "sanctioned_two.py").write_bytes(row)
    with pytest.raises(GuardDataError, match="another area"):
        atomic_write.load(copy, areas=areas)


@pytest.mark.parametrize("stem, body", [
    ("sanctioned_core", b"ROWS = {('tools/x.py', 'f'): 'why'}\n"),
    ("sanctioned_core", b"ROWS = {('core/x.py', 'f'): ''}\n"),
    ("sanctioned_core", b"ROWS = {'core/x.py': 'why'}\n"),
    ("sanctioned_core", b"ROWS = {'core/x.py'}\n"),
    ("runtime_tools", b"ROWS = {'core/x.py'}\n"),
    ("runtime_tools", b"ROWS = {'tools/x.py': 'why'}\n"),
    ("tools_unclassified", b"ROWS = {'lib/x.py'}\n"),
    ("runtime_tools", b"OTHER = {'tools/x.py'}\n"),
    ("runtime_tools", b"ROWS = frozenset({'tools/x.py'})\n"),
])
def test_atomic_misplaced_or_malformed_row_fails(tmp_path, stem, body):
    copy = _copy(tmp_path, "atomic_write")
    (copy / (stem + ".py")).write_bytes(body)
    with pytest.raises(GuardDataError):
        atomic_write.load(copy)


def test_atomic_a_required_kind_with_no_area_fails(tmp_path):
    copy = _copy(tmp_path, "atomic_write")
    (copy / "excluded_prefixes.py").unlink()
    areas = {k: v for k, v in atomic_write.AREAS.items() if k != "excluded_prefixes"}
    with pytest.raises(GuardDataError, match="no excluded_prefixes rows"):
        atomic_write.load(copy, areas=areas)


def test_atomic_tools_unclassified_may_retire_with_its_area(tmp_path):
    """It only shrinks: the emptied baseline is removed, not left as a switch."""
    copy = _copy(tmp_path, "atomic_write")
    (copy / "tools_unclassified.py").unlink()
    areas = {k: v for k, v in atomic_write.AREAS.items() if k != "tools_unclassified"}
    assert atomic_write.load(copy, areas=areas).tools_unclassified == frozenset()


# The CI impact selector must still run a guard when only its data changes.

@pytest.mark.parametrize("changed, guard", [
    ("tests/guard_data/web_live_half/js_main.txt", "tests/test_web_ascii_sweep.py"),
    ("tests/guard_data/atomic_write/sanctioned_ops.py",
     "tests/test_atomic_write_guard_rm258_rm261.py"),
])
def test_a_data_only_change_selects_its_guard(changed, guard):
    out = sel.select_impacted([changed], sel.git_tracked(_REPO) + [changed], sel.disk_reader(_REPO))
    assert guard in out.modules, (out.mode, out.detail, len(out.modules))
