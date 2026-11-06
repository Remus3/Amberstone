"""s144 true-audit cycle 153: agents/agent4_coach_mentor/ui_applier.py.

The applier writes dashboard source files from a ``ui-proposal`` task payload
(agents/supervisor.py dispatches it; agents/agent7_context/ui_feedback.py files
it, partly from an LLM answer). Every test here points the module at a tmp
project root, so nothing under the real web/ tree is touched.

Findings pinned (RM-1900..RM-1907):
- 433 a non-object payload raised AttributeError, not UIApplyError.
- 434 a non-list ``changes`` (int, bool, dict) raised TypeError out of the
  error message itself, or was misreported.
- 435 a non-str ``file`` raised AttributeError; ``_is_path_allowed`` (also
  called by ui_feedback on the LLM path) raised on a non-str / unhashable path.
- 436 a panel stem with non-ASCII letters or digits, or a Windows reserved
  device name (con, nul, aux, prn, com1, lpt1), passed the whitelist.
- 437 containment was checked against the PROJECT ROOT, so a link under a
  whitelisted dir that points elsewhere in the repo let a proposal overwrite
  a non-UI file.
- 438 the same target twice (or two case variants of it on Windows) was
  written twice, last one wins, reported twice.
- 439 a write failing part-way left the earlier files written (half-applied,
  despite the module's "never half-apply" claim) and escaped as a raw OSError.
- 440 a lone surrogate in content raised UnicodeEncodeError, not UIApplyError;
  a NUL byte was written; CRLF was written into an LF-only tree.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import agents.agent4_coach_mentor.ui_applier as ui_applier
from agents.agent4_coach_mentor.ui_applier import (
    UIApplyError,
    _is_path_allowed,
    apply_ui_proposal,
)


@pytest.fixture
def root(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(ui_applier, "_PROJECT_ROOT", tmp_path)
    (tmp_path / "web" / "js" / "panels").mkdir(parents=True)
    (tmp_path / "web" / "css" / "panels").mkdir(parents=True)
    return tmp_path


def _one(file, content="a { color: red; }\n"):
    return {"changes": [{"file": file, "content": content}]}


# -- characterization: the well-formed path is unchanged ----------------------

def test_well_formed_result_shape(root: Path) -> None:
    css = root / "web" / "css" / "panels" / "base.css"
    css.write_bytes(b"old\n")
    res = apply_ui_proposal({"changes": [
        {"file": "web/css/panels/base.css", "content": "new body\n"},
        {"file": "web/js/panels/foo_bar-1.js", "content": "export const x = {};\n"},
    ]})
    assert res["applied"] is True
    assert res["count"] == 2
    assert res["files"][0] == {
        "file": "web/css/panels/base.css",
        "prev_bytes": 4, "new_bytes": 9, "delta_bytes": 5,
    }
    assert res["files"][1]["prev_bytes"] is None
    assert res["files"][1]["new_bytes"] == len(b"export const x = {};\n")
    assert css.read_bytes() == b"new body\n"


def test_utf8_glyph_content_still_allowed(root: Path) -> None:
    # web/ carries live UI glyphs; the applier must not start refusing them.
    apply_ui_proposal(_one("web/css/panels/base.css", "a::after{content:'\u2610'}\n"))
    assert (root / "web/css/panels/base.css").read_bytes() == (
        "a::after{content:'\u2610'}\n".encode())


# -- RM-1900: payload shape -------------------------------------------------

@pytest.mark.parametrize("payload", [[1], "changes", 5, 1.5, True, ("a",)])
def test_non_object_payload_is_uiapplyerror(root: Path, payload) -> None:
    with pytest.raises(UIApplyError):
        apply_ui_proposal(payload)


def test_none_payload_is_uiapplyerror(root: Path) -> None:
    with pytest.raises(UIApplyError):
        apply_ui_proposal(None)


# -- RM-1901: changes shape -------------------------------------------------

@pytest.mark.parametrize("changes", [5, True, 2.5, {"file": "web/index.html"}, "ab"])
def test_non_list_changes_is_uiapplyerror(root: Path, changes) -> None:
    with pytest.raises(UIApplyError) as exc:
        apply_ui_proposal({"changes": changes})
    assert "list" in str(exc.value)


# -- RM-1902: non-str file --------------------------------------------------

@pytest.mark.parametrize("file", [5, ["web/index.html"], {"a": 1}, b"web/index.html", True])
def test_non_str_file_is_uiapplyerror(root: Path, file) -> None:
    with pytest.raises(UIApplyError):
        apply_ui_proposal(_one(file))


@pytest.mark.parametrize("value", [None, 5, ["web/index.html"], {"a": 1}, b"web/index.html"])
def test_is_path_allowed_never_raises_on_non_str(value) -> None:
    assert _is_path_allowed(value) is False


# -- RM-1903: stem charset + reserved device names --------------------------

@pytest.mark.parametrize("stem", [
    "caf\u00e9", "panel\u0661", "\uff41bc", "\u00b2x",
])
def test_non_ascii_stem_refused(root: Path, stem: str) -> None:
    rel = f"web/js/panels/{stem}.js"
    assert _is_path_allowed(rel) is False
    with pytest.raises(UIApplyError):
        apply_ui_proposal(_one(rel, "export const a = 1;\n"))


@pytest.mark.parametrize("stem", ["con", "NUL", "Aux", "prn", "com1", "LPT9"])
def test_reserved_device_stem_refused(stem: str) -> None:
    assert _is_path_allowed(f"web/css/panels/{stem}.css") is False


def test_ascii_stems_still_allowed() -> None:
    for rel in ("web/css/panels/base.css", "web/js/panels/a-b_C9.js",
                "web/js/panels/console.js", "web/css/panels/com10.css",
                "web/index.html", "web/js/main.js"):
        assert _is_path_allowed(rel) is True, rel


# -- RM-1904: link escape out of the whitelisted dir ------------------------

def _make_dir_link(link: Path, target: Path) -> None:
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def test_linked_panel_dir_cannot_redirect_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ui_applier, "_PROJECT_ROOT", tmp_path)
    coaches = tmp_path / "coaches"
    coaches.mkdir()
    victim = coaches / "evil.js"
    victim.write_bytes(b"ORIGINAL\n")
    (tmp_path / "web" / "js").mkdir(parents=True)
    _make_dir_link(tmp_path / "web" / "js" / "panels", coaches)
    assert (tmp_path / "web/js/panels/evil.js").read_bytes() == b"ORIGINAL\n"
    with pytest.raises(UIApplyError):
        apply_ui_proposal(_one("web/js/panels/evil.js", "export const p = 1;\n"))
    assert victim.read_bytes() == b"ORIGINAL\n"
    assert sorted(p.name for p in coaches.iterdir()) == ["evil.js"]


# -- RM-1905: duplicate targets ---------------------------------------------

def test_same_file_twice_refused(root: Path) -> None:
    css = root / "web/css/panels/base.css"
    css.write_bytes(b"orig\n")
    with pytest.raises(UIApplyError):
        apply_ui_proposal({"changes": [
            {"file": "web/css/panels/base.css", "content": "one\n"},
            {"file": "web/css/panels/base.css", "content": "two\n"},
        ]})
    assert css.read_bytes() == b"orig\n"


@pytest.mark.skipif(sys.platform != "win32", reason="case-insensitive FS only")
def test_case_variant_twice_refused_on_windows(root: Path) -> None:
    css = root / "web/css/panels/base.css"
    css.write_bytes(b"orig\n")
    with pytest.raises(UIApplyError):
        apply_ui_proposal({"changes": [
            {"file": "web/css/panels/base.css", "content": "one\n"},
            {"file": "web/css/panels/BASE.css", "content": "two\n"},
        ]})
    assert css.read_bytes() == b"orig\n"


# -- RM-1906: rollback on a part-way write failure --------------------------

def test_partway_write_failure_rolls_back(root: Path, monkeypatch) -> None:
    a = root / "web/css/panels/a.css"
    a.write_bytes(b"A-ORIG\n")
    real = ui_applier._atomic_write
    calls: list[str] = []

    def flaky(target: Path, content: bytes) -> None:
        calls.append(target.name)
        if target.name == "c.css":
            raise PermissionError(13, "locked by a reader")
        real(target, content)

    monkeypatch.setattr(ui_applier, "_atomic_write", flaky)
    with pytest.raises(UIApplyError) as exc:
        apply_ui_proposal({"changes": [
            {"file": "web/css/panels/a.css", "content": "A-NEW\n"},
            {"file": "web/css/panels/b.css", "content": "B-NEW\n"},
            {"file": "web/css/panels/c.css", "content": "C-NEW\n"},
        ]})
    assert "c.css" in str(exc.value)
    assert isinstance(exc.value.__cause__, OSError)
    assert a.read_bytes() == b"A-ORIG\n"            # restored
    assert not (root / "web/css/panels/b.css").exists()  # created, then removed
    assert not (root / "web/css/panels/c.css").exists()
    assert calls[:3] == ["a.css", "b.css", "c.css"]


def test_target_that_is_a_directory_refused_before_any_write(root: Path) -> None:
    a = root / "web/css/panels/a.css"
    a.write_bytes(b"A-ORIG\n")
    (root / "web/css/panels/d.css").mkdir()
    with pytest.raises(UIApplyError, match="not a regular file"):
        apply_ui_proposal({"changes": [
            {"file": "web/css/panels/a.css", "content": "A-NEW\n"},
            {"file": "web/css/panels/d.css", "content": "D\n"},
        ]})
    assert a.read_bytes() == b"A-ORIG\n"


# -- RM-1907: content bytes -------------------------------------------------

def test_lone_surrogate_is_uiapplyerror(root: Path) -> None:
    with pytest.raises(UIApplyError):
        apply_ui_proposal(_one("web/css/panels/base.css", "a{}\ud800\n"))
    assert not (root / "web/css/panels/base.css").exists()


def test_nul_byte_refused(root: Path) -> None:
    with pytest.raises(UIApplyError):
        apply_ui_proposal(_one("web/css/panels/base.css", "a{}\x00\n"))
    assert not (root / "web/css/panels/base.css").exists()


def test_crlf_and_cr_written_as_lf(root: Path) -> None:
    res = apply_ui_proposal(_one("web/css/panels/base.css", "a{}\r\nb{}\rc{}\n"))
    assert (root / "web/css/panels/base.css").read_bytes() == b"a{}\nb{}\nc{}\n"
    assert res["files"][0]["new_bytes"] == len(b"a{}\nb{}\nc{}\n")
