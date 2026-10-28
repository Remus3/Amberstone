"""
tests/snapshot_panels/test_active_match_live_directive_gate.py
RM-1093: the Active Match CALL pane on the :2999 FEED path reads the coach
payload through the B4 client mirror (web/js/lib/live_directive_gate.js), the
same defence-in-depth line RM-896 gave next.js and right_now.js.

Why the feed path can be handed an unblanked live payload (measured
2026-10-28 against dashboard/_state_builder.py with the real functions):
in the no-draft champ select -> game window, apply_cs_retention re-splices
the last champ_select while the LCU already reads InProgress and the health
flags are not up yet. resolve_mode_key then answers ("aram", preflip_active
True), apply_preflip_mirror stamps aram_mode on the SERVED health, and
suppress_live_directives returns the coach untouched because is_live_game
is False for a pre-flip. If the :2999 relay answers in that window, the
envelope carries mode_key aram + a non-empty liveclient + lcu InProgress +
coach.action: the client predicate (isLiveGame) says live, and
renderActiveMatch's feed branch (phase InProgress, mode aram) painted
coach.action / immediate / next into #am-call-body.

The row below is that envelope, built from the real session-134 client row
(fixtures/tft_live_s134_client.json) with the mode, health flag and coach
text replaced by synthetic values and the ui_mock ARAM liveclient as the
feed. coach.objective is NOT in LIVE_SUPPRESSED_FIELDS and must keep
painting. textContent, not innerText: the guarantee must not rest on view
routing.
"""
import copy
import json
from pathlib import Path

from tests.snapshot_panels.conftest import _WS_STUB

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = Path(__file__).parent / "fixtures"

_LIVE_TICK_MS = 20_000

_ACTION = "Group mid now - their carry is dead"
_IMMEDIATE = "Trade now - they are low after poke"
_NEXT = "Push the outer tower after the fight"
_OBJECTIVE = "Outer tower is at 30 percent"


def _row(liveclient: dict) -> dict:
    row = json.loads(
        (FIXTURES / "tft_live_s134_client.json").read_text(encoding="utf-8")
    )
    row["mode_key"] = "aram"
    row["health"] = dict(row["health"], mode="aram", aram_mode=True)
    row["liveclient"] = liveclient
    row["coach"] = dict(
        row["coach"],
        mode="aram",
        action=_ACTION,
        immediate=_IMMEDIATE,
        next=_NEXT,
        objective=_OBJECTIVE,
    )
    return row


def _mock_liveclient() -> dict:
    mock = json.loads(
        (ROOT / "web" / "data" / "ui_mock" / "active_match_aram.json")
        .read_text(encoding="utf-8")
    )
    return copy.deepcopy(mock["liveclient"])


def _open(mock_server, pw_browser, data: dict):
    mock_server._store["data"] = data
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + "/", wait_until="domcontentloaded", timeout=15_000)
    return ctx, page, errors


def _wait_objective(page) -> None:
    """The feed branch has painted this row: the OBJECTIVE line is up."""
    page.wait_for_function(
        "(t) => (document.getElementById('am-call-body')?.textContent || '')"
        ".includes(t)",
        arg=_OBJECTIVE,
        timeout=_LIVE_TICK_MS,
    )


def _wait_state_ticks(page, n: int) -> None:
    for _ in range(n):
        with page.expect_response(
            lambda r: r.url.split("?")[0].endswith("/api/state"),
            timeout=_LIVE_TICK_MS,
        ):
            pass


def _call_text(page) -> str:
    return page.evaluate(
        "() => document.getElementById('am-call-body').textContent"
    )


def test_feed_live_row_call_pane_holds_no_live_suppressed_field(
    mock_server, pw_browser
):
    """Feed live (mode_key aram + liveclient + lcu InProgress) with an
    unblanked coach: #am-call-body keeps the OBJECTIVE line and holds none
    of coach.action / immediate / next."""
    ctx, page, errors = _open(mock_server, pw_browser, _row(_mock_liveclient()))
    try:
        _wait_objective(page)
        _wait_state_ticks(page, 1)
        call = _call_text(page)
        assert _OBJECTIVE in call
        for needle in (_ACTION, _IMMEDIATE, _NEXT):
            assert needle not in call, (
                f"live-suppressed text {needle!r} held in #am-call-body mid-game"
            )
        for label in ("RIGHT NOW", "ACTION", "NEXT"):
            assert label not in call, f"{label} row painted from a blanked field"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_loading_screen_row_still_paints_the_call(mock_server, pw_browser):
    """Positive control: the same row with an empty liveclient is the feed
    mode's loading screen (LCU InProgress, :2999 not answering), which the
    B4 contract keeps coached. The feed branch paints RIGHT NOW / ACTION /
    OBJECTIVE / NEXT from the very same coach, so the gate is driven by the
    live predicate and the test above is not passing because the feed path
    never renders this row."""
    ctx, page, errors = _open(mock_server, pw_browser, _row({}))
    try:
        _wait_objective(page)
        _wait_state_ticks(page, 1)
        call = _call_text(page)
        for needle in (_ACTION, _IMMEDIATE, _NEXT, _OBJECTIVE):
            assert needle in call, f"{needle!r} missing from the loading-screen call"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
