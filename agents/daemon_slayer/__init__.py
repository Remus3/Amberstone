"""Daemon Slayer — local item-build engine.

Phase 3 + Phase 4 thin slice: stat math + auto-attack DPS (now layered
with per-item conditional effects from `effects.py` for IE / Kraken /
Stormrazor / BT / Shieldbow) + item ranker, exposed over a local HTTP
server on `:8893` (`server.py`). The package is still importable for
direct use without spinning the server.
"""

ENGINE_VERSION = "0.6.0"
