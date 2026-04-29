"""
core/version.py — single source of truth for RC's app-version string.

Semantic versioning, MAJOR.MINOR.PATCH:
  * MAJOR — phase-shaped overhauls (Phase 1/2/3 boundary)
  * MINOR — feature batches that ship together (audit batches, new
            dashboard surfaces, new mode coaches)
  * PATCH — bug fixes + small refactors that don't add features

Bump the constant below; importers (web_dashboard, supervisor health
endpoint, log banner) re-read on next process start. Keep CHANGELOG.md
or the audit-report directory in sync — this file is the canonical
machine-readable value.
"""
from __future__ import annotations

# 3.5.0 — 2026-04-28
#   First version stamp. Reflects: Phase 3 architecture, all 12 audit
#   batches landed (1.x architecture, 5.x cost limiting, dashboard
#   endpoints, UI tile, replay scrubber, recommender, M-02 single-
#   source modes, deferred-frozen pass).
RC_VERSION = "3.5.0"

# Optional build tag — surfaced alongside the version in the dashboard
# footer and /api/health so a hot-fix build is distinguishable from the
# tagged release without a full version bump.
RC_BUILD_TAG = ""


def version_string() -> str:
    """Compact version + build for footer display, e.g. '3.5.0' or
    '3.5.0+hotfix-2026-04-28'."""
    return f"{RC_VERSION}+{RC_BUILD_TAG}" if RC_BUILD_TAG else RC_VERSION
