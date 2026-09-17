"""RM-462 (1): how tools/rc_facts.py renders a null LCU phase.

RM-382 moved both LCU snapshot producers off the truthy sentinels: where
tools/lcu_agent.capture_state used to emit ``"Offline"`` (no lockfile) and
lcu/snapshot_shape used to emit ``"Unknown"`` (one failed phase read), both
now emit ``phase: None``. rc_facts read ``lcu.get("phase") or "?"``, so the
SessionStart facts block lost the distinction and printed ``phase=?`` for
both states - the same glyph it prints for a snapshot with no phase key at
all.

DECIDED rendering. The client-closed / phase-read-failed split uses the same
shape derivation as web/legacy_index.html renderLcuPanel (every producer
stamps ``config``; ``lcu_port`` is stamped only while connected). Keeping
``?`` for a missing phase key is rc_facts' OWN choice, not taken from the
legacy page:

  * a real phase string            -> printed verbatim (``phase=Lobby``)
  * null phase, no ``lcu_port``    -> ``phase=-(client-closed)``
  * null phase, ``lcu_port`` set   -> ``phase=-(phase-read-failed)``
  * no ``phase`` key at all        -> ``phase=?`` (malformed snapshot)

``-`` is the repo's no-data sentinel. The label must NOT start with ``None``:
the REAL LCU phase string ``"None"`` (logged in, idle) prints ``phase=None``,
so a ``None(...)`` label would make a search for ``phase=None`` match two
opposite states. The parenthesis is the derivation, so a reader never
mistakes it for a retired sentinel.

The main() case drives the real report path with every probe stubbed, so this
pins the printed line, not only the helper.

All authored content here is 7-bit ASCII.
"""

from __future__ import annotations

import io
import time

import tools.rc_facts as rc_facts


def test_real_phase_verbatim():
    assert rc_facts._lcu_phase_label({"config": {}, "lcu_port": "1", "phase": "Lobby"}) == "Lobby"


def test_null_phase_without_port_is_client_closed():
    assert rc_facts._lcu_phase_label({"config": {}, "phase": None}) == "-(client-closed)"


def test_null_phase_with_port_is_phase_read_failed():
    lcu = {"config": {}, "lcu_port": "51234", "phase": None}
    assert rc_facts._lcu_phase_label(lcu) == "-(phase-read-failed)"


# The LCU gameflow phase strings (lol-gameflow/v1/gameflow-phase). "None" is a
# REAL phase - logged in and idle - and is the one a null label once collided
# with.
_REAL_PHASES = (
    "None", "Lobby", "Matchmaking", "CheckedIntoTournament", "ReadyCheck",
    "ChampSelect", "GameStart", "FailedToLaunch", "InProgress", "Reconnect",
    "WaitingForStats", "PreEndOfGame", "EndOfGame", "TerminatedInError",
)


def test_real_None_phase_and_null_phase_render_differently_and_unprefixed():
    real = "phase=" + rc_facts._lcu_phase_label({"config": {}, "lcu_port": "1", "phase": "None"})
    assert real == "phase=None"
    for lcu in ({"config": {}, "phase": None}, {"config": {}, "lcu_port": "1", "phase": None}):
        null = "phase=" + rc_facts._lcu_phase_label(lcu)
        assert null != real
        assert not null.startswith(real), (null, real)
        assert not real.startswith(null), (null, real)


def test_no_null_label_is_prefixed_by_or_prefixes_any_real_phase():
    nulls = [rc_facts._lcu_phase_label({"phase": None}),
             rc_facts._lcu_phase_label({"phase": None, "lcu_port": "1"})]
    for null in nulls:
        for phase in _REAL_PHASES:
            real = rc_facts._lcu_phase_label({"phase": phase, "lcu_port": "1"})
            assert real == phase
            assert not null.startswith(real) and not real.startswith(null), (null, real)


def test_missing_phase_key_stays_question_mark():
    assert rc_facts._lcu_phase_label({"config": {}}) == "?"


def test_labels_are_ascii_and_never_a_retired_sentinel():
    cases = [{"phase": None}, {"phase": None, "lcu_port": "1"}, {}]
    for lcu in cases:
        label = rc_facts._lcu_phase_label(lcu)
        assert label.isascii()
        assert label not in ("Offline", "Unknown")


def test_main_prints_derived_label(monkeypatch, tmp_path):
    health = tmp_path / "health.json"
    health.write_text('{"pid": 1, "alive": true, "last_reload_ok": true}', encoding="utf-8")
    monkeypatch.setattr(rc_facts, "_HEALTH", health)
    monkeypatch.setattr(rc_facts, "_port_listening", lambda *a, **k: True)
    monkeypatch.setattr(rc_facts, "_health_all", lambda: {})
    monkeypatch.setattr(rc_facts, "_legion_tasks", lambda: [])
    monkeypatch.setattr(rc_facts, "_last_boot_iso", lambda: None)
    monkeypatch.setattr(rc_facts, "_inbox_section", lambda *a, **k: ([], [], set()))
    state = {"lcu": {"config": {}, "phase": None, "ts": time.time()}}
    monkeypatch.setattr(rc_facts, "_http_get_json", lambda *a, **k: state)
    buf = io.StringIO()
    monkeypatch.setattr(rc_facts.sys, "stdout", buf)
    assert rc_facts.main(session=None) == 0
    lines = [ln for ln in buf.getvalue().splitlines() if ln.startswith("- LCU agent:")]
    assert len(lines) == 1, buf.getvalue()
    assert "phase=-(client-closed)" in lines[0]
    assert "phase=None" not in lines[0]
