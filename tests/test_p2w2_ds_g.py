"""P2-W2 cycle 12 DS-engine audit (slice G) - regression tests.

Covers the FIX-NOW hardening landed in this slice:

* ``fight_report.FightReport.to_dict`` coerces a non-finite ``mana_pool``
  (``math.inf`` for a manaless / energy champion) to JSON-safe ``None``
  instead of emitting a bare ``Infinity`` token. The DS server serializes a
  fight-report via ``json.dumps(payload, default=str)`` with the DEFAULT
  ``allow_nan=True`` (``server.Handler._send_json``), so an
  ``Infinity`` token survives to the wire and breaks the dashboard's
  ``JSON.parse`` (the cycle-7..11 dominant finding class). The
  ``ManaBoundedResult.mana_pool`` dataclass field itself stays ``math.inf``
  (its documented "no finite-mana gate" sentinel, pinned by
  ``ManalessChampionTests.test_zed_energy_is_not_gated`` in
  ``agents/daemon_slayer/tests/test_mana_sim.py``) - only the JSON BOUNDARY
  is hardened.

Characterization locks (already-correct guards, proven here so a future
edit cannot silently regress them):

* ``matchup.compute_matchup`` guards a zero / unresolvable HP pool
  (the 0-HP guards in ``matchup.compute_matchup`` on ``pct_b_removed`` /
  ``pct_a_removed``) so a 0-HP target never divides by zero -> the
  serialized ``to_dict`` carries no NaN / Infinity token.

Every emitted scorer number must be JSON-finite. The mana_pool test asserts
the OLD behavior would have failed (a bare ``Infinity`` leak via the
production ``allow_nan=True`` encoder) and the NEW behavior is JSON-safe.

Symbols this file relies on, cited by symbol (a line number goes stale):
  data_loader.DataSnapshot.load
  fight_report.compute_fight_report
  fight_report.FightReport.to_dict - and its mana_pool emit
  mana_sim.compute_mana_bounded_combo
  mana_sim.ManaBoundedResult.mana_pool - a dataclass field
  mana_sim._champion_mana_profile - its non-mana branch returns the inf pool
  matchup.compute_matchup
  matchup.MatchupResult.to_dict
  server.Handler._send_json - json.dumps with the default allow_nan=True
"""

from __future__ import annotations

import json
import math

import pytest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.fight_report import compute_fight_report
from agents.daemon_slayer.mana_sim import compute_mana_bounded_combo
from agents.daemon_slayer.matchup import compute_matchup


@pytest.fixture(scope="module")
def snap() -> DataSnapshot:
    return DataSnapshot.load()


# A manaless champion: partype is "None" -> _champion_mana_profile returns
# math.inf for the pool (the non-mana branch of
# ``mana_sim._champion_mana_profile``). Garen is the canonical
# manaless bruiser; if Garen ever changes, any energy champ (Kennen / Lee
# Sin) exhibits the same inf pool.
_MANALESS_CHAMP = "Garen"


def _production_encode(payload: dict) -> str:
    """Encode exactly as the DS server does: json.dumps(default=str).

    The production ``server.Handler._send_json`` uses the DEFAULT
    ``allow_nan=True``, so a non-finite float survives as a bare ``NaN`` /
    ``Infinity`` token rather than raising. This helper reproduces that path
    so the test exercises the real leak.
    """
    return json.dumps(payload, default=str)


class TestFightReportManaPoolNonFinite:
    def test_manaless_mana_pool_is_json_finite(self, snap: DataSnapshot) -> None:
        # The mana ledger reports an INFINITE pool for a manaless champion
        # (the documented "no finite-mana gate" sentinel).
        ledger = compute_mana_bounded_combo(
            _MANALESS_CHAMP, 9, item_ids=[], sequence=["Q", "W", "E", "R"],
            snapshot=snap,
        )
        assert math.isinf(ledger.mana_pool), (
            "precondition: a manaless champion must report an inf mana pool "
            f"(the ManaBoundedResult sentinel); got {ledger.mana_pool!r}"
        )

        report = compute_fight_report(_MANALESS_CHAMP, 9, item_ids=[], snapshot=snap)
        d = report.to_dict()

        # Pre-fix: d["mana_pool"] was math.inf -> the production encoder emits
        # a bare ``Infinity`` token. Post-fix: it is JSON-safe (None / finite).
        mp = d["mana_pool"]
        assert mp is None or math.isfinite(mp), (
            f"mana_pool must be JSON-finite (None or finite), got {mp!r}"
        )

    def test_production_encode_carries_no_infinity_token(
        self, snap: DataSnapshot
    ) -> None:
        report = compute_fight_report(_MANALESS_CHAMP, 9, item_ids=[], snapshot=snap)
        d = report.to_dict()

        # The exact production serialization path (allow_nan=True).
        body = _production_encode(d)
        assert "Infinity" not in body, (
            "fight-report JSON leaked a bare Infinity token (invalid JSON that "
            "breaks the dashboard JSON.parse)"
        )
        assert "NaN" not in body, "fight-report JSON leaked a bare NaN token"

        # And it must round-trip under a strict (finite-only) parser, which is
        # what a browser JSON.parse does.
        json.loads(
            body,
            parse_constant=lambda c: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {c}")
            ),
        )

    def test_strict_allow_nan_false_encode_succeeds(self, snap: DataSnapshot) -> None:
        # A stricter belt-and-suspenders: allow_nan=False RAISES on any
        # non-finite float anywhere in the payload. Pre-fix this raised for a
        # manaless champion; post-fix it succeeds.
        report = compute_fight_report(_MANALESS_CHAMP, 9, item_ids=[], snapshot=snap)
        d = report.to_dict()
        json.dumps(d, allow_nan=False)  # must not raise

    def test_mana_champion_pool_still_finite_and_present(
        self, snap: DataSnapshot
    ) -> None:
        # Guard against an over-broad fix: a real mana champion must keep its
        # finite, positive pool in the serialized dict (the fix only touches
        # the non-finite case).
        report = compute_fight_report("Lux", 9, item_ids=[], snapshot=snap)
        d = report.to_dict()
        mp = d["mana_pool"]
        assert mp is not None and math.isfinite(mp) and mp > 0.0, (
            f"a mana champion must keep a finite positive mana_pool, got {mp!r}"
        )


class TestMatchupZeroHpDivGuard:
    """Characterization lock: matchup guards a 0-HP target div-by-zero."""

    def test_zero_hp_target_yields_finite_serializable(
        self, snap: DataSnapshot
    ) -> None:
        # hp_*_pct=0.0 drives a_hp_eff / b_hp_eff to 0; the pct_removed lines
        # (the 0-HP guards in compute_matchup) must NOT divide by zero into a
        # NaN/inf.
        r = compute_matchup(
            snap, "Garen", "Darius", 9, 9, hp_a_pct=0.0, hp_b_pct=0.0,
        )
        d = r.to_dict()
        for k, v in d.items():
            if isinstance(v, float):
                assert math.isfinite(v), f"matchup field {k!r} non-finite: {v!r}"
        body = json.dumps(d, default=str)
        assert "Infinity" not in body and "NaN" not in body
        json.dumps(d, allow_nan=False)  # strict: must not raise
