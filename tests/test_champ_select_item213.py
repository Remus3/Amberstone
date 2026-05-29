"""item 213 (2026-05-28) champ-select frontend redesign pins.

Covers the 5 operator-verbatim sub-tasks + the CC-card clarity rewrite:
  (A) experimental row removed (frontend + routes_loadout backend).
  (B) DS-vs-enemy-comp save+push uses a distinct set_uid via the
      existing apply_item_sets_batch contract + the build is enemy-comp
      aware (cache key includes enemy signature).
  (C) the "source: 101.qq.com" / "(101.qq.com)" UI strings are gone.
  (D) pick/ban cells carry the reformatted .csv-pb168 hierarchy.
  (E) the ally-picks-by-role panel replaced the duo-synergy grid.
  (7) the CC threat cards render plain-language verdict lines.

These are grep/structure pins (no live engine), so they are fast +
deterministic. Drift here means a stale re-wire of a removed surface.
"""

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CS_JS = _ROOT / "web" / "js" / "panels" / "champ_select.js"
_BO_JS = _ROOT / "web" / "js" / "panels" / "build_order.js"
_CCC_JS = _ROOT / "web" / "js" / "panels" / "cc_conditional_pressure.js"
_CCB_JS = _ROOT / "web" / "js" / "panels" / "cc_blended_ehp_threat.js"
_LOADOUT_PY = _ROOT / "dashboard" / "routes_loadout.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class ExperimentalRowRemovedTests(unittest.TestCase):
    """(A) the synthetic experimental build-chooser row is gone."""

    def test_frontend_no_experimental_row_construction(self) -> None:
        js = _read(_CS_JS)
        self.assertNotIn("is_experimental", js)
        self.assertNotIn("_CSV_EXPERIMENTAL_RUNES", js)
        self.assertNotIn("_csvExperimentalRunesFor", js)
        self.assertNotIn('key:        "experimental"', js)

    def test_frontend_no_exp_data_attrs(self) -> None:
        js = _read(_CS_JS)
        self.assertNotIn("data-exp-keystone", js)
        self.assertNotIn("row.dataset.expKeystone", js)

    def test_backend_no_experimental_resolver(self) -> None:
        py = _read(_LOADOUT_PY)
        self.assertNotIn("_build_experimental_resolved", py)

    def test_backend_no_rc_experimental_page_name(self) -> None:
        py = _read(_LOADOUT_PY)
        self.assertNotIn("RC Experimental - ", py)

    def test_backend_keeps_userbuild_and_resolver_branches(self) -> None:
        py = _read(_LOADOUT_PY)
        self.assertIn('variant.startswith("userbuild_")', py)
        self.assertIn("resolved = resolve(champ, variant, mode)", py)


class DsEnemyCompBuildTests(unittest.TestCase):
    """(B) DS-vs-enemy-comp live-update + save+push."""

    def test_build_order_cache_key_includes_enemy_sig(self) -> None:
        js = _read(_BO_JS)
        self.assertIn("_enemySig", js)
        self.assertIn("function _boKey(champion, dsMode, archetype, enemies)", js)

    def test_build_order_fetch_passes_enemies_to_route(self) -> None:
        js = _read(_BO_JS)
        self.assertIn("body.enemies", js)

    def test_champ_select_passes_live_enemies(self) -> None:
        js = _read(_CS_JS)
        self.assertIn("resolveChampNames(_boEnemyIds)", js)
        self.assertIn("enemies: _boEnemyNames", js)

    def test_save_push_button_emitted(self) -> None:
        js = _read(_BO_JS)
        self.assertIn("data-bo-push", js)
        self.assertIn("save + push to client", js)

    def test_push_uses_apply_item_sets_batch_with_distinct_uid(self) -> None:
        js = _read(_CS_JS)
        self.assertIn("data-bo-push", js)
        self.assertIn("-dsenemycomp", js)
        self.assertIn('cmd: "apply_item_sets_batch"', js)


class QqSourceStringRemovedTests(unittest.TestCase):
    """(C) the 101.qq.com / source: UI strings are gone from the page."""

    def test_no_source_qq_ui_string(self) -> None:
        js = _read(_CS_JS)
        self.assertNotIn("source: 101.qq.com", js)
        self.assertNotIn("DUO SYNERGY (101.qq.com)", js)
        self.assertNotIn("csv-duosyn-source", js)

    def test_internal_source_data_vars_retained(self) -> None:
        # resolved.source / fetched.source / "user_cs" are internal data,
        # NOT UI text - they must stay.
        js = _read(_CS_JS)
        self.assertIn('source: "user_cs"', js)


class PickBanReformatTests(unittest.TestCase):
    """(D) pick + ban rows reformatted with clearer hierarchy."""

    def test_pick_ban_sections_present(self) -> None:
        js = _read(_CS_JS)
        self.assertIn("csv-pb168-section csv-pb168-picks", js)
        self.assertIn("csv-pb168-section csv-pb168-bans", js)

    def test_pick_and_ban_cells_keep_classes(self) -> None:
        js = _read(_CS_JS)
        self.assertIn("csv-pb168-pick", js)
        self.assertIn("csv-pb168-ban", js)


class AllyRolesPanelTests(unittest.TestCase):
    """(E) bottom/support panel mirrors live ally picks by role."""

    def test_ally_roles_renderer_present(self) -> None:
        js = _read(_CS_JS)
        self.assertIn("_csvRenderAllyRolesHtml", js)
        self.assertIn("ALLY PICKS BY ROLE", js)

    def test_ally_roles_reads_my_team_and_assigned_position(self) -> None:
        js = _read(_CS_JS)
        head = js.find("function _csvRenderAllyRolesHtml")
        self.assertGreater(head, 0)
        body = js[head:head + 2500]
        self.assertIn("cs.my_team", body)
        self.assertIn("assignedPosition", body)
        self.assertIn("championPickIntent", body)
        self.assertIn("cs.local_cell", body)


class CcCardClarityTests(unittest.TestCase):
    """(7) CC threat cards render plain-language verdict lines."""

    def test_conditional_card_has_verdict(self) -> None:
        js = _read(_CCC_JS)
        self.assertIn("_conditionalVerdict", js)
        self.assertIn("cc-conditional-pressure-verdict", js)
        self.assertIn("can chain on one target", js)

    def test_blended_card_has_verdict(self) -> None:
        js = _read(_CCB_JS)
        self.assertIn("_ccVerdict", js)
        self.assertIn("cc-blended-ehp-threat-verdict", js)
        self.assertIn("CC chain on one target", js)

    def test_verdict_actionable_advice(self) -> None:
        # Both verdicts surface a Cleanse / QSS suggestion when at risk.
        self.assertIn("Cleanse", _read(_CCC_JS))
        self.assertIn("Cleanse", _read(_CCB_JS))


class AsciiHygieneTests(unittest.TestCase):
    def test_touched_sources_ascii(self) -> None:
        # champ_select.js + the two CC panels are fully ASCII; this run's
        # edits must not regress them. build_order.js + routes_loadout.py
        # carry PRE-EXISTING non-ASCII bytes (arrows / etc.) under the
        # operator-gated retro-sweep policy - not in scope here.
        for p in (_CS_JS, _CCC_JS, _CCB_JS):
            data = p.read_bytes()
            bad = [i for i, b in enumerate(data) if b > 127]
            self.assertEqual(bad, [], f"{p.name} has non-ASCII bytes at {bad[:5]}")

    def test_self_is_ascii(self) -> None:
        data = Path(__file__).read_bytes()
        self.assertEqual([b for b in data if b > 127], [])


if __name__ == "__main__":
    unittest.main()
