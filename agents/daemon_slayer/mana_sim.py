# arch: bounded-rotation combat simulator - finite-mana gate over the burst walker | section=daemon_slayer | frozen=no

"""Mana-bounded combat simulator - a rotation gated on FINITE mana.

Daemon Slayer V2 flagship. ``combo.py`` (V1) walks a clock over an ordered
cast list but assumes the caster always has the resources to cast what was
typed (its module docstring: "NO regen / mana-gating between actions"). This
module adds the missing constraint: it walks the SAME per-cast damage that
``burst.compute_burst_damage`` resolves, but maintains a live mana ledger and
SKIPS any cast the caster cannot afford (``status="oom"``). The result reports
how many casts a real, mana-limited rotation actually lands (``bounded_dps``)
versus the V1-parity infinite-mana reference (``unbounded_dps``).

This is NET-NEW COMPOSE, not net-new scoring math:

  * Per-cast damage + cost: ``burst.compute_burst_damage`` returns one
    ``ComboCast`` per token, each carrying ``.cost`` (mana), ``.raw_damage``
    (pre-mode/amp/mit), ``.final_damage`` (post-mode/amp/mit), ``.cooldown``,
    ``.ability_key``, ``.is_ability``, ``.token``, ``.rank``. NO scoring math
    is duplicated or moved here - the per-hit damage agrees byte-for-byte with
    the burst scorer.
  * Mana pool at level: ``stats.scaled(base_mp, mpperlevel, level)`` plus item
    mana (the ``mp`` key out of ``stats.aggregate_item_stats`` over the build's
    item stat blocks). Manamune / Archangel's / Tear bonus mana already lands
    in those item stat blocks, so the pool is read, not re-modeled.
  * Mana regen per second: ``stats.scaled(base_mpregen, mpregenperlevel,
    level) / 5.0`` plus item ``mpregen / 5.0`` (DDragon mp5 is per-5-seconds).

Resource gate
~~~~~~~~~~~~~
``resource_type`` is the champion record ``partype`` (``"Mana"`` /
``"Energy"`` / ``"None"`` / ``"Blood Well"`` / ``"Fury"`` / ``"Rage"`` ...).
A rotation is only mana-gated when ``partype == "Mana"`` AND base mp > 0. For
every other resource type the pool is treated as effectively infinite
(``float('inf')``): the walk never goes OOM, ``bounded_dps == unbounded_dps``
byte-identical, and ``resource_type`` still carries the real value so the
caller can see why no gate applied. Energy / Fury / Heat are NOT modeled as
constraints in v1 - energy regenerates far faster than mana and those kits do
not gate a fight on the resource the way a mana caster does.

Cooldown cadence - the one deliberate departure from combo.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``combo.py`` models a ~2 second BURST window and SKIPS any ability re-cast
that is still on cooldown (its window is too short for a spell to come back).
This simulator models a bounded ROTATION over a longer fight, so on a cast
whose slot is still on cooldown it ADVANCES the clock to the slot's ready time
(``ready_at``), accruing mana regen during the wait, then resolves the cast.
This is the ONLY way a finite-mana pool can ever bind: with strict
skip-on-cooldown only ~6 distinct casts ever resolve in any sequence (well
under any champion's mana pool), so OOM is unreachable and the V2 gate is
meaningless. Waiting-for-cooldown is the faithful "real finite-mana rotation"
semantics. ``status="on_cooldown"`` is reserved for a cast whose ready time
would push the clock past the hard ``_MAX_DURATION_S`` rotation cap - that
cast cannot fire within the modeled window and is recorded (zero damage, no
spend) rather than waited on. AA has no cooldown and always fires.

Ammo (charge) gate - OPT-IN refinement (item 225)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Some spells store CHARGES instead of (or alongside) a flat cooldown - Vi E,
Jhin E, Caitlyn W, Heimerdinger Q, etc. The charge model lives in the optional
``cdragon_spell_stats.json`` sidecar (``DataSnapshot.spell_ammo``) as
``{"max": [r1..r7], "recharge": [r1..r7]}``. ``compute_mana_bounded_combo``
takes an OPT-IN ``gate_ammo`` flag (default False). When False the function is
BYTE-IDENTICAL to the mana-only walk - no charge tracking at all - mirroring
the ``runes=None`` opt-in precedent. When True, every cast of a slot that has a
charge model consumes one charge; charges recharge over the rotation clock at
``recharge[rank]`` seconds per charge (capped at ``max[rank]``). A cast that
finds 0 charges available and has not yet recharged one is gated with
``status="no_ammo"`` (parallel to the ``"oom"`` mana gate - zero damage, no
spend, no clock advance, slot cooldown NOT consumed). Slots WITHOUT a charge
model are untouched (mana-only gating as before). The rank index into the ammo
arrays uses the resolved ``ComboCast.rank`` DIRECTLY (it is already 0-based -
rank 0 at the spell's first level), clamped to the array bounds; this is NOT
``rank - 1``.

Fail-soft contract (mirrors ``combo.py`` + the burst walker): no champion /
empty sequence / burst failure yields an empty ``hits`` tuple with a note
rather than raising.

This is an ADDITIVE substrate - NOT wired into any live scorer and NOT an
ENGINE_VERSION bump.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from ._item_ability_haste import effective_cooldown, total_item_ability_haste
from .burst import compute_burst_damage
from .data_loader import DataSnapshot
from .stats import aggregate_item_stats, scaled

# Hard rotation cap (seconds). A cast whose cooldown-ready time would push the
# clock past this is recorded "on_cooldown" instead of waited on, so the
# simulation always terminates and a runaway long-cooldown sequence does not
# spin the clock to infinity. 180s is a generous full-fight ceiling.
_MAX_DURATION_S = 180.0

# Fallback cast time when burst carries no per-form cast_time - mirrors
# combo.py's _DEFAULT_SPELL_CAST_S. The live patch median spell cast is 0.25s.
_DEFAULT_CAST_S = 0.25

# Fixed auto-attack windup default (v1: no AS-derived windup curve). Matches
# combo.py's _DEFAULT_AA_WINDUP_S round midpoint.
_DEFAULT_AA_WINDUP_S = 0.25

# The four active spell slots that carry a cooldown. AA + unknown tokens are
# cooldown-free.
_COOLDOWN_KEYS = ("Q", "W", "E", "R")

_FLOAT_EPS = 1e-9


@dataclass(frozen=True)
class ManaLedgerHit:
    """One resolved action in the mana-bounded rotation timeline.

    ``t`` is the clock time (seconds from 0) at which the action STARTS (after
    any cooldown wait). ``cost`` is the mana cost of the cast (0.0 for AA /
    unknown). ``mana_before`` / ``mana_after`` bracket the cast: for an ``ok``
    cast ``mana_after = mana_before - cost`` (regen is applied AFTER, between
    casts). For an ``oom`` cast the cast is skipped, ``mana_after ==
    mana_before``, ``raw`` / ``mitigated`` are 0.0, and ``note`` records the
    shortfall. ``cumulative`` is the running sum of ``mitigated`` through this
    action inclusive. ``status`` is ``"ok"`` | ``"oom"`` | ``"on_cooldown"`` |
    ``"no_ammo"`` (the OPT-IN charge gate - same skip shape as ``"oom"``).
    """

    index: int
    action: str
    ability_key: str
    t: float
    cost: float
    mana_before: float
    mana_after: float
    raw: float
    mitigated: float
    cumulative: float
    status: str
    note: str = ""


@dataclass(frozen=True)
class ManaBoundedResult:
    """Resolved mana-bounded rotation + totals.

    ``hits`` is the per-action timeline in cast order (skipped ``oom`` /
    ``on_cooldown`` / ``no_ammo`` actions are retained with zero damage so the
    timeline stays 1:1 with the resolvable casts). ``casts_allowed`` counts ``status=="ok"``
    rows; ``casts_requested`` counts the resolvable casts (unlocked rows that
    reached the mana gate). ``mana_spent`` is the cumulative mana deducted.
    ``oom_at_t`` is the clock of the first ``oom`` cast or None. ``bounded_dps``
    is ``total_mitigated / duration_s`` (the real mana-limited rotation);
    ``unbounded_dps`` is the same walk with infinite mana (the V1-parity
    reference). For a manaless / non-mana resource the two are byte-identical.
    """

    champion: str
    champion_name: str
    level: int
    mode: str
    resource_type: str
    mana_pool: float
    mana_regen_per_s: float
    sequence: Tuple[str, ...]
    hits: Tuple[ManaLedgerHit, ...]
    casts_allowed: int
    casts_requested: int
    mana_spent: float
    oom_at_t: Optional[float]
    total_mitigated: float
    duration_s: float
    bounded_dps: float
    unbounded_dps: float
    notes: Tuple[str, ...] = field(default_factory=tuple)


def _champion_mana_profile(
    snap: DataSnapshot,
    champ_id: str,
    level: int,
    item_blocks: List[dict],
) -> Tuple[str, float, float]:
    """Return ``(resource_type, mana_pool, mana_regen_per_s)`` for the build.

    Reads the champion record ``partype`` + base mp / mpregen (and per-level
    growth) exactly as ``dps.py`` reads the champion record, then folds item
    mana / mp5 from ``aggregate_item_stats``. When ``partype`` is not ``"Mana"``
    (case-insensitive) OR base mp <= 0 the pool is ``float('inf')`` (no gate);
    ``resource_type`` still carries the real partype string.
    """
    try:
        rec = snap.champion(champ_id)
    except Exception:
        return ("Unknown", math.inf, 0.0)
    stat_block = rec.get("stats") or {}
    resource_type = str(rec.get("partype") or "Unknown")

    base_mp = float(stat_block.get("mp", 0.0) or 0.0)
    mp_perlevel = float(stat_block.get("mpperlevel", 0.0) or 0.0)
    base_mpregen = float(stat_block.get("mpregen", 0.0) or 0.0)
    mpregen_perlevel = float(stat_block.get("mpregenperlevel", 0.0) or 0.0)

    item_totals = aggregate_item_stats(item_blocks)
    item_mp = float(item_totals.get("mp_flat", 0.0))
    item_mpregen = float(item_totals.get("mpregen_flat", 0.0))

    # mana regen per second: DDragon mpregen is per-5-seconds, hence /5.
    regen_per_s = (
        scaled(base_mpregen, mpregen_perlevel, level) / 5.0
        + item_mpregen / 5.0
    )

    if resource_type.strip().lower() != "mana" or base_mp <= 0.0:
        # Non-mana resource (Energy / None / Blood Well / Fury / ...) or a
        # champion with no base mp -> no finite-mana gate. Pool is infinite so
        # the walk never goes OOM and bounded == unbounded.
        return (resource_type, math.inf, max(0.0, regen_per_s))

    pool = scaled(base_mp, mp_perlevel, level) + item_mp
    return (resource_type, max(0.0, pool), max(0.0, regen_per_s))


def _cast_time_for(cast) -> float:
    """Effective clock advance for one resolved ComboCast.

    Abilities use the burst cast row's ``cast_time`` when present (real
    positive float), else the spell default. AA / non-cooldown tokens use the
    AA windup default. The burst ``ComboCast`` does not expose cast_time
    directly, so spells fall back to the spell default - the relative
    invariants (more mana -> more casts, bounded <= unbounded) do not depend on
    exact cast times, only on the mana arithmetic + regen-during-wait.
    """
    if getattr(cast, "is_ability", False):
        return _DEFAULT_CAST_S
    return _DEFAULT_AA_WINDUP_S


def _walk(
    casts: Sequence,
    pool: float,
    regen_per_s: float,
    *,
    gate_mana: bool,
    gate_ammo: bool = False,
    ammo_by_slot: Optional[dict] = None,
    ability_haste: float = 0.0,
) -> Tuple[List[ManaLedgerHit], int, int, float, Optional[float], float, float]:
    """Walk the resolved cast list once.

    Returns ``(hits, casts_allowed, casts_requested, mana_spent, oom_at_t,
    total_mitigated, duration_s)``. When ``gate_mana`` is False the mana check
    is bypassed (the infinite-mana reference pass); ``hits`` is still produced
    so the unbounded pass can reuse the same code path.

    When ``gate_ammo`` is True the per-slot charge ledger sourced from
    ``ammo_by_slot`` (slot -> ``{"max": [...], "recharge": [...]}``) is layered
    on top: a cast of a charge-bearing slot consumes one charge, charges
    recharge over the clock, and a cast that finds 0 available charges is gated
    with ``status="no_ammo"``. When False the ammo ledger is never consulted -
    BYTE-IDENTICAL to the prior mana-only walk.
    """
    clock = 0.0
    mana = pool
    cumulative = 0.0
    total_mitigated = 0.0
    mana_spent = 0.0
    casts_allowed = 0
    casts_requested = 0
    oom_at_t: Optional[float] = None
    last_cast_t: dict = {}
    hits: List[ManaLedgerHit] = []
    # Per-slot charge state, lazily initialized on first encounter of a slot
    # that carries an ammo model: {slot: {"charges": float, "max": float,
    # "recharge": float, "last_t": float}}. Only used when gate_ammo is True.
    ammo_state: dict = {}
    ammo = ammo_by_slot or {}

    for i, cast in enumerate(casts):
        is_ability = bool(getattr(cast, "is_ability", False))
        rank = int(getattr(cast, "rank", -1))
        # Locked spell (rank < 0) is NOT resolvable - mirror combo/burst, skip
        # silently (not counted as requested/allowed/oom).
        if is_ability and rank < 0:
            continue

        token = str(getattr(cast, "token", ""))
        key = str(getattr(cast, "ability_key", ""))
        cooldown_s = float(getattr(cast, "cooldown", 0.0) or 0.0)
        # item 234 - ability-haste CDR (Riot canonical base/(1+AH/100)) via the
        # shared _item_ability_haste.effective_cooldown helper. Applied
        # uniformly to every cooldown-bearing slot; ability_haste==0.0 (the
        # default / no-haste build) leaves cooldown_s byte-identical.
        if ability_haste > 0.0 and cooldown_s > 0.0:
            cooldown_s = effective_cooldown(cooldown_s, ability_haste)
        cost = float(getattr(cast, "cost", 0.0) or 0.0)
        cast_time = _cast_time_for(cast)

        # Cooldown handling: a cooldown-bearing ability still on cooldown WAITS
        # until ready (advance clock, accrue regen) rather than skip-forever -
        # the bounded-rotation semantics (see module docstring). If the ready
        # time would push past the hard rotation cap, record "on_cooldown" and
        # move on without firing.
        wait_to = None
        if is_ability and key in _COOLDOWN_KEYS and cooldown_s > 0.0:
            prev = last_cast_t.get(key)
            if prev is not None:
                ready_at = prev + cooldown_s
                if ready_at > clock + _FLOAT_EPS:
                    wait_to = ready_at

        if wait_to is not None and wait_to > _MAX_DURATION_S:
            casts_requested += 1
            hits.append(ManaLedgerHit(
                index=i, action=token, ability_key=key,
                t=round(clock, 3), cost=round(cost, 2),
                mana_before=_round_mana(mana), mana_after=_round_mana(mana),
                raw=0.0, mitigated=0.0, cumulative=round(cumulative, 2),
                status="on_cooldown",
                note=(
                    f"{key} ready at {wait_to:.1f}s exceeds {_MAX_DURATION_S:.0f}s "
                    "rotation cap - not cast"
                ),
            ))
            continue

        if wait_to is not None:
            dt = wait_to - clock
            mana = _accrue(mana, regen_per_s, dt, pool)
            clock = wait_to

        # This cast is resolvable (off cooldown / waited, unlocked).
        casts_requested += 1
        mana_before = mana

        # Ammo (charge) gate - OPT-IN, only when gate_ammo + this slot carries a
        # charge model. Recharge accrues over the clock; a cast with 0 charges
        # available is gated (same skip shape as oom). Slots without ammo are
        # untouched (slot_ammo is None -> no charge bookkeeping).
        slot_ammo = ammo.get(key) if (gate_ammo and is_ability) else None
        if slot_ammo is not None:
            st = _ammo_slot_state(ammo_state, key, slot_ammo, rank, clock)
            if st is not None:
                _recharge_to(st, clock)
                if st["charges"] < 1.0 - _FLOAT_EPS:
                    # No charge ready: skip (no damage, no spend, no clock
                    # advance, cooldown NOT consumed - the cast never fired).
                    hits.append(ManaLedgerHit(
                        index=i, action=token, ability_key=key,
                        t=round(clock, 3), cost=round(cost, 2),
                        mana_before=_round_mana(mana_before),
                        mana_after=_round_mana(mana_before),
                        raw=0.0, mitigated=0.0,
                        cumulative=round(cumulative, 2),
                        status="no_ammo",
                        note=(
                            f"no {key} charges ready (recharge "
                            f"{st['recharge']:.1f}s/charge) - skipped"
                        ),
                    ))
                    continue

        if gate_mana and mana_before < cost - _FLOAT_EPS:
            # Out of mana: skip the cast (no damage, no spend, no clock
            # advance, slot cooldown NOT consumed since it never fired).
            if oom_at_t is None:
                oom_at_t = clock
            hits.append(ManaLedgerHit(
                index=i, action=token, ability_key=key,
                t=round(clock, 3), cost=round(cost, 2),
                mana_before=_round_mana(mana_before),
                mana_after=_round_mana(mana_before),
                raw=0.0, mitigated=0.0, cumulative=round(cumulative, 2),
                status="oom",
                note=(
                    f"out of mana: need {cost:.0f}, have {mana_before:.0f} "
                    f"- {key or token} skipped"
                ),
            ))
            continue

        raw = float(getattr(cast, "raw_damage", 0.0) or 0.0)
        mitigated = float(getattr(cast, "final_damage", 0.0) or 0.0)
        mana_after = mana_before - cost
        mana = mana_after
        mana_spent += cost
        cumulative += mitigated
        total_mitigated += mitigated
        casts_allowed += 1
        if is_ability and key in _COOLDOWN_KEYS:
            last_cast_t[key] = clock
        # Consume one charge on a fired charge-bearing cast (gate_ammo only).
        if slot_ammo is not None and key in ammo_state:
            ammo_state[key]["charges"] -= 1.0

        hits.append(ManaLedgerHit(
            index=i, action=token, ability_key=key,
            t=round(clock, 3), cost=round(cost, 2),
            mana_before=_round_mana(mana_before),
            mana_after=_round_mana(mana_after),
            raw=round(raw, 2), mitigated=round(mitigated, 2),
            cumulative=round(cumulative, 2), status="ok",
        ))

        # Advance the clock + accrue regen across the cast time.
        clock += cast_time
        mana = _accrue(mana, regen_per_s, cast_time, pool)

    return (
        hits, casts_allowed, casts_requested, mana_spent, oom_at_t,
        total_mitigated, round(clock, 3),
    )


def _accrue(mana: float, regen_per_s: float, dt: float, pool: float) -> float:
    """Add ``regen_per_s * dt`` mana, capped at the pool (no-op when infinite)."""
    if math.isinf(pool):
        return mana
    return min(pool, mana + regen_per_s * max(0.0, dt))


def _round_mana(value: float) -> float:
    """Round a mana figure for the ledger; pass inf through untouched."""
    return value if math.isinf(value) else round(value, 2)


def _ammo_index(rank: int, length: int) -> int:
    """Clamp the resolved (0-based) ComboCast rank into an ammo-array index.

    ``ComboCast.rank`` is already 0-based (rank 0 at a spell's first level), so
    the array index IS the rank - not ``rank - 1``. A locked rank (< 0) clamps
    to 0; an out-of-range rank clamps to the last element.
    """
    if length <= 0:
        return 0
    return max(0, min(rank, length - 1))


def _ammo_slot_state(
    ammo_state: dict, key: str, slot_ammo: dict, rank: int, clock: float
) -> Optional[dict]:
    """Lazily init + return the per-slot charge ledger entry, or None if unusable.

    Initializes ``charges`` to ``max[rank]`` (full charges at fight start) and
    pins ``recharge`` to ``recharge[rank]`` on first encounter. Returns None if
    the ammo arrays are missing / empty (so the consumer treats the slot as
    charge-free).
    """
    existing = ammo_state.get(key)
    if existing is not None:
        return existing
    max_arr = slot_ammo.get("max") or []
    rec_arr = slot_ammo.get("recharge") or []
    if not max_arr:
        return None
    idx = _ammo_index(rank, len(max_arr))
    max_charges = float(max_arr[idx])
    if max_charges <= 0.0:
        return None
    rec_idx = _ammo_index(rank, len(rec_arr)) if rec_arr else 0
    recharge = float(rec_arr[rec_idx]) if rec_arr else 0.0
    st = {
        "charges": max_charges,
        "max": max_charges,
        "recharge": max(0.0, recharge),
        "last_t": clock,
    }
    ammo_state[key] = st
    return st


def _recharge_to(st: dict, clock: float) -> None:
    """Accrue charges for the elapsed time since ``last_t``, capped at ``max``.

    A recharge of 0 means charges never regenerate (charges stay where they
    are). ``last_t`` always advances to ``clock`` so elapsed time is not
    double-counted on the next call.
    """
    recharge = st["recharge"]
    if recharge > _FLOAT_EPS and st["charges"] < st["max"] - _FLOAT_EPS:
        dt = max(0.0, clock - st["last_t"])
        gained = math.floor(dt / recharge)
        if gained > 0:
            st["charges"] = min(st["max"], st["charges"] + float(gained))
            # Advance last_t by the consumed whole-charge intervals so the
            # remaining fractional time carries into the next recharge.
            st["last_t"] += gained * recharge
            return
    st["last_t"] = clock


def compute_mana_bounded_combo(
    champion: str,
    level: int,
    item_ids: Optional[Sequence[str | int]] = None,
    sequence: Optional[Sequence[str]] = None,
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    mode: str = "SR",
    snapshot: Optional[DataSnapshot] = None,
    gate_ammo: bool = False,
    apply_ability_haste: bool = False,
) -> ManaBoundedResult:
    """Walk a bounded rotation over ``sequence`` gated on the champion's mana.

    ``sequence`` is an ordered list of action tokens (``"Q"``, ``"AA"``,
    ``"W"``, ``"R"``, ...). Per-cast damage + cost come from the burst walker
    (full mitigation pipeline); this function layers the live mana ledger:
    start at the resolved mana pool, accrue regen between casts (and during a
    cooldown wait), and skip any cast the caster cannot afford
    (``status="oom"``). A second infinite-mana pass produces ``unbounded_dps``
    so the caller sees the V1-parity reference.

    ``gate_ammo`` (default False) is the OPT-IN charge refinement: when False
    the walk is BYTE-IDENTICAL to the mana-only behavior (no charge tracking);
    when True a per-slot charge ledger from ``snap.spell_ammo`` is layered on
    the BOUNDED pass and a cast with 0 charges available is gated
    (``status="no_ammo"``). The unbounded reference pass is never ammo-gated so
    the denominator stays the full V1-parity rotation.

    ``apply_ability_haste`` (default False) is the OPT-IN CDR refinement: when
    False the rotation uses the raw rank cooldowns (BYTE-IDENTICAL). When True
    the build's item ability haste (``total_item_ability_haste`` over the
    resolved item list - the SAME hand-curated 16.x registry the live ability
    scorer uses) reduces every cooldown-bearing slot via Riot's canonical
    ``base_cd / (1 + ability_haste / 100)``. It is applied to BOTH passes so
    the shared wall-clock denominator stays consistent (bounded_dps <=
    unbounded_dps holds); a faster rotation accrues less regen between casts so
    haste can also bind the mana gate earlier. A build with no haste items
    (ability_haste == 0) is byte-identical to apply_ability_haste=False. Haste
    is applied UNIFORMLY: the wiki static-CD (haste-immune) bucket is NOT used
    to exempt slots - its QWER coverage is 3 abilities with a mislabel
    (Amumu Q scales with haste in-game), too unreliable to gate, and a burst
    rotation's spells all scale with haste regardless.

    Fail-soft: no champion / empty sequence / burst failure yields an empty
    ``hits`` tuple with a note rather than raising.
    """
    champ = str(champion or "").strip()
    seq = _normalize_sequence(sequence)
    snap = snapshot if snapshot is not None else DataSnapshot.load()

    notes: List[str] = []
    if not champ:
        notes.append("no champion supplied")
        return _empty(champ, level, mode, tuple(seq), notes)
    if not seq:
        notes.append("empty sequence")
        return _empty(champ, int(level), mode, (), notes, champ_name=champ)

    # Single burst-walker call resolves per-cast damage + cost for the WHOLE
    # sequence through the full mitigation pipeline. One ComboCast per token.
    try:
        burst = compute_burst_damage(
            snap, champ, int(level), item_ids=list(item_ids or []),
            mode=mode, target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            combo_sequence=seq,
        )
    except Exception as exc:  # fail-soft: surface a note, never raise
        notes.append(f"burst walker failed: {str(exc)[:120]}")
        return _empty(champ, int(level), mode, tuple(seq), notes, champ_name=champ)

    champ_id = burst.champion_id or champ
    champ_name = burst.champion_name or champ

    if not burst.per_cast:
        for n in (burst.notes or ()):
            notes.append(str(n))
        notes.append(
            "no resolvable actions (champion absent or sequence empty)"
        )
        return _empty(
            champ_id, int(level), mode, tuple(seq), notes, champ_name=champ_name,
        )

    # Mana profile from the RESOLVED (mode-mirrored) item list so item mana
    # (Tear / Archangel's / Manamune) is counted.
    item_blocks: List[dict] = []
    for iid in burst.item_ids:
        try:
            item_blocks.append(snap.item(iid).get("stats", {}) or {})
        except Exception:
            continue
    resource_type, pool, regen_per_s = _champion_mana_profile(
        snap, champ_id, burst.level, item_blocks,
    )

    is_mana_gated = (not math.isinf(pool)) and pool > 0.0

    # Resolve the per-slot ammo (charge) model ONLY when the caller opted in.
    # When gate_ammo is False this stays empty so the bounded walk is
    # byte-identical to the mana-only behavior. Missing sidecar / no-ammo slot
    # -> spell_ammo returns None -> the slot is simply absent from the map.
    ammo_by_slot: dict = {}
    if gate_ammo:
        for slot in _COOLDOWN_KEYS:
            slot_ammo = snap.spell_ammo(champ_id, slot)
            if isinstance(slot_ammo, dict) and slot_ammo.get("max"):
                ammo_by_slot[slot] = slot_ammo

    # Resolve item ability haste ONLY when the caller opted in (default 0.0 ->
    # raw cooldowns -> byte-identical). Same source the live ability scorer
    # uses; applied uniformly to both passes' cooldown clock below.
    ability_haste = (
        total_item_ability_haste(burst.item_ids) if apply_ability_haste else 0.0
    )

    # Unbounded reference pass FIRST - same walk, mana gate OFF. It establishes
    # the full-rotation wall-clock (``ref_duration``). Both DPS figures are
    # measured over that SAME denominator so the invariant bounded_dps <=
    # unbounded_dps always holds: OOM only ever REMOVES damage from the
    # bounded total (it never adds), and a shorter bounded wall-clock must not
    # inflate its DPS. ``duration_s`` on the result is still the bounded
    # rotation's own end time (informational).
    (_uh, _ua, _ur, _us, _uoom, unbounded_mit, unbounded_dur) = _walk(
        burst.per_cast, pool, regen_per_s, gate_mana=False,
        ability_haste=ability_haste,
    )

    # Bounded pass (mana gate active iff this champion is mana-gated; the ammo
    # charge gate layered on top only when the caller opted in via gate_ammo).
    (
        hits, casts_allowed, casts_requested, mana_spent, oom_at_t,
        total_mitigated, duration_s,
    ) = _walk(
        burst.per_cast, pool, regen_per_s, gate_mana=is_mana_gated,
        gate_ammo=gate_ammo, ammo_by_slot=ammo_by_slot,
        ability_haste=ability_haste,
    )

    # Shared denominator = the full rotation wall-clock from the unbounded
    # pass. For a manaless / non-mana champion the two passes are identical so
    # bounded_dps == unbounded_dps byte-for-byte.
    ref_duration = unbounded_dur
    if ref_duration > _FLOAT_EPS:
        bounded_dps = total_mitigated / ref_duration
        unbounded_dps = unbounded_mit / ref_duration
    else:
        bounded_dps = 0.0
        unbounded_dps = 0.0

    notes.extend(str(n) for n in (burst.notes or ()))
    if not is_mana_gated:
        notes.append(
            f"resource_type={resource_type!r} - no finite-mana gate; "
            "bounded_dps == unbounded_dps"
        )
    elif oom_at_t is not None:
        notes.append(
            f"out of mana at t={oom_at_t:.1f}s after {casts_allowed} of "
            f"{casts_requested} casts"
        )
    n_no_ammo = sum(1 for h in hits if h.status == "no_ammo")
    if n_no_ammo:
        notes.append(
            f"{n_no_ammo} cast(s) gated on charges (gate_ammo=True)"
        )
    if ability_haste > 0.0:
        notes.append(
            f"ability_haste={ability_haste:.0f} applied "
            f"(cooldowns x {effective_cooldown(1.0, ability_haste):.3f})"
        )

    return ManaBoundedResult(
        champion=champ_id,
        champion_name=champ_name,
        level=burst.level,
        mode=mode,
        resource_type=resource_type,
        mana_pool=(pool if not math.isinf(pool) else math.inf),
        mana_regen_per_s=round(regen_per_s, 4),
        sequence=tuple(seq),
        hits=tuple(hits),
        casts_allowed=casts_allowed,
        casts_requested=casts_requested,
        mana_spent=round(mana_spent, 2),
        oom_at_t=(round(oom_at_t, 3) if oom_at_t is not None else None),
        total_mitigated=round(total_mitigated, 2),
        duration_s=duration_s,
        bounded_dps=round(bounded_dps, 2),
        unbounded_dps=round(unbounded_dps, 2),
        notes=tuple(notes),
    )


def _normalize_sequence(sequence: Optional[Sequence[str]]) -> List[str]:
    """Clean the authored action list - strip blanks / None, uppercase."""
    out: List[str] = []
    for raw in sequence or []:
        if raw is None:
            continue
        tok = str(raw).strip().upper()
        if not tok:
            continue
        out.append(tok)
    return out


def _empty(
    champ_id: str,
    level: int,
    mode: str,
    seq: Tuple[str, ...],
    notes: List[str],
    *,
    champ_name: Optional[str] = None,
) -> ManaBoundedResult:
    """Fail-soft empty result with an explanatory note - never raises."""
    return ManaBoundedResult(
        champion=champ_id,
        champion_name=champ_name if champ_name is not None else champ_id,
        level=int(level),
        mode=mode,
        resource_type="Unknown",
        mana_pool=0.0,
        mana_regen_per_s=0.0,
        sequence=seq,
        hits=(),
        casts_allowed=0,
        casts_requested=0,
        mana_spent=0.0,
        oom_at_t=None,
        total_mitigated=0.0,
        duration_s=0.0,
        bounded_dps=0.0,
        unbounded_dps=0.0,
        notes=tuple(notes),
    )


__all__ = [
    "ManaLedgerHit",
    "ManaBoundedResult",
    "compute_mana_bounded_combo",
]
