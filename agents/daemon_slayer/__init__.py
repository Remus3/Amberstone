"""Daemon Slayer — local item-build engine.

Phase 3 + Phase 4 (thin slice + first expansion): stat math + auto-attack
DPS layered with per-item conditional effects from ``effects.py`` —
IE / Kraken / Stormrazor / BT / Shieldbow (thin slice) plus the
energized family (Statikk Shiv, Rapid Firecannon, Voltaic), scaling
procs (Wit's End, Runaan's, Trinity Force, Sundered Sky, Guinsoo's),
the armor pen / reduction layer (LDR, Mortal Reminder, Black Cleaver),
and 13 defensive_only items proving full coverage of the Tier-1 SR /
Arena pool. CallContext + callable ``bonus_damage`` lets stat-scaling
procs bind to ``base_ad`` / ``bonus_ad`` / ``level``.

Item ranker (``rank.py``) and local HTTP server (``server.py``) consume
the same engine; the package stays importable for direct use without
spinning :8893.
"""

ENGINE_VERSION = "0.7.0"
