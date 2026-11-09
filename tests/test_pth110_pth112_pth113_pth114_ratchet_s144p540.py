"""S144-P-540 - ruff PTH110 / PTH112 / PTH113 / PTH114 held at a named baseline.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): 32 findings (``os.path.exists`` / ``isdir`` /
``isfile`` / ``islink`` on a string path). Sixteen became pathlib in eight modules: ``tools/perseus_sync.py`` (four, the
vault binary, memory dir, LEDGER and ROADMAP / BACKLOG probes), ``tools/freeze_witness.py`` (three, the pruned walk's
symlink and regular-file checks), ``ops/audit/opponent_prior_gonogo.py``, ``tools/live_write_tracer.py``,
``core/vision_tesseract.py`` (two), ``tft/cv/ocr_fields.py`` (two), ``vision_server/_inference.py`` (two) and
``tools/precommit_gate.py``. Each is the same predicate on the same string (``Path(p).is_file()`` follows links exactly as
``os.path.isfile`` does), so no behaviour moves.

Fifteen sites stay baselined (one more is fenced, below), each in a file this slice does not take: ``tools/perseus_recall.py`` (its test binds
``os.path.exists`` on the module through ``tests._module_view.bind_os_path``, a seam this slice does not rewrite),
``dashboard/routes_recordings.py`` (``_is_link`` also consults ``os.path.isjunction``, one idiom family), ``ops/launcher/``
(PKG-owned), ``ops/migrate/e_move_helpers.py`` (one-shot migration owner's string handling) and eight test sites that
probe relative or Linux-only strings. ``ops/fleet_kit/`` is vendored byte-for-byte and fenced. The baseline only shrinks:
ANY new finding, or a further finding in a baselined file, fails ``test_no_file_exceeds_its_baseline``. The run uses NO
config (``--isolated``) so a per-file-ignore cannot hide a finding, and ``--preview`` because the PTH family differs under
it.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = "PTH110,PTH112,PTH113,PTH114"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE: dict[str, int] = {
    "dashboard/routes_recordings.py": 2,  # _is_link islink beside os.path.isjunction; the isfile guard beside it
    "ops/launcher/updater.py": 1,  # PKG-owned
    "ops/migrate/e_move_helpers.py": 3,  # one-shot migrate helper, string handling not touched blind
    "tests/_replace_faults.py": 1,  # fault-injection harness probing a string directory
    "tests/test_build_order_boots.py": 1,
    "tests/test_inbox_responder_runner.py": 1,  # os.path.isdir of the Linux-only /proc/self/fd
    "tests/test_item_wpa.py": 1,
    "tests/test_junction_drive_spellings_pubrepo_f.py": 1,
    "tests/test_minimap_blob_detect_precision.py": 1,
    "tests/test_rune_wpa.py": 1,
    "tests/test_summspell_wpa.py": 1,
    "tools/perseus_recall.py": 1,  # tests bind os.path.exists on this module (tests/_module_view.bind_os_path)
}
_FIXED = (
    "tools/perseus_sync.py",
    "tools/freeze_witness.py",
    "ops/audit/opponent_prior_gonogo.py",
    "tools/live_write_tracer.py",
    "core/vision_tesseract.py",
    "tft/cv/ocr_fields.py",
    "vision_server/_inference.py",
    "tools/precommit_gate.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--preview", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULES, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _in_scope(rel: str) -> bool:
    return not any(rel.startswith(prefix) for prefix in _NOT_THIS_SCOPE)


@pytest.fixture(scope="module")
def held_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    held = {t for t in tracked if _in_scope(t)}
    assert len(held) > 500, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in held:
            counts[rel] += 1
    return dict(counts)


def test_no_file_exceeds_its_baseline(held_counts):
    over = {f: n for f, n in held_counts.items() if n > _BASELINE.get(f, 0)}
    assert not over, f"ruff {_RULES} findings above the baseline, file: count: {over}"


def test_the_baseline_only_shrinks(held_counts):
    stale = {f: n for f, n in _BASELINE.items() if held_counts.get(f, 0) < n}
    assert not stale, f"baseline entries to lower or remove (fixed since): {stale}"


def test_the_fixed_modules_are_clean_tracked_and_in_scope(held_counts):
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in _FIXED:
        assert rel in tracked, rel
        assert _in_scope(rel), rel
        assert rel not in _BASELINE, rel
        assert held_counts.get(rel, 0) == 0, rel


def test_the_fence_is_not_empty_of_findings_by_accident():
    """A positive control: all four rules fire on the pattern each exists for."""
    probe = (
        "import os\n"
        'os.path.exists("a")\n'
        'os.path.isdir("a")\n'
        'os.path.isfile("a")\n'
        'os.path.islink("a")\n'
    )
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe)
    assert sorted(d["code"] for d in found) == ["PTH110", "PTH112", "PTH113", "PTH114"]


def _load_by_path(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def test_the_freeze_witness_walk_lists_regular_files_and_skips_links(tmp_path):
    """Behaviour pin: a regular file is listed, a nested one too, and a file symlink (where creatable) is not."""
    fw = _load_by_path("_s144p540_freeze_witness", "tools/freeze_witness.py")
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "sub" / "b.txt").write_text("b", encoding="utf-8")
    try:
        (tmp_path / "link.txt").symlink_to(tmp_path / "a.txt")
    except (OSError, NotImplementedError):
        pass  # no symlink privilege on this host: the regular-file half still holds
    assert fw._walk(tmp_path) == ["a.txt", "sub/b.txt"]


def test_the_tesseract_resolvers_keep_an_existing_binary_and_reject_a_directory(tmp_path):
    """Behaviour pin: is_file() is true for a file and false for a directory or a missing path."""
    from tft.cv import ocr_fields

    exe = tmp_path / "tesseract.exe"
    exe.write_bytes(b"x")
    assert ocr_fields.TesseractEngine(cmd=str(exe)).available() is True
    assert ocr_fields.TesseractEngine(cmd=str(tmp_path)).available() is False
    assert ocr_fields.TesseractEngine(cmd=str(tmp_path / "missing.exe")).available() is False
    assert ocr_fields.TesseractEngine(cmd="").available() is False
