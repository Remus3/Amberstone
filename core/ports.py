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

**Block reservations (operator-assigned 2026-08-01, and CONFIRMED IN WRITING by
both siblings the same day).** The blocks are wider than current use on purpose:
the point is that a new service can be added to any project without first
re-auditing the other two.

    8770-8789   Sibling-C        (named: 8777 8778 8779 8780 8783; bound today: 8777 8780)
    8860-8879   Daemon Slayer   (RESERVED - see MIGRATION below)
    8888-8895   Riot Commander  (in use: 8888 8889 8890 8891 8893 8894 8895)
    8900-8919   Sibling-A (named: 8901; bound only while the operator runs it)

RC keeps 8888-8895 because moving a live control plane is churn with no payoff;
the block is stated so the other two projects can route around it.

Provenance, so a later session does not re-open a closed negotiation. Sibling-C
accepted 8770-8789 unchanged and Sibling-A accepted 8900-8919 unchanged;
both replies are in `moon_sync_inbox/` dated 2026-08-01. Neither asked RC to
move anything, and neither owes RC a renumber.

**AUDIT BY SOURCE, NEVER BY NETSTAT.** This is the durable lesson from the
confirmation round, and it inverts the obvious method. LW's monitor is an
operator-launched GUI that is idle most of the time, so a live listener scan on
any ordinary morning finds ZERO Sibling-A ports - LW would read as
portless and the collision would still be waiting. Sibling-C is the same shape
from the other direction: three of its five named ports (8778 8779 8783) are
reserved-and-unbound pending later cycles, so a port scan says "free" about
numbers that are already spoken for. A reservation is a claim about the future;
only source and the owner's own registry can answer it.

**Third-party stock defaults are the next collision, and each project pins its
own.** LW flagged two tools on its roadmap whose stock ports sit outside every
block here. The agreed rule: whoever wires a third-party listener passes it an
explicit port from that project's own block rather than letting it take its
default. Otherwise the defaults quietly become a fourth, unowned, undocumented
block that appears in nobody's tree until it collides.

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

RC carrying all four blocks is an RC-side choice, not a shared convention. Red
Moon deliberately does the opposite: it names only its own ports and proves
disjointness from the negative side, with a guard that fails on any FORBIDDEN
foreign literal (8888, 8889 and 8893 among them) appearing in its source. So do
NOT paste RC's literals into that repo - cite the block, not the port. RM
excluded `moon_sync_inbox/` from that scan on 2026-08-01, which makes prose
notes safe in any file type; the rule above still governs anything TRACKED.
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


def next_free(block: str = "rc", taken=None) -> int:
    """Lowest unallocated port in `block`, so wiring a new service is mechanical.

    Adopted from Sibling-A's `tools/lw_ports.py` (offered back 2026-08-01).
    The value is that adding a service becomes "take this number, name it, pin
    it" instead of a hand-scan of bind sites - and a hand-scan is the exact
    method that nearly handed 8901 to Daemon Slayer.

    Only the RC block can be answered from this repo. `taken` exists for the
    sibling blocks: RC does not know what LW or RM have allocated and must not
    guess, so asking for one of those without passing their allocations raises
    rather than returning a number that would be a fabrication.
    """
    if block not in BLOCKS:
        raise KeyError(f"unknown block {block!r} - known: {', '.join(sorted(BLOCKS))}")
    if taken is None:
        if block not in ("rc", "ds"):
            raise ValueError(
                f"cannot compute a free port in the {block!r} block from this repo - "
                f"pass taken=<that project's allocations>, or ask its owner")
        taken = ALL
    free = sorted(set(BLOCKS[block]) - set(taken))
    if not free:
        raise ValueError(f"the {block!r} block is fully allocated")
    return free[0]
