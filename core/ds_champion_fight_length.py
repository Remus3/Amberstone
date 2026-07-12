"""Per-champion short ``fight_length`` blend for burst-carry calibration.

Pure leaf module - ZERO engine imports so it can be imported from
``core.daemon_slayer_client`` (the :8893 HTTP boundary) WITHOUT importing the
``agents.daemon_slayer`` engine package in-process. That import is structurally
forbidden by the split-brain guard (tests/test_ds_preview_e2e_p1l21.py
TestNoEngineSplitBrain): the client must reach the engine only over HTTP, never
run a second in-process copy at a possibly-different ENGINE_VERSION. This
allow-map is a caller-side POLICY value (a champion -> assumed fight duration),
not engine math, so it lives here in ``core`` next to its only consumer, the
carry branch of ``rank_for_primary_archetype``. It is the exact sibling of
``core.ds_archetype_hp_pct`` (another carry-branch caller-side policy value).

WHY a per-champion fight_length at all
--------------------------------------
The DS carry / ``ds.dps`` scorer optimizes SUSTAINED auto-attack DPS: total
damage integrated over a long fight. A small class of marksmen have a kit whose
real value is PER-SHOT / BURST, not sustained uptime - so the sustained scorer
structurally under-values their real (lethality-crit) meta core. ``rank_items``
already ships a ``fight_length`` reweight knob that blends front-loaded BURST
with sustained DPS::

    effective = burst_delta + delta_dps * fight_length

A SHORT ``fight_length`` tilts the ranking toward the champion's one-rotation
burst core; ``None`` (every champion absent from the map) pays no burst compute
and is byte-identical to the pre-knob ranking. Consult this map at the carry
chokepoint so BOTH the live per-tick coach path and the offline build-order /
loadout backfill (which share ``rank_for_primary_archetype``) apply it.

WHY AN EXPLICIT ALLOW-MAP, not a heuristic
------------------------------------------
Gated per-champion (mirroring the sibling ``_passive_as_lock_overrides`` and the
ARAM archetype-override table): a champion is calibrated only when its meta is
verified to be burst-carry. SUSTAINED / on-hit crit marksmen (Jinx, Ashe,
Caitlyn, Kog'Maw, Twitch, Aphelios) whose value IS integrated DPS are
DELIBERATELY absent -> ``None`` -> their carry ranking is byte-identical.

Jhin (pilot)
------------
Jhin's ``Whisper`` passive HARD-LOCKS his attack speed (item AS converts to AD),
so his damage is a few high-impact shots (the 4th-shot missing-HP execute + his
AD/lethality-scaling Q/W/R), not a fast auto stream - a lethality-crit BURST
carry (real meta: Hubris / The Collector / Youmuu's / Serylda's, IE the retained
crit core). Value re-verified in-process AFTER the AS-lock fix landed (ENGINE
1.204.0, patch 16.13.1) with a Jhin rank_items sweep at levels 11/13/16, target
armor 80: ``fight_length = 0.5`` surfaces the full lethality-crit core (IE ~#4,
Serylda's ~#7, The Collector ~#8, Hubris ~#9, Axiom Arc ~#10, Youmuu's ~#11) and
pushes sustained on-hit (Runaan's) BELOW the whole core, while keeping the burst
term's mild off-class noise (Hextech Gunblade) out of the top 8. The AS-lock fix
converts Jhin's wasted attack speed into AD, which INFLATES his sustained
``delta_dps`` term; a longer fight_length lets that inflated sustained term
re-dominate and re-sinks the lethality core - hence the short 0.5s (his true
combo window is a near-instant 4th-shot execute + R, not a sustained fight). See
the sibling AS-lock fix (agents/daemon_slayer/_passive_as_lock_overrides.py):
the two are orthogonal and complementary (AS-lock corrects the sustained term's
CORRECTNESS; fight_length re-weights burst-vs-sustained).
"""
from __future__ import annotations

from typing import Optional

# champion (normalized, see ``_norm``) -> fight_length seconds for the carry /
# ds.dps blend. GATED allow-map: a champion ABSENT here resolves to ``None`` ->
# byte-identical default ranking (no burst term paid). Exactly ONE entry today.
_CHAMPION_FIGHT_LENGTH: dict[str, float] = {
    # Jhin Whisper (AS-locked lethality-crit burst carry). 0.5s re-verified on
    # the AS-lock baseline ENGINE 1.204.0 - see the module docstring.
    "jhin": 0.5,
}


def _norm(champion: str) -> str:
    """Case/format-insensitive champion key: lowercase, alphanumerics only.

    Maps ``"Jhin"`` / ``"JHIN"`` / ``"jhin"`` -> ``"jhin"`` and
    ``"Kog'Maw"`` -> ``"kogmaw"`` so a coach-supplied display id, DDragon id, or
    lower-cased name all resolve identically. A numeric champion key (e.g.
    ``"202"``) simply will not match any authored entry -> ``None``.
    """
    return "".join(ch for ch in (champion or "").lower() if ch.isalnum())


def champion_fight_length(champion: str) -> Optional[float]:
    """Return the per-champion carry ``fight_length``, or ``None`` if unmapped.

    ``None`` (the default for every champion absent from the allow-map) means
    the carry / ds.dps ranking is byte-identical to the no-knob path - no burst
    compute is paid. A positive float engages ``rank_items``' fight-length
    reweight blend for that champion only.
    """
    return _CHAMPION_FIGHT_LENGTH.get(_norm(champion))
