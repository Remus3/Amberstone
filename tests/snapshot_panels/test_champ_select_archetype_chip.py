"""Contract tests for the champ-select combat-style archetype chip (R89).

Aggregator C competitor lift - RC resolves + client-caches the primary archetype
(carry / bruiser / tank / mage / assassin / enchanter) but never rendered it as a
glanceable tag once the operator archetype picker was removed (LEDGER 823); the
resolved primary lived on only in the DS scorer cache key. This slice surfaces it
read-only on the My Pick card, reusing the existing .csv-build-badge tint family
(no new CSS). Pure presentation over already-computed + already-client-cached
data - no fetch, no backend, no new math.

Behavioral rendering (tint map, label, fail-soft empty, escape) is pinned in the
sibling node runner web/js/panels/archetype_chip.test.mjs (node --test); this
Python wrapper is the CI-enforced source contract, mirroring the ds_matchup /
spike_curve panel-test idiom.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CHIP_JS = ROOT / "web" / "js" / "panels" / "archetype_chip.js"
CHIP_MJS = ROOT / "web" / "js" / "panels" / "archetype_chip.test.mjs"
CHAMP_SELECT_JS = ROOT / "web" / "js" / "panels" / "champ_select.js"
CS_VIEW_CSS = ROOT / "web" / "css" / "panels" / "champ_select_view.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_archetype_chip_js_exists():
    assert CHIP_JS.exists(), f"archetype_chip.js missing at {CHIP_JS}"
    assert CHIP_JS.stat().st_size > 0


def test_archetype_chip_mjs_exists():
    assert CHIP_MJS.exists(), f"archetype_chip.test.mjs missing at {CHIP_MJS}"


def test_archetype_chip_exports_public_api():
    src = _read(CHIP_JS)
    assert "export function archetypeChipHtml" in src
    assert "export const __test" in src


def test_champ_select_imports_and_calls_archetype_chip():
    src = _read(CHAMP_SELECT_JS)
    assert "from './archetype_chip.js'" in src
    assert "archetypeChipHtml(" in src


def test_chip_wired_into_my_pick_card_next_to_name():
    # The chip renders inside the My Pick body next to the champion name, fed by
    # the existing resolved archetype (no new network call).
    src = _read(CHAMP_SELECT_JS)
    name_at = src.index('id="csv-mypick-name"')
    window = src[name_at:name_at + 300]
    assert "archetypeChipHtml(" in window, (
        "archetype chip must be interpolated next to the My Pick champion name"
    )


def test_chip_reuses_existing_badge_tints_no_orphan_css():
    # The chip only uses tint classes that already exist, so it needs zero new
    # CSS and introduces zero new UI-audit surface.
    css = _read(CS_VIEW_CSS)
    for tint in ("crit", "ap", "tank", "lethality", "support", "default"):
        assert f".csv-build-badge-{tint}" in css, f"missing tint .csv-build-badge-{tint}"
    assert ".csv-build-badge {" in css, "base pill rule (shape/font tokens) missing"


def test_new_files_are_ascii():
    for p in (CHIP_JS, CHIP_MJS):
        raw = p.read_bytes()
        nonascii = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        assert not nonascii, f"{p.name} has non-ASCII bytes at {nonascii[:5]}"
