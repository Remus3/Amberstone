"""Sync test: CLAUDE.md 'Frozen files' ↔ bridge_watcher_config.json legion.escalate_always.

CLAUDE.md is the canonical source of truth for the project's frozen-file list.
The bridge watcher's `legion.escalate_always` must contain every frozen path,
because that list drives `_has_frozen_intent()` — the gate that escalates
auto-action bridge tasks attempting to write a frozen file.

Drift here is a real safety gap, not just docs noise: a CLAUDE.md entry that
isn't mirrored in escalate_always means a bridge task that mentions writing
that path would slip past the gate.

History: s173.2 closed the Legion `/process-bridge-tasks` skill-spec half of
this finding by deferring to CLAUDE.md at runtime; this test closes the
`bridge_watcher_config.json` half by enforcing equality at CI time.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = ROOT / "CLAUDE.md"
CONFIG_JSON = ROOT / "tools" / "bridge_watcher_config.json"

# Paths legitimately in escalate_always that are NOT source files in CLAUDE.md's
# frozen list. restart_trigger.txt is a supervisor sentinel — writing it is a
# valid restart trigger from the operator, but a bridge auto-action attempting
# the same write must still escalate for review.
EXTRA_PROTECTED: frozenset[str] = frozenset({"restart_trigger.txt"})


def _parse_claude_md_frozen_files() -> set[str]:
    """Extract backtick-quoted paths from the CLAUDE.md 'Frozen files' bullet block.

    Bullet shape (single bullet, multi-line continuation):

        - **Frozen files** (do not modify without explicit user approval):
          `main.py`, `core/log_setup.py`, ...
          ...
          `dashboard/routes_bridge_pending.py`, `ops/RC-BridgeWatcher.xml`.

    Block ends at the next `## ` heading or top-level `- ` bullet.
    """
    text = CLAUDE_MD.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("- **Frozen files**"):
            start = i
            break
    if start is None:
        raise AssertionError(
            "CLAUDE.md is missing the `- **Frozen files**` bullet. "
            "Either the bullet was renamed (update this parser) or removed "
            "(reconsider the whole sync invariant)."
        )

    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if line.startswith("- "):
            break
        block.append(line)

    return set(re.findall(r"`([^`]+)`", "\n".join(block)))


def _parse_config_escalate_always() -> set[str]:
    config = json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
    return set(config["legion"]["escalate_always"])


def test_legion_escalate_always_contains_every_claude_md_frozen_file() -> None:
    claude_frozen = _parse_claude_md_frozen_files()
    config_escalate = _parse_config_escalate_always()
    missing = claude_frozen - config_escalate
    assert not missing, (
        "Frozen files declared in CLAUDE.md are missing from "
        "tools/bridge_watcher_config.json legion.escalate_always — the "
        "watcher's intent gate cannot protect them:\n"
        f"  {sorted(missing)}\n"
        "Add them to escalate_always (or remove from CLAUDE.md if no "
        "longer frozen)."
    )


def test_legion_escalate_always_extras_are_on_allowlist() -> None:
    claude_frozen = _parse_claude_md_frozen_files()
    config_escalate = _parse_config_escalate_always()
    extras = config_escalate - claude_frozen
    unexpected = extras - EXTRA_PROTECTED
    assert not unexpected, (
        "tools/bridge_watcher_config.json legion.escalate_always contains "
        "paths that are neither in CLAUDE.md's Frozen files list nor on the "
        f"EXTRA_PROTECTED allowlist in this test: {sorted(unexpected)}\n"
        "Either declare them frozen in CLAUDE.md or extend EXTRA_PROTECTED "
        "with a comment explaining why they're escalation-only."
    )


def test_claude_md_frozen_parser_sanity() -> None:
    """Guard against parser regressions that silently return zero entries."""
    paths = _parse_claude_md_frozen_files()
    assert len(paths) >= 20, (
        f"Parser found only {len(paths)} frozen paths in CLAUDE.md; "
        "expected >= 20. The Frozen files bullet may have been reformatted "
        "in a way the parser doesn't recognize."
    )
