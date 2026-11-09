"""S144-P-525 - ruff PTH207 (glob.glob replaceable by Path.glob) held at a named baseline.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): five findings in five files, none in the
vendored kit. Three became ``Path.glob`` (``ops/audit/ds_perm_swarm/build_aram_archetype_override``,
``ops/audit/ds_perm_swarm/build_marksman_offclass_exempt``, ``tools/ds_cross_eval/aggregate``): each looped over
``sorted(glob.glob(str(dir / "*.json")))`` and re-wrapped every string back into a ``Path``; they now sort the Path
objects with ``key=str`` (the same ordering the old string sort gave, whatever the platform's Path comparison does with
case) and read the Path directly, and the three ``import glob`` lines went.

The other two sites belonged to the gated lane, whose branch changed both files (``tools/gated_lx01_draft_check.py``,
``tests/test_vision_profile_2560_ocr_boxes.py``). S144-P-543 converted the test (its pattern is a fixed relative
literal); ``tools/gated_lx01_draft_check.py`` stays in ``_BASELINE`` at one finding because its spec may be absolute. The baseline only
shrinks: ANY new finding, or a third finding in a baselined file, fails ``test_no_file_exceeds_its_baseline``.
The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding, and ``--preview`` because PTH207 is
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

_RULE = "PTH207"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE: dict[str, int] = {
    # the pattern is caller-supplied and may be ABSOLUTE; Path.glob refuses a non-relative pattern, so the swap changes behaviour
    "tools/gated_lx01_draft_check.py": 1,
}
_FIXED = (
    "ops/audit/ds_perm_swarm/build_aram_archetype_override.py",
    "ops/audit/ds_perm_swarm/build_marksman_offclass_exempt.py",
    "tools/ds_cross_eval/aggregate.py",
    # converted in S144-P-543 once no lane branch changed it any more
    "tests/test_vision_profile_2560_ocr_boxes.py",
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
    probe = 'import glob\nfor f in sorted(glob.glob("*.json")):\n    pass\n'
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe)
    assert [d["code"] for d in found] == [_RULE]


def _load_by_path(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_aggregate_load_reads_sorted_json_and_reports_parse_errors(tmp_path, monkeypatch):
    """Behaviour pin: sorted order, only *.json, a bad file becomes a PARSE_ERR row named by its stem."""
    agg = _load_by_path("_s144p525_aggregate", "tools/ds_cross_eval/aggregate.py")
    verdicts = tmp_path / "verdicts"
    verdicts.mkdir()
    (verdicts / "b.json").write_text(json.dumps({"champion": "B"}), encoding="utf-8")
    (verdicts / "a.json").write_text(json.dumps({"champion": "A"}), encoding="utf-8")
    (verdicts / "c.json").write_text("{not json", encoding="utf-8")
    (verdicts / "note.txt").write_text("ignored", encoding="utf-8")
    monkeypatch.setattr(agg, "BASE", tmp_path)
    rows = agg.load()
    assert [r["champion"] for r in rows] == ["A", "B", "c"]
    assert rows[2]["severity"] == "PARSE_ERR"


def test_marksman_exempt_table_reads_every_json_in_the_dir(tmp_path, monkeypatch):
    """Behaviour pin: a cross-eval file reaches the table through the Path read."""
    mod = _load_by_path("_s144p525_marksman", "ops/audit/ds_perm_swarm/build_marksman_offclass_exempt.py")
    item = sorted(mod.OFFCLASS_MARKSMAN_ITEM_NAMES)[0]
    monkeypatch.setattr(mod, "_is_ranged_marksman", lambda rec: True)
    snap = type("Snap", (), {"champions": {"Zed": object(), "Yi": object()}})()
    block = {"all": {"wr": 50.0, "items": [{"name": item, "n": 99, "wr": 50.0}]}}
    for champ in ("Zed", "Yi"):
        (tmp_path / f"{champ}.json").write_text(
            json.dumps({"champion": champ, "empirical": {"SR": block}}), encoding="utf-8")
    (tmp_path / "skip.txt").write_text("{}", encoding="utf-8")
    table = mod.build_table(snapshot=snap, cross_eval_dir=tmp_path)
    assert table["ranged_marksmen_considered"] == 2
    assert table["champions"] == {"Yi": [item], "Zed": [item]}


def test_aram_override_table_reads_every_verdict_in_the_dir(tmp_path):
    """Behaviour pin: verdict files are found by the Path glob and read as UTF-8 JSON."""
    mod = _load_by_path("_s144p525_aram", "ops/audit/ds_perm_swarm/build_aram_archetype_override.py")
    verdicts = tmp_path / "verdicts"
    data = tmp_path / "data"
    verdicts.mkdir()
    data.mkdir()
    (verdicts / "p.json").write_text(json.dumps({"champion": "P", "archetype_ok": False}), encoding="utf-8")
    (verdicts / "q.json").write_text(json.dumps({"champion": "Q", "archetype_ok": True}), encoding="utf-8")
    (verdicts / "r.txt").write_text(json.dumps({"champion": "R", "archetype_ok": False}), encoding="utf-8")
    (data / "P.json").write_text(
        json.dumps({"archetype": {"source": "user"}}), encoding="utf-8")
    table = mod.build_table(verdicts_dir=verdicts, data_dir=data)
    assert table["champions"] == {}
    assert [v for k, v in table.items() if "considered" in k] == [1]
