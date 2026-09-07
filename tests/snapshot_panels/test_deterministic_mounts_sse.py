"""Behavioral characterization: the LIVE SSE ingest path paints the three
deterministic-coaching mounts (item-378 tail / chip task_8a4ebe04).

/api/state ships callouts + lead_projection top-level (item 265 W3E,
dashboard/_state_builder.py) and coach.choices via resolve_choices - but
main.js's renderers are fed ``state.latest`` (the per-mode payload MAP from
web/js/lib/state.js), and until the 74ba5d31 sibling stamp nothing ever
assigned state.latest.coach / .callouts / .lead_projection, so #rn-choices,
#rn-callouts and #rn-lead never painted from SSE/HTTP. ``state.latest`` is
always truthy, so the ``|| p`` fallback never fired either.

Forensics (git -S, 2026-06-10): the call form renderCoachChoices(state.latest
|| p) and the state.coach read are byte-original from 95ea5aca (2026-05-20,
the A/B chip ship) and 74ba5d31 is the FIRST commit ever assigning
state.latest.coach - the live feed was dead from day one, NOT an item-314
regression (that unified the backend choices decode only). The May-2026
"proven live" journal rows in data/decisions_log.jsonl are smoke-test
synthetics (objective_contest shape, extra.note "test from smoke test").

This test drives the REAL EventSource path: the conftest mock server streams
the full fixture dict as one SSE event (raw StateResponse, NOT the WS
envelope), exactly like the production /api/state-stream. Red on
74ba5d31~1's main.js; green after the stamp.
"""
import json

from tests.snapshot_panels.conftest import _WS_STUB

# Minimal but realistic StateResponse: mode_key drives setMode("sr") +
# driveNow; the three deterministic surfaces ride top-level / under coach,
# mirroring the live /api/state probed 2026-06-10 (client-mode Legion).
_FIXTURE = {
    "mode_key": "sr",
    "coach": {
        "action": "Hold mid wave - back off Darius",
        "immediate": "Recall at 1350g",
        "choices": [
            {
                "key": "A",
                "label": "Back off Darius",
                "expected_outcome": "survive the all-in window",
                "confidence": "high",
                "source_tag": "hz-laning",
            },
            {
                "key": "B",
                "label": "Recall now",
                "expected_outcome": "spike Lost Chapter first",
                "confidence": "medium",
                "source_tag": "hz-econ",
            },
        ],
    },
    "callouts": [
        {"tag": "dragon", "line": "Drake spawns 5:00 - set up vision",
         "eta_s": 300.0, "kind": "objective"},
        {"tag": "plates", "line": "Plates fall 14:00 - shove for gold",
         "eta_s": 840.0, "kind": "objective"},
    ],
    "lead_projection": {
        "state": "ahead",
        "magnitude": "slight",
        "line": "Ahead: press the lane, trade on cooldowns.",
        "source_tag": "lead-proj",
    },
    "liveclient": None,
    "summoner_cooldowns": None,
    "lcu": {},
}


def test_sse_paints_choices_lead_callouts(mock_server, pw_browser):
    """One real SSE event carrying coach.choices + callouts +
    lead_projection must light all three mounts."""
    mock_server._store["data"] = json.loads(json.dumps(_FIXTURE))

    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + "/", wait_until="domcontentloaded",
                  timeout=15_000)
        # The SSE event lands within ~2s; renderCoachChoices un-hides the
        # mount and writes the chip buttons.
        page.wait_for_function(
            "document.querySelectorAll('#rn-choices .rc-chip').length >= 2",
            timeout=10_000,
        )
        # A/B chips: keys + labels from coach.choices.
        keys = page.eval_on_selector_all(
            "#rn-choices .rc-chip", "els => els.map(e => e.dataset.key)"
        )
        assert keys == ["A", "B"], f"chip keys {keys}"
        assert "Back off Darius" in page.locator(
            "#rn-choices .rc-chip"
        ).first.inner_text()

        # Lead pill: painted + state class from lead_projection.
        lead_cls = page.eval_on_selector("#rn-lead", "el => el.className")
        assert "rc-lead-ahead" in lead_cls, f"lead class {lead_cls!r}"
        assert "Ahead: press the lane" in page.locator("#rn-lead").inner_text()
        assert page.eval_on_selector("#rn-lead", "el => el.hidden") is False

        # Callouts: both deterministic rows painted.
        rows = page.locator("#rn-callouts .rc-co-row")
        assert rows.count() == 2, f"callout rows {rows.count()}"
        assert "Drake spawns 5:00" in rows.first.inner_text()
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [sse mounts]: {errors[:3]}"


def test_ascii():
    from pathlib import Path
    raw = Path(__file__).read_bytes()
    assert all(b < 128 for b in raw), "non-ASCII byte in test file"
