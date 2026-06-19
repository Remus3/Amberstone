"""Regression: RuneWriter re-applies on EVERY champ-select, not just the first.

Pins the contract broken by reference_runewriter_dies_after_game1 (the LCU rune
auto-push went silent after game 1). The "champ select ended" branch must clear
_last_applied so the SAME champion picked again in a later champ-select re-fires
the rune write - while a continuous single champ-select still dedups."""
from __future__ import annotations

import threading

from lcu.lcu_rune_writer import RuneWriter


class _FakeLcu:
    """get_champ_select() returns one scripted value per poll, then None."""

    def __init__(self, script):
        self._script = list(script)

    def get_champ_select(self):
        return self._script.pop(0) if self._script else None


def _make_writer(script):
    w = RuneWriter.__new__(RuneWriter)  # skip __init__ (no build_champ_id_map / LCU)
    w._lcu = _FakeLcu(script)
    w._stop_event = threading.Event()
    w._last_applied_champion = ""
    w._last_applied_mode = ""
    w._in_champ_select = False
    w._applied: list = []
    # Stub every LCU-touching helper so _poll exercises only the state machine.
    w._detect_game_mode = lambda: "ARAM"
    w._sync_spells = lambda session, mode: True
    w._detect_my_champion = lambda session: (session or {}).get("champ", "")

    def _apply(champion, mode):
        w._applied.append((champion, mode))
        return True

    w._apply_runes = _apply
    return w


def test_rearms_after_champ_select_ends():
    sivir = {"champ": "Sivir"}
    # poll order: idle, pick Sivir, same Sivir (dedup), end (re-arm), Sivir again.
    w = _make_writer([None, sivir, sivir, None, sivir])

    w._poll()                       # idle
    assert w._applied == []
    w._poll()                       # Sivir -> apply
    assert w._applied == [("Sivir", "ARAM")]
    w._poll()                       # Sivir again, same session -> dedup
    assert w._applied == [("Sivir", "ARAM")]
    w._poll()                       # champ select ended -> re-arm
    assert w._last_applied_champion == ""
    assert w._in_champ_select is False
    w._poll()                       # Sivir in a NEW champ select -> applies AGAIN
    assert w._applied == [("Sivir", "ARAM"), ("Sivir", "ARAM")]


def test_dedup_within_one_continuous_champ_select():
    olaf = {"champ": "Olaf"}
    w = _make_writer([olaf, olaf, olaf])
    for _ in range(3):
        w._poll()
    # No "ended" transition between polls -> a single apply, the rest dedup.
    assert w._applied == [("Olaf", "ARAM")]


def test_champion_swap_within_session_reapplies():
    # ARAM trade: Yuumi -> Olaf inside one champ-select must re-apply (the
    # observed game-1 behaviour that DID work).
    w = _make_writer([{"champ": "Yuumi"}, {"champ": "Olaf"}])
    w._poll()
    w._poll()
    assert w._applied == [("Yuumi", "ARAM"), ("Olaf", "ARAM")]


def test_no_champion_does_not_apply():
    # Session present but still picking (no champ yet) -> no write, no crash.
    # Truthy sessions (non-empty) so we stay in the champ-select branch.
    w = _make_writer([{"champ": "", "phase": "PLANNING"},
                      {"champ": "", "phase": "PLANNING"}])
    w._poll()
    w._poll()
    assert w._applied == []
    assert w._in_champ_select is True
