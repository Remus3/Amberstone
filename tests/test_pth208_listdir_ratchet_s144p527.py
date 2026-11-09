"""S144-P-527 - ruff PTH208 (os.listdir replaceable by Path.iterdir) held at a named baseline.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): seven findings in six files. Five became
``Path.iterdir`` (``tools/perseus_sync.py`` memory-file walk, ``tools/live_write_tracer.py`` ``--merge`` directory scan,
``tests/test_routes_ban_suggestions_true_audit.py`` icon-name set, ``tests/test_tft_placement_rm616.py`` two
"no tmp left" listings); each already held a ``str`` / ``Path`` directory and wanted only the entry names, so the change
reads ``entry.name`` and drops the ``os`` import where the listing was its last use.

The other two sites are the launcher's ``_listing`` (``ops/launcher/first_run.py``), which lists a directory through an
OPEN FILE DESCRIPTOR (``os.listdir(self.run.fd)``) on POSIX - ``Path.iterdir`` takes no descriptor - so the pair stays
in ``_BASELINE`` at two findings (the file is also the main session's: the launcher is PKG-owned). The baseline only
shrinks: ANY new finding, or a third finding in a baselined file, fails ``test_no_file_exceeds_its_baseline``.
The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding, and ``--preview`` because PTH208 is
preview-only in this ruff.
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

_RULE = "PTH208"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE: dict[str, int] = {
    "ops/launcher/first_run.py": 2,  # os.listdir(fd) on POSIX: iterdir takes no descriptor; PKG-owned file
}
_FIXED = (
    "tools/perseus_sync.py",
    "tools/live_write_tracer.py",
    "tests/test_routes_ban_suggestions_true_audit.py",
    "tests/test_tft_placement_rm616.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--preview", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULE, *args],
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
    assert not over, f"ruff {_RULE} findings above the baseline, file: count: {over}"


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
    """A positive control: the rule does fire on the pattern it exists for."""
    probe = 'import os\nfor name in sorted(os.listdir("d")):\n    pass\n'
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe)
    assert [d["code"] for d in found] == [_RULE]


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


def test_perseus_sync_walks_memory_files_in_sorted_name_order(tmp_path, monkeypatch):
    """Behaviour pin: .md files only, MEMORY.md skipped, sorted by name; nothing else is read."""
    ps = _load_by_path("_s144p527_perseus_sync", "tools/perseus_sync.py")
    memdir = tmp_path / "memory"
    memdir.mkdir()
    for stem in ("zeta", "alpha", "MEMORY"):
        (memdir / f"{stem}.md").write_text(f"---\nname: {stem}\ntype: reference\n---\nbody {stem}\n", encoding="utf-8")
    (memdir / "notes.txt").write_text("not a memory", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("", encoding="utf-8")
    monkeypatch.setattr(ps, "MEMDIR", str(memdir))
    monkeypatch.setattr(ps, "REPO", str(repo))

    class _Vault:
        def __init__(self):
            self.keys = []

        def call(self, _tool, args):
            self.keys.append(args["key"])
            return {"result": {}}

    vault = _Vault()
    counts = ps.sync(vault)
    assert vault.keys == ["alpha", "zeta"]
    assert counts["memory"] == 2


def test_tracer_merge_scans_a_directory_for_trace_reports_only(tmp_path, capsys):
    """Behaviour pin: --merge DIR takes live_write_trace*.json in sorted order and ignores the rest."""
    tracer = _load_by_path("_s144p527_tracer", "tools/live_write_tracer.py")
    for name, units in (("live_write_trace_b.json", 3), ("live_write_trace_a.json", 4)):
        (tmp_path / name).write_text(json.dumps({"wrote_units": {"x.json": units}}), encoding="utf-8")
    (tmp_path / "other.json").write_text(json.dumps({"wrote_units": {"x.json": 100}}), encoding="utf-8")
    (tmp_path / "live_write_trace_c.txt").write_text("{}", encoding="utf-8")
    assert tracer.main(["--merge", str(tmp_path)]) == 0
    merged = json.loads(capsys.readouterr().out)
    assert merged["totals"]["reports_merged"] == 2
    assert merged["wrote_units"] == {"x.json": 7}
