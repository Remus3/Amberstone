"""Guard: four DS tests cite by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. Each file below carried exactly one
line cite, and all four had rotted:

- ``test_beam.py`` cited ``beam.py:280-360`` for the ``boots_unique=False``
  branch of ``beam.beam_search_build``; the beam-loop gates on that flag have
  since moved below :360, so the range now catches only the note line.
- ``test_quinn_rm89_a20.py`` cited ``rank.py:1146`` for the
  ``exempt_offclass_by_win`` gate; :1146 is the fight-length reweight comment
  inside ``rank.rank_items`` and the gate sits ~150 lines lower.
- ``test_server_listen_backlog.py`` cited
  ``core/daemon_slayer_client.py:95-112`` for the transport-failure-to-None
  mapping; :95-112 straddles ``_emit_ehp_family_seams`` and the top of
  ``_post_json``, and the ``except`` that does the mapping is below it.
- ``test_akshan_passive_carry_rm42.py`` cited ``server.py:1609`` for the
  docstring RM-42 corrected; that docstring is ``_route_rank_mage``'s, now
  near :1883.

The tests below pin the cites and the claims they carried by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import beam, cli, rank, server
from core import daemon_slayer_client

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "agents" / "daemon_slayer" / "tests"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d")

TARGETS = {
    "test_beam.py": ("``beam.beam_search_build``",),
    "test_quinn_rm89_a20.py": ("``rank.rank_items``",),
    "test_server_listen_backlog.py": ("`core.daemon_slayer_client._post_json`",),
    "test_akshan_passive_carry_rm42.py": ("`server._route_rank_mage`",),
}


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "live (beam.py:280-360, exposed",
        "(``rank.py:1146``)",
        "`core/daemon_slayer_client.py:95-112` maps",
        "A docstring at `server.py:1609` asserted",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "``beam.beam_search_build``",
        "`core.daemon_slayer_client._post_json`",
        "test_beam.py:",
    ):
        assert not _LINE_CITE.search(sample), sample


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (TESTS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    text = (TESTS / name).read_text(encoding="utf-8")
    for symbol in TARGETS[name]:
        assert symbol in text, f"{name}: {symbol}"


def test_boots_unique_is_a_live_beam_knob():
    param = inspect.signature(beam.beam_search_build).parameters["boots_unique"]
    assert param.default is True
    assert "if not boots_unique:" in inspect.getsource(beam.beam_search_build)
    assert "--no-boots-unique" in inspect.getsource(cli)
    assert '_opt_bool(body, "boots_unique", True)' in inspect.getsource(
        server._route_beam
    )


def test_exempt_offclass_by_win_is_gated_in_rank_items():
    param = inspect.signature(rank.rank_items).parameters["exempt_offclass_by_win"]
    assert param.default is False
    assert "if exempt_offclass_by_win:" in inspect.getsource(rank.rank_items)


def test_post_json_maps_transport_failure_to_none():
    src = inspect.getsource(daemon_slayer_client._post_json)
    assert "except (URLError, HTTPError, socket.timeout, TimeoutError, ConnectionError)" in src
    assert src.count("return None") >= 2


def test_rank_mage_docstring_carries_the_rm42_correction():
    doc = inspect.getdoc(server._route_rank_mage)
    assert "since RM-42 - by ``/rank`` at default False" in doc
