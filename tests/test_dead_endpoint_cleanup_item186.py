"""Item 186 + 194 dead-endpoint cleanup drift guard.

Pins the 11 routes deleted in item 186 + 1 in item 194 as PERMANENTLY removed.
The item 186 batch was truly-dead endpoints from item 184 Phase 6's flagged
candidate list: each had ZERO live callers across web/js/main.js, web/js/lib/,
web/js/panels/, tests/, tools/, coaches/, core/, agents/, lcu/, tft/, ops/,
vision_server/ (excluding the documented-dead web/js/dashboard.js + web/js/sim.js
+ dated audit reports). Item 194 added /api/preview-build after a follow-up audit:
only caller was the dead web/legacy_index.html:1523, so it survived the item 186
sweep purely because that file is excluded.

Per CLAUDE.md item 184 carry (h) the risky candidates (aram_analyze +
sr_draft + post_game_*) were vetted individually:
  - /api/aram-analyze        DELETED - 0 callers; module aram_team_analyzer kept
  - /api/sr-draft/profile    DELETED - 0 callers; build_profile kept (imported direct)
  - /api/sr-draft/apply      KEPT    - has tests/phase8_smoke coverage
  - /api/post-game-rubric    KEPT    - active route, in-flight feature
  - /api/post-game-wpa       KEPT    - active route, in-flight feature

The 12 deletions also dropped these handler symbols:
  - _serve_aram_analyze_post
  - _serve_experimental_get_post / _adapt_post / _mark_post
  - _serve_logs
  - _serve_preview_build (item 194)
  - _serve_recommend_champ
  - _serve_replay_coach_post
  - _serve_reload_regions
  - _serve_validate_ocr
  - _serve_ocr_crop
  - _serve_sr_draft_profile_post

If you find yourself adding any of these back, first re-run the dead-endpoint
audit pattern (grep callers across web/js/main.js + panels/ + tools/ + tests/)
and confirm there is a real consumer. Otherwise the route is dead-on-arrival.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from tests import _repo_walk

_PROJECT_ROOT = Path(__file__).parent.parent

# 11 routes deleted in item 186 + 1 in item 194.
_DELETED_ROUTES: tuple[str, ...] = (
    "/api/aram-analyze",
    "/api/experimental/adapt",
    "/api/experimental/get",
    "/api/experimental/mark",
    "/api/logs",
    "/api/ocr-crop",
    "/api/preview-build",
    "/api/recommend-champ",
    "/api/reload-regions",
    "/api/replay-coach",
    "/api/sr-draft/profile",
    "/api/validate-ocr",
)

# Handler symbols also removed. None of these may reappear in the dashboard
# routes namespace without the operator vetting the deletion.
_DELETED_HANDLERS: tuple[str, ...] = (
    "_serve_aram_analyze_post",
    "_serve_experimental_adapt_post",
    "_serve_experimental_get_post",
    "_serve_experimental_mark_post",
    "_serve_logs",
    "_serve_ocr_crop",
    "_serve_preview_build",
    "_serve_recommend_champ",
    "_serve_reload_regions",
    "_serve_replay_coach_post",
    "_serve_sr_draft_profile_post",
    "_serve_validate_ocr",
)

_ROUTE_MODULES: tuple[str, ...] = (
    "dashboard/routes_coach.py",
    "dashboard/routes_diag.py",
    "dashboard/routes_sr_draft.py",
)

# Floor for a repo-wide sweep. Well under the true counts (2386 tracked .py at
# the root, 1331 files across the caller surface, measured 2026-09-09) so it
# tracks a COLLAPSE, not the roster.
_MIN_SCANNED = 100


def _assert_enumeration_reached(case, scanned, anchors, label):
    """Fail unless the sweep actually reached `anchors` and a plausible bulk.

    Both repo-wide tests in this module assert `offenders == []`, and an EMPTY
    enumeration satisfies that - a vacuous walk and a spotless repo are the
    same verdict. ADR-015 "Watch for" 1 requires every empty-set-safe guard to
    carry its own anti-vacuity arm, so this is it.

    It cannot be satisfied vacuously because each anchor is checked TWICE
    against different oracles: `is_file()` proves the path is really on disk
    (so the anchor cannot be a stale constant naming something that no longer
    exists), and membership in `scanned` proves the walk plus this guard's own
    scope filters actually delivered that file to the scanning arm. `scanned`
    is populated only inside the loop body, after every filter, so an empty or
    fully-filtered enumeration fails here even though the offender assertion
    below would have passed.
    """
    for anchor in anchors:
        case.assertTrue(
            (_PROJECT_ROOT / anchor).is_file(),
            f"{label} anchor {anchor!r} is no longer on disk. Replace it with "
            "a live tracked file - do NOT delete the anchor arm, it is the "
            "only thing standing between this guard and a silent always-green.",
        )
        case.assertIn(
            anchor, scanned,
            f"{label} enumeration collapsed: it never reached {anchor!r}, "
            "which is tracked and present on disk. An empty sweep passes the "
            "offender assertion below for the wrong reason (ADR-015 Watch "
            "for 1). Fix the walker or the scope filters, not this check.",
        )
    case.assertGreaterEqual(
        len(scanned), _MIN_SCANNED,
        f"{label} enumeration reached only {len(scanned)} files, under the "
        f"{_MIN_SCANNED} floor. A repo-wide sweep this thin is a collapsed "
        "walk, not a small repo.",
    )


class DeadRouteAbsenceTests(unittest.TestCase):
    """The 11 deleted route strings must not appear in any dashboard/routes_*.py
    registration table. Comment / docstring mentions are fine."""

    def test_no_deleted_route_registered(self):
        offenders: list[str] = []
        for mod_path in _ROUTE_MODULES:
            text = (_PROJECT_ROOT / mod_path).read_text(encoding="utf-8")
            tree = ast.parse(text)
            # Walk for any string literal that matches a deleted route inside
            # GET_ROUTES / POST_ROUTES assignment values.
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                    if not any(name in ("GET_ROUTES", "POST_ROUTES") for name in targets):
                        continue
                    for sub in ast.walk(node.value):
                        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                            if sub.value in _DELETED_ROUTES:
                                offenders.append(f"{mod_path}: route {sub.value!r}")
        self.assertEqual(
            offenders, [],
            "Deleted routes reappeared in route tables: " + "; ".join(offenders),
        )

    def test_no_deleted_handler_defined(self):
        offenders: list[str] = []
        for mod_path in _ROUTE_MODULES:
            text = (_PROJECT_ROOT / mod_path).read_text(encoding="utf-8")
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name in _DELETED_HANDLERS:
                    offenders.append(f"{mod_path}: handler def {node.name}")
        self.assertEqual(
            offenders, [],
            "Deleted handlers reappeared: " + "; ".join(offenders),
        )


class CallerSurfaceAbsenceTests(unittest.TestCase):
    """The deleted routes must not have a live caller anywhere in the
    production source tree. Comments / dated audit reports / dead-dashboard.js
    do not count."""

    _CALLER_DIRS: tuple[str, ...] = (
        "web/js/main.js",
        "web/js/lib",
        "web/js/panels",
        "web/index.html",
        "tools",
        "coaches",
        "core",
        "agents",
        "lcu",
        "tft",
        "ops",
        "vision_server",
        "coach_integration",
        "dashboard",
    )

    _EXTENSIONS: tuple[str, ...] = (".py", ".js", ".html")

    # Glob form of _EXTENSIONS, for tests/_repo_walk.iter_repo_files.
    _PATTERNS: tuple[str, ...] = ("*.py", "*.js", "*.html")

    # Anti-vacuity anchors (ADR-015 "Watch for" 1). This test asserts
    # `offenders == []`, which an EMPTY enumeration satisfies, so the walk has
    # to prove it still reaches real files or the conversion to the shared
    # walker would trade a live exposure for a silent always-green. One anchor
    # per pattern, so a broken *.js or *.html arm is caught too. Each is
    # asserted against the DISK before it is asserted against the scan, so a
    # renamed anchor fails as "anchor gone", not as "walk collapsed".
    _ENUMERATION_ANCHORS: tuple[str, ...] = (
        "core/build_order.py",
        "web/js/main.js",
        "web/index.html",
    )

    def _in_caller_surface(self, rel: str) -> bool:
        """True when a repo-relative path is inside one of _CALLER_DIRS.

        _CALLER_DIRS mixes directories with single files (web/js/main.js,
        web/index.html), so this is a prefix test rather than a walk per entry.
        Enumerating from the repo root and filtering here is the ADR-015 idiom -
        the shared walker owns the infrastructure exclusions, this guard owns
        its own scope - and it needs ONE cached `git ls-files` instead of one
        per entry. Measured 2026-09-09: identical result set either way.
        """
        return any(rel == entry or rel.startswith(entry + "/")
                   for entry in self._CALLER_DIRS)

    def test_no_live_caller(self):
        offenders: list[str] = []
        scanned: set[str] = set()
        for path in _repo_walk.repo_files(_PROJECT_ROOT, self._PATTERNS):
            rel = _repo_walk.relative_posix(path, _PROJECT_ROOT)
            if not self._in_caller_surface(rel):
                continue
            # This guard's OWN scope choices, applied on top of the walker.
            # Skip the route registrations + the dashboard.js legacy dead
            # file + the SPA mock sim.js + the legacy web/legacy_index.html
            # shell (the dead web/js/dashboard.js caller of /api/preview-build
            # lives here) + runtime artifacts. The old `.claude` / `_archive`
            # hand-skips are gone: tests/_repo_walk already does those.
            if rel.startswith("dashboard/routes_"):
                continue
            if rel in {"web/js/dashboard.js", "web/js/sim.js",
                       "web/legacy_index.html"}:
                continue
            if rel.startswith("ops/runtime/"):
                continue
            scanned.add(rel)
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for route in _DELETED_ROUTES:
                # Match the actual URL string (fetch / curl) in code, not
                # bare unquoted prose. Require quote-or-backtick boundary.
                candidates = (
                    f'"{route}"', f"'{route}'", f"`{route}`",
                    f'"{route}?', f"'{route}?", f"`{route}?",
                )
                if any(needle in text for needle in candidates):
                    offenders.append(f"{rel}: refs {route}")
                    break
        _assert_enumeration_reached(self, scanned, self._ENUMERATION_ANCHORS,
                                    "caller-surface")
        self.assertEqual(
            offenders, [],
            "Live callers found for deleted routes: " + "; ".join(offenders),
        )


class HandlerSymbolAbsenceTests(unittest.TestCase):
    """The deleted handler symbol names must not appear as imports elsewhere."""

    # See CallerSurfaceAbsenceTests._ENUMERATION_ANCHORS for the reasoning.
    # Only *.py here, since that is the only pattern this sweep walks.
    _ENUMERATION_ANCHORS: tuple[str, ...] = (
        "web_dashboard.py",
        "dashboard/routes_coach.py",
        "core/build_order.py",
    )

    def test_no_import_of_deleted_handler(self):
        offenders: list[str] = []
        scanned: set[str] = set()
        # tests/_repo_walk owns the infrastructure exclusions (ADR-015). Until
        # 2026-09-09 this walked _PROJECT_ROOT.rglob("*.py") behind a hand-list
        # of `.claude/` + `/_archive/` that removed ZERO files, so it swept 9112
        # .py of which 4772 sat in the gitignored full-repo copies under
        # ops/runtime/responder_export/<sha>/. Those copies carry their own
        # stale copy of THIS file, which the path-exact self-exemption below
        # does not cover - the guard was green only because no line in them
        # happened to hold both "import" and a deleted symbol.
        for path in _repo_walk.repo_files(_PROJECT_ROOT):
            rel = _repo_walk.relative_posix(path, _PROJECT_ROOT)
            if rel == "tests/test_dead_endpoint_cleanup_item186.py":
                # this guard file legitimately lists the names
                continue
            scanned.add(rel)
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line in text.splitlines():
                stripped = line.strip()
                if "import" not in stripped:
                    continue
                for sym in _DELETED_HANDLERS:
                    if sym in stripped:
                        offenders.append(f"{rel}: imports {sym}")
                        break
        _assert_enumeration_reached(self, scanned, self._ENUMERATION_ANCHORS,
                                    "handler-symbol")
        self.assertEqual(
            offenders, [],
            "Deleted handler symbols are still imported: " + "; ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
