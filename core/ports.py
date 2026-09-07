# arch: canonical TCP port registry for RC + Daemon Slayer, and the cross-project block reservations | section=core | frozen=no
"""Amberstone port registry.

Projects run concurrently on Legion - Amberstone (this repo, which contains
Daemon Slayer), Sibling-A, Sibling-C, Sibling-D, Sibling-E and
Sibling-B - and until 2026-08-01 none of them could answer "which ports are
mine" without grepping bind sites and filtering vendored noise out of the
result. Sibling-C solved it first with `core/ports.py` plus a guard test; this
module is the same idea for RC.

Three of them did not exist when the blocks were first negotiated (Sibling-D
and Sibling-E were both specced after 2026-08-01, Sibling-B on 2026-09-06),
which is how BOTH collisions recorded below happened. A project scaffolded after
the registry was drawn is the recurring shape, not a one-off.

SIBLING-C IS ARCHIVED (2026-09-06, read-only at a sibling private repo; the
working copy at `C:\\Sibling-C\\` was deleted). Its block is deliberately NOT
freed or reallocated here. Reassigning a retired project's band is an operator
decision, and leaving 8770-8789 reserved costs nothing - a dead project cannot
collide, but a half-remembered reassignment can.

Import these constants. A port literal spelled out at a bind site is how the
registry silently goes stale, and `tests/test_ports.py` fails when a live
definition site disagrees with the value here - so this file is checked, not
merely descriptive.

**Block reservations (operator-assigned 2026-08-01, and CONFIRMED IN WRITING by
both siblings the same day).** The blocks are wider than current use on purpose:
the point is that a new service can be added to any project without first
re-auditing the other two.

    8770-8789   Sibling-C        (ARCHIVED 2026-09-06; block held, not reallocated)
    8790-8809   Sibling-B    (named: 8790 PityEngine, 8791 dashboard; 8792-8809 unassigned)
    8810-8819   Sibling-D    (named: 8810-8814; nothing bound)
    8860-8879   Daemon Slayer   (in use: 8860 8861 - see MIGRATION below)
    8888-8895   Amberstone      (in use: 8888 8889 8890 8891 8895), plus 2999,
                                which RIOT binds - see LIVE_CLIENT
    8900-8919   Sibling-A (named: 8900 8901; bound only while the operator runs it)
    8920-8939   Sibling-E      (named: 8920; nothing bound yet - see COLLISION below)

Three of these were assigned after the original round: the operator widened
Sibling-D from 8810-8814 to 8810-8819 on 2026-08-27, assigned Sibling-E
8920-8939 on 2026-08-29, and Sibling-B reserved 8790-8809 on 2026-09-06
(`moon_sync_inbox/2026-09-06-1918-from-RSC-port-block-reservation.md`). The
first two are recorded independently in `C:/Sibling-D/CLAUDE.md`, which
carried a six-row table when last read. Whether that table has grown the rsc
row is a fact about THAT tree, not this one - do not assert it from here.

RC keeps 8888-8895 because moving a live control plane is churn with no payoff;
the block is stated so the other two projects can route around it.

Provenance, so a later session does not re-open a closed negotiation. Sibling-C
accepted 8770-8789 unchanged and Sibling-A accepted 8900-8919 unchanged;
both replies are in `moon_sync_inbox/` dated 2026-08-01. Neither asked RC to
move anything, and neither owes RC a renumber.

**COLLISION FOUND AND CLEARED 2026-08-29, and it is the rule below proving
itself.** Sibling-E allocated itself 8900-8911 with a dashboard on 8901 - a
band wholly inside Sibling-A's block, whose 8900 and 8901 are LW's
RUNDASH and MONITOR (`C:/Sibling-A/tools/lw_ports.py` - the local root
gained a real space on 2026-09-06; the GitHub repo keeps the hyphen). It was found by
reading SOURCE: CS's `BOOTSTRAP.md` recorded "8900-8911 all free and unbound on
this machine" and its `config/ports.json` said "verified free at allocation
time", which is exactly the listener-scan method this next paragraph refutes -
LW's monitor is an operator-launched GUI, so on any ordinary morning it reads
as portless and the band reads as free. CS had already met the symptom and
mis-filed it: its BACKLOG said 8901 "has been held since 2026-08-16 by an
unrelated process", when in fact 8901 was never CS's to hold. CS names
Sibling-A in zero files, so it never read the owner's registry. Moved to
8920-8939 by operator assignment.

**SECOND COLLISION, CAUGHT BEFORE IT BOUND ANYTHING (2026-09-06).**
Sibling-B scaffolded its compute engine on **8870** - chosen by mirroring
Daemon Slayer's 8860 and adding ten - which is inside DS's reserved 8860-8879.
This one is worth more than the first, because it shows the failure is SILENT
in both directions: nothing was listening on 8870, DS binds only 8860 and 8861,
so no bind failed, no log warned, and a listener scan of that number reads clean
every second of every day. It surfaced only because RSC read THIS file instead
of the machine. It has migrated to 8790 and pinned the number against the module
that binds it. Note also that RSC verified 8790 free partly from
`RM_BLOCK = range(8770, 8790)` - whose end is EXCLUSIVE, so Sibling-C stops at
8789. A registry that is read by siblings must be read correctly by them, which
is an argument for ranges over prose.

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

**MIGRATION, DONE 2026-08-01 (RM-129).** Daemon Slayer bound 8893 and 8894 -
inside the RC block rather than its own - until this move. It now binds 8860
and 8861. `DS_ENGINE` / `DS_MATCH_DB_MCP` below are both TRUE TODAY and inside
`DS_BLOCK`, and `tests/test_ports.py` asserts exactly that.

Two things about the move worth keeping, because both would be re-derived
wrongly. First, the "~186 places" this ticket was filed with was SUBSTRING
noise - `8893` matches inside longer numbers, and `data/daemon_slayer/
spell_cast_rates.json` scored four hits that were all fragments of floats. The
real count was 499 standalone occurrences across 190 files, measured with a
digit-bounded pattern and, for `.py`, an AST pass that ignores docstrings.

Second, the old numbers deliberately SURVIVE in one class of file: anything
recording a measurement taken against the old port. `champion_block_index.json`
and `core/ds_support_route_overrides.json` carry live-A/B provenance ("measured
on live :8893"), and the append-only history (LEDGER, history_notes,
ROADMAP_HISTORY, CHANGELOG, dated specs and audits) says where things were at
the time. Rewriting those would falsify evidence, so a residual `8893` there is
correct and must not be swept.

Do not renumber 8895. Mission Control shipped 2026-07-31 as its own process
with its own scheduled task; it is the one port whose move would take the
control plane down with it.
"""
from __future__ import annotations

# --- Amberstone core (block 8888-8895) ---------------------------------

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

DS_ENGINE = 8860
"""Daemon Slayer combat-math engine, HTTP (not HTTPS).

Defined at `agents/daemon_slayer/server.py:98` and `core/daemon_slayer_client.py:32`.
"""

DS_MATCH_DB_MCP = 8861
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
RSC_BLOCK = range(8790, 8810)
LL_BLOCK = range(8810, 8820)
CS_BLOCK = range(8920, 8940)

BLOCKS = {
    "rc": RC_BLOCK,
    "ds": DS_BLOCK,
    "lw": LW_BLOCK,
    "rm": RM_BLOCK,
    "rsc": RSC_BLOCK,
    "ll": LL_BLOCK,
    "cs": CS_BLOCK,
}
"""Every project's reserved range, keyed by short name.

LW, RM, RSC, LL and CS are listed so RC can prove disjointness without reading
their trees. Listing a sibling is NOT a licence to bind in its range, and it is
not a claim that RC knows what the sibling has allocated INSIDE the block -
`next_free` refuses to answer for a sibling for exactly that reason.

RC carrying all five blocks is an RC-side choice, not a shared convention. Red
Moon deliberately does the opposite: it names only its own ports and proves
disjointness from the negative side, with a guard that fails on any FORBIDDEN
foreign literal (8888, 8889 and 8860 among them) appearing in its source. So do
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

    Only the RC and DS blocks can be answered from this repo. `taken` exists
    for the sibling blocks: RC does not know what LW, RM, RSC, LL or CS have
    allocated and must not guess, so asking for one of those without passing
    their allocations raises rather than returning a number that would be a
    fabrication.
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
