"""Guards for the two Immolate-family provenance NOTES (2026-08-08, note-only).

An adversarial audit of the Immolate family found the registry notes claiming
more than the data on disk supports. The notes were rewritten to state what is
actually measured; this file pins the two facts those notes rest on, so a
future edit cannot silently make them false again.

FACT 1 - the three Arena Immolate mirrors are ABSENT from the Meraki snapshot.
``223068`` Sunfire Aegis, ``226664`` Hollow Radiance and ``226660`` Bami's
Cinder carry no Meraki row at any patch on disk, and DDragon leaves their
Immolate magnitude placeholder EMPTY. Their formulas in ``_effects_data`` are
therefore ASSUMED SR-parity inheritances, not measurements, and the notes now
say so. If a future Meraki refresh starts shipping these rows, this test fails
and the "no source carries the Arena row" wording must be re-measured rather
than left standing.

The control in the same assertion is ``223069`` Void Immolation, which IS
present - and is the ONLY Arena Immolate id that is. Its formula is genuinely
sourced; the trap is that Meraki files it under the row's ``active`` key with
``passives == []``, so a passives-only probe reads it as unsourced. One audit
already reached exactly that wrong conclusion, which is why the presence and
the key are both pinned here.

FACT 2 - ``PeriodicProc`` has NO activation-window / duration field. That is
why Void Immolation's 5-second window is modelled with the same uptime as the
SR items' 3-second window, and the limitation is documented in the
``PeriodicProc`` docstring. If someone ADDS such a field, this test fails on
purpose: the limitation note is then stale and must be deleted, and the
223069 uptime caveat re-examined.

Note-only slice - no number, formula, damage type or behaviour was changed.
"""

from __future__ import annotations

import dataclasses
import json
import unittest
from pathlib import Path

from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._effects_types import PeriodicProc

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DS_DATA = _REPO_ROOT / "data" / "daemon_slayer"

# Absent from Meraki -> their Immolate formulas are inherited assumptions.
_UNSOURCED_ARENA_MIRRORS = ("223068", "226664", "226660")
# Present in Meraki, but under `active` rather than `passives`.
_SOURCED_ARENA_IMMOLATE = "223069"

# Any field whose name suggests a bounded activation window. PeriodicProc has
# none of these today; the docstring's limitation 1 depends on that.
_WINDOW_FIELD_TOKENS = ("window", "duration", "uptime", "active_for", "seconds_active")


def _meraki_snapshots() -> list[tuple[str, dict]]:
    """Every ``items_meraki.json`` on disk, newest-first by directory name.

    Globbed rather than pinned: only the current patch snapshot is guaranteed
    on disk, so a hardcoded patch list would make this guard unrunnable.
    """
    out: list[tuple[str, dict]] = []
    for path in sorted(_DS_DATA.glob("*/items_meraki.json"), reverse=True):
        payload = json.loads(path.read_text(encoding="utf-8"))
        out.append((path.parent.name, payload["items"]))
    return out


class ArenaImmolateMirrorsAreUnsourcedTests(unittest.TestCase):
    """The three mirrors have no Meraki row; 223069 does. Pins both halves."""

    def setUp(self) -> None:
        self.snapshots = _meraki_snapshots()
        self.assertTrue(
            self.snapshots,
            "no items_meraki.json found under data/daemon_slayer - the guard "
            "cannot measure absence against an empty corpus",
        )

    def test_mirrors_absent_from_every_meraki_snapshot(self) -> None:
        for patch, items in self.snapshots:
            for item_id in _UNSOURCED_ARENA_MIRRORS:
                with self.subTest(patch=patch, item_id=item_id):
                    self.assertNotIn(
                        item_id,
                        items,
                        f"{item_id} now HAS a Meraki row at {patch}. The "
                        f"_effects_data note calls its Immolate formula an "
                        f"assumed SR-parity inheritance because no source "
                        f"carried the Arena row - re-measure the formula "
                        f"against the new row and rewrite that note.",
                    )

    def test_void_immolation_is_present_and_filed_under_active(self) -> None:
        for patch, items in self.snapshots:
            with self.subTest(patch=patch):
                self.assertIn(
                    _SOURCED_ARENA_IMMOLATE,
                    items,
                    f"223069 is the one Arena Immolate id Meraki carries; its "
                    f"note at {patch} cites that row as MEASURED",
                )
                row = items[_SOURCED_ARENA_IMMOLATE]
                self.assertEqual(
                    list(row.get("passives") or []),
                    [],
                    "223069's passives list is expected EMPTY - that is the "
                    "trap the note warns about",
                )
                active_names = [
                    entry.get("name") for entry in (row.get("active") or [])
                ]
                self.assertIn(
                    "Immolate",
                    active_names,
                    "223069's Immolate clause must stay on the `active` key; "
                    "the note tells the next reader to probe `active`, not "
                    "`passives`, before calling the entry unsourced",
                )

    def test_all_four_ids_are_registered_immolate_procs(self) -> None:
        """The notes hang off these entries; keep them findable."""
        for item_id in _UNSOURCED_ARENA_MIRRORS + (_SOURCED_ARENA_IMMOLATE,):
            with self.subTest(item_id=item_id):
                effect = ITEM_EFFECTS.get(item_id)
                self.assertIsNotNone(effect, f"{item_id} left ITEM_EFFECTS")
                self.assertEqual(effect.unique_passive_key, "immolate")
                proc_names = [proc.name for proc in effect.periodics]
                self.assertIn("Immolate", proc_names)


class PeriodicProcHasNoActivationWindowTests(unittest.TestCase):
    """Limitation 1 in the PeriodicProc docstring must stay true."""

    def test_field_set_is_exactly_the_documented_eight(self) -> None:
        self.assertEqual(
            [f.name for f in dataclasses.fields(PeriodicProc)],
            [
                "name",
                "bonus_damage",
                "damage_type",
                "every_n_attacks",
                "every_n_seconds",
                "stack_ramp_seconds",
                "ability_dot",
                "ranged_only",
            ],
        )

    def test_no_window_or_duration_field(self) -> None:
        names = [f.name.lower() for f in dataclasses.fields(PeriodicProc)]
        for name in names:
            for token in _WINDOW_FIELD_TOKENS:
                # every_n_seconds is a PERIOD, not a window - it is the field
                # the limitation note contrasts against, so it must not trip
                # the scan. It carries none of the tokens; assert that stays so.
                with self.subTest(field=name, token=token):
                    self.assertNotIn(
                        token,
                        name,
                        f"PeriodicProc gained field {name!r}, which looks like "
                        f"an activation-window field. If it is one, DELETE "
                        f"limitation 1 from the PeriodicProc docstring and the "
                        f"'uptime modelled as equal to Sunfire's' caveat on "
                        f"223069 in _effects_data.py - both are now stale.",
                    )


if __name__ == "__main__":
    unittest.main()
