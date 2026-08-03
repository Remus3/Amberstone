"""tests/test_aram_coach_shadow_choices_native_emit.py

Regression pin for the ARAM shadow log's once-always-empty live `choices`
column, and for the ARAM coach reading that column through the SHARED parser.

Measured 2026-08-02 over data/aram_coach_shadow.jsonl: 4066 rows carried the
live_haiku `choices` KEY and every single one was empty, so `both = 0` and the
deterministic-vs-Haiku choices surface could never be compared - the blocker
for the ARAM half of the Haiku-to-ZERO program. The live model DOES emit the
field (logs/2026-08-02.log carries `Choices: [{"key":"A",...` on the raw
response); it was lost between the response and the artifact.

Root cause, fixed in coaches/_base_coach.py: parse_fields clipped EVERY
extracted value at 220 characters, which is shorter than a two-entry choices
array, so the JSON arrived truncated and the CoachOutput before-validator
(correctly) decoded the malformed string to []. parse_fields now bounds by
content class - see tests/test_base_coach_structured_field_limit.py.

This file pins the ARAM consequence: the coach decodes choices straight out of
the shared parse_fields dict, exactly as the Arena and Brawl coaches do. There
is deliberately NO ARAM-local raw-response re-read; a second mechanism for the
same job is what let the first one rot unnoticed.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coaches._base_coach import parse_fields  # noqa: E402
from core.coach_output import CoachOutput  # noqa: E402

# The exact key list coaches/aram_coach.py hands parse_fields.
_ARAM_KEYS = [
    "action", "immediate", "fight rule",
    "reset / item", "risk", "item build", "item extra",
    "item reasons", "choices",
]

_CHOICES_JSON = (
    '[{"key":"A","label":"Poke with Q now",'
    '"expected_outcome":"You chip Malzahar below half without taking return '
    'damage","confidence":"mid","source_tag":"fight-trade"},'
    '{"key":"B","label":"Hold for the pack",'
    '"expected_outcome":"You reset HP and re-enter the trade window even",'
    '"confidence":"high","source_tag":"pack-grab"}]'
)

_RAW = (
    "Action: POKE PHASE\n"
    "Fight rule: Only engage if Malzahar R is down\n"
    "Reset / item: No fountain. Buy Mercurial Scimitar\n"
    "Risk: Malzahar Nether Grasp suppresses you for 2.5s\n"
    "Item build: The Collector, Phantom Dancer, Kraken Slayer\n"
    "Item extra: omit\n"
    "Item reasons: Collector=lethality spike early\n"
    "Choices: " + _CHOICES_JSON + "\n"
)


def _choices(raw):
    """Decode choices the way coaches/aram_coach.py does."""
    return CoachOutput.from_fields(parse_fields(raw, _ARAM_KEYS)).choices


def test_parse_fields_keeps_the_choices_array_whole():
    """The array is longer than the prose cap and must survive it intact."""
    flds = parse_fields(_RAW, _ARAM_KEYS)
    assert len(_CHOICES_JSON) > 220
    assert flds["choices"] == _CHOICES_JSON


def test_shared_parser_decodes_a_full_length_array():
    out = _choices(_RAW)
    assert isinstance(out, list)
    assert [c["key"] for c in out] == ["A", "B"]
    assert out[0]["label"] == "Poke with Q now"
    assert out[1]["source_tag"] == "pack-grab"


def test_a_deliberate_empty_array_is_honoured():
    assert _choices("Action: WAIT RESPAWN\nChoices: []\n") == []


@pytest.mark.parametrize("raw", [
    "",
    "Action: HOLD\n",
    "Action: HOLD\nChoices: not json at all\n",
    'Action: HOLD\nChoices: {"key":"A"}\n',
])
def test_malformed_or_absent_input_is_fail_soft(raw):
    assert _choices(raw) == []


def test_a_markdown_bold_label_does_not_cost_the_array():
    """The model is told to emit no markdown, but a bolded label must not
    silently cost the whole array. parse_fields strips markdown globally
    before matching, which is why no ARAM-local re-read is needed."""
    raw = "Action: HOLD\n**Choices:** " + _CHOICES_JSON + "\n"
    assert [c["key"] for c in _choices(raw)] == ["A", "B"]


def test_the_aram_local_workaround_is_gone():
    """Two mechanisms for one job is the shim this repo forbids. The ARAM
    coach must decode choices through the shared parser, like Arena and Brawl.
    """
    import coaches.aram_coach as aram

    assert not hasattr(aram, "_native_choices")
    src = Path(aram.__file__).with_suffix(".py").read_text(encoding="utf-8")
    assert "_native_choices" not in src
    assert "CoachOutput.from_fields(flds).choices" in src


def test_shadow_row_records_the_live_choices_column(tmp_path):
    """End-to-end over the surface the shadow report reads: a live artifact
    carrying a decoded choices list must land in the row's live_haiku column."""
    from dashboard._deterministic_coaching import shadow_log_aram_coach

    live_artifact = tmp_path / "aram_coaching_data.json"
    live_artifact.write_text(json.dumps({
        "action": "POKE PHASE",
        "fight_rule": "Only engage if Malzahar R is down",
        "risk": "Malzahar Nether Grasp",
        "reset_item": "No fountain",
        "item_build": "The Collector, Phantom Dancer",
        "item_build_reasons": {"The Collector": "lethality spike"},
        "choices": json.loads(_CHOICES_JSON),
        "item_extra": "",
        "objective": "",
        "champion": "Caitlyn",
    }), encoding="utf-8")

    target = tmp_path / "shadow.jsonl"
    coach = {"champion": "Caitlyn", "hp_pct": 80}
    lc = {"champion": "Caitlyn", "enemy_team": ["Malzahar", "Gragas"]}
    shadow_log_aram_coach(coach, lc, "aram", path=target,
                          live_path=live_artifact)

    lines = [l for l in target.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert [c["key"] for c in rec["live_haiku"]["choices"]] == ["A", "B"]
