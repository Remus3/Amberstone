"""RM-601 (directive X-01, external reference E): Live Client shape audit,
the unconsumed-EventName guard, and the voidgrub / steal wiring.

Probe at origin/main fc9b12431 (git grep): zero references to ``HordeKill``
and zero to the ``Stolen`` event key anywhere in RC source, so objective
callouts ignored voidgrubs and steals. The objective parse is
``dashboard/_liveclient.py`` ``objective_events`` (name map
DragonKill/BaronKill/HeraldKill); its callout consumer is
``core/event_callouts.py`` ``next_callouts``.

The fixture ``tests/fixtures/liveclient/allgamedata_synthetic_rm601.json`` is
SYNTHETIC and name-scrubbed (SyntheticN#TST), never a capture.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core import event_callouts
from tools import liveclient_shape_audit as audit_tool

_FIXTURE = (Path(__file__).parent / "fixtures" / "liveclient"
            / "allgamedata_synthetic_rm601.json")

# EventName values that appear in the synthetic fixture but have NO RC
# consumer on purpose. Every entry carries its reason. Remove an entry when a
# consumer lands (the stale-entry test below enforces that).
UNCONSUMED_ALLOWLIST: dict[str, str] = {
    "GameStart": "game start is taken from the LCU gameflow phase and the "
                 "gameData clock, never from this marker event",
    "FirstBrick": "first-tower bonus marker; the same tower fall is consumed "
                  "via its TurretKilled event",
    "Multikill": "kill-streak flavour; ChampionKill already carries every "
                 "kill the coaches count",
    "Ace": "team-wipe marker; derivable from ChampionKill + respawn timers, "
           "no callout planned",
}


def _fixture() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def consumed() -> set[str]:
    names = audit_tool.consumed_event_names()
    # Vacuity anchor: the scan must still reach known consumers. An empty
    # scan would make every name "unconsumed" and fail loudly anyway, but a
    # scan that lost dashboard/ would silently lose these three.
    assert {"DragonKill", "BaronKill", "InhibKilled"} <= names
    return names


# -- the guard -----------------------------------------------------------------

def test_fixture_is_synthetic_and_scrubbed():
    raw = _FIXTURE.read_text(encoding="utf-8")
    assert raw.isascii()
    data = _fixture()
    for p in data["allPlayers"]:
        assert p["riotId"].startswith("Synthetic") and p["riotId"].endswith("#TST")


def test_every_fixture_event_name_has_a_consumer_or_a_reasoned_allowlist(consumed):
    names = audit_tool.event_names([_fixture()])
    assert "HordeKill" in names  # the fixture still exercises the item
    missing = sorted(n for n in names
                     if n not in consumed and n not in UNCONSUMED_ALLOWLIST)
    assert missing == [], (
        f"EventName(s) with no RC consumer: {missing}. Wire a consumer or add "
        "an UNCONSUMED_ALLOWLIST entry WITH a reason.")


def test_allowlist_entries_carry_reasons_and_are_not_stale(consumed):
    for name, reason in UNCONSUMED_ALLOWLIST.items():
        assert isinstance(reason, str) and len(reason.strip()) >= 20, name
        assert name not in consumed, (
            f"{name} now has a consumer; drop it from UNCONSUMED_ALLOWLIST")


# -- the audit tool --------------------------------------------------------------

def _probe_payload() -> dict:
    data = _fixture()
    data["events"]["Events"].append(
        {"EventID": 99, "EventName": "Rm601ProbeEvent", "EventTime": 1.0,
         "Rm601ProbeKey": 1})
    data["gameData"]["gameTime"] = "510"  # a modelled number sent as a string
    return data


def test_audit_reports_the_three_lists(tmp_path):
    rep = audit_tool.audit([_probe_payload()])
    assert "Rm601ProbeEvent" in rep["unconsumed_events"]
    assert "HordeKill" not in rep["unconsumed_events"]
    joined = "\n".join(rep["type_mismatches"])
    assert "events.Events[].Stolen: expected bool, got str" in joined
    assert "gameData.gameTime: expected number, got str" in joined
    assert "events.Events[].Rm601ProbeKey" in rep["unread_keys"]
    assert "events.Events[].EventName" not in rep["unread_keys"]


def test_audit_cli_reads_a_directory_and_a_wrapped_capture(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(_probe_payload()), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({"ts": 1, "data": _fixture()}),
                                     encoding="utf-8")
    assert len(audit_tool.load_payloads(tmp_path)) == 2
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, str(root / "tools" / "liveclient_shape_audit.py"),
         str(tmp_path)],
        capture_output=True, text=True, timeout=120, cwd=str(root))
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "over 2 payload(s)" in out
    for title in ("EventName values with no RC consumer",
                  "Modelled fields with a mismatched JSON type",
                  "Keys nothing in RC reads"):
        assert title in out
    assert "Rm601ProbeEvent" in out


# -- HordeKill / Stolen wiring ---------------------------------------------------

def _summary(data: dict) -> dict:
    from tests.test_liveclient_objective_events import _summary as _s
    return _s(data)


def test_hordekill_parses_into_voidgrub_objective_events():
    out = _summary(_fixture())
    grubs = [e for e in out["objective_events"] if e["name"] == "voidgrub"]
    assert [e["down_at_s"] for e in grubs] == [488.0, 492.0, 497.0]
    assert [e["killer_team"] for e in grubs] == ["ally", "ally", "enemy"]


def test_stolen_string_parses_to_a_steal_flag():
    out = _summary(_fixture())
    by_t = {e["down_at_s"]: e for e in out["objective_events"]}
    assert by_t[497.0]["stolen"] is True     # "True"
    assert by_t[488.0]["stolen"] is False    # "False"
    assert by_t[330.0]["stolen"] is False    # DragonKill "False"


def test_missing_stolen_key_is_not_a_steal():
    data = _fixture()
    for ev in data["events"]["Events"]:
        ev.pop("Stolen", None)
    out = _summary(data)
    assert all(e["stolen"] is False for e in out["objective_events"])


def test_fixture_hordekill_yields_a_grub_callout_with_steal_flag():
    out = _summary(_fixture())
    rows = event_callouts.next_callouts(
        "sr", 510.0, 7, 0, max_n=None, objective_events=out["objective_events"])
    grub = [r for r in rows if r["tag"] == "voidgrub"]
    assert len(grub) == 1
    row = grub[0]
    assert row["kind"] == "objective"
    assert row["eta_s"] <= 0
    assert row["stolen"] is True
    assert "STOLEN" in row["line"]
    assert "ally 2" in row["line"] and "enemy 1" in row["line"]
    assert row["line"].isascii()


def test_grub_callout_without_steal_and_after_its_window():
    oes = [{"name": "voidgrub", "killer_team": "ally", "down_at_s": 490.0,
            "stolen": False}]
    row = event_callouts.voidgrub_callout(oes, 500.0)
    assert row is not None and row["stolen"] is False
    assert "STOLEN" not in row["line"]
    late = 490.0 + event_callouts.GRUB_CALLOUT_WINDOW_S + 1
    assert event_callouts.voidgrub_callout(oes, late) is None


@pytest.mark.parametrize("bad", [None, "x", 5, [None, "x", {"name": "voidgrub"}],
                                 [{"name": "voidgrub", "down_at_s": float("nan")}]])
def test_grub_callout_fails_soft(bad):
    assert event_callouts.voidgrub_callout(bad, 500.0) is None


def test_grub_callout_is_sr_only():
    oes = [{"name": "voidgrub", "killer_team": "ally", "down_at_s": 490.0,
            "stolen": False}]
    rows = event_callouts.next_callouts("aram", 500.0, 7, 0, max_n=None,
                                        objective_events=oes)
    assert not [r for r in rows if r["tag"] == "voidgrub"]
