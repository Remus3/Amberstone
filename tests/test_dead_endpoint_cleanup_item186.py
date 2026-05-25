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
    "dashboard/routes_bridge.py",
    "dashboard/routes_coach.py",
    "dashboard/routes_diag.py",
    "dashboard/routes_sr_draft.py",
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

    def test_no_live_caller(self):
        offenders: list[str] = []
        for entry in self._CALLER_DIRS:
            base = _PROJECT_ROOT / entry
            if not base.exists():
                continue
            paths: list[Path] = (
                [base] if base.is_file()
                else [p for p in base.rglob("*") if p.is_file()
                      and p.suffix in self._EXTENSIONS]
            )
            for path in paths:
                rel = str(path.relative_to(_PROJECT_ROOT)).replace("\\", "/")
                # Skip the route registrations + the dashboard.js legacy dead
                # file + the SPA mock sim.js + dated archives + the legacy
                # web/legacy_index.html shell (the dead web/js/dashboard.js
                # caller of /api/preview-build lives here) + runtime/cache
                # artifacts.
                if rel.startswith("dashboard/routes_"):
                    continue
                if rel in {"web/js/dashboard.js", "web/js/sim.js",
                           "web/legacy_index.html"}:
                    continue
                if "/_archive/" in rel:
                    continue
                if rel.startswith("ops/runtime/"):
                    continue
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
        self.assertEqual(
            offenders, [],
            "Live callers found for deleted routes: " + "; ".join(offenders),
        )


class HandlerSymbolAbsenceTests(unittest.TestCase):
    """The deleted handler symbol names must not appear as imports elsewhere."""

    def test_no_import_of_deleted_handler(self):
        offenders: list[str] = []
        for path in _PROJECT_ROOT.rglob("*.py"):
            rel = str(path.relative_to(_PROJECT_ROOT)).replace("\\", "/")
            if rel.startswith(".claude/") or "/_archive/" in rel:
                continue
            if rel == "tests/test_dead_endpoint_cleanup_item186.py":
                # this guard file legitimately lists the names
                continue
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
        self.assertEqual(
            offenders, [],
            "Deleted handler symbols are still imported: " + "; ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
