"""Pin the generated ``Share/MANIFEST.md`` as a PRODUCT artifact, not a stamp.

``Share/`` is the external-facing DS package, and ``MANIFEST.md`` is regenerated
wholesale by ``tools/ds_share_sync.py`` on a pre-commit hook - a hand edit is
silently reverted. So the only place its prose can live is the template, and the
only place its contract can be pinned is here.

Two halves, and both must hold at once:
  1. Every machine-parsed field a reader or script already keys off (the
     ENGINE_VERSION / patch / count / timestamp lines, the Layout block, the run
     recipe) survives verbatim.
  2. The generated file also answers what the package IS, what the stamp MEANS,
     which paths are generated vs authored, and where to start reading.
"""
from __future__ import annotations

from tools import ds_share_sync as sync

_VERSION = "9.99.0"
_N_FILES = 501
_ENG_FILES = 455
_TS = "2026-07-21 00:00:00 UTC"


def _body(ts: str = _TS) -> str:
    return sync._manifest_body(_VERSION, _N_FILES, _ENG_FILES, ts)


def test_machine_fields_survive_verbatim():
    """The pre-existing machine record is unchanged - same lines, live values."""
    body = _body()
    for line in (
        f"- ENGINE_VERSION: {_VERSION}",
        f"- data patch: {sync._PATCH}",
        f"- files mirrored under Share/src: {_N_FILES}",
        f"- engine .py modules: {_ENG_FILES}",
        f"- last synced: {_TS}",
    ):
        assert line in body, f"machine field dropped from the manifest: {line!r}"


def test_structural_sections_survive():
    """The layout tree and the run recipe stay - they are the package's map."""
    body = _body()
    assert "## Layout" in body
    assert "## Running the engine from this package" in body
    for fragment in (
        "agents/daemon_slayer/   the engine package (source + tests)",
        f"the versioned reference-data snapshot ({sync._PATCH})",
        "python -m pytest agents/daemon_slayer/tests -q",
        "python tools/start_daemon_slayer.py",
    ):
        assert fragment in body, f"structural fragment dropped: {fragment!r}"


def test_says_what_the_package_is():
    """An external reader lands here cold - the file must orient them."""
    body = _body()
    assert "offline, deterministic" in body
    assert "external technical review" in body


def test_explains_what_the_stamp_means():
    """The counts and timestamp are meaningless without their definitions."""
    body = _body()
    assert "## Package stamp" in body
    assert "not a release date" in body


def test_marks_generated_vs_authored():
    """The whole point: nobody should hand-edit a regenerated path."""
    body = _body()
    assert "## Generated vs authored" in body
    assert "silently reverted" in body
    for path in ("`Share/src/**`", "`Share/MANIFEST.md`", "`Share/README.md`",
                 "`Share/docs/*.md`", "`Share/CHANGELOG.md`"):
        assert path in body, f"generated-vs-authored table is missing {path}"


def test_points_at_the_readme_and_the_five_docs():
    """The manifest is a hub, so the reading order must be discoverable."""
    body = _body()
    assert "## Where to start" in body
    assert "`README.md`" in body
    for doc in ("01_OVERVIEW", "02_FUNCTION_REFERENCE", "03_DATA_AND_SOURCES",
                "04_GAPS_AND_ROADMAP", "05_AUDIT_AND_REFACTOR"):
        assert f"`docs/{doc}.md`" in body, f"doc pointer missing: {doc}"


def test_body_is_7bit_ascii():
    """Repo-wide hard rule; a smuggled dash or smart quote fails CI hygiene."""
    body = _body()
    offenders = sorted({c for c in body if ord(c) > 127})
    assert not offenders, f"non-ASCII in the generated manifest: {offenders}"


def test_body_is_deterministic():
    """Same inputs -> byte-identical output (no clock or dict-order leakage)."""
    assert _body() == _body()


def test_only_the_timestamp_line_moves_between_syncs():
    """Two syncs of an unchanged mirror must differ in the stamp line alone."""
    first = _body("2026-07-21 00:00:00 UTC").splitlines()
    second = _body("2026-07-22 11:22:33 UTC").splitlines()
    assert len(first) == len(second)
    differing = [a for a, b in zip(first, second) if a != b]
    assert differing == ["- last synced: 2026-07-21 00:00:00 UTC"]


def test_stamp_manifest_writes_the_template(tmp_path, monkeypatch):
    """The write path emits the template - not a second, divergent copy."""
    monkeypatch.setattr(sync, "_SHARE", tmp_path)
    monkeypatch.setattr(sync, "_build_expected", lambda: {
        "agents/daemon_slayer/dps.py": b"",
        "data/daemon_slayer/current.txt": b"",
    })
    sync._stamp_manifest(_VERSION, _N_FILES)

    written = (tmp_path / "MANIFEST.md").read_text(encoding="utf-8")
    assert f"- ENGINE_VERSION: {_VERSION}" in written
    assert f"- files mirrored under Share/src: {_N_FILES}" in written
    assert "- engine .py modules: 1" in written
    assert "## Generated vs authored" in written
    assert "## Where to start" in written
