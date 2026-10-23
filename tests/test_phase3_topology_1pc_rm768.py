"""RM-768: the phase3 seed names Legion as the only runtime host (1-PC, ADR-011).

``merge_resolved_decisions`` (ops/phase3_setup.py) refreshes every static
block of agents/state/resolved_decisions.json from the ``RESOLVED_DECISIONS``
literal and preserves only the locked-decision register. C6 F3 rewrote
decision ``phase3-d011`` to the 1-PC record, but the literal still carried a
3-machine ``topology`` (``legion_pc`` + ``game_pc`` + ``moon_pc``) and the
retired Game-PC SMB share in ``cross_machine`` / ``bypass_mode``, so any
re-run wrote the retired Game-PC straight back. These guards pin the seed
itself and the tracked file as a re-run of it.

Placeholders only (CLAUDE.md topology): ``rc-host`` = the node name,
``100.64.0.x`` = a tailnet address; the real ones are per-host config in the
gitignored ops/local_hosts.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ops.phase3_setup import RESOLVED_DECISIONS, merge_resolved_decisions

REPO_ROOT = Path(__file__).resolve().parent.parent
DECISIONS = REPO_ROOT / "agents" / "state" / "resolved_decisions.json"

_RETIRED_ROLE_KEYS = ("game_pc", "gamepc", "moon_pc", "peer_pc")
# Wording / addresses that only fit the retired 2-PC SMB path.
_TWO_PC = re.compile(r"Game[-_ ]?PC|RCClient|\bSMB\b|smb_|cmdkey|forwarder", re.I)
_RETIRED = re.compile(r"retired|decommissioned", re.I)
_DOTTED_QUAD = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def _static_blocks(doc: dict) -> dict:
    # The decisions register is history and accretes at runtime; the rest is
    # the generator-owned static register.
    return {k: v for k, v in doc.items() if k != "decisions"}


def _strings(obj: object):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def test_seed_topology_has_no_game_pc_role() -> None:
    topo = RESOLVED_DECISIONS["topology"]
    stale = [k for k in topo if k.lower() in _RETIRED_ROLE_KEYS]
    assert not stale, f"seed topology still carries retired roles: {stale}"


def test_seed_topology_names_legion_as_only_runtime_host() -> None:
    topo = RESOLVED_DECISIONS["topology"]
    assert topo["runtime_hosts"] == ["legion_pc"]
    assert topo["legion_pc"] == "rc-host"
    assert topo["legion_tailnet_address"] == "100.64.0.x"
    assert topo["install_root"] == "<repo>\\"


def test_seed_static_blocks_carry_no_address() -> None:
    # Placeholders only: no dotted quad survives anywhere in the static
    # register (the Game-PC LAN address used to sit in topology AND in every
    # cross_machine path).
    hits = [s for s in _strings(_static_blocks(RESOLVED_DECISIONS))
            if _DOTTED_QUAD.search(s)]
    assert not hits, f"seed static blocks still carry an address: {hits}"


def test_seed_static_blocks_name_no_live_two_pc_path() -> None:
    strings = list(_strings(_static_blocks(RESOLVED_DECISIONS)))
    assert len(strings) > 50, f"static-block walk collapsed: {len(strings)}"
    live = [s for s in strings if _TWO_PC.search(s) and not _RETIRED.search(s)]
    assert not live, f"seed static blocks still describe the 2-PC path: {live}"


def test_seed_cross_machine_is_a_retired_marker() -> None:
    assert RESOLVED_DECISIONS["cross_machine"] == {
        "status": "retired",
        "superseded_by": ["phase3-d021", "phase3-d024", "phase3-d026"],
    }
    assert (RESOLVED_DECISIONS["bypass_mode"]["cross_machine_mechanism"]
            == "retired_see_phase3-d026")


def test_seed_version_pin_unchanged() -> None:
    # Fail-closed at startup (EXPECTED_DECISIONS_VERSION); never bump here.
    assert RESOLVED_DECISIONS["version"] == "phase3-1.1"


def test_tracked_register_is_a_rerun_of_the_seed() -> None:
    data = json.loads(DECISIONS.read_text(encoding="utf-8"))
    assert data["version"] == "phase3-1.1"
    assert merge_resolved_decisions(data) == data, (
        "agents/state/resolved_decisions.json static blocks drifted from "
        "ops/phase3_setup.py RESOLVED_DECISIONS - regenerate the file"
    )
    assert "game_pc" not in data["topology"]
