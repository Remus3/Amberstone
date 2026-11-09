"""
tests/snapshot_panels/test_threat_strip_team_resolve.py
S144-U-218: the Active Match THREATS strip never lists the operator or the duo.

docs/qa/UI_UX_QUEUE_2026-07-21.md (In-game overlay) filed "DS panel THREATS
row renders 5 (SR) / 12 (Arena) EMPTY placeholder circles". S144-U-217 fixed
the empty circles. The 12 is the other half: an Arena lobby has 12 players,
and the strip filtered the roster with ``pl.team && pl.team !== myTeam``, so
when ``_resolveMyTeam`` found no row for the activePlayer name (myTeam null)
every player, the operator and the duo included, was drawn as a threat.

Two renders of the Arena ui_mock fixture (web/data/ui_mock/
active_match_arena.json, 6 subteams of 2, synthetic names), served through a
page route:
  - as authored: the activePlayer resolves to subteam "100", so the strip has
    the 10 players off it and neither Jinx (me) nor Karma (the duo);
  - with an activePlayer name no roster row carries: no THREATS strip at all,
    instead of 12 rows that start with the operator's own champion.
Why the name did not match in the live capture is the live-gated half
(docs/LIVE_GAME_GATED_SYNC.md G5-11, the Arena team layout); not claimed.
Text-first: DOM counts and alt text; /api/damage-mix answered by a stand-in so
nothing leaves the box. No pixels.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ARENA_FIXTURE = ROOT / "web" / "data" / "ui_mock" / "active_match_arena.json"

_MIX = {"physical": 0.6, "magical": 0.3, "true": 0.1, "on_hit": 0.0}


def _fixture(unmatched: bool) -> dict:
    data = json.loads(ARENA_FIXTURE.read_text(encoding="utf-8"))
    if unmatched:
        data["liveclient"]["activePlayer"]["summonerName"] = "NotInThisLobby#TAG"
        data["liveclient"]["activePlayer"]["riotIdGameName"] = "NotInThisLobby"
    return data


def _render(pw_browser, mock_server, unmatched: bool) -> dict:
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    body = json.dumps(_fixture(unmatched))
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route(
        "**/data/ui_mock/active_match_arena.json*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=body),
    )
    page.route(
        "**/api/damage-mix*",
        lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"ok": True, "mix": _MIX}),
        ),
    )
    try:
        page.goto(mock_server.url + "/?ui_mock=1&mode=arena#active-match",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "document.querySelector('#am-sub') && "
            "document.querySelector('#am-sub').textContent.indexOf('InProgress') >= 0",
            timeout=10_000,
        )
        # The BUILD pane is painted (its first line is in) before we read the strip.
        page.wait_for_function(
            "(() => { const b = document.querySelector('#am-build-body');"
            " return !!b && b.textContent.trim().length > 0; })()",
            timeout=10_000,
        )
        out = page.evaluate(
            """() => {
              const b = document.querySelector('#am-build-body');
              const s = b.querySelector('.threat-strip');
              const heads = b.querySelectorAll('[data-call-line="threats"]');
              return {
                strips: b.querySelectorAll('.threat-strip').length,
                heads: heads.length,
                alts: s ? Array.from(s.querySelectorAll('img.threat-portrait')).map((i) => i.alt) : [],
                rows: s ? s.querySelectorAll('.threat-row').length : 0,
                children: b.children.length,
                text: b.textContent.trim().slice(0, 200),
              };
            }"""
        )
    finally:
        page.close()
        ctx.close()
    out["errors"] = errors
    return out


def test_arena_threats_exclude_me_and_duo(mock_server, pw_browser):
    out = _render(pw_browser, mock_server, unmatched=False)
    assert not out["errors"], out["errors"][:3]
    assert out["strips"] == 1, out
    assert out["heads"] == 1, out
    assert out["rows"] == 10, out
    assert len(out["alts"]) == 10, out
    assert "Jinx" not in out["alts"], out
    assert "Karma" not in out["alts"], out


def test_arena_threats_hidden_when_my_team_unresolved(mock_server, pw_browser):
    out = _render(pw_browser, mock_server, unmatched=True)
    assert not out["errors"], out["errors"][:3]
    # The BUILD pane did paint (the fixture's build module), so an empty strip
    # is not an empty page.
    assert out["children"] >= 1 and out["text"], out
    # Before S144-U-218 this was 12 rows led by the operator's own Jinx.
    assert out["strips"] == 0, out
    assert out["heads"] == 0, out
    assert out["alts"] == [], out
