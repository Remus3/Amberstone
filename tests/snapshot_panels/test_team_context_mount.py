"""
tests/snapshot_panels/test_team_context_mount.py
RM-328 regression guard: the champ-select TEAM CONTEXT mount must exist.

web/js/panels/team_context.js is wired into all three live /api/state
consumers in web/js/main.js (the import at :32, the HTTP-fallback call, the
SSE call, and the 2000 ms pollLcu call). Every one of those calls returned at
renderTeamContext's second line:

    const block = document.getElementById("cs-team-context-block");
    if (!block) return;

because commit ed3ae6f7f (2026-05-14, s208, "retire legacy #cs-overlay
champ-select page") deleted web/index.html's 124-line #cs-overlay block and
the team-context markup lived INSIDE it. That was collateral damage, not a
supersession: the same commit REWROTE web/css/panels/team_context.css:2-3
from "Sits inside the cs-overlay" to "Rendered into the champ-select view",
and decoupled every selector from a .cs-overlay ancestor - a documented
re-home that was never executed. The backend never stopped producing the
payload (tools/lcu_agent.py _maybe_refresh_team_context POSTs on every
champ-select entry; dashboard/_state_builder.py splices coach.team_context),
and the operator repaired that transport 41 days AFTER the mount died
(a3b7e0f03, 2026-06-24).

This drives the REAL EventSource ingest path - the conftest mock server
streams the fixture dict as one SSE event, exactly like the production
/api/state-stream - so the assertions cover the whole seam, not just the
presence of four ids.

Deliberately asserts PAINTED CONTENT, not merely slot count. renderTeamContext
has a no-payload branch that also pads #tc-allies to 5 placeholder slots, so a
count-only test would stay green even if the payload never reached the DOM.

RED at 8599f1adf (no mount -> the guard early-returns -> zero .tc-slot nodes).
"""
import json

# queue 450 (ARAM) on purpose: _RANKED_BLANK_QUEUES is {420, 440}, so a
# ranked queue id would force-blank every summoner_name at the render layer
# and the name assertions below would be testing the obfuscation gate
# instead of the mount.
_QUEUE_ID = 450

_ALLY_NAMES = ["Moonbeam", "Kestrel", "Vantablack", "Orrery", "Pellucid"]
_ENEMY_NAMES = ["Dovetail", "Marlinspike", "Quillon", "Sconce", "Tessitura"]
_ALLY_CHAMPS = ["Jinx", "Thresh", "Ahri", "Sett", "Nunu"]
_ENEMY_CHAMPS = ["Caitlyn", "Nautilus", "Syndra", "Darius", "Rengar"]


def _entry(name, champ, team_id, rank):
    return {
        "puuid": "puuid-" + name.lower(),
        "summoner_name": name,
        "team_id": team_id,
        "locked_champion": champ,
        "rank": rank,
        "mastery_on_locked": 287_000,
        "w_l_streak_7": [4, 3],
        "mains": [champ, "Lux", "Ezreal"],
        "win_rate_recent": 0.55,
    }


_FIXTURE = {
    "mode_key": "client",
    "coach": {
        "team_context": {
            "allies": [
                _entry(n, c, 100, "PLATINUM IV 47 LP")
                for n, c in zip(_ALLY_NAMES, _ALLY_CHAMPS)
            ],
            "enemies": [
                _entry(n, c, 200, "GOLD I 12 LP")
                for n, c in zip(_ENEMY_NAMES, _ENEMY_CHAMPS)
            ],
            "refreshed_at": "2026-09-04T12:00:00+00:00",
            "partial": False,
            "queue_id": _QUEUE_ID,
        },
    },
    "liveclient": None,
    # Gate 1 in renderTeamContext: the panel only paints during ChampSelect.
    "lcu": {"phase": "ChampSelect", "queue_id": _QUEUE_ID},
}


def _open(mock_server, pw_browser):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = json.loads(json.dumps(_FIXTURE))
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + "/", wait_until="domcontentloaded", timeout=15_000
    )
    return ctx, page, errors


def test_team_context_mount_paints_five_ally_slots(mock_server, pw_browser):
    """One real /api/state envelope carrying coach.team_context must light
    #tc-allies with 5 slots carrying the payload's OWN data."""
    ctx, page, errors = _open(mock_server, pw_browser)
    try:
        page.wait_for_function(
            "document.querySelectorAll('#tc-allies .tc-slot').length === 5",
            timeout=10_000,
        )

        # The acceptance criterion: 5 ally child slots.
        assert page.locator("#tc-allies .tc-slot").count() == 5
        # Enemies is the symmetric half of the 5+5 row.
        assert page.locator("#tc-enemies .tc-slot").count() == 5

        # Past `if (!block) return;` AND past both render gates: the block is
        # un-hidden only on the payload path.
        assert page.eval_on_selector(
            "#cs-team-context-block", "el => el.hidden"
        ) is False

        # PAINTED, not merely mounted. The no-payload branch pads to 5 empty
        # placeholders too, so pin content the placeholders cannot produce.
        ally_text = page.eval_on_selector("#tc-allies", "el => el.textContent")
        for name in _ALLY_NAMES:
            assert name in ally_text, f"ally {name!r} missing from #tc-allies"
        assert "PLATINUM IV 47 LP" in ally_text
        assert "287k m" in ally_text          # mastery_on_locked
        assert "55% wr" in ally_text          # win_rate_recent
        assert "4W 3L" in ally_text           # w_l_streak_7

        enemy_text = page.eval_on_selector("#tc-enemies", "el => el.textContent")
        for name in _ENEMY_NAMES:
            assert name in enemy_text, f"enemy {name!r} missing from #tc-enemies"

        # The status chip is the payload branch's own output ("ready" only
        # fires when partial is False); substring-matched so the renderer's
        # separator glyph never reaches this file.
        status = page.eval_on_selector("#tc-status", "el => el.textContent")
        assert status.startswith("ready"), f"unexpected tc-status {status!r}"
        assert f"queue {_QUEUE_ID}" in status

        assert not errors, f"page errors: {errors}"
    finally:
        ctx.close()


def test_team_context_mount_sits_after_the_csv_grid(mock_server, pw_browser):
    """Topology guard: the block is a full-width sibling directly below the
    team rows, inside .view-section-body and immediately after .csv-grid.

    This is the placement the stylesheet was re-homed to in ed3ae6f7f (a flat
    `margin-top: 10px` block with no .cs-overlay ancestor). Pinning it stops a
    future edit from re-orphaning the mount into another view, which is the
    exact failure this row exists to close.
    """
    ctx, page, errors = _open(mock_server, pw_browser)
    try:
        where = page.evaluate(
            """() => {
              const b = document.getElementById("cs-team-context-block");
              if (!b) return null;
              const prev = b.previousElementSibling;
              return {
                parentClass: b.parentElement ? b.parentElement.className : "",
                sectionId: b.closest("section") ? b.closest("section").id : "",
                prevClass: prev ? prev.className : "",
                blockClass: b.className,
                ids: ["tc-status", "tc-allies", "tc-enemies"]
                       .filter((i) => b.querySelector("#" + i) !== null),
              };
            }"""
        )
        assert where is not None, "#cs-team-context-block is not in the DOM"
        assert where["sectionId"] == "view-champ-select"
        assert where["parentClass"] == "view-section-body"
        assert where["prevClass"] == "csv-grid"
        assert where["blockClass"] == "cs-team-context-block"
        # All three inner ids renderTeamContext reads live under the block.
        assert where["ids"] == ["tc-status", "tc-allies", "tc-enemies"]

        assert not errors, f"page errors: {errors}"
    finally:
        ctx.close()
