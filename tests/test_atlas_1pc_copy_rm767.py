"""RM-767: atlas.html node copy carries no live 2-PC role (1-PC, ADR-011/012).

Node ``rca2`` ("Agent 2 - Backend Ingest") said Agent 2 "Runs the WebSocket
server and SMB push - win/loss is left NULL in the MVP". The Legion -> Game-PC
SMB push was retired (ADR-011, phase3-d026) and its module deleted 2026-10-22
(C6 F4); win/loss is now inferred from the summary and the NULL rest is
backfilled from postgame_stats by ``win_reconcile``. The atlas is the
operator-kept hand-built page (LEDGER 1713), so these guards pin the copy
itself: every capability the rca2 desc names must exist in Agent 2's package,
and no node desc may describe a Game-PC / SMB / cross-machine role as live.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ATLAS = REPO_ROOT / "atlas.html"
AGENT2 = REPO_ROOT / "agents" / "agent2_backend"

# Wording that only fits the retired 2-PC topology (Game-PC share, forwarder,
# cross-machine push). A desc may still name one when it says so is history.
_TWO_PC = re.compile(
    r"\bSMB\b|Game[- ]?PC|\bForwarder\b|RCClient|cross-machine|kiosk", re.I
)
_RETIRED = re.compile(r"retired|dead code|decommission", re.I)


@pytest.fixture(scope="module")
def html() -> str:
    assert ATLAS.is_file(), f"missing {ATLAS}"
    return ATLAS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def nodes(html: str) -> list[dict]:
    start = html.index("var NODES=")
    body = html[start : html.index("var DUST=", start)]
    arr = json.loads(body[body.index("[") : body.rindex("]") + 1])
    # Not vacuous: the parse reached the real node table.
    assert len(arr) > 100, f"NODES parse collapsed: {len(arr)} nodes"
    return arr


def _node(nodes: list[dict], node_id: str) -> dict:
    for n in nodes:
        if n["id"] == node_id:
            return n
    raise AssertionError(f"atlas node {node_id!r} missing")


def test_rca2_desc_drops_the_retired_share_push(nodes: list[dict]) -> None:
    # (Named without the deleted module's name: tests/test_c6_game_pc_push_
    # retired.py fails on any live file that spells it.)
    desc = _node(nodes, "rca2")["desc"]
    assert "SMB" not in desc, desc
    assert not (AGENT2 / ("smb" + "_push.py")).exists()
    # The MVP-era "win/loss left NULL" claim is stale: win_reconcile fills it.
    assert "left NULL" not in desc, desc


def test_rca2_desc_names_only_what_agent2_runs(nodes: list[dict]) -> None:
    desc = _node(nodes, "rca2")["desc"]
    # Each capability the copy names is backed by a module in the package.
    assert "game-summary" in desc and (AGENT2 / "game_ingest.py").is_file()
    assert "postgame_stats" in desc and (AGENT2 / "win_reconcile.py").is_file()
    assert "WebSocket" in desc and (AGENT2 / "ws_server.py").is_file()
    # The relay is Legion-local since 1-PC; the copy says so.
    assert "Legion-local" in desc, desc
    assert "Legion-only" in (AGENT2 / "ws_server.py").read_text(encoding="utf-8")


def test_no_node_desc_describes_a_live_two_pc_role(nodes: list[dict]) -> None:
    offenders = [
        f"{n['id']}: {n['desc']}"
        for n in nodes
        if _TWO_PC.search(n.get("desc", "")) and not _RETIRED.search(n["desc"])
    ]
    assert not offenders, "atlas node copy names a live 2-PC role:\n" + "\n".join(
        offenders
    )


def test_page_text_outside_data_uris_names_no_smb(html: str) -> None:
    # The inlined font data: URIs are base64 and carry "SMB" by chance, so
    # strip them before scanning the authored text.
    text = re.sub(r"data:[^\"')\s]+", "", html)
    hits = [m.start() for m in re.finditer(r"\bSMB\b", text)]
    assert not hits, f"atlas.html authored text still names SMB at offsets {hits}"
