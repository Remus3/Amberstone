"""Tests for tools/gated_g419_cache_freeze.py (G4-19 PREP, s144 lane gated c63).

Every game input is hand-built (RM-906: no real game, match or player id). The
tool is a read-only sampler and grader; these tests pin its classes, verdicts and
the source facts the doc row cites.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools import gated_g419_cache_freeze as g419

ROOT = Path(__file__).resolve().parent.parent
T0 = 1_000_000.0


def _relay(age: float, now: float = T0, mode: str = "CLASSIC") -> dict:
    return {"ts": now - age, "data": {"activePlayer": {"level": 3},
                                       "gameData": {"gameTime": 321.4, "gameMode": mode}}}


def _state(keys: int) -> dict:
    return {"liveclient": {f"k{i}": i for i in range(keys)}}


def _s(cls: str, t: float) -> dict:
    return {"cls": cls, "t": t, "game_mode": "CLASSIC", "game_time_s": t - T0}


# ---- classify_sample ----------------------------------------------------------

def test_ok_when_relay_fresh_and_liveclient_present():
    s = g419.classify_sample(_relay(0.8), None, _state(29), None, T0)
    assert s["cls"] == "OK" and s["lc_keys"] == 29 and s["relay_age_s"] == 0.8
    assert s["game_mode"] == "CLASSIC" and s["game_time_s"] == 321.4


def test_empty_while_fresh_is_the_freeze_signature():
    assert g419.classify_sample(_relay(1.0), None, _state(0), None, T0)["cls"] \
        == "EMPTY_WHILE_FRESH"


def test_stale_relay_is_not_a_freeze():
    # The 5 s TTL vs relay capture lag is a different defect; never G4-19.
    s = g419.classify_sample(_relay(9.0), None, _state(0), None, T0)
    assert s["cls"] == "RELAY_STALE"


def test_margin_between_fresh_max_and_ttl_is_ambiguous():
    s = g419.classify_sample(_relay(4.0), None, _state(0), None, T0)
    assert s["cls"] == "AMBIGUOUS"


def test_untimed_or_future_relay_is_ambiguous():
    body = _relay(1.0)
    body["ts"] = None
    assert g419.classify_sample(body, None, _state(0), None, T0)["cls"] == "AMBIGUOUS"
    assert g419.classify_sample(_relay(-30.0), None, _state(0), None, T0)["cls"] \
        == "AMBIGUOUS"


def test_relay_404_is_no_game_and_other_errors_are_relay_down():
    assert g419.classify_sample(None, "HTTPError: HTTP Error 404: Not Found", None,
                                None, T0)["cls"] == "NO_GAME"
    assert g419.classify_sample(None, "URLError: refused", None, None, T0)["cls"] \
        == "RELAY_DOWN"


def test_relay_without_active_player_or_with_error_is_no_game():
    assert g419.classify_sample({"ts": T0, "data": {}}, None, _state(0), None,
                                T0)["cls"] == "NO_GAME"
    assert g419.classify_sample({"error": "x"}, None, _state(0), None, T0)["cls"] \
        == "NO_GAME"


def test_dashboard_down_with_fresh_relay():
    assert g419.classify_sample(_relay(0.5), None, None, "URLError", T0)["cls"] \
        == "DASH_DOWN"


def test_tft_standalone_fill_in_counts_as_empty():
    # dashboard/_state_builder.py swaps an EMPTY summary for this fill-in in TFT.
    state = {"liveclient": {"source": "tft_standalone", "live_api": False, "x": 1}}
    assert g419.classify_sample(_relay(1.0), None, state, None, T0)["cls"] \
        == "EMPTY_WHILE_FRESH"


def test_candidate_lists_the_three_causes_it_cannot_tell_apart():
    r = g419.grade_samples([_s("EMPTY_WHILE_FRESH", T0 + 5 * i) for i in range(3)])
    assert r["verdict"] == "FREEZE_CANDIDATE" and len(r["causes_not_excluded"]) == 3
    joined = " ".join(r["causes_not_excluded"])
    assert "liveclient_summary" in joined and "fetch" in joined and "G4-19" in joined
    ok = g419.grade_samples([_s("OK", T0 + i) for i in range(g419.MIN_OK)])
    assert ok["causes_not_excluded"] == []


def test_bool_ts_is_not_a_timestamp():
    body = _relay(1.0)
    body["ts"] = True
    assert g419.classify_sample(body, None, _state(5), None, T0)["relay_age_s"] is None


# ---- grade_samples ------------------------------------------------------------

def test_candidate_needs_streak_and_span():
    samples = [_s("OK", T0)] + [_s("EMPTY_WHILE_FRESH", T0 + 5 * i) for i in range(1, 4)]
    r = g419.grade_samples(samples)
    assert r["verdict"] == "FREEZE_CANDIDATE" and r["longest_empty_while_fresh"] == 3
    assert r["streak_span_s"] == 10.0 == g419.FROZEN_SPAN_S


def test_short_span_streak_is_not_a_candidate():
    # A healed freeze or a few 2 s fetch timeouts last well under FROZEN_SPAN_S.
    samples = [_s("EMPTY_WHILE_FRESH", T0 + 2 * i) for i in range(5)]
    assert g419.grade_samples(samples)["verdict"] == "NO_EVIDENCE"


def test_broken_streak_does_not_add_up():
    cls = ["EMPTY_WHILE_FRESH", "EMPTY_WHILE_FRESH", "OK", "EMPTY_WHILE_FRESH",
           "EMPTY_WHILE_FRESH"]
    r = g419.grade_samples([_s(c, T0 + 3 * i) for i, c in enumerate(cls)])
    assert r["longest_empty_while_fresh"] == 2 and r["verdict"] != "FREEZE_CANDIDATE"


def test_healthy_needs_min_ok():
    ok = [_s("OK", T0 + i) for i in range(g419.MIN_OK)]
    assert g419.grade_samples(ok)["verdict"] == "HEALTHY"
    assert g419.grade_samples(ok[:-1])["verdict"] == "NO_EVIDENCE"


def test_relay_stale_never_counts_toward_healthy_or_frozen():
    r = g419.grade_samples([_s("RELAY_STALE", T0 + 2 * i) for i in range(30)])
    assert r["verdict"] == "NO_EVIDENCE" and r["counts"] == {"RELAY_STALE": 30}


def test_frozen_wins_over_enough_ok():
    samples = [_s("OK", T0 + i) for i in range(20)]
    samples += [_s("EMPTY_WHILE_FRESH", T0 + 20 + 5 * i) for i in range(3)]
    assert g419.grade_samples(samples)["verdict"] == "FREEZE_CANDIDATE"


def test_grade_reports_first_and_last_game_time():
    r = g419.grade_samples([_s("OK", T0 + 1), _s("OK", T0 + 5), _s("OK", T0 + 9)])
    assert r["game_time_first_last_s"] == [1.0, 9.0]


# ---- log respawns ---------------------------------------------------------------

LOG = """\
08:00:01.100 INFO     rc.boot              [main.py:1] unrelated line
09:00:05.865 INFO     rc.liveclient_cache  [liveclient_cache.py:481] liveclient_cache started (poll=0.50s, async)
09:30:00.000 WARNING  rc.liveclient_cache  [liveclient_cache.py:403] liveclient_cache poll task ended with RuntimeError('x'); will respawn on next get()
09:30:00.500 INFO     rc.liveclient_cache  [liveclient_cache.py:481] liveclient_cache started (poll=0.50s, async)
"""
DAY = datetime(2026, 1, 2)


def test_parse_log_events_reads_starts_and_ends():
    ev = g419.parse_log_events(LOG, DAY)
    assert [k for _, k in ev] == ["started", "ended", "started"]
    assert ev[0][0] == datetime(2026, 1, 2, 9, 0, 5)


def test_respawn_after_grace_is_exercised():
    r = g419.find_respawns(g419.parse_log_events(LOG, DAY), datetime(2026, 1, 2, 9, 0, 0))
    assert r["boot_starts"] == 1 and r["respawns"] == ["09:30:00"]
    assert r["ended_warnings"] == ["09:30:00"] and r["self_heal_exercised"] is True


def test_boot_start_only_is_not_exercised():
    only_boot = LOG.splitlines()[1]
    r = g419.find_respawns(g419.parse_log_events(only_boot, DAY),
                           datetime(2026, 1, 2, 9, 0, 0))
    assert r["self_heal_exercised"] is False and r["boot_starts"] == 1


def test_thread_path_start_is_not_the_fix_path():
    thread = ("09:30:00.500 INFO     rc.liveclient_cache  [liveclient_cache.py:488] "
              "liveclient_cache started (poll=0.50s, thread)")
    assert g419.parse_log_events(thread, DAY) == []


def test_module_reload_voids_the_respawn():
    r = g419.find_respawns(g419.parse_log_events(LOG, DAY), datetime(2026, 1, 2, 9, 0, 0),
                           reloads=1)
    assert r["respawns"] == ["09:30:00"] and r["module_reloads"] == 1
    assert r["self_heal_exercised"] is False


def test_count_reloads_reads_only_new_files_naming_the_module(tmp_path):
    d = tmp_path / "results"
    d.mkdir()
    (d / "a.result.json").write_text('{"reloaded": ["core.liveclient_cache"]}',
                                     encoding="utf-8")
    (d / "b.result.json").write_text('{"reloaded": ["coaches.sr_coach"]}', encoding="utf-8")
    old = d / "c.result.json"
    old.write_text('{"reloaded": ["core.liveclient_cache"]}', encoding="utf-8")
    import os
    os.utime(old, (T0, T0))
    assert g419.count_reloads(d, T0 + 10) == 1
    assert g419.count_reloads(tmp_path / "missing", 0.0) == 0
    src = (ROOT / "ops" / "rc_dev_runtime.py").read_text(encoding="utf-8")
    assert 'self.control_results_dir  = self.runtime_dir / "control" / "results"' in src
    assert 'runtime_dir:          str   = "ops/runtime",' in src
    assert "importlib.reload(sys.modules[name])" in src


def test_lines_before_process_start_belong_to_an_earlier_process():
    r = g419.find_respawns(g419.parse_log_events(LOG, DAY), datetime(2026, 1, 2, 9, 29, 0))
    assert r["boot_starts"] == 1 and r["respawns"] == []


def test_started_at_utc_converts_to_local_naive():
    got = g419.parse_started_at("2026-01-02T15:00:00+00:00")
    want = datetime(2026, 1, 2, 15, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    assert got == want and got.tzinfo is None


@pytest.mark.parametrize("bad", [None, "", 5])
def test_started_at_refuses_junk(bad):
    with pytest.raises(ValueError):
        g419.parse_started_at(bad)


def test_log_date_from_name_and_refusal():
    assert g419._log_date(Path("2026-03-04.log")) == datetime(2026, 3, 4)
    with pytest.raises(ValueError):
        g419._log_date(Path("rc.log"))


# ---- run (no network) ---------------------------------------------------------

def test_run_sample_uses_injected_probe_and_exit_codes(capsys):
    seq = iter([_s("OK", T0 + i) for i in range(g419.MIN_OK)])
    args = argparse.Namespace(cmd="sample", samples=g419.MIN_OK, interval=0.0, json=False)
    assert g419.run(args, probe=lambda: next(seq), sleep=lambda _s: None) == 0
    assert '"HEALTHY"' in capsys.readouterr().out
    frozen = iter([_s("EMPTY_WHILE_FRESH", T0 + 5 * i) for i in range(3)])
    args = argparse.Namespace(cmd="sample", samples=3, interval=0.0, json=True)
    assert g419.run(args, probe=lambda: next(frozen), sleep=lambda _s: None) == 3


def test_run_sample_refuses_bad_counts():
    args = argparse.Namespace(cmd="sample", samples=0, interval=1.0, json=False)
    with pytest.raises(ValueError):
        g419.run(args, probe=lambda: None, sleep=lambda _s: None)


def test_run_respawns_with_explicit_log(tmp_path, capsys):
    log = tmp_path / "2026-01-02.log"
    log.write_text(LOG, encoding="utf-8")
    local = datetime(2026, 1, 2, 9, 0, 0).astimezone()
    args = argparse.Namespace(cmd="respawns", log=str(log), started_at=local.isoformat(),
                              grace=g419.GRACE_S, root=str(tmp_path))
    assert g419.run(args) == 0
    assert '"self_heal_exercised": true' in capsys.readouterr().out


# ---- source facts the doc row cites ---------------------------------------------

def test_state_liveclient_is_liveclient_summary_with_5s_gate():
    src = (ROOT / "dashboard" / "_liveclient.py").read_text(encoding="utf-8")
    assert "if snap.data is None or snap.age_s > 5:" in src
    builder = (ROOT / "dashboard" / "_state_builder.py").read_text(encoding="utf-8")
    assert '"liveclient": lc,' in builder and "lc = liveclient_summary()" in builder
    assert g419.STATE_TTL_S == 5.0


def test_summary_swallows_exceptions_and_tft_fill_in_exists():
    src = (ROOT / "dashboard" / "_liveclient.py").read_text(encoding="utf-8")
    body = src[src.index("def liveclient_summary()"):]
    assert "    except Exception:  # noqa: BLE001\n        return {}\n    return out" in body
    builder = (ROOT / "dashboard" / "_state_builder.py").read_text(encoding="utf-8")
    assert 'if mode_key == "tft":' in builder
    assert "standalone_liveclient_summary(" in builder
    tft = (ROOT / "tft" / "tft_standalone.py").read_text(encoding="utf-8")
    assert f'SOURCE_TAG = "{g419.TFT_STANDALONE}"' in tft


def test_cache_age_is_measured_from_the_relay_ts():
    src = (ROOT / "core" / "liveclient_cache.py").read_text(encoding="utf-8")
    assert "observation_age(self.ts," in src


def test_self_heal_symbols_and_log_lines_exist():
    src = (ROOT / "core" / "liveclient_cache.py").read_text(encoding="utf-8")
    assert "def _task_alive()" in src and "def _on_task_done(" in src
    # The fourth empty-liveclient cause: RC's own fetch fails and publishes data=None.
    assert src.count("Snapshot(data=None, ts=0.0, fetched_at=fetched_at") >= 4
    assert '"liveclient_cache started (poll=%.2fs, async)"' in src
    assert '"liveclient_cache poll task ended with %r; will respawn on next get()"' in src


def test_tool_source_is_ascii_and_read_only():
    text = (ROOT / "tools" / "gated_g419_cache_freeze.py").read_text(encoding="utf-8")
    assert text.isascii()
    assert not re.search(r"write_text|\.open\(|restart_trigger|urlopen\(.*data=", text)
