"""
tests/snapshot_panels/test_ui_mock_champ_select_fixture_per_mode.py
The ?ui_mock=1 Champ Select audit page reads ONE fixture per ?mode= - the
fixture it renders - for its build chooser and capability-gap chip too
(session 144, lane uiux, RM-970).

main.js _csMockLoad renders mode=aram from champ_select_aram.json and
mode=arena from champ_select_arena.json, but the two champ_select.js mock
fetches (_csvFetchUserVariants, _csvFetchCapabilityGap) read
champ_select_sr.json whatever ?mode= was. The chooser looks its rows up by
"<champion>|<mode>", and the SR fixture carries only "Jinx|sr", so the ARAM
and Arena audit pages painted "no build variants for this champion / mode
yet" while their own fixtures carry "Jinx|aram" / "Jinx|arena" rows
(measured headless before the fix). The chip half was latent: the SR gap
would have shown on any non-SR page that mounts the chip.

The fix is one ?mode= -> fixture map in champ_select.js (CS_MOCK_FIXTURES /
csMockFixtureUrl) that main.js _csMockLoad and both mock fetches read.

Drive path: /?ui_mock=1&mode=<m>#champ-select with an empty /api/state
(the same path as test_champ_select_view.py).
"""
import json
from pathlib import Path

import pytest

from tests.snapshot_panels.test_champ_select_view import _open_champ_select

_FIXTURES = Path(__file__).resolve().parents[2] / "web" / "data" / "ui_mock"


def _fixture(mode: str) -> dict:
    return json.loads(
        (_FIXTURES / f"champ_select_{mode}.json").read_text(encoding="utf-8")
    )


_SR_GAP = _fixture("sr")["capability_gap"]["verdict"]

_MOCK_URLS_JS = (
    "() => performance.getEntriesByType('resource').map(e => e.name)"
    ".filter(n => n.indexOf('/data/ui_mock/champ_select_') >= 0)"
)


def _first_row_label(mode: str) -> str:
    rows = _fixture(mode)["build_variants"][f"Jinx|{mode}"]
    return rows[0]["label"]


def _builds_text(page) -> str:
    return page.evaluate(
        "(document.querySelector('#view-champ-select .csv-builds') || {})"
        ".innerText || ''"
    )


def _wait_builds(page, label: str) -> None:
    page.wait_for_function(
        "(l) => ((document.querySelector('#view-champ-select .csv-builds')"
        " || {}).innerText || '').indexOf(l) >= 0",
        arg=label,
        timeout=10_000,
    )


def test_fixtures_carry_their_own_mode_rows():
    """The data the pages must render exists: each fixture keys its chooser
    rows by its own mode, and only the SR fixture carries a capability gap."""
    for mode in ("sr", "aram", "arena"):
        bv = _fixture(mode)["build_variants"]
        assert list(bv) == [f"Jinx|{mode}"], (mode, list(bv))
        assert bv[f"Jinx|{mode}"], mode
    assert _SR_GAP
    assert "capability_gap" not in _fixture("aram")
    assert "capability_gap" not in _fixture("arena")


def test_sr_chooser_and_chip_paint_the_sr_fixture(mock_server, pw_browser):
    """Positive control: the SR page renders its fixture's rows and gap, so
    the aram / arena assertions below are not vacuous."""
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, "sr")
    try:
        _wait_builds(page, _first_row_label("sr"))
        page.wait_for_function(
            "!document.getElementById('csv-sugg-capability-gap').hidden",
            timeout=10_000,
        )
        assert _SR_GAP in page.evaluate(
            "document.getElementById('csv-sugg-capability-gap').innerText"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [sr]: {errors[:3]}"


@pytest.mark.parametrize("mode", ["aram", "arena"])
def test_chooser_renders_the_pages_own_fixture_rows(mode, mock_server, pw_browser):
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, mode)
    try:
        label = _first_row_label(mode)
        _wait_builds(page, label)
        text = _builds_text(page)
        assert "no build variants for this champion / mode yet" not in text, text
        # The chooser settled an active build from the page's own rows.
        assert page.evaluate(
            "(document.querySelector('.csv-rune-side') || {dataset: {}})"
            ".dataset.buildId || ''"
        ), "no active build id on the rune side panel"
        urls = page.evaluate(_MOCK_URLS_JS)
        assert urls, "no champ-select fixture fetched"
        assert all(u.endswith(f"/champ_select_{mode}.json") for u in urls), urls
        chip = page.evaluate(
            "() => { const b = document.getElementById("
            "'csv-sugg-capability-gap'); return b ? [b.hidden, b.innerText]"
            " : null; }"
        )
        if chip is not None:
            hidden, chip_text = chip
            assert _SR_GAP not in chip_text, f"{mode} paints the SR gap"
            assert hidden is True, f"{mode}: chip shown with no fixture gap"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{mode}]: {errors[:3]}"
