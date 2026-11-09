"""
tests/snapshot_panels/test_threat_strip_live_names.py
S144-U-217: the Active Match THREATS strip with the LIVE Live Client name shape.

docs/qa/UI_UX_QUEUE_2026-07-21.md (In-game overlay) filed "DS panel THREATS
row renders 5 (SR) / 12 (Arena) EMPTY placeholder circles". Root cause: the
Live Client serves allPlayers[].rawChampionName as a localization key,
"game_character_displayname_Kaisa" (measured live 2026-07-20, see
web/js/panels/aram_balance.js _AB_RAW_PREFIX), and _threatRow PREFERRED that
field, so every live enemy got the portrait
/img/champion/gamecharacterdisplaynameKaisa.png (404 locally, 404 on the
CDN retry, then hidden) and asked /api/damage-mix for
champ_id=gamecharacterdisplaynameKaisa (the route cannot resolve it, answers
400, the donut draws its grey "?" ring). Five enemies, five empty circles.

The ui_mock fixture never showed it: web/data/ui_mock/active_match_sr.json
sets rawChampionName equal to the DDragon id. This module serves that same
fixture with the live name shape instead (display championName + the
localization key, one enemy swapped to Wukong, whose display name is not its
DDragon id MonkeyKing), and stands in for the two server answers the way the
real ones behave:
  - a champion square answers 404 unless its file name is a real DDragon id
    (the byId values of web/data/champions_index.json); the public CDN retry
    is refused too, so nothing leaves the box;
  - /api/damage-mix answers a mix only for a real DDragon id, else 400.
Asserts every enemy row keeps a visible portrait named by its DDragon id,
every donut asked for that id and drew its arcs, and no row fell back to the
"?" tile. Text-first (computed display, attributes, request log); no pixels.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SR_FIXTURE = ROOT / "web" / "data" / "ui_mock" / "active_match_sr.json"
CHAMPS_INDEX = ROOT / "web" / "data" / "champions_index.json"

_RAW_PREFIX = "game_character_displayname_"
# DDragon id -> the display name the Live Client puts in championName.
_DISPLAY = {"Kaisa": "Kai'Sa", "MonkeyKing": "Wukong"}
# The SR fixture's jungle enemy becomes Wukong, so one row needs the key.
_SWAP = {"Elise": "MonkeyKing"}

_MIX = {"physical": 0.6, "magical": 0.3, "true": 0.1, "on_hit": 0.0}


def _ddragon_ids() -> set:
    data = json.loads(CHAMPS_INDEX.read_text(encoding="utf-8"))
    return {str(v) for v in data["byId"].values()}


def _live_shaped_fixture() -> tuple[dict, list]:
    """The SR ui_mock fixture with the live allPlayers name shape, plus the
    DDragon ids of the enemy team in roster order."""
    data = json.loads(SR_FIXTURE.read_text(encoding="utf-8"))
    enemies = []
    for pl in data["liveclient"]["allPlayers"]:
        slug = _SWAP.get(pl["rawChampionName"], pl["rawChampionName"])
        pl["championName"] = _DISPLAY.get(slug, slug)
        pl["rawChampionName"] = _RAW_PREFIX + slug
        if pl["team"] == "CHAOS":
            enemies.append(slug)
    return data, enemies


def _open(pw_browser, mock_server):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    fixture, enemies = _live_shaped_fixture()
    known = _ddragon_ids()
    asked: list[str] = []
    portraits_404: list[str] = []

    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    def _fixture(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(fixture))

    def _damage_mix(route):
        from urllib.parse import parse_qs, urlparse

        q = parse_qs(urlparse(route.request.url).query)
        champ = (q.get("champ_id") or [""])[0]
        asked.append(champ)
        if champ in known:
            body = {"ok": True, "champ_id": champ, "mix": _MIX}
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(body))
        else:
            route.fulfill(status=400, content_type="application/json",
                          body=json.dumps({"ok": False, "error": "unknown_champ"}))

    def _champ_square(route):
        name = route.request.url.rsplit("/", 1)[-1].split("?", 1)[0]
        stem = name.removesuffix(".png")
        if stem in known and "ddragon.leagueoflegends.com" not in route.request.url:
            route.continue_()
        else:
            portraits_404.append(name)
            route.fulfill(status=404, body="")

    page.route("**/data/ui_mock/active_match_sr.json*", _fixture)
    page.route("**/api/damage-mix*", _damage_mix)
    page.route("**/img/champion/*", _champ_square)

    page.goto(mock_server.url + "/?ui_mock=1&mode=sr#active-match",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "document.querySelector('#am-sub') && "
        "document.querySelector('#am-sub').textContent.indexOf('InProgress') >= 0",
        timeout=10_000,
    )
    # Every donut settles: no row still shows the loading wrap.
    page.wait_for_function(
        "(() => { const s = document.querySelector('#view-active-match .threat-strip');"
        " return !!s && s.querySelectorAll('.threat-row').length > 0"
        " && !s.querySelector('.threat-donut-loading'); })()",
        timeout=10_000,
    )
    return ctx, page, errors, enemies, asked, portraits_404


_READ_ROWS = """
() => {
  const s = document.querySelector('#view-active-match .threat-strip');
  return Array.from(s.querySelectorAll('.threat-row')).map((row) => {
    const img = row.querySelector('img.threat-portrait');
    const donut = row.querySelector('.threat-donut');
    return {
      src: img ? img.getAttribute('src') : null,
      alt: img ? img.alt : null,
      display: img ? getComputedStyle(img).display : null,
      loaded: img ? (img.complete && img.naturalWidth > 0) : false,
      empty: donut ? donut.classList.contains('threat-donut-empty') : true,
      arcs: donut ? donut.querySelectorAll('svg circle').length : 0,
      title: donut ? donut.title : null,
    };
  });
}
"""


def test_threat_strip_resolves_live_localization_keys(mock_server, pw_browser):
    ctx, page, errors, enemies, asked, portraits_404 = _open(pw_browser, mock_server)
    try:
        # Portrait loads are async; wait until each has either loaded or been hidden.
        page.wait_for_function(
            "Array.from(document.querySelectorAll('#view-active-match img.threat-portrait'))"
            ".every((i) => i.complete)",
            timeout=10_000,
        )
        rows = page.evaluate(_READ_ROWS)
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors: {errors[:3]}"
    # An empty strip would pass every per-row check below, so pin the count.
    assert len(enemies) == 5
    assert len(rows) == len(enemies), rows
    for row, slug in zip(rows, enemies):
        assert row["src"].endswith(f"/img/champion/{slug}.png"), row
        assert row["display"] != "none", row
        assert row["loaded"], row
        assert row["alt"] == _DISPLAY.get(slug, slug), row
        assert not row["empty"], row
        # Background ring plus at least one damage arc.
        assert row["arcs"] >= 2, row
        assert row["title"].startswith("Damage mix:"), row
    assert sorted(set(asked)) == sorted(enemies), asked
    assert not portraits_404, portraits_404
