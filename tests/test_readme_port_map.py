"""The README port map must name every port RC actually binds.

MEASURED 2026-09-06. `README.md` carries a "Port | Service" table presented as
THE port map, and it was missing `:8861` (`DS_MATCH_DB_MCP`) - a port that is in
`core.ports.ALL`, is bound by a live scheduled task (`RC-DS-MatchDB-MCP`), and
holds its own credential since `tools/mcp_token.txt` was split out of the vision
token. Nothing noticed, because nothing compared the two.

This is the same producing-side shape as
`tests/test_docs_operations_test_scope_rm322.py`: `core/ports.py` produces the
truth, the README restates it for a reader, and a restatement with no guard is a
claim that decays. It matters more than an ordinary doc nit because the repo's
own port doctrine (`core/ports.py`, and the cross-project blocks it declares) is
that a band is verified against the OWNING project's registry IN SOURCE, never
against a live scan - a sibling project reading this README to check for a
collision would have been reading an incomplete list.

Deliberately NOT asserted: that the README lists ONLY ports in `ALL`. `:2999` is
in the table on purpose and is not RC's to bind - it is the Riot client's own
Live Client API, which RC reads. A guard that demanded set equality would have
to special-case it, and would then fail the day RC documents another foreign
port it consumes. The invariant that carries the weight is one-directional:
every port RC binds appears in the map.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_README = _REPO / "README.md"

# Rows look like:  | :8888 | Web dashboard (HTTPS) |
_ROW = re.compile(r"^\|\s*:(\d{2,5})\s*\|\s*(.+?)\s*\|\s*$", re.MULTILINE)


def _documented() -> dict[int, str]:
    return {int(p): desc for p, desc in _ROW.findall(_README.read_text(encoding="utf-8"))}


def test_the_parser_actually_finds_the_table():
    """A regex that silently matches nothing would make the real test pass."""
    found = _documented()
    assert len(found) >= 5, (
        f"parsed {len(found)} port rows out of README.md; the table format "
        f"changed and this guard is reading nothing. Rows are expected to look "
        f"like '| :8888 | Web dashboard (HTTPS) |'."
    )


def test_every_port_rc_binds_is_in_the_readme_port_map():
    from core import ports

    documented = _documented()
    missing = sorted(p for p in ports.ALL if p not in documented)
    assert not missing, (
        f"core.ports.ALL binds {missing} but README.md's port map does not list "
        f"{'it' if len(missing) == 1 else 'them'}. The README table is the "
        f"outward-facing restatement of core/ports.py - add the row, or remove "
        f"the port from ALL if it is genuinely gone. Documented: "
        f"{sorted(documented)}; bound: {sorted(ports.ALL)}."
    )


def test_the_documented_ports_are_not_silently_renumbered():
    """Catches a row edited to a port nothing binds - the other direction of the
    same drift, scoped to RC's own block so `:2999` and any future foreign port
    stay legal."""
    from core import ports

    rc_block = {p for p in _documented() if 8860 <= p <= 8919}
    unbound = sorted(rc_block - set(ports.ALL))
    assert not unbound, (
        f"README.md documents {unbound} inside RC's own port block, but "
        f"core.ports.ALL does not bind {'it' if len(unbound) == 1 else 'them'}. "
        f"Either the row is stale or the port was dropped from ALL without "
        f"updating the map."
    )
