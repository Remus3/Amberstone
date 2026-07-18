# arch: offline tests for the Meraki attackdamageperlevel backfill | section=tools-tests | frozen=no
"""Offline unit tests for ``fetch_meraki_perlevel_overlay`` in
``tools/daemon_slayer_extract.py``.

NO network. Both fetch paths are injected via the ``_bulk_fn`` / ``_per_champ_fn``
test seams.

Regression context (2026-07-18): the backfill fetched Meraki's PER-CHAMPION
endpoint (``.../champions/<id>.json``), which 404s for champions Meraki has not
published individually. Meraki's BULK endpoint (``.../champions.json``) carries
171 champions including Yunara at ``perLevel = 2.5``, but the per-champion URL
404s for her - so she was stored with ``attackdamageperlevel = 0``. DDragon
ships 0 for EVERY champion (Riot stopped exporting AD growth), so a failed
backfill silently persists a false zero. Yunara is a marksman: her whole kit
scales off AD.

Exactly 4 champions stored 0 before this fix - Locke, Zaahen, Yunara, Senna -
and only Senna's zero is genuine (she gains AD from Mist souls, and Meraki
really does report 0 for her).
"""
from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import daemon_slayer_extract as E  # noqa: E402


def _champ(per_level):
    """Minimal Meraki champion payload carrying only the backfilled field."""
    return {"stats": {"attackDamage": {"perLevel": per_level}}}


class TestBulkBackfill:
    def test_bulk_recovers_champion_missing_from_per_champion_endpoint(self):
        """The Yunara regression: present in bulk, 404 per-champion."""
        calls = []

        def per_champ(cid):
            calls.append(cid)
            return None  # simulates the 404

        overlay = E.fetch_meraki_perlevel_overlay(
            {"Yunara"},
            _bulk_fn=lambda: {"Yunara": _champ(2.5)},
            _per_champ_fn=per_champ,
        )
        assert overlay == {"Yunara": {"attackdamageperlevel": 2.5}}
        assert calls == [], "bulk hit should make the per-champion fetch unnecessary"

    def test_bulk_used_for_every_champion_it_covers(self):
        overlay = E.fetch_meraki_perlevel_overlay(
            {"Lux", "Yunara"},
            _bulk_fn=lambda: {"Lux": _champ(3.3), "Yunara": _champ(2.5)},
            _per_champ_fn=lambda cid: None,
        )
        assert overlay == {
            "Lux": {"attackdamageperlevel": 3.3},
            "Yunara": {"attackdamageperlevel": 2.5},
        }

    def test_champion_absent_from_bulk_falls_back_to_per_champion(self):
        """Locke / Zaahen are absent from bulk; the fallback must still run."""
        overlay = E.fetch_meraki_perlevel_overlay(
            {"Locke"},
            _bulk_fn=lambda: {"Lux": _champ(3.3)},
            _per_champ_fn=lambda cid: _champ(4.2) if cid == "Locke" else None,
        )
        assert overlay == {"Locke": {"attackdamageperlevel": 4.2}}

    def test_bulk_failure_falls_back_to_per_champion_for_all(self):
        """Old behaviour is preserved when the bulk endpoint is unreachable."""
        overlay = E.fetch_meraki_perlevel_overlay(
            {"Lux", "Ahri"},
            _bulk_fn=lambda: None,
            _per_champ_fn=lambda cid: _champ(3.3) if cid == "Lux" else None,
        )
        assert overlay == {"Lux": {"attackdamageperlevel": 3.3}}

    def test_genuine_zero_is_not_written(self):
        """Senna really is 0; the overlay must not fabricate a value for her."""
        overlay = E.fetch_meraki_perlevel_overlay(
            {"Senna"},
            _bulk_fn=lambda: {"Senna": _champ(0)},
            _per_champ_fn=lambda cid: None,
        )
        assert overlay == {}

    def test_malformed_bulk_entry_is_skipped_not_fatal(self):
        overlay = E.fetch_meraki_perlevel_overlay(
            {"Lux", "Broken"},
            _bulk_fn=lambda: {"Lux": _champ(3.3), "Broken": {"stats": None}},
            _per_champ_fn=lambda cid: None,
        )
        assert overlay == {"Lux": {"attackdamageperlevel": 3.3}}

    def test_bulk_fetched_once_regardless_of_roster_size(self):
        hits = []
        E.fetch_meraki_perlevel_overlay(
            {f"C{i}" for i in range(50)},
            _bulk_fn=lambda: (hits.append(1), {f"C{i}": _champ(1.5) for i in range(50)})[1],
            _per_champ_fn=lambda cid: None,
        )
        assert len(hits) == 1
