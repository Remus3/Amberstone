"""FLEET-KIT v6 (MAIN order 2026-10-04, sections 4c/4d): the EW code replaces LL.

The responder and the sibling-name sweep resolve counterparty codes from the
gitignored participants map, never from a hard-coded list, so EW needs no code
literal in either. These tests pin that claim: EW is admitted end to end by the
same paths that admitted LL, with only the map changed.

They also pin the session-start anomaly the swap produced. The live arming
record still names the retired code in `counterparties` after the map dropped
it, and `load_agreement` refused the whole record as `malformed:counterparties`
- the same detail as a structurally broken field, which sent a session hunting
for a JSON fault that was not there. The refusal is correct and stays fail
closed; the DETAIL now says which of the two it is, the way
`contract_version` / `contract_version_mismatch` already do.

Every path and name here is synthetic; no sibling checkout name appears.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from tools import inbox_responder, sibling_name_sweep as sweep
from tools import inbox_responder_runner as runner

# Drive prefix ASSEMBLED, not spelled: a literal drive-rooted path in this
# file is a live STRUCT_DRIVE_ROOT hit for the sweep's tree arm (same
# pattern as tests/test_sibling_name_sweep.py).
_D = "C:" + "\\"

NOW = datetime(2026, 10, 5, 12, 0, 0)


def _record(**over) -> dict:
    rec = {
        "counterparties": ["EW"],
        "note": "synthetic",
        "window_open": "2026-10-05T00:00:00",
        "window_close": "2026-10-06T00:00:00",
        "hop_budget": 4,
        "grammar": runner.GRAMMAR_A5,
        "expires": "2026-10-06T00:00:00",
        "model": runner.MODEL,
        "contract_version": runner.CHANNEL_VERSION,
    }
    rec.update(over)
    return rec


def _write(root: Path, rec: dict) -> None:
    path = runner.agreement_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec), encoding="ascii")


def test_an_agreement_naming_ew_arms_when_ew_is_mapped(tmp_path):
    _write(tmp_path, _record(counterparties=["CS", "EW"]))
    record, detail = runner.load_agreement(
        tmp_path, {"CS": tmp_path / "a", "EW": tmp_path / "b"}, now=NOW
    )
    assert detail == ""
    assert record is not None and record["counterparties"] == ["CS", "EW"]


def test_a_retired_code_left_in_the_record_disarms_with_a_distinct_detail(tmp_path):
    """The live 2026-10-04 shape: the map swapped LL for EW, the record did not."""
    _write(tmp_path, _record(counterparties=["CS", "LL", "LW", "RSC", "SS"]))
    participants = {c: tmp_path / c for c in ("CS", "EW", "LW", "RSC", "SS")}
    record, detail = runner.load_agreement(tmp_path, participants, now=NOW)
    assert record is None
    assert detail == "malformed:counterparties_unmapped"
    # No code reaches the detail: participant keys never reach a log line.
    assert "LL" not in detail and "EW" not in detail


def test_a_structurally_bad_counterparties_field_keeps_the_shape_detail(tmp_path):
    for bad in ([], "EW", [1], None):
        _write(tmp_path, _record(counterparties=bad))
        record, detail = runner.load_agreement(tmp_path, {"EW": tmp_path}, now=NOW)
        assert record is None
        assert detail == "malformed:counterparties", bad


def test_pending_notes_admits_an_ew_note_when_ew_is_a_participant(tmp_path):
    inbox = tmp_path / "moon_sync_inbox"
    inbox.mkdir()
    ew = "2026-10-05-0900-from-EW-hello.md"
    ll = "2026-10-05-0901-from-LL-hello.md"
    (inbox / ew).write_text("x", encoding="ascii")
    (inbox / ll).write_text("x", encoding="ascii")
    got = inbox_responder.pending_notes(inbox, tmp_path, participants=("EW",))
    assert ew in got
    assert ll not in got


def test_the_sweep_carries_ew_as_a_code_and_halts_on_its_path():
    cfg = sweep.config_from_parts(
        [_D + "Synthetic Wake Tree"], {"EW": _D + "Synthetic Wake Tree"}
    )
    assert cfg.mode == sweep.MODE_ARMED
    assert "EW" in cfg.codes
    needles = sweep.build_needles(cfg)
    hits = sweep.scan_text(
        needles, cfg.codes, "see " + _D + "Synthetic Wake Tree\\notes.txt",
        path="probe.txt", source="TEST", status="A",
    )
    assert hits, "a path into the EW participant's checkout must halt a push"


# ---------------------------------------------------------------------------
# Retired siblings stay NEEDLES (MAIN order 2026-10-05-0230 section 2.2)
# ---------------------------------------------------------------------------
# A retired tree leaves participants (the responder must never address or spawn
# for it) but its name is still a leak, so the sweep reads a separate
# `retired` map from the same gitignored file: code -> path, or code -> list of
# paths / bare project names. Every value arms a name slot and every key arms a
# code, exactly like a participant.

def _cfg(tmp_path: Path, blob: dict):
    ops = tmp_path / "ops"
    ops.mkdir(parents=True, exist_ok=True)
    (ops / "moon_sync_repos.json").write_text(json.dumps(blob), encoding="ascii")
    return sweep.load_config(root=tmp_path, env={})


def _scan(cfg, text: str):
    return sweep.scan_text(
        sweep.build_needles(cfg), cfg.codes, text,
        path="probe.txt", source="TEST", status="A",
    )


def test_a_retired_sibling_still_trips_the_sweep(tmp_path):
    cfg = _cfg(tmp_path, {
        "repos": [_D + "Synthetic Wake Tree"],
        "participants": {"EW": _D + "Synthetic Wake Tree"},
        "retired": {"QQ": [_D + "Synthetic Lamp Tree", "Synthfogname"]},
    })
    assert cfg.mode == sweep.MODE_ARMED
    assert "QQ" in cfg.codes and "EW" in cfg.codes
    assert "QQ" not in cfg.participants, "a retired code must never become a participant"
    assert _scan(cfg, "see " + _D + "Synthetic Lamp Tree\\notes.txt"), "retired PATH arm"
    assert _scan(cfg, "the Synthfogname project said so"), "retired internal-NAME arm"
    assert _scan(cfg, "see " + _D + "Synthetic Wake Tree\\x"), "live EW arm"


def test_a_retired_value_may_be_a_single_path_string(tmp_path):
    cfg = _cfg(tmp_path, {
        "repos": [_D + "Synthetic Wake Tree"],
        "retired": {"QQ": _D + "Synthetic Lamp Tree"},
    })
    assert _scan(cfg, "see " + _D + "Synthetic Lamp Tree\\notes.txt")


def test_a_config_holding_only_retired_siblings_is_still_armed(tmp_path):
    cfg = _cfg(tmp_path, {"retired": {"QQ": _D + "Synthetic Lamp Tree"}})
    assert cfg.mode == sweep.MODE_ARMED


def test_the_responder_never_reads_the_retired_map(tmp_path):
    lamp = tmp_path / "lamp"
    (lamp / "moon_sync_inbox").mkdir(parents=True)
    repo = tmp_path / "repo"
    (repo / "ops").mkdir(parents=True)
    (repo / "ops" / "moon_sync_repos.json").write_text(
        json.dumps({"participants": {}, "retired": {"QQ": str(lamp)}}), encoding="ascii")
    keep, _detail = runner.load_participants(repo)
    assert "QQ" not in keep


def test_the_example_template_documents_the_retired_key():
    blob = json.loads(
        (Path(__file__).resolve().parent.parent / "ops" / "moon_sync_repos.example.json")
        .read_text(encoding="utf-8"))
    assert "retired" in blob and "_retired_doc" in blob
    assert isinstance(blob["retired"], dict) and blob["retired"]
