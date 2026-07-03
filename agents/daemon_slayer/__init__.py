"""Daemon Slayer - local item-build engine.

Stat math + auto-attack DPS layered with per-item conditional effects
(``effects.py``), single-slot item ranking (``rank.py``), full-build beam
search (``beam.py``), the V2 bounded-combat substrate (mana / runes / passive
procs / cross-scenario validation), the cc_pressure + cc_conditional ecosystem,
and the six archetype scorers (carry / tank / bruiser / mage / assassin /
enchanter). Pure + deterministic: new capabilities are added as opt-in flags
that are byte-identical to the prior version at their default.

``ENGINE_VERSION`` below is the single source of truth for the engine revision.
The full per-version history (effects coverage, Phase batches, ENGINE bumps,
cc_conditional waves) lives in ``CHANGELOG.md`` beside this file. Future ENGINE
bumps PREPEND a new entry to that file's changelog section, never extend a prior
version's line.
"""

ENGINE_VERSION = "1.175.0"
