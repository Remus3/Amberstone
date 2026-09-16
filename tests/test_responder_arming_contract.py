"""The arming data contract: the child model and the channel contract version.

Five-way-arm criteria (h) and (j). `load_agreement` already fails CLOSED on the
counterparties, the note, the hop budget, the grammar, both window edges and the
expiry. Two things it could not see:

(h) WHICH MODEL the spawned child runs. The runner pins one at `MODEL` and
    `RunnerConfig.model` defaults to it, so the record now has to NAME that pin
    and match it. It is a required MATCH rather than an override on purpose: a
    record is the arming artifact, and letting it choose the child model would
    hand the counterparty-facing file an authority the spawn never gave it.

(j) WHICH CONTRACT VERSION the record was written against. After a five-way
    re-pin bumps `CHANNEL_VERSION`, every record written against the old one
    disarms itself instead of running under a contract that moved.

Both are fail-closed: absent, mistyped or unknown returns `(None, detail)`,
which disarms the cycle.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import tools.inbox_responder_runner as runner  # noqa: E402

NOW = datetime(2026, 9, 8, 20, 0, 0)
PARTICIPANTS = {"RSC": "inbox", "CS": "inbox"}


def _record(**over) -> dict:
    record = {
        "counterparties": ["RSC"],
        "note": "prior.md",
        "window_open": "2026-09-08T19:00:00",
        "window_close": "2026-09-08T21:00:00",
        "hop_budget": 8,
        "grammar": runner.GRAMMAR_A5,
        "expires": "2026-09-08T21:30:00",
        "model": runner.MODEL,
        "contract_version": runner.CHANNEL_VERSION,
        "authored_by": "operator",
        "authored_at": "2026-09-08T18:00:00",
    }
    record.update(over)
    return {k: v for k, v in record.items() if v is not _ABSENT}


class _Absent:
    def __repr__(self) -> str:
        return "<absent>"


_ABSENT = _Absent()


def _load(tmp_path: Path, record: dict):
    path = runner.agreement_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="ascii", newline="\n")
    return runner.load_agreement(tmp_path, PARTICIPANTS, now=NOW)


# ---------------------------------------------------------------------------
# Control: the complete record still arms
# ---------------------------------------------------------------------------


def test_a_complete_record_still_arms(tmp_path):
    """Without this, every arm below could pass on a record nothing accepts."""
    record, detail = _load(tmp_path, _record())
    assert detail == ""
    assert record is not None
    assert record["model"] == runner.MODEL
    assert record["contract_version"] == runner.CHANNEL_VERSION


# ---------------------------------------------------------------------------
# (h) the model id
# ---------------------------------------------------------------------------


MODEL_CASES = [
    ("absent", _ABSENT),
    ("null", None),
    ("empty", ""),
    ("wrong-type-int", 1),
    ("wrong-type-list", ["claude-opus-5"]),
    ("unknown-id", "claude-not-a-model"),
    ("bare-family", "sonnet"),
    ("case-shifted", "CLAUDE-SONNET-4-5"),
]


@pytest.mark.parametrize("label,value", MODEL_CASES, ids=[c[0] for c in MODEL_CASES])
def test_model_fails_closed(tmp_path, label, value):
    record, detail = _load(tmp_path, _record(model=value))
    assert record is None, f"{label} armed the responder"
    assert detail == "malformed:model"


def test_a_known_model_that_is_not_the_spawn_pin_fails_closed(tmp_path):
    """Membership in the allowed tuple is NOT sufficient; it must be the pin.

    This is the arm that makes the field a required match rather than an
    override: a record naming a real, currently allowed model that the spawn
    would not run disarms instead of quietly swapping the child.
    """
    other = [m for m in runner.ALLOWED_MODELS if m != runner.MODEL]
    assert other, "the allowed tuple holds only the pinned id, so this arm is vacuous"
    for model in other:
        record, detail = _load(tmp_path, _record(model=model))
        assert record is None, f"{model} armed the responder"
        assert detail == "malformed:model"


def test_the_allowed_tuple_is_small_explicit_and_contains_the_pin():
    assert isinstance(runner.ALLOWED_MODELS, tuple)
    assert runner.MODEL in runner.ALLOWED_MODELS, (
        "the spawn pin is not an allowed value, so no record could ever satisfy "
        "both the membership check and the required match"
    )
    assert 2 <= len(runner.ALLOWED_MODELS) <= 8
    assert len(set(runner.ALLOWED_MODELS)) == len(runner.ALLOWED_MODELS)
    for model in runner.ALLOWED_MODELS:
        assert isinstance(model, str) and model.startswith("claude-")


def test_the_required_match_is_against_the_model_the_spawn_actually_runs():
    """`load_agreement` compares to `MODEL`; the spawn reads `config.model`.

    Those are the same value only because `RunnerConfig.model` defaults to
    `MODEL`. If that default ever moves, the match above stops being a match
    against the child and this arm is what says so.
    """
    assert runner.RunnerConfig().model == runner.MODEL


# ---------------------------------------------------------------------------
# (j) the contract version
# ---------------------------------------------------------------------------


ABSENT_VERSION_CASES = [
    ("absent", _ABSENT),
    ("null", None),
    ("string", "1"),
    ("float", 1.0),
    ("bool-true", True),
    ("list", [1]),
]


@pytest.mark.parametrize("label,value", ABSENT_VERSION_CASES,
                         ids=[c[0] for c in ABSENT_VERSION_CASES])
def test_contract_version_absent_or_mistyped_fails_closed(tmp_path, label, value):
    record, detail = _load(tmp_path, _record(contract_version=value))
    assert record is None, f"{label} armed the responder"
    assert detail == "malformed:contract_version"


@pytest.mark.parametrize("value", [0, 2, 3, -1, 99])
def test_a_mismatched_contract_version_fails_closed_with_its_own_detail(tmp_path, value):
    if value == runner.CHANNEL_VERSION:
        pytest.skip("that value is the live version, so it is not a mismatch")
    record, detail = _load(tmp_path, _record(contract_version=value))
    assert record is None
    assert detail == "malformed:contract_version_mismatch", (
        "a record written against a different contract must be distinguishable "
        "from one that declares no contract at all"
    )


def test_absent_and_mismatched_are_different_details(tmp_path):
    _, absent = _load(tmp_path, _record(contract_version=_ABSENT))
    _, wrong = _load(tmp_path, _record(contract_version=runner.CHANNEL_VERSION + 1))
    assert absent != wrong


def test_the_runner_constant_equals_the_version_the_doc_declares():
    """The guarded-constant half of the (j) decision.

    The runner carries `CHANNEL_VERSION` as a module constant rather than
    reading `docs/CHANNEL.md` at import time: an import that parses a markdown
    file fails in any tree where the doc is absent, renamed or mid-re-pin, and a
    runner that cannot import cannot even write its disarmed row. This arm is
    what keeps the constant honest, and it reddens on a bump of either side.
    """
    text = (REPO_ROOT / "docs" / "CHANNEL.md").read_bytes().decode("ascii")
    hit = re.search(r"^CHANNEL_VERSION:\s*(\d+)\s*$", text, re.MULTILINE)
    assert hit is not None, (
        "docs/CHANNEL.md declares no CHANNEL_VERSION line; an unparsed doc must "
        "fail here rather than leave the constant unchecked"
    )
    assert int(hit.group(1)) == runner.CHANNEL_VERSION, (
        f"the doc declares CHANNEL_VERSION {hit.group(1)} and the runner carries "
        f"{runner.CHANNEL_VERSION}; a bump is a five-way re-pin round and both "
        "sides move in it"
    )


# ---------------------------------------------------------------------------
# Both fields are SEMANTIC: changing either is a different agreement
# ---------------------------------------------------------------------------


def test_both_new_fields_change_the_agreement_id():
    base = _record()
    first = runner.agreement_id_of(base)
    assert runner.agreement_id_of(dict(base, model="claude-opus-5")) != first, (
        "a model swap kept the agreement id, so the hop chain would carry across "
        "a change of child"
    )
    assert runner.agreement_id_of(
        dict(base, contract_version=runner.CHANNEL_VERSION + 1)) != first
    assert runner.agreement_id_of(dict(base, authored_by="someone-else")) == first
