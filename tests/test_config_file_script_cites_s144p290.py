"""S144-P-290 - a CI workflow, git hook, tool config or top-level README never names a removed repo script.

Fifth sibling of test_dangling_py_cite_ratchet_s144p273 (production .py prose), the doc guards p284 / p285, the
test-prose guard p286 and the script-file guard p289. None of those reads a file that is neither source, a docs/ or
tools/ prompt, nor a shell / Node script. The files here are the ones that RUN a repo script by name from outside
Python: a ``.github/workflows/*.yml`` step (``python tools/x.py``), a ``.githooks/*`` hook, an AutoHotkey / VBScript
launcher, the ruff / pytest / mypy config, ``requirements*.in`` and the READMEs a contributor follows. When the
named script is removed the workflow step or hook fails at run time, so a stale cite here is a live break.

Measured 2026-11-06 over the tracked files below: ZERO cites of an untracked path (the workflows alone carry 34
repo-rooted cites, the hooks 7, ``ruff.toml`` 14), so the guard ships at zero with nothing to fix and nothing to
allow. BACKLOG.md, ROADMAP.md, CLAUDE.md, WAKEUP_NOTES.md, the ledgers and the dated ``ops/audit`` / ``agents/*/proposals``
artifacts are out of scope on purpose: they are planning and history records whose cites name files that were never
built or were later removed, and the first group is owned by the main session. ``docs/specs/**/*.txt`` kickoff
prompts name files they are about to create ("NEW core/x.py"), so ``.txt`` is not scanned either.

Known blind spots, measured the same day: a backslash-spelled cite (``tools\\x.ps1`` in a ``.vbs`` or ``.ahk``) is not
matched, and a path assembled at run time is invisible by construction.

The rule is the p273 rule (``scan_source``): an untracked cite needs a removed / retired / quarantined word within
three lines, else it fails. ``test_scanner_is_live`` proves the file selection and the scan each report a bare cite,
since an empty scan would pass for any reason.
"""
from __future__ import annotations

from tests.test_dangling_py_cite_ratchet_s144p273 import _CITE_RE, _tracked, scan_source
from tests._repo_walk import REPO_ROOT

_CONFIG_NAMES = frozenset({"ruff.toml", "pytest.ini", "mypy.ini", "requirements.in", "README.md"})
_CONFIG_SUFFIXES = (".yml", ".yaml", ".ahk", ".vbs", ".in")
_CONFIG_PREFIXES = (".github/", ".githooks/")
# A README outside the repo root belongs to a sub-project with its own layout (``oss/`` is a standalone package, the
# lane widget an Electron app): its relative cites are not repo-rooted.
_OUT_OF_SCOPE_PREFIXES = ("web/", "data/", "tests/", "docs/", "ops/fleet_kit/", "rc-shell/", "ops/launcher/", "oss/",
                          "lane-widget/", "agents/")


def _files(tracked: frozenset[str]) -> list[str]:
    picked = []
    for rel in tracked:
        if rel.startswith(_OUT_OF_SCOPE_PREFIXES):
            continue
        name = rel.rsplit("/", 1)[-1]
        if (
            (rel.startswith(_CONFIG_PREFIXES) and not rel.endswith((".txt", ".json")))
            or ("/" not in rel and (name in _CONFIG_NAMES or rel.endswith(_CONFIG_SUFFIXES)))
            or rel.endswith((".ahk", ".vbs"))
        ):
            picked.append(rel)
    return sorted(picked)


def _tree_hits() -> set[tuple[str, str]]:
    tracked = _tracked()
    found: set[tuple[str, str]] = set()
    for rel in _files(tracked):
        try:
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found.update((rel, cited) for _line, cited in scan_source(src, tracked))
    return found


def test_no_config_file_names_a_missing_repo_script():
    hits = sorted(_tree_hits())
    assert not hits, (
        "a workflow / hook / config / README cites a repo script that is not tracked (restore it, drop the cite, or "
        f"mark the cite removed / retired within 3 lines): {hits}"
    )


def test_scanner_is_live():
    tracked = frozenset(
        {
            ".github/workflows/ci.yml", ".github/ci/requirements-ci.txt", ".github/ci/requirements-ci.in",
            ".githooks/pre-push", "ruff.toml", "pytest.ini", "README.md", "ops/x.vbs", "tools/y.ahk",
            "oss/pkg/README.md", "lane-widget/README.md", "BACKLOG.md", "docs/specs/leap/k.txt", "docs/a.yml",
            "ops/audit/p2.json", "tools/real.py", "data/cfg.yml", "mypy.ini", "ops/loop/control/z.in",
        }
    )
    assert _files(tracked) == [
        ".githooks/pre-push", ".github/ci/requirements-ci.in", ".github/workflows/ci.yml", "README.md", "mypy.ini",
        "ops/x.vbs", "pytest.ini", "ruff.toml", "tools/y.ahk",
    ]
    assert scan_source("run: python tools/absent.py --go\n", tracked) == [(1, "tools/absent.py")]
    assert scan_source("run: python tools/absent.py --go # it was removed\n", tracked) == []
    assert scan_source("run: python tools/real.py --go\n", tracked) == []


def test_real_config_files_carry_cites_so_the_scan_is_not_empty():
    """The measured population: if no selected file cites any repo path, the zero above proves nothing."""
    tracked = _tracked()
    files = _files(tracked)
    assert ".github/workflows/ci.yml" in files and ".githooks/pre-push" in files and "ruff.toml" in files
    cites = 0
    for rel in files:
        try:
            cites += len(_CITE_RE.findall((REPO_ROOT / rel).read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            continue
    assert cites >= 25, cites
