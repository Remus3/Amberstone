"""RM-1401 - web/js comments name the symbol, not a line, and a ratchet holds it.

RM-1400 ratcheted the Python tree. The same rot lives in web/js comments:
measured 2026-11-04 over every tracked non-test web/js/**/*.js, eleven modules
cited a neighbour by `<file>:<line>` and the cites had already drifted (the
`core/build_planner/scoring.py:106-123` stage function and its `:57-60`
constants had moved; `cd_ledger.js:74-79` names a file that no longer exists).
Each of the eleven now names the function, constant or block it means.

This pins (a) none of the eleven cites by line again, (b) each still carries its
replacement prose, (c) a ratchet: any other tracked non-test web/js .js that
cites `<file>.<ext>:<n>` fails unless it is in the shrinking _BASELINE with a
reason, and a baseline entry that stops citing fails until it is dropped.

RM-1402 moved last_match.js, build_insights.js and active_match.js (one cite
each) out of the baseline into FIXED; only the two other-lane files remain.
"""
from __future__ import annotations

import re

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

FIXED = (
    "web/js/lib/next_buy_model.js",
    "web/js/panels/objective_gauges.js",
    "web/js/panels/champ_select.js",
    "web/js/panels/ds_matchup.js",
    "web/js/lib/overlay_priority.js",
    "web/js/lib/overlay_item_radial.js",
    "web/js/panels/replay_minimap.js",
    "web/js/panels/replay_events.js",
    "web/js/panels/callouts.js",
    "web/js/lib/summoner_spells.js",
    "web/js/lib/overlay_tooltip.js",
    # RM-1402: the next slice out of the baseline.
    "web/js/panels/last_match.js",
    "web/js/panels/build_insights.js",
    "web/js/panels/active_match.js",
)

# (module, prose it must still carry)
NEW_PROSE = (
    ("web/js/lib/next_buy_model.js", "`liveclient_summary()` in dashboard/_liveclient.py"),
    ("web/js/lib/next_buy_model.js", "`stage_for` in core/build_planner/scoring.py"),
    ("web/js/lib/next_buy_model.js", "the `upgrade_trinket` action in core/build_planner/replan.py"),
    ("web/js/panels/objective_gauges.js", '`out["game_time_s"]` in `liveclient_summary()`'),
    ("web/js/panels/objective_gauges.js", "`_dynamic_epic_callouts` / `_objective_callouts`"),
    ("web/js/panels/objective_gauges.js", "(`_soul_secured_at`)"),
    ("web/js/panels/champ_select.js", "`_LOBBY_QUEUE_NAMES` map in lcu/snapshot_shape.py"),
    ("web/js/panels/champ_select.js", "`active_round` in lcu/champ_select_shape.py"),
    ("web/js/panels/ds_matchup.js", "`assignedPosition` (the role pip in web/js/panels/champ_select.js"),
    ("web/js/panels/ds_matchup.js", "`liveclient_summary()` in dashboard/_liveclient.py"),
    ("web/js/lib/overlay_priority.js", "right_now.js `renderRightNow`"),
    ("web/js/lib/overlay_item_radial.js", "the <html>-mount trick in champ_select.js"),
    ("web/js/panels/replay_minimap.js", "`calculate_death_timer` in core/post_game_score.py"),
    ("web/js/panels/replay_events.js", "alphanumeric-strip normalisation of web/js/lib/items_index.js"),
    ("web/js/panels/callouts.js", "`# Per-mode directive table` block of core/lead_projection.py"),
    ("web/js/lib/overlay_tooltip.js", "the <html>-mount trick in champ_select.js"),
    ("web/js/lib/summoner_spells.js", "the `/icons/spells/` entry of GET_ROUTES in dashboard/routes_static.py"),
    ("web/js/panels/last_match.js", "the success branch of the rubric fetch in `_setHeroRoleGrade`"),
    ("web/js/panels/build_insights.js", "the CHAMPS.byId slug lookup in `_renderTcRow` of web/js/panels/last_match.js"),
    ("web/js/panels/active_match.js", 'the `out["players"]` block of `liveclient_summary()` in dashboard/_liveclient.py'),
)

# (file the anchor must be IN, anchor text) - the replacement still resolves.
ANCHORS = (
    ("dashboard/_liveclient.py", "def liveclient_summary"),
    ("dashboard/_liveclient.py", 'out["game_time_s"]'),
    ("core/build_planner/scoring.py", "def stage_for"),
    ("core/build_planner/replan.py", 'kind="upgrade_trinket"'),
    ("core/event_callouts.py", "def _dynamic_epic_callouts"),
    ("core/event_callouts.py", "def _objective_callouts"),
    ("core/event_callouts.py", "def _soul_secured_at"),
    ("lcu/champ_select_shape.py", "def active_round"),
    ("lcu/snapshot_shape.py", "_LOBBY_QUEUE_NAMES = {"),
    ("core/post_game_score.py", "def calculate_death_timer"),
    ("core/lead_projection.py", "# Per-mode directive table"),
    ("dashboard/routes_static.py", 'prefix("/icons/spells/")'),
    ("web/js/panels/right_now.js", "function renderRightNow"),
    ("web/js/lib/items_index.js", "replace(/[^a-z0-9]/g"),
    ("web/js/panels/champ_select.js", "assignedPosition"),
    ("web/js/panels/last_match.js", "function _setHeroRoleGrade"),
    ("web/js/panels/last_match.js", "function _renderTcRow"),
    ("dashboard/_liveclient.py", 'out["players"] = ['),
)

# A file cited by position: "x.py:12", "x.js:7506+", "x.toml:27", "x.py:12-15".
_LINE_CITE = re.compile(r"[\w./\\-]+\.(?:py|md|js|css|ps1|html|toml|ya?ml|json):\d+")

# rel path -> why it may keep a line cite. Only shrinks.
_BASELINE = {
    "web/js/main.js": "another lane branch changed it",
    "web/js/panels/review_player_model.js": "another lane branch changed it",
}


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_bytes().decode("utf-8")


def _citers() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path in repo_files(REPO_ROOT, ("*.js",)):
        rel = relative_posix(path)
        if not rel.startswith("web/js/"):
            continue
        if rel.endswith(".test.js") or "/vendor/" in rel:
            continue
        hits = _LINE_CITE.findall(path.read_text(encoding="utf-8"))
        if hits:
            out[rel] = hits
    return out


@pytest.mark.parametrize("rel", FIXED)
def test_fixed_module_cites_nothing_by_line(rel):
    hits = _LINE_CITE.findall(_read(rel))
    assert not hits, f"{rel} cites by line again: {hits} (RM-1401)"


@pytest.mark.parametrize("rel,needle", NEW_PROSE)
def test_fixed_module_carries_its_replacement_prose(rel, needle):
    text = " ".join(_read(rel).replace("\n//", " ").replace("\n  //", " ")
                    .replace("\n *", " ").split())
    assert needle in text, f"{rel} lost its replacement prose: {needle!r}"


@pytest.mark.parametrize("rel,anchor", ANCHORS)
def test_replacement_anchor_still_resolves(rel, anchor):
    assert anchor in _read(rel), f"{anchor!r} is gone from {rel}: re-point the prose"


def test_ratchet_no_new_line_cites():
    new = {rel: hits for rel, hits in _citers().items() if rel not in _BASELINE}
    assert not new, f"new web/js line cites (name the symbol instead): {new}"


def test_ratchet_baseline_only_shrinks():
    citers = _citers()
    stale = sorted(rel for rel in _BASELINE if rel not in citers)
    assert not stale, f"baseline entries that no longer cite - drop them: {stale}"


def test_ratchet_sees_files():
    """An empty enumeration must not pass: the walk finds the known citers."""
    citers = _citers()
    assert "web/js/main.js" in citers
    assert len(list(repo_files(REPO_ROOT, ("*.js",)))) > 50
