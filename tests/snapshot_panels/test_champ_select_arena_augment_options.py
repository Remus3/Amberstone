"""
tests/snapshot_panels/test_champ_select_arena_augment_options.py
RM-1202 (s144 uiux): the Arena champ-select "pick one" augment option
rows (web/js/panels/champ_select.js _csvArenaPaneHtml /
_csvWireArenaAugments, styled by web/css/panels/champ_select_view.css
.csv-augment-option) had never been rendered by any test: the ?ui_mock=1
Arena fixture carries "options": [], and so does the live shape
(lcu/champ_select_shape.py emits an empty augments scaffold until the
/lol-cherry/v1/* discovery lands). This module routes a fixture with a
real offer into the page and pins the rows' contract.

The offers are REAL Arena augments (id, name, rarity) from the tracked
CommunityDragon snapshot data/daemon_slayer/16.21.1/arena_augments.json
(rarity 0 = silver, 1 = gold); each blurb is the first sentence of that
row's desc with the markup stripped.

MEASURED headless under /?ui_mock=1&mode=arena#champ-select at 1920x1080
before the fix:
- each option was a bare <div> with a click listener: no role, no
  tabindex, no key handler, no :focus-visible rule - the decision surface
  was mouse-only (HIT-TARGETS phase);
- the visual pick (.is-selected) lived only on the clicked node, and the
  pane rebuilds through innerHTML, so a rebuild dropped the pick and threw
  a focused row to <body> (lane doc section 6, trap 2);
- the idempotent render gate (_csvComputeSig) folded nothing from
  cs.augments, so a new offer, a new round or a filled slot did not
  re-render the pane until some unrelated field changed;
- lcu/champ_select_shape.py emits current_round as an int (0), and the
  pane called .toUpperCase() on it: 0 survived only because it is falsy,
  and any later round index threw a TypeError out of the whole render.
"""
import json
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _lum, _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = _REPO / "web" / "data" / "ui_mock" / "champ_select_arena.json"
_OPT = "#view-champ-select .csv-augment-options .csv-augment-option"

_SILVER = [
    {"id": 120, "name": "Serve Beyond Death", "tier": "silver",
     "blurb": "The first time you would die each round, instead return to"
              " full Health, decaying over time."},
    {"id": 308, "name": "Firefox", "tier": "silver",
     "blurb": "Autocast: gain Movement Speed and conjure three flames that"
              " orbit you, targeting the closest visible enemy."},
    {"id": 51, "name": "Light 'em Up!", "tier": "silver",
     "blurb": "Every 4th Attack deals additional magic damage On-Hit."},
]
_GOLD = [
    {"id": 89, "name": "Vanish", "tier": "gold",
     "blurb": "Gain the Vanish Summoner Spell. Vanish turns you Invisible."},
    {"id": 23, "name": "Demon's Dance", "tier": "gold",
     "blurb": "Gain the Fleet Footwork and Grasp of the Undying Keystone"
              " Runes."},
    {"id": 21, "name": "Defensive Maneuvers", "tier": "gold",
     "blurb": "Gain the Defensive Maneuvers Summoner Spell."},
]


def _fixture(options, current_round="silver"):
    fx = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    fx["champ_select"]["augments"]["options"] = options
    fx["champ_select"]["augments"]["current_round"] = current_round
    return fx


_INSET_RING = """() => {
  const probe = document.createElement('div');
  probe.style.boxShadow = 'inset var(--focus-ring)';
  document.body.appendChild(probe);
  const ring = getComputedStyle(probe).boxShadow;
  probe.remove();
  return ring;
}"""

# Same rebuild trigger as test_champ_select_lock_button_focus.py: the
# lol-descriptions land clears the section sig and schedules one rAF
# render; wait until the row is a NEW node, i.e. the pane really rebuilt.
_REBUILD = """async (sel) => {
  const old = document.querySelector(sel);
  old.dataset.preRebuild = '1';
  document.dispatchEvent(new Event('rc:lol-descriptions-ready'));
  const t0 = performance.now();
  while (performance.now() - t0 < 5000) {
    await new Promise((r) => requestAnimationFrame(r));
    const now = document.querySelector(sel);
    if (now && now !== old && !now.dataset.preRebuild) {
      const a = document.activeElement;
      return {rebuilt: true,
              active: a ? (a.dataset.augmentId || a.id || a.tagName) : null,
              cls: now.className,
              pressed: now.getAttribute('aria-pressed')};
    }
  }
  return {rebuilt: false, active: null};
}"""

# Settled read of the focused row. _open returns at the first rendered row, but
# the pane rebuilds through innerHTML as each load-time fetch lands, so a rebuild
# can land inside the 0.12s ring transition. A node held across that wait is then
# detached: its cancelled transition rejects .finished with AbortError (CI nightly
# 41287693946) and its computed style reads every property as "" (CI nightly
# 41863120477), while the page has the rebuilt row focused with the ring. So
# re-resolve the row on every pass, and read it in the task that saw it settled.
_READ_FOCUSED = """async (sel) => {
  let el;
  for (;;) {
    el = document.querySelector(sel);
    const as = el.getAnimations().filter((a) => a.playState !== 'finished');
    if (!as.length) break;
    await Promise.allSettled(as.map((a) => a.finished));
  }
  const cs = getComputedStyle(el);
  return {focused: document.activeElement === el,
          visible: el.matches(':focus-visible'),
          outline: cs.outlineStyle, shadow: cs.boxShadow};
}"""

# The rebuild pinned inside that read, with no race: everything up to the
# read's first await runs in ONE task, and the ring transition is paused so it
# cannot finish before the scheduled rAF render lands.
_READ_ACROSS_A_REBUILD = """async (sel) => {
  const old = document.querySelector(sel);
  old.focus();
  const held = old.getAnimations();
  held.forEach((a) => a.pause());
  const stop = setTimeout(() => held.forEach((a) => a.finish()), 5000);
  document.dispatchEvent(new Event('rc:lol-descriptions-ready'));
  const got = await (""" + _READ_FOCUSED + """)(sel);
  clearTimeout(stop);
  return Object.assign(got, {held: held.length, rebuilt: !old.isConnected});
}"""

_RECORD_LCU_POSTS = """() => {
  window.__lcuPosts = [];
  const orig = window.fetch;
  window.fetch = (u, o) => {
    if (String(u).indexOf('/api/lcu-cmd') !== -1 && o && o.method === 'POST')
      window.__lcuPosts.push(JSON.parse(o.body));
    return orig(u, o);
  };
}"""

# A load-time render also pushes the build variants (_csvMaybePushBuildsToLCU),
# so that POST can land inside a recording whenever its fetch lands (measured:
# 16 of 60 runs of the Enter / Space test before it filtered by cmd). Sent on
# purpose, so the race is pinned instead of left to timing.
_AUTO_PUSH = """() => { fetch('/api/lcu-cmd', {method: 'POST',
  body: JSON.stringify({cmd: 'apply_item_sets_batch', sets: []})}); }"""

_ROWS = """(sel) => [...document.querySelectorAll(sel)].map((e) => ({
  id: e.dataset.augmentId,
  name: e.dataset.augmentName,
  text: e.querySelector('.csv-augment-option-name').textContent,
  role: e.getAttribute('role'),
  tabindex: e.getAttribute('tabindex'),
  pressed: e.getAttribute('aria-pressed'),
  selected: e.classList.contains('is-selected'),
  h: e.getBoundingClientRect().height,
}))"""


def _open(mock_server, pw_browser, fixture, theme="hextech"):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    body = json.dumps(fixture)
    ctx.route(
        "**/data/ui_mock/champ_select_arena.json",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=body),
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + f"/?ui_mock=1&mode=arena&theme={theme}#champ-select",
        wait_until="domcontentloaded", timeout=15_000,
    )
    page.wait_for_function(
        f"document.querySelectorAll('{_OPT}').length > 0", timeout=10_000,
    )
    return ctx, page, errors


def _close(ctx, page):
    page.close()
    ctx.close()


def _focus_by_keyboard(page, sel) -> None:
    # A real key press first, so a programmatic focus matches :focus-visible
    # the way it does after Tab.
    page.keyboard.press("Shift")
    page.evaluate("(s) => document.querySelector(s).focus()", sel)


def _sel(aug_id):
    return f'{_OPT}[data-augment-id="{aug_id}"]'


def test_offered_options_are_keyboard_buttons(mock_server, pw_browser):
    ctx, page, errors = _open(mock_server, pw_browser, _fixture(_SILVER))
    try:
        rows = page.evaluate(_ROWS, _OPT)
        hit = page.evaluate(
            "() => { const p = document.createElement('div');"
            " p.style.height = 'var(--hit-min)'; document.body.appendChild(p);"
            " const h = p.getBoundingClientRect().height; p.remove();"
            " return h; }")
        empty = page.evaluate(
            "() => !!document.querySelector("
            "'#view-champ-select .csv-augment-options .csv-empty')")
        # STRUCTURE: the wrapped blurbs stay inside the pick box and the
        # page gains no horizontal scroll at the 1920 baseline.
        over = page.evaluate(
            "() => { const b = document.querySelector("
            "'#view-champ-select .csv-augment-options');"
            " return {box: b.scrollWidth - b.clientWidth,"
            " page: document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth}; }")
    finally:
        _close(ctx, page)
    assert over == {"box": 0, "page": 0}, over
    assert [r["text"] for r in rows] == [o["name"] for o in _SILVER], rows
    # The apostrophe survives the escaped attribute round trip.
    assert [r["name"] for r in rows] == [o["name"] for o in _SILVER], rows
    for r in rows:
        assert r["role"] == "button" and r["tabindex"] == "0", r
        assert r["pressed"] == "false" and not r["selected"], r
        assert r["h"] >= hit >= 42, (r, hit)
    assert not empty, "the empty-offer note rendered beside a real offer"
    assert not errors, errors[:3]


def test_enter_and_space_pick_exactly_one_option(mock_server, pw_browser):
    ctx, page, errors = _open(mock_server, pw_browser, _fixture(_SILVER))
    try:
        page.evaluate(_RECORD_LCU_POSTS)
        page.evaluate(_AUTO_PUSH)
        _focus_by_keyboard(page, _sel(120))
        page.keyboard.press("Enter")
        after_enter = page.evaluate(_ROWS, _OPT)
        y0 = page.evaluate("() => window.scrollY")
        _focus_by_keyboard(page, _sel(51))
        page.keyboard.press(" ")
        after_space = page.evaluate(_ROWS, _OPT)
        y1 = page.evaluate("() => window.scrollY")
        posts = page.evaluate("() => window.__lcuPosts")
    finally:
        _close(ctx, page)
    assert [r["pressed"] for r in after_enter] == ["true", "false", "false"]
    assert [r["selected"] for r in after_enter] == [True, False, False]
    assert [r["pressed"] for r in after_space] == ["false", "false", "true"]
    assert [r["selected"] for r in after_space] == [False, False, True]
    assert y1 == y0, "Space scrolled the page instead of picking"
    assert [(p.get("cmd"), p.get("augment_id")) for p in posts
            if p.get("cmd") == "set_augment_intent"] == [
        ("set_augment_intent", 120), ("set_augment_intent", 51)], posts
    assert not errors, errors[:3]


@pytest.mark.parametrize("theme", _THEMES)
def test_focused_option_draws_the_inset_system_ring(mock_server, pw_browser,
                                                    theme):
    ctx, page, errors = _open(mock_server, pw_browser, _fixture(_SILVER),
                              theme)
    try:
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        ring = page.evaluate(_INSET_RING)
        _focus_by_keyboard(page, _sel(308))
        got = page.evaluate(_READ_FOCUSED, _sel(308))
    finally:
        _close(ctx, page)
    assert "inset" in ring, f"inset --focus-ring resolved {ring!r}"
    assert got["focused"] and got["visible"], got
    assert got["shadow"] == ring, (
        f"{theme}: focused option box-shadow {got['shadow']!r}, ring {ring!r}")
    assert got["outline"] == "none", got
    assert not errors, errors[:3]


def test_the_ring_read_follows_the_row_across_a_rebuild(mock_server, pw_browser):
    ctx, page, errors = _open(mock_server, pw_browser, _fixture(_SILVER))
    try:
        ring = page.evaluate(_INSET_RING)
        page.keyboard.press("Shift")
        got = page.evaluate(_READ_ACROSS_A_REBUILD, _sel(308))
    finally:
        _close(ctx, page)
    assert got["held"] >= 1, f"no ring transition to hold, proved nothing: {got}"
    assert got["rebuilt"], f"the pane never rebuilt inside the read: {got}"
    assert got["focused"] and got["visible"], got
    assert got["shadow"] == ring, got
    assert got["outline"] == "none", got
    assert not errors, errors[:3]


def test_focus_and_pick_survive_a_pane_rebuild(mock_server, pw_browser):
    ctx, page, errors = _open(mock_server, pw_browser, _fixture(_SILVER))
    try:
        _focus_by_keyboard(page, _sel(308))
        page.keyboard.press("Enter")
        out = page.evaluate(_REBUILD, _sel(308))
    finally:
        _close(ctx, page)
    assert out["rebuilt"], "the Arena pane never rebuilt"
    assert out["active"] == "308", f"a rebuild threw focus to {out['active']}"
    assert "is-selected" in out["cls"].split(), out
    assert out["pressed"] == "true", out
    assert not errors, errors[:3]


def test_a_rebuild_never_steals_focus_onto_an_option(mock_server, pw_browser):
    ctx, page, errors = _open(mock_server, pw_browser, _fixture(_SILVER))
    try:
        page.evaluate(
            "() => { if (document.activeElement) document.activeElement.blur(); }")
        out = page.evaluate(_REBUILD, _sel(120))
    finally:
        _close(ctx, page)
    assert out["rebuilt"], "the Arena pane never rebuilt"
    assert out["active"] not in {"120", "308", "51"}, out
    assert not errors, errors[:3]


# Every render below runs inside ONE synchronous evaluate, so no app tick
# (which would re-render the routed silver fixture) can interleave.
_DIRECT = """async (args) => {
  const mod = await import('/js/panels/champ_select.js');
  const fx = await (await fetch(
    mod.csMockFixtureUrl(location.search), {cache: 'no-store'})).json();
  const lcu = (aug) => ({phase: 'ChampSelect', config: fx.config || {},
    champ_select: Object.assign({}, fx.champ_select, {
      augments: Object.assign({}, fx.champ_select.augments, aug)})});
  const read = () => {
    const box = document.querySelector(
      '#view-champ-select .csv-augment-options');
    const act = document.querySelector(
      '#view-champ-select .csv-augment-slot.is-active');
    return {
      title: box.querySelector('.csv-augments-title').textContent,
      names: [...box.querySelectorAll('.csv-augment-option-name')]
        .map((e) => e.textContent),
      pressed: [...box.querySelectorAll('.csv-augment-option')]
        .filter((e) => e.getAttribute('aria-pressed') === 'true')
        .map((e) => e.dataset.augmentId),
      active: act ? act.className : null,
    };
  };
  const out = [];
  for (const step of args) {
    try {
      if (step === 'leave') mod.renderChampSelectView({phase: 'None'});
      else mod.renderChampSelectView(lcu(step));
      out.push(step === 'leave' ? null : read());
    } catch (e) {
      out.push({error: String(e)});
    }
  }
  return out;
}"""


def test_a_new_offer_re_renders_and_leaving_clears_the_pick(mock_server,
                                                           pw_browser):
    ctx, page, errors = _open(mock_server, pw_browser, _fixture(_SILVER))
    try:
        page.click(_sel(51))
        # NO sig bust: the render gate itself must see the new offer.
        out = page.evaluate(_DIRECT, [
            {"options": _GOLD, "current_round": "gold"},
            {"options": _SILVER, "current_round": "silver"},
            "leave",
            # The next game offers the picked augment again (a new offer,
            # so the render gate fires; an identical champ select is not
            # a new game).
            {"options": _SILVER[::-1], "current_round": "silver"},
        ])
    finally:
        _close(ctx, page)
    gold, silver_again, _left, silver_new = out
    assert gold["names"] == [o["name"] for o in _GOLD], gold
    assert gold["title"] == "GOLD round . pick one", gold
    assert gold["pressed"] == [], gold
    # Same offer, same session: the pick is still shown.
    assert silver_again["names"] == [o["name"] for o in _SILVER], silver_again
    assert silver_again["pressed"] == ["51"], silver_again
    # Left champ select and came back: a fresh session starts unpicked.
    assert silver_new["names"] == [o["name"] for o in _SILVER[::-1]]
    assert silver_new["pressed"] == [], silver_new
    assert not errors, errors[:3]


def test_a_numeric_round_index_renders_its_tier(mock_server, pw_browser):
    ctx, page, errors = _open(mock_server, pw_browser, _fixture(_SILVER))
    try:
        out = page.evaluate(_DIRECT, [
            {"options": _GOLD, "current_round": 1},
            {"options": _SILVER, "current_round": 0},
            {"options": _SILVER, "current_round": "bogus"},
        ])
    finally:
        _close(ctx, page)
    one, zero, bogus = out
    assert "error" not in one, one
    assert one["title"] == "GOLD round . pick one", one
    assert "gold" in one["active"].split(), one
    assert zero["title"] == "SILVER round . pick one", zero
    assert "silver" in zero["active"].split(), zero
    assert bogus["title"] == "SILVER round . pick one", bogus
    assert not errors, errors[:3]


_MEASURE = """async () => {
  await document.fonts.ready;
""" + _HELPERS + """
  const op = (e) => {
    let o = 1;
    for (let n = e; n; n = n.parentElement)
      o *= parseFloat(getComputedStyle(n).opacity);
    return o;
  };
  const out = [];
  for (const row of document.querySelectorAll(
      '#view-champ-select .csv-augment-options .csv-augment-option')) {
    for (const cls of ['csv-augment-option-name', 'csv-augment-option-blurb']) {
      const e = row.querySelector('.' + cls);
      const s = surface(e);
      out.push([cls, e.textContent, row.classList.contains('is-selected'),
                s ? over(rgba(getComputedStyle(e).color), s) : null, s,
                op(e), e.checkVisibility()]);
    }
  }
  return out;
}"""


@pytest.mark.parametrize("theme", _THEMES)
def test_option_text_reaches_aa_picked_or_not(mock_server, pw_browser, theme):
    ctx, page, errors = _open(mock_server, pw_browser, _fixture(_SILVER),
                              theme)
    try:
        page.click(_sel(308))
        page.mouse.move(0, 0)
        page.evaluate(
            "async () => { for (let as; (as = document.getAnimations().filter("
            "(a) => a.playState !== 'finished')).length;)"
            " await Promise.allSettled(as.map((a) => a.finished)); }")
        rows = page.evaluate(_MEASURE)
    finally:
        _close(ctx, page)
    assert len(rows) == 6, rows
    assert sum(1 for r in rows if r[2]) == 2, "one picked row expected"
    low = []
    for cls, text, picked, fg, bg, opacity, visible in rows:
        assert visible and opacity == 1, (cls, text, opacity)
        assert fg and bg, f"no resolved surface under {cls!r}"
        r = _ratio(fg, bg)
        if r < 4.5:
            state = "picked" if picked else "offered"
            low.append(f"{cls} {text.strip()[:24]!r} ({state}) {r:.2f}:1")
    assert not low, f"{theme}: under 4.5:1 - " + "; ".join(low)
    # The augment name is the thing to read; its blurb sits below it.
    for picked in (False, True):
        names = [r for r in rows if r[0].endswith("-name") and r[2] == picked]
        blurbs = [r for r in rows if r[0].endswith("-blurb") and r[2] == picked]
        assert min(_lum(n[3]) for n in names) > max(_lum(b[3]) for b in blurbs)
    assert not errors, errors[:3]
