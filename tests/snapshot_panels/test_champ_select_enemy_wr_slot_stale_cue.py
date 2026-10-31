"""
tests/snapshot_panels/test_champ_select_enemy_wr_slot_stale_cue.py
RM-1201 (s144 uiux): the SR champ-select enemy win-rate slot
(web/js/panels/champ_select.js _csvWrSlotApply / _csvWrSlotFetch, the
leading .csv-enemy-wr-slot on each enemy cell, styled in
web/css/panels/champ_select_view.css) has two follow-ups to RM-1200.

(a) STALE CUE. Since RM-1200 a refetch that fails keeps the last good
    win rate, but before this slice the kept rate looked IDENTICAL to a
    fresh one; only the hover title said the refresh failed. A kept rate
    now carries `is-stale`, rendered italic with a dotted underline. The
    cue changes SHAPE, never colour, so each band keeps its AA pair on
    the --surface-2 enemy cell (pinned below on all six themes, measured
    on the resolved colours, against the same slot's fresh colour).
(b) ok:false POLICY. dashboard/routes_personal_vs.py only ever answers
    ok:false together with an error status (400 / 503 / 500), so an
    ok:false body is a DEGRADED answer, not a "no games" one: it is now
    handled like a failure (negative-cached, the last good rate kept and
    marked stale). Before, a 200 ok:false after a good answer overwrote
    the good rate with "--". An ok:true sample_n 0 answer IS a real
    "no games" answer and still paints "--" with no stale cue.

Routing (synthetic numbers, RM-906). First answer, then every refetch:
  122 -> 62% (is-good), then 503              -> 62% kept, stale
  157 -> 38% (is-bad),  then 503              -> 38% kept, stale
  121 -> 50% (is-mid),  then 200 ok:false     -> 50% kept, stale
  145 -> 58% (is-good), then 200 sample_n 0   -> "--", not stale
  412 -> 503 every time                       -> "--", not stale
Time moves with Playwright's clock (installed before navigation);
re-renders are forced by clearing data-csv-sig, which is what a real
champ-select state change does.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]


def _ok(wr, wins, losses, name):
    return {"ok": True, "sample_n": wins + losses, "wr_pct": wr,
            "wins": wins, "losses": losses, "days": 30, "champ_name": name}


_FIRST = {
    122: _ok(62, 5, 3, "Darius"),
    157: _ok(38, 3, 5, "Yasuo"),
    121: _ok(50, 3, 3, "Kha'Zix"),
    145: _ok(58, 7, 5, "Sion"),
}
_503 = (503, {"ok": False, "error": "rewind_history.db missing"})
_LATER = {
    122: _503,
    157: _503,
    121: (200, {"ok": False, "error": "degraded"}),
    145: (200, {"ok": True, "sample_n": 0, "wr_pct": 0, "wins": 0,
                "losses": 0, "days": 30}),
    412: _503,
}

# Read every slot synchronously (no timers: the page clock is fake).
_READ = """async () => {
  await document.fonts.ready;
""" + _HELPERS + """
  const out = {};
  for (const slot of document.querySelectorAll(
      '#view-champ-select #csv-enemies-list .csv-enemy-wr-slot')) {
    if (!slot.dataset.champId) continue;
    const cs = getComputedStyle(slot);
    const s = surface(slot);
    out[slot.dataset.champId] = {
      text: slot.textContent.trim(),
      cls: slot.className.split(/\\s+/).filter(Boolean),
      title: slot.title || '',
      fg: s ? over(rgba(cs.color), s) : null,
      bg: s,
      opacity: parseFloat(cs.opacity),
      fontStyle: cs.fontStyle,
      deco: cs.textDecorationLine,
      decoStyle: cs.textDecorationStyle,
      visible: slot.checkVisibility(),
    };
  }
  return out;
}"""

_RERENDER = """async () => {
  const mod = await import('/js/panels/champ_select.js');
  const fx = await (await fetch(
    mod.csMockFixtureUrl(location.search), {cache: 'no-store'})).json();
  const lcu = {phase: fx.phase || 'ChampSelect',
               champ_select: fx.champ_select, config: fx.config || {}};
  delete document.getElementById('view-champ-select').dataset.csvSig;
  mod.renderChampSelectView(lcu);
}"""

_ALL_PAINTED = """() => {
  const s = [...document.querySelectorAll(
    '#view-champ-select #csv-enemies-list .csv-enemy-wr-slot')]
    .filter((e) => e.dataset.champId);
  return s.length === 5 && s.every((e) => e.textContent.trim());
}"""


def _cid(url):
    return int(url.split("champ_id=")[1].split("&")[0])


def _measure(mock_server, pw_browser, theme):
    hits: dict[int, int] = {}

    def _route(route):
        cid = _cid(route.request.url)
        hits[cid] = hits.get(cid, 0) + 1
        if hits[cid] == 1 and cid in _FIRST:
            status, body = 200, _FIRST[cid]
        else:
            status, body = _LATER.get(cid, _503)
        route.fulfill(status=status, content_type="application/json",
                      body=json.dumps(body))

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.clock.install()
    page.add_init_script(_WS_STUB)
    page.route("**/api/personal-vs*", _route)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url
            + f"/?ui_mock=1&mode=sr&theme={theme}#champ-select",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(_ALL_PAINTED, timeout=10_000)
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        fresh = page.evaluate(_READ)
        # Past the 60 s success TTL: every champion refetches once.
        page.clock.run_for(70_000)
        page.evaluate(_RERENDER)
        page.wait_for_timeout(300)
        later = page.evaluate(_READ)
        counts = dict(hits)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return {"fresh": fresh, "later": later, "hits": counts}


@pytest.fixture(scope="module")
def measured():
    return {}


def _get(measured, mock_server, pw_browser, theme):
    if theme not in measured:
        measured[theme] = _measure(mock_server, pw_browser, theme)
    return measured[theme]


@pytest.mark.parametrize("theme", ["hextech"])
def test_every_champion_really_refetched(theme, measured, mock_server,
                                         pw_browser):
    # Positive control: the first answers painted and the refetch ran.
    m = _get(measured, mock_server, pw_browser, theme)
    f = m["fresh"]
    assert [f[k]["text"] for k in ("122", "157", "121", "145", "412")] == [
        "62%", "38%", "50%", "58%", "--"], f
    for k in ("122", "157", "121", "145"):
        assert m["hits"].get(int(k)) == 2, m["hits"]
    # No slot is stale before any refresh has failed.
    assert not [k for k, v in f.items() if "is-stale" in v["cls"]], f
    assert all(v["fontStyle"] == "normal" for v in f.values()), f


@pytest.mark.parametrize("theme", ["hextech"])
def test_kept_rate_carries_the_stale_cue(theme, measured, mock_server,
                                         pw_browser):
    m = _get(measured, mock_server, pw_browser, theme)
    for k, band, text in (("122", "is-good", "62%"),
                          ("157", "is-bad", "38%")):
        slot = m["later"][k]
        assert slot["text"] == text, slot
        assert band in slot["cls"], slot
        assert "is-stale" in slot["cls"], (
            f"a kept, stale win rate looks identical to a fresh one: {slot}")
        assert slot["fontStyle"] == "italic", slot
        assert "underline" in slot["deco"], slot
        assert slot["decoStyle"] == "dotted", slot
        assert "refresh failed" in slot["title"], slot


@pytest.mark.parametrize("theme", ["hextech"])
def test_ok_false_after_good_is_degraded_not_no_games(theme, measured,
                                                      mock_server,
                                                      pw_browser):
    slot = _get(measured, mock_server, pw_browser, theme)["later"]["121"]
    assert slot["text"] == "50%", (
        f"a 200 ok:false answer overwrote the good win rate: {slot}")
    assert "is-mid" in slot["cls"] and "is-stale" in slot["cls"], slot
    assert "refresh failed" in slot["title"], slot
    assert "3W 3L" in slot["title"], slot


@pytest.mark.parametrize("theme", ["hextech"])
def test_real_no_games_answer_still_reads_dashes(theme, measured,
                                                 mock_server, pw_browser):
    later = _get(measured, mock_server, pw_browser, theme)["later"]
    for k in ("145", "412"):
        slot = later[k]
        assert slot["text"] == "--", slot
        assert "is-new" in slot["cls"], slot
        assert "is-stale" not in slot["cls"], slot
        assert slot["fontStyle"] == "normal", slot
        assert "no games" in slot["title"], slot
        assert "refresh failed" not in slot["title"], slot


@pytest.mark.parametrize("theme", _THEMES)
def test_stale_cue_keeps_the_band_colour_and_aa(theme, measured,
                                                mock_server, pw_browser):
    m = _get(measured, mock_server, pw_browser, theme)
    low = []
    for k in ("122", "157", "121"):
        fresh, stale = m["fresh"][k], m["later"][k]
        assert "is-stale" in stale["cls"], (theme, k, stale["cls"])
        assert stale["visible"] and stale["opacity"] == 1, stale
        assert stale["fg"] and stale["bg"], stale
        # The cue is shape only: the resolved colour pair is unchanged.
        assert stale["fg"] == fresh["fg"], (theme, k, fresh["fg"],
                                            stale["fg"])
        assert stale["bg"] == fresh["bg"], (theme, k)
        ratio = _ratio(stale["fg"], stale["bg"])
        if ratio < 4.5:
            low.append(f"{k} {stale['text']} {ratio:.2f}:1")
    assert not low, f"{theme}: stale slot under 4.5:1 - " + "; ".join(low)
