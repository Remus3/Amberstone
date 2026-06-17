"""DSP4 - core.rune_wpa annotates each WPA row with ``proc_modeled``.

The self-rune completion picture spans two surfaces: the EMPIRICAL personal-corpus
WPA lens (core.rune_wpa) and the MECHANICAL combat-proc model
(agents.daemon_slayer.rune_procs.RUNE_PROCS). DSP4 cross-links them: every
rune-WPA row now carries ``proc_modeled`` (True when the DS engine mechanically
models that rune's combat proc, False for WPA-only runes such as mana / move-speed
/ stat-grant minors). Additive field (existing rows + fields unchanged); the
import is fail-soft so a missing engine degrades to proc_modeled=False, never
raising in the dashboard route.
"""

from __future__ import annotations

import unittest

from core import rune_wpa
from tests.test_rune_wpa import _add_match, _build_db

# 8112 Electrocute IS in RUNE_PROCS (proc-modeled keystone); 8226 Manaflow Band
# is a mana minor with no damage proc (WPA-only -> proc_modeled False).
ELECTROCUTE = 8112
MANAFLOW_BAND = 8226


class ProcModeledFieldTests(unittest.TestCase):
    def _rows(self):
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"P{i}", team100_gold=0, team200_gold=0, team100_win=1,
                runes={1: {"keystone": ELECTROCUTE, "minors": [MANAFLOW_BAND]}},
            )
        out = rune_wpa.compute_rune_wpa(conn, min_n=20)
        return {it["rune_id"]: it for it in out["items"]}

    def test_field_present_on_every_row(self):
        rows = self._rows()
        self.assertTrue(rows)
        for it in rows.values():
            self.assertIn("proc_modeled", it)
            self.assertIsInstance(it["proc_modeled"], bool)

    def test_modeled_keystone_true(self):
        rows = self._rows()
        self.assertTrue(rows[ELECTROCUTE]["proc_modeled"])

    def test_unmodeled_minor_false(self):
        rows = self._rows()
        self.assertFalse(rows[MANAFLOW_BAND]["proc_modeled"])


if __name__ == "__main__":
    unittest.main()
