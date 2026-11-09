"""S144-P-545 - ruff PTH101 / PTH119 / PTH211 (os.chmod / os.path.basename / os.symlink) held at a named baseline.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): 36 findings in 24 files, none in the
vendored kit (``ops/fleet_kit/``, fenced anyway). Sixteen sites in ten test files became pathlib (``Path.symlink_to`` /
``Path.chmod``; both call the same ``os`` function with the same arguments, ``target_is_directory`` included), so
those ten files are pinned clean. Twenty findings in fourteen files stayed baselined, for a stated reason each; S144-P-546 then
converted the ten files whose basename only formats a log or display name (twelve PTH119 sites; the existing
log-line tests ``tests/test_state_builder_inprocess_degrade.py`` and
``tests/rc2_l3/test_lcu_inprocess_degrade_log_rm312.py`` still anchor the frame basename), leaving eight findings in
four files:

- ``os.path.basename`` is NOT ``Path.name`` on a string with a trailing separator (``basename("a/")`` is ``""``,
  ``Path("a/").name`` is ``"a"``), so the two name-validation sites (``lib/icons/downloader.py``, which compares the
  basename to the input to refuse a path, and ``tools/ddragon_mirror_refresh.py``) are behaviour-bearing and stay.
- ``tests/_basetemp_guard.py`` chmods inside a gate that must never raise on odd input; ``tests/test_launcher_first_run.py``
  (five sites) is the packaging owner's.

The baseline only shrinks: ANY new finding, or a second finding in a baselined file, fails
``test_no_file_exceeds_its_baseline``. The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding,
and ``--preview`` because the PTH family differs under it.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = "PTH101,PTH119,PTH211"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE: dict[str, int] = {
    "lib/icons/downloader.py": 1,  # name validation: basename(img) != img refuses a path
    "tests/_basetemp_guard.py": 1,  # chmod inside a gate that must not raise
    "tests/test_launcher_first_run.py": 5,  # packaging owner's test
    "tools/ddragon_mirror_refresh.py": 1,  # name validation: basename(name) != name
}
_FIXED = (
    "dashboard/_lcu_inprocess.py",
    "dashboard/_state_builder.py",
    "tests/rc2_l3/test_lcu_inprocess_degrade_log_rm312.py",
    "tests/test_ascii_rule_true_audit_s144.py",
    "tests/test_log_rotation_rm718a.py",
    "tests/test_state_builder_inprocess_degrade.py",
    "tests/test_vision_profile_2560_ocr_boxes.py",
    "tools/console_flash_control.py",
    "tools/console_flash_detector.py",
    "tools/perseus_sync.py",
    "tests/test_ddragon_mirror_prune.py",
    "tests/test_guard_grading_rc_facts.py",
    "tests/test_install_bat_key_stage_rm779.py",
    "tests/test_loop_executor.py",
    "tests/test_outbound_reciprocity_check.py",
    "tests/test_rc_transactional_deploy.py",
    "tests/test_routes_recordings.py",
    "tests/test_session_intents_true_audit_s144t169.py",
    "tests/test_static_helpers_true_audit_s144t175.py",
    "tests/test_ui_applier_true_audit_s144t153.py",
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
    """A positive control: each rule fires on the pattern the baseline exists for."""
    probe = "import os\nos.chmod('a', 0o644)\nos.path.basename('a')\nos.symlink('a', 'b')\n"
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe)
    assert sorted(d["code"] for d in found) == ["PTH101", "PTH119", "PTH211"]


def test_basename_is_not_path_name_on_a_trailing_separator():
    """Why the two name-validation sites stay baselined."""
    assert os.path.basename("a/") == ""  # noqa: PTH119 - the old spelling is the control
    assert Path("a/").name == "a"


@pytest.mark.parametrize("name", [
    "ascii_rule.py", "<string>", "<stdin>", "<frozen importlib._bootstrap>", "", "no_extension",
    "dir/mod.py", "dir/sub/mod.py", "/abs/dir/mod.py", "C" + ":/abs/dir/mod.py", "x.tar.gz",
])
def test_path_name_matches_basename_on_the_converted_sites_inputs(name):
    """The converted PTH119 sites feed a traceback frame filename, ``__file__``, an argv[0], a process image
    name or a memory-file path: none ends in a separator, and for those the two spellings agree."""
    assert Path(name).name == os.path.basename(name)  # noqa: PTH119 - the old spelling is the control


def test_path_symlink_to_matches_os_symlink_and_forwards_target_is_directory(tmp_path, monkeypatch):
    """The converted sites: same os call, same arguments, directory flag included."""
    seen = []
    real = os.symlink

    def spy(src, dst, target_is_directory=False, **kw):
        seen.append((Path(src), Path(dst), target_is_directory))
        return real(src, dst, target_is_directory=target_is_directory, **kw)

    monkeypatch.setattr(os, "symlink", spy)
    target = tmp_path / "t"
    target.mkdir()
    link = tmp_path / "l"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need a privilege this account lacks")
    assert seen == [(target, link, True)]
    assert link.resolve() == target.resolve()


def test_path_chmod_goes_through_os_chmod(tmp_path, monkeypatch):
    """Path.chmod and os.chmod are one call, so a test's scoped fault on os.chmod still bites."""
    seen = []
    real = os.chmod

    def spy(p, mode, **kw):
        seen.append((Path(p), mode))
        return real(p, mode, **kw)

    monkeypatch.setattr(os, "chmod", spy)
    f = tmp_path / "f.txt"
    f.write_text("x", encoding="utf-8")
    f.chmod(0o644)
    assert seen == [(f, 0o644)]
