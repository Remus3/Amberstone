# arch: canonical TCP port registry for RC + Daemon Slayer, and the cross-project block reservations | section=core | frozen=no
"""Riot Commander port registry.

Three projects run concurrently on Legion - Riot Commander (this repo, which
contains Daemon Slayer), Sibling-A and Sibling-C - and until 2026-08-01
none of them could answer "which ports are mine" without grepping bind sites
and filtering vendored noise out of the result. Sibling-C solved it first with
`core/ports.py` plus a guard test; this module is the same idea for RC.

Import these constants. A port literal spelled out at a bind site is how the
registry silently goes stale, and `tests/test_ports.py` fails when a live
definition site disagrees with the value here - so this file is checked, not
merely descriptive.

**Block reservations (operator-assigned 2026-08-01).** The blocks are wider
than current use on purpose: the point is that a new service can be added to
any project without first re-auditing the other two.

    8770-8789   Sibling-C        (in use: 8777 8778 8779 8780 8783)
    8860-8879   Daemon Slayer   (RESERVED - see MIGRATION below)
    8888-8895   Riot Commander  (in use: 8888 8889 8890 8891 8895)
    8900-8919   Sibling-A (in use: 8901)

RC keeps 8888-8895 because moving a live control plane is churn with no payoff;
the block is stated so the other two projects can route around it.

**MIGRATION, deliberately not done yet.** Daemon Slayer today binds 8893 and
8894, which sit INSIDE the RC block rather than the DS block. Renumbering is
Tier-2, not cosmetic: 8893 appears in ~186 places, `agents/daemon_slayer/` is
mirrored into `Share/src`, and the move needs a Share sync plus a `:8893`
bounce plus the ENGINE doc anchors. So the block is reserved now and the move
happens on its own ticket. `DS_ENGINE` / `DS_MATCH_DB_MCP` below are the values
that are TRUE TODAY; `DS_BLOCK` is where they are going.

Do not renumber 8895. Mission Control shipped 2026-07-31 as its own process
with its own scheduled task; it is the one port whose move would take the
control plane down with it.
"""
from __future__ import annotations

# --- Riot Commander core (block 8888-8895) ---------------------------------

DASHBOARD = 8888
"""RC dashboard, HTTPS. Defined at `dashboard/server.py:28`."""

VISION = 8889
"""Vision server, in-process and self-healing. `vision_server/_config.py:34`.

`core/moon_proxy.py:22` MOON_PORT is the same listener seen from the client
side; it is a frozen file, so the duplicate literal there is expected.
"""

AGENTS_SUPERVISOR = 8890
"""Phase 3 agents supervisor. `agents/_supervisor_common.py:32` WEB_PORT.

`:8888` proxies a fixed path list here (`dashboard/_handler.py:115`) so the
dashboard never has to know this number.
"""

AGENTS_WS = 8891
"""Phase 3 WS relay / ingest. `agents/_supervisor_common.py:31` WS_PORT."""

MISSION_CONTROL = 8895
"""Mission Control, the headless-lane control plane. `mc/server.py:36`.

Its own process and scheduled task since S10 (2026-07-31), deliberately NOT
served by the dashboard, so an overlay or dashboard restart cannot take the
control plane with it.
"""

# --- Daemon Slayer (currently inside the RC block; block 8860-8879 reserved)

DS_ENGINE = 8893
"""Daemon Slayer combat-math engine, HTTP (not HTTPS).

Defined at `agents/daemon_slayer/server.py:98` and `core/daemon_slayer_client.py:32`.
Mirrored into `Share/src`, which is why renumbering is Tier-2.
"""

DS_MATCH_DB_MCP = 8894
"""Local DS + match-DB MCP, scheduled task `RC-DS-MatchDB-MCP`."""

# --- Third-party, not ours to assign ---------------------------------------

LIVE_CLIENT = 2999
"""Riot's Live Client Data API. Riot owns this number; it is here so a block
scheme never accidentally claims it. The HOST is config, not code - see
`core/game_host.py` `RC_GAME_HOST`.
"""

# --- Block reservations ----------------------------------------------------

RC_BLOCK = range(8888, 8896)
DS_BLOCK = range(8860, 8880)
LW_BLOCK = range(8900, 8920)
RM_BLOCK = range(8770, 8790)

BLOCKS = {
    "rc": RC_BLOCK,
    "ds": DS_BLOCK,
    "lw": LW_BLOCK,
    "rm": RM_BLOCK,
}
"""Every project's reserved range, keyed by short name.

LW and RM are listed so RC can prove disjointness without reading their trees.
Sibling-C's own guard test greps its source for foreign port numbers, so do NOT
paste RC's literals into that repo - cite the block, not the port.
"""

ALL = frozenset({
    DASHBOARD, VISION, AGENTS_SUPERVISOR, AGENTS_WS,
    MISSION_CONTROL, DS_ENGINE, DS_MATCH_DB_MCP,
})
"""Every port THIS repo binds. Excludes LIVE_CLIENT, which Riot binds."""


def block_for(port: int) -> str | None:
    """Return the short name of the block owning `port`, or None if unassigned.

    Order matters only in that the blocks are disjoint by construction; the
    disjointness itself is asserted in `tests/test_ports.py` rather than
    assumed here.
    """
    for name, block in BLOCKS.items():
        if port in block:
            return name
    return None
