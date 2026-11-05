"""RM-1400 - source comments name the symbol, not a line, and a ratchet holds it.

RM-1396 fixed seven modules that cited a doc or script by LINE. Measured
2026-11-04 over every tracked non-test .py outside ops/launcher (main session)
and agents/daemon_slayer (own symbol-cite guards): that left six modules whose
comments still pointed at a line that moved or was only ever a snapshot (the
last one was found by the ratchet itself):

- game_reader/mode_router.py said snapshot_normalizer imports it "at its own
  line 22"; the import is on line 23 now. It names the import statement.
- dashboard/routes_diag.py cited "line 20" and "ruff.toml:27"; it names the
  `diagnostics_cached` import and the F401 entry.
- tools/rm_id_registry.py cited ROADMAP.md:55 and ROADMAP.md:28; it names the
  bullet and the header note.
- tools/drift_guard.py cited docs/OVERLAY_COMPLIANCE_PLAN.md:35; it names the
  doc and quotes the sentence (the quote is the anchor).
- ops/loop/executor.py cited control/directive.md:3; it names the
  PREMISE-CHECK line.
- ops/loop/queue_loop.py cited .github/workflows/ci.yml:38-40; it names the
  concurrency block.

This pins (a) none of the six cites by line again, (b) each still names its
replacement, (c) a tree-wide ratchet: any other tracked non-test .py outside
the two owned areas that cites `<file>.<ext>:<n>` fails unless it is in the
shrinking _BASELINE with a reason, and a baseline entry that stops citing
fails until it is dropped.
"""
from __future__ import annotations

import re

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

FIXED = (
    "game_reader/mode_router.py",
    "dashboard/routes_diag.py",
    "tools/rm_id_registry.py",
    "tools/drift_guard.py",
    "ops/loop/executor.py",
    "ops/loop/queue_loop.py",
)

# (module, prose it must still carry)
NEW_PROSE = (
    ("game_reader/mode_router.py", "at module level (its"),
    ("game_reader/mode_router.py", "`from .mode_router import is_tft_mode, ...`"),
    ("dashboard/routes_diag.py", "module-level `diagnostics_cached` import"),
    ("dashboard/routes_diag.py", "F401 entry in ruff.toml"),
    ("tools/rm_id_registry.py", "One ROADMAP.md bullet carried"),
    ("tools/rm_id_registry.py", "The ROADMAP.md header note"),
    ("tools/drift_guard.py", "reported a line of ``docs/OVERLAY_COMPLIANCE_PLAN.md``"),
    ("ops/loop/executor.py", "off the PREMISE-CHECK line of control/directive.md"),
    ("ops/loop/queue_loop.py", "`concurrency:` block of `.github/workflows/ci.yml`"),
)

# (file the anchor must be IN, anchor text) - the replacement still resolves.
ANCHORS = (
    ("game_reader/snapshot_normalizer.py", "from .mode_router import is_tft_mode"),
    ("dashboard/routes_diag.py", "from dashboard._diagnostics import diagnostics_cached"),
    ("ruff.toml", '"F401"'),
    ("ROADMAP.md", "relocate verbatim to"),
    ("tools/drift_guard.py", "as of <YYYY-MM-DD>"),
    ("ops/loop/executor.py", "PREMISE-CHECK: [from-digest] LAST AUDIT"),
    (".github/workflows/ci.yml", "cancel-in-progress: true"),
)

# A file cited by position: "x.py:12", "x.md:12-15", "x.js:7506+", "x.toml:27".
_LINE_CITE = re.compile(r"[\w./\\-]+\.(?:py|md|js|css|ps1|html|toml|ya?ml|json|txt):\d+")

# Out of the ratchet by scope: the main session owns the packaged app, the DS
# engine carries its own symbol-cite guards, the kit is vendored byte-for-byte.
_SCOPE_SKIP = ("ops/launcher/", "ops/fleet_kit/", "agents/daemon_slayer/")

# rel path -> why it may keep a line cite. Only shrinks.
_BASELINE = {
    "app/_game_lifecycle.py": "frozen",
    "tools/citation_audit.py": "cites are the tool's subject",
    "tools/stop_claim_gate.py": "quotes a cite as the pattern it detects",
    "dashboard/routes_loop_control.py": "another lane branch changed it",
    "dashboard/routes_state.py": "another lane branch changed it",
    "dashboard/routes_build_plan.py": "another lane branch changed it",
    "dashboard/routes_coach.py": "another lane branch changed it",
    "dashboard/routes_sr_user_builds.py": "another lane branch changed it",
}


def _in_scope(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    if rel.startswith("tests/") or "/tests/" in rel:
        return False
    if name.startswith("test_") or name == "conftest.py":
        return False
    return not rel.startswith(_SCOPE_SKIP)


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_bytes().decode("utf-8")


def _citers() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path in repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(path)
        if not _in_scope(rel):
            continue
        hits = _LINE_CITE.findall(path.read_text(encoding="utf-8"))
        if hits:
            out[rel] = hits
    return out


@pytest.mark.parametrize("rel", FIXED)
def test_fixed_module_cites_nothing_by_line(rel):
    hits = _LINE_CITE.findall(_read(rel))
    assert not hits, f"{rel} cites by line again: {hits} (RM-1400)"


@pytest.mark.parametrize("rel", FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


@pytest.mark.parametrize(("rel", "prose"), NEW_PROSE)
def test_module_still_names_its_replacement(rel, prose):
    assert prose in _read(rel), f"{rel} lost {prose!r}"


@pytest.mark.parametrize(("rel", "anchor"), ANCHORS)
def test_anchor_still_exists_in_its_target(rel, anchor):
    assert anchor in _read(rel), f"{rel} no longer carries {anchor!r}; re-point"


def test_walk_is_not_vacuous():
    rels = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert {"tools/drift_guard.py", "ops/loop/executor.py"} <= rels
    assert len([r for r in rels if _in_scope(r)]) > 400


def test_no_unclassified_line_cite_in_source():
    new = {r: h for r, h in _citers().items() if r not in _BASELINE}
    assert not new, (
        f"source cites a file by line: {new}. Name the symbol, heading or "
        "quoted sentence instead; a quoted pattern joins _BASELINE with a reason.")


def test_baseline_is_exact():
    citers = _citers()
    stale = sorted(r for r in _BASELINE if r not in citers)
    assert not stale, f"no longer cite by line - drop from _BASELINE: {stale}"
    missing = [r for r in _BASELINE if not (REPO_ROOT / r).is_file()]
    assert not missing, f"not tracked files: {missing}"
    assert not [r for r in _BASELINE if not _in_scope(r)]


def test_pattern_catches_the_old_forms_and_spares_the_new():
    for probe in ("ROADMAP.md:55", "ruff.toml:27", "control/directive.md:3",
                  "docs/OVERLAY_COMPLIANCE_PLAN.md:35", "main.js:7506+",
                  "routes_coach.py:214"):
        assert _LINE_CITE.search(probe), probe
    for probe in ("control/directive.md:", "the F401 entry in ruff.toml",
                  "ROADMAP.md header note", "version 1.2.3:4"):
        assert not _LINE_CITE.search(probe), probe
