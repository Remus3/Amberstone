"""S144-D-244..247 - the eleven roster fan-out builders are one-shot, say so,
refuse a re-run before writing anything, and never land a partial block.

WHY. Each fan-out axis (items 294-309) shipped ``tools/ds_<axis>_build.py``:
it validates a workflow JSON, splices ``add(...)`` calls into
``agents/daemon_slayer/<axis>.py`` at the ``    # <ENTRIES>`` marker and
rewrites ``<axis>_registry_notes.json``. The splice CONSUMES the marker, and
no shipped module carries it any more, so every re-run stops with
"marker ... not found (already injected?)". Measured 2026-11-09 (patch
16.22.1, ENGINE 1.291.0), all eleven builders:

* S144-D-244. Every builder docstring said "Reusable as a drift-guard
  re-build when the roster scan is re-run" - false: a re-run refuses. The
  docstrings now say the builder is one-shot and how a re-seeded re-run
  behaves (it drops every later hand edit to the registry).
* S144-D-245. A builder that found PROBLEMS still wrote the module and the
  sidecar and exited 0, so a bad fan-out row was silently dropped and a
  partial ``add(...)`` block landed in a tracked engine module (cc_output
  with one bad row wrote an EMPTY block and a count-0 sidecar, exit 0). Each
  builder now fails closed: it prints the problems and exits 2 before any
  write. Alternative rejected: write, then exit non-zero (the partial block
  would still land).
* S144-D-246. The refusal is pinned: against the shipped module every
  builder exits with the marker error and leaves both files byte-unchanged.
  A positive control re-seeds the marker in a tmp copy and shows the same
  builder DOES splice one entry from its own sidecar, so the refusal test
  is not vacuous.
* S144-D-247. Eighteen comments in the eleven ``test_<axis>_item*.py``
  files said "re-running tools/ds_<axis>_build.py against a fresh scan
  updates these" - false for the same reason; they now say the builder is
  one-shot.

All builder runs here write only under tmp_path (MODULE / NOTES are
monkeypatched); no tracked file is touched.
"""

from __future__ import annotations

import ast
import contextlib
import importlib
import io
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

import pytest

ROOT = Path(__file__).resolve().parents[3]
DS_DIR = ROOT / "agents" / "daemon_slayer"
TESTS_DIR = DS_DIR / "tests"
TOOLS_DIR = ROOT / "tools"

AXES = (
    "allyamp",
    "antitank",
    "cc_output",
    "extendedduel",
    "mobility",
    "objdamage",
    "scaling",
    "sustain",
    "threatrange",
    "waveclear",
    "zonecontrol",
)
MARKER = "    # <ENTRIES>"
FALSE_DOC_CLAIM = "Reusable as a drift-guard re-build"
FALSE_TEST_CLAIM = re.compile(
    r"re-running\s+tools/ds_\w+_build\.py\s+against\s+a\s+fresh\s+scan\s+updates",
    re.IGNORECASE,
)


def _builder(axis: str) -> ModuleType:
    return importlib.import_module(f"tools.ds_{axis}_build")


def _sidecar_entries(axis: str) -> list[dict[str, Any]]:
    path = DS_DIR / f"{axis}_registry_notes.json"
    return json.loads(path.read_text(encoding="utf-8"))["entries"]


def _workflow_entry(axis: str) -> dict[str, Any]:
    """The first sidecar entry, in the workflow-JSON shape its builder reads."""
    entry = dict(_sidecar_entries(axis)[0])
    if axis == "cc_output":
        # The cc_output builder reads the fan-out's max_rank_duration_s and
        # writes it to the sidecar as duration_s.
        entry["max_rank_duration_s"] = entry.pop("duration_s")
    return entry


def _bad_entry(axis: str) -> dict[str, Any]:
    entry = _workflow_entry(axis)
    entry["champion"] = "Zz_NotAChampion"
    entry["cc_kind" if axis == "cc_output" else "kind"] = "NOT_A_KIND"
    return entry


def _run(
    axis: str,
    module_text: str,
    entries: list[dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Optional[object], str, str, str]:
    """Run one builder's main() against tmp copies; return
    (exit code or None, stdout, module text after, sidecar text after)."""
    builder = _builder(axis)
    mod = tmp_path / f"{axis}.py"
    notes = tmp_path / f"{axis}_registry_notes.json"
    workflow = tmp_path / "workflow.json"
    mod.write_bytes(module_text.encode("utf-8"))
    notes.write_bytes(b"SENTINEL\n")
    workflow.write_bytes(json.dumps({"entries": entries}).encode("utf-8"))
    monkeypatch.setattr(builder, "MODULE", mod)
    monkeypatch.setattr(builder, "NOTES", notes)
    monkeypatch.setattr(sys, "argv", ["builder", str(workflow)])
    out = io.StringIO()
    code: Optional[object] = None
    with contextlib.redirect_stdout(out):
        try:
            builder.main()
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
    return (
        code,
        out.getvalue(),
        mod.read_bytes().decode("utf-8"),
        notes.read_bytes().decode("utf-8"),
    )


def _docstring(axis: str) -> str:
    tree = ast.parse((TOOLS_DIR / f"ds_{axis}_build.py").read_text(encoding="utf-8"))
    return ast.get_docstring(tree) or ""


# --- S144-D-246: the marker is consumed and a re-run refuses -------------


@pytest.mark.parametrize("axis", AXES)
def test_builder_marker_is_the_one_this_guard_checks(axis: str) -> None:
    src = (TOOLS_DIR / f"ds_{axis}_build.py").read_text(encoding="utf-8")
    assert f'marker = "{MARKER}"' in src


@pytest.mark.parametrize("axis", AXES)
def test_shipped_module_no_longer_carries_the_marker(axis: str) -> None:
    builder = _builder(axis)
    assert Path(builder.MODULE) == DS_DIR / f"{axis}.py"
    assert Path(builder.NOTES) == DS_DIR / f"{axis}_registry_notes.json"
    assert MARKER not in Path(builder.MODULE).read_text(encoding="utf-8")


@pytest.mark.parametrize("axis", AXES)
def test_rerun_against_shipped_module_refuses_before_any_write(
    axis: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipped = (DS_DIR / f"{axis}.py").read_bytes().decode("utf-8")
    code, _out, mod_after, notes_after = _run(
        axis, shipped, [_workflow_entry(axis)], tmp_path, monkeypatch
    )
    assert isinstance(code, str) and "marker" in code and "not found" in code
    assert mod_after == shipped
    assert notes_after == "SENTINEL\n"


@pytest.mark.parametrize("axis", AXES)
def test_reseeded_marker_positive_control_splices_one_entry(
    axis: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = "HEAD = 1\n" + MARKER + "\nTAIL = 2\n"
    entry = _workflow_entry(axis)
    code, out, mod_after, notes_after = _run(
        axis, seeded, [entry], tmp_path, monkeypatch
    )
    assert code in (None, 0), out
    assert "PROBLEMS=0" in out
    assert MARKER not in mod_after
    assert mod_after.startswith("HEAD = 1\n") and mod_after.endswith("\nTAIL = 2\n")
    assert f'    add("{entry["champion"]}", ' in mod_after
    notes = json.loads(notes_after)
    assert notes["count"] == 1 and len(notes["entries"]) == 1
    assert notes["entries"][0]["champion"] == entry["champion"]


# --- S144-D-245: PROBLEMS fail closed, nothing written --------------------


@pytest.mark.parametrize("axis", AXES)
def test_problems_fail_closed_before_any_write(
    axis: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = "HEAD = 1\n" + MARKER + "\nTAIL = 2\n"
    code, out, mod_after, notes_after = _run(
        axis,
        seeded,
        [_workflow_entry(axis), _bad_entry(axis)],
        tmp_path,
        monkeypatch,
    )
    assert code == 2, out
    assert "PROBLEMS=1" in out
    assert "Zz_NotAChampion" in out
    assert mod_after == seeded
    assert notes_after == "SENTINEL\n"


@pytest.mark.parametrize("axis", AXES)
def test_only_problem_rows_fail_closed_with_no_empty_block(
    axis: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The measured worst case: every row bad used to write an EMPTY block."""
    seeded = "HEAD = 1\n" + MARKER + "\nTAIL = 2\n"
    code, _out, mod_after, notes_after = _run(
        axis, seeded, [_bad_entry(axis)], tmp_path, monkeypatch
    )
    assert code == 2
    assert mod_after == seeded
    assert notes_after == "SENTINEL\n"


# --- S144-D-244: the builder docstrings tell the truth --------------------


@pytest.mark.parametrize("axis", AXES)
def test_builder_docstring_says_one_shot(axis: str) -> None:
    doc = _docstring(axis)
    assert FALSE_DOC_CLAIM not in doc
    flat = " ".join(doc.split())
    assert "One-shot" in flat
    assert "already injected?" in flat
    assert "S144-D-244" in flat
    assert "exits 2" in flat


# --- S144-D-247: the item tests do not repeat the false claim -------------


def _item_test_files() -> list[Path]:
    files = sorted(TESTS_DIR.glob("test_*_item29*.py")) + sorted(
        TESTS_DIR.glob("test_*_item30*.py")
    )
    return [p for p in files if re.search(r"ds_\w+_build", p.read_text(encoding="utf-8"))]


def _flatten_comments(text: str) -> str:
    return re.sub(r"\n[ \t]*#[ \t]*", " ", text)


def test_item_test_files_are_the_eleven_axes() -> None:
    names = {p.name.split("_item")[0][len("test_"):] for p in _item_test_files()}
    assert names == set(AXES)


@pytest.mark.parametrize("path", _item_test_files(), ids=lambda p: p.name)
def test_item_test_comments_do_not_claim_a_rerun_updates_pins(path: Path) -> None:
    flat = _flatten_comments(path.read_text(encoding="utf-8"))
    assert not FALSE_TEST_CLAIM.search(flat)
    assert "one-shot" in flat


def test_false_test_claim_pattern_is_live() -> None:
    planted = (
        "        # 8 PROTECT mechanisms. Re-running\n"
        "        # tools/ds_allyamp_build.py against a fresh scan updates these.\n"
    )
    assert FALSE_TEST_CLAIM.search(_flatten_comments(planted))
