"""Guard (WP-F6a): docs/ARCHITECTURE.md must not carry a stale engine header.

ARCHITECTURE.md:172 used to recite the live engine identity verbatim
("547 item effects, ENGINE_VERSION 1.153.0, 7537 tests, patch 16.13.1").
CI runs no pytest, so the line drifted silently on every ENGINE bump - it
read 1.153.0 / 7537 long after the engine reached 1.154.0 / 7557.

The fix removes the drift-prone numeric recital and points at the
drift-guarded source of truth (docs/DAEMON_SLAYER.md status banner +
agents/daemon_slayer/__init__.py ENGINE_VERSION). This guard pins that
intent so a future edit that re-hardcodes a version literal fails locally:

  * any ``ENGINE_VERSION <semver>`` literal in ARCHITECTURE.md MUST equal
    the live ENGINE_VERSION (so a stale restatement fails);
  * ARCHITECTURE.md MUST keep a pointer to docs/DAEMON_SLAYER.md for the
    live engine identity (so the recital is not silently re-inlined).

It does NOT pin item-effect / test counts - those are approximate prose
that belongs (drift-guarded) in DAEMON_SLAYER.md, not here. ASCII only
(CLAUDE.md hard rule).
"""
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ARCH = _REPO_ROOT / "docs" / "ARCHITECTURE.md"
_INIT = _REPO_ROOT / "agents" / "daemon_slayer" / "__init__.py"

_SEMVER = r"\d+\.\d+\.\d+"
_INIT_ENGINE = re.compile(rf'^ENGINE_VERSION = "({_SEMVER})"', re.MULTILINE)
# Match the engine-identity literal specifically: the token ENGINE_VERSION
# followed by a semver. Per-feature tags like "(ENGINE 1.38.0)" use the
# bare word ENGINE and are intentionally not matched.
_ARCH_ENGINE = re.compile(rf"ENGINE_VERSION\s+({_SEMVER})")


def _live_engine_version() -> str:
    m = _INIT_ENGINE.search(_INIT.read_text(encoding="utf-8"))
    assert m, "no ENGINE_VERSION literal in agents/daemon_slayer/__init__.py"
    return m.group(1)


def test_architecture_engine_literals_match_live_or_absent():
    """No ENGINE_VERSION literal in ARCHITECTURE.md may differ from live."""
    live = _live_engine_version()
    found = _ARCH_ENGINE.findall(_ARCH.read_text(encoding="utf-8"))
    stale = sorted({v for v in found if v != live})
    assert not stale, (
        f"docs/ARCHITECTURE.md hardcodes stale ENGINE_VERSION {stale} "
        f"(live = {live} from agents/daemon_slayer/__init__.py). Point at "
        "docs/DAEMON_SLAYER.md for the live identity instead of restating it."
    )


def test_architecture_points_to_daemon_slayer_doc():
    """ARCHITECTURE.md must defer to the drift-guarded SOT for engine truth."""
    text = _ARCH.read_text(encoding="utf-8")
    assert "DAEMON_SLAYER.md" in text, (
        "docs/ARCHITECTURE.md no longer references docs/DAEMON_SLAYER.md - the "
        "live engine identity pointer was lost; re-add it so the recital is "
        "not silently re-inlined."
    )
