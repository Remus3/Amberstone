# arch: offline tests for the daily upstream content-drift detector | section=tools-tests | frozen=no
"""Offline unit tests for ``tools/upstream_drift_check.py``.

NO network, NO real disk sentinel. The 3 probe functions are monkeypatched
with canned values and ``SENTINEL_PATH`` is redirected inside ``tmp_path``.
Side effects (bridge note / refresh) are monkeypatched with recording fakes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import upstream_drift_check as M  # noqa: E402


# --------------------------------------------------------------------------- helpers
@pytest.fixture(autouse=True)
def _isolate_sentinel(tmp_path, monkeypatch):
    """Point the sentinel at a tmp file so no test ever touches ops/runtime."""
    monkeypatch.setattr(M, "SENTINEL_PATH", tmp_path / "upstream_drift.json")
    return tmp_path / "upstream_drift.json"


def _patch_probes(monkeypatch, ddragon=None, meraki=None, cdragon=None):
    """Monkeypatch the 3 probes to return (signal, error) tuples directly."""
    monkeypatch.setattr(M, "probe_ddragon_version", lambda: ddragon)
    monkeypatch.setattr(M, "probe_meraki_content_patch", lambda: meraki)
    monkeypatch.setattr(M, "probe_cdragon_content_version", lambda: cdragon)


# --------------------------------------------------------------------------- _patch_sort_key
class TestPatchSortKey:
    def test_numeric_not_lexical(self):
        # 25.15 must outrank 25.9 (numeric, not string) and 25.10.
        assert M._patch_sort_key("25.15") > M._patch_sort_key("25.9")
        assert M._patch_sort_key("25.15") > M._patch_sort_key("25.10")
        assert M._patch_sort_key("25.10") > M._patch_sort_key("25.9")

    def test_garbage_sorts_last(self):
        assert M._patch_sort_key("not.a.patch") == (-1, -1)
        assert M._patch_sort_key(None) == (-1, -1)
        assert M._patch_sort_key(12345) == (-1, -1)


# --------------------------------------------------------------------------- _meraki_content_patch
class TestMerakiContentPatch:
    def test_newest_selected_numeric(self):
        raw = {
            "Aatrox": {"patchLastChanged": "25.9"},
            "Ahri": {"patchLastChanged": "25.15"},
            "Akali": {"patchLastChanged": "25.10"},
        }
        assert M._meraki_content_patch(raw) == "25.15"

    def test_skips_non_dict_and_missing_field(self):
        raw = {
            "Aatrox": {"patchLastChanged": "25.9"},
            "_meta": ["not", "a", "dict"],
            "Ahri": {"noField": True},
            "Akali": {"patchLastChanged": "25.12"},
        }
        assert M._meraki_content_patch(raw) == "25.12"

    def test_empty_returns_none(self):
        assert M._meraki_content_patch({}) is None
        assert M._meraki_content_patch({"x": {"noField": 1}}) is None


# --------------------------------------------------------------------------- per-field drift
class TestComputeFields:
    def test_changed_only_when_both_present_and_differ(self):
        prev = {"ddragon_version": "16.11.1",
                "meraki_content_patch": "25.15",
                "cdragon_content_version": "buildA"}
        cur = {"ddragon_version": "16.12.1",   # changed
               "meraki_content_patch": "25.15",  # same -> not changed
               "cdragon_content_version": "buildA"}
        errs = {"ddragon_version": None,
                "meraki_content_patch": None,
                "cdragon_content_version": None}
        fields = M.compute_fields(prev, cur, errs)
        by = {f.name: f for f in fields}
        assert by["ddragon_version"].changed is True
        assert by["meraki_content_patch"].changed is False
        assert by["cdragon_content_version"].changed is False

    def test_first_run_null_previous_is_not_drift(self):
        prev = {"ddragon_version": None,
                "meraki_content_patch": None,
                "cdragon_content_version": None}
        cur = {"ddragon_version": "16.11.1",
               "meraki_content_patch": "25.15",
               "cdragon_content_version": "buildA"}
        errs = {k: None for k in cur}
        fields = M.compute_fields(prev, cur, errs)
        assert all(f.changed is False for f in fields)
        assert M.any_drift(fields) is False

    def test_errored_current_carries_previous_and_not_changed(self):
        prev = {"ddragon_version": "16.11.1",
                "meraki_content_patch": "25.15",
                "cdragon_content_version": "buildA"}
        cur = {"ddragon_version": None,  # probe failed this run
               "meraki_content_patch": "25.15",
               "cdragon_content_version": "buildA"}
        errs = {"ddragon_version": "boom",
                "meraki_content_patch": None,
                "cdragon_content_version": None}
        fields = M.compute_fields(prev, cur, errs)
        by = {f.name: f for f in fields}
        assert by["ddragon_version"].changed is False
        assert by["ddragon_version"].error == "boom"
        # carry-forward: advancing keeps the old value (see advance test).


# --------------------------------------------------------------------------- any_drift
class TestAnyDrift:
    def test_true_when_one_changed(self):
        prev = {"ddragon_version": "16.11.1", "meraki_content_patch": "25.15",
                "cdragon_content_version": "A"}
        cur = {"ddragon_version": "16.11.1", "meraki_content_patch": "25.16",
               "cdragon_content_version": "A"}
        errs = {k: None for k in cur}
        assert M.any_drift(M.compute_fields(prev, cur, errs)) is True

    def test_false_when_none_changed(self):
        prev = {"ddragon_version": "16.11.1", "meraki_content_patch": "25.15",
                "cdragon_content_version": "A"}
        cur = dict(prev)
        errs = {k: None for k in cur}
        assert M.any_drift(M.compute_fields(prev, cur, errs)) is False


# --------------------------------------------------------------------------- sentinel round-trip
class TestSentinelRoundTrip:
    def test_missing_file_is_all_null_baseline(self, _isolate_sentinel):
        prev = M.load_sentinel()
        assert prev["ddragon_version"] is None
        assert prev["meraki_content_patch"] is None
        assert prev["cdragon_content_version"] is None

    def test_write_then_read_advances_values(self, _isolate_sentinel):
        prev = M.load_sentinel()
        cur = {"ddragon_version": "16.11.1", "meraki_content_patch": "25.15",
               "cdragon_content_version": "buildA"}
        errs = {k: None for k in cur}
        fields = M.compute_fields(prev, cur, errs)
        M.advance_sentinel(prev, cur, fields, drift=M.any_drift(fields))
        back = M.load_sentinel()
        assert back["ddragon_version"] == "16.11.1"
        assert back["meraki_content_patch"] == "25.15"
        assert back["cdragon_content_version"] == "buildA"
        assert back["updated_at"]  # timestamp set
        # First-ever seeding is NOT drift -> last_drift_at stays null.
        assert back["last_drift_at"] is None

    def test_last_drift_at_set_only_on_drift(self, _isolate_sentinel):
        # seed
        M.advance_sentinel(
            {"ddragon_version": None, "meraki_content_patch": None,
             "cdragon_content_version": None},
            {"ddragon_version": "16.11.1", "meraki_content_patch": "25.15",
             "cdragon_content_version": "A"},
            [], drift=False)
        seeded = M.load_sentinel()
        assert seeded["last_drift_at"] is None
        # now a real drift advance
        prev = M.load_sentinel()
        cur = {"ddragon_version": "16.12.1", "meraki_content_patch": "25.15",
               "cdragon_content_version": "A"}
        errs = {k: None for k in cur}
        fields = M.compute_fields(prev, cur, errs)
        M.advance_sentinel(prev, cur, fields, drift=True)
        drifted = M.load_sentinel()
        assert drifted["last_drift_at"] is not None

    def test_none_field_keeps_previous_on_advance(self, _isolate_sentinel):
        prev = {"ddragon_version": "16.11.1", "meraki_content_patch": "25.15",
                "cdragon_content_version": "A", "updated_at": "x",
                "last_drift_at": None}
        cur = {"ddragon_version": None,  # probe failed
               "meraki_content_patch": "25.16",
               "cdragon_content_version": "A"}
        errs = {"ddragon_version": "err", "meraki_content_patch": None,
                "cdragon_content_version": None}
        fields = M.compute_fields(prev, cur, errs)
        M.advance_sentinel(prev, cur, fields, drift=M.any_drift(fields))
        back = M.load_sentinel()
        # None field carried previous forward; present field advanced.
        assert back["ddragon_version"] == "16.11.1"
        assert back["meraki_content_patch"] == "25.16"


# --------------------------------------------------------------------------- CLI: --check-only
class TestCheckOnly:
    def test_exit_1_on_drift_and_no_sentinel_write(self, monkeypatch, _isolate_sentinel):
        # seed the sentinel first (default run writes it)
        _patch_probes(monkeypatch, ddragon="16.11.1", meraki="25.15", cdragon="A")
        assert M.main([]) == 0
        assert _isolate_sentinel.exists()
        before = _isolate_sentinel.read_text(encoding="utf-8")
        # now ddragon drifts; --check-only must report 1 and NOT write
        _patch_probes(monkeypatch, ddragon="16.12.1", meraki="25.15", cdragon="A")
        assert M.main(["--check-only"]) == 1
        after = _isolate_sentinel.read_text(encoding="utf-8")
        assert before == after  # sentinel untouched by --check-only

    def test_exit_0_when_no_drift(self, monkeypatch, _isolate_sentinel):
        _patch_probes(monkeypatch, ddragon="16.11.1", meraki="25.15", cdragon="A")
        assert M.main([]) == 0
        assert M.main(["--check-only"]) == 0


# --------------------------------------------------------------------------- CLI: default mode
class TestDefaultMode:
    def test_default_writes_and_advances_sentinel_returns_0(self, monkeypatch, _isolate_sentinel):
        _patch_probes(monkeypatch, ddragon="16.11.1", meraki="25.15", cdragon="A")
        assert M.main([]) == 0
        assert _isolate_sentinel.exists()
        data = json.loads(_isolate_sentinel.read_text(encoding="utf-8"))
        assert data["ddragon_version"] == "16.11.1"
        assert data["meraki_content_patch"] == "25.15"
        assert data["cdragon_content_version"] == "A"

    def test_json_dump_written(self, monkeypatch, _isolate_sentinel, tmp_path):
        _patch_probes(monkeypatch, ddragon="16.11.1", meraki="25.15", cdragon="A")
        out = tmp_path / "report.json"
        assert M.main(["--json", str(out)]) == 0
        report = json.loads(out.read_text(encoding="utf-8"))
        assert "current" in report and "previous" in report
        assert "fields" in report and "any_drift" in report
        assert report["current"]["ddragon_version"] == "16.11.1"

    def test_patch_pin_overrides_ddragon_probe(self, monkeypatch, _isolate_sentinel):
        # If --patch is honored, the ddragon probe value is ignored.
        called = {"n": 0}

        def _boom():
            called["n"] += 1
            return "SHOULD_NOT_BE_USED"

        monkeypatch.setattr(M, "probe_ddragon_version", _boom)
        monkeypatch.setattr(M, "probe_meraki_content_patch", lambda: "25.15")
        monkeypatch.setattr(M, "probe_cdragon_content_version", lambda: "A")
        assert M.main(["--patch", "16.99.9"]) == 0
        data = json.loads(_isolate_sentinel.read_text(encoding="utf-8"))
        assert data["ddragon_version"] == "16.99.9"
        assert called["n"] == 0  # probe skipped entirely


# --------------------------------------------------------------------------- side effects
class TestSideEffects:
    def test_bridge_note_fires_once_on_drift(self, monkeypatch, _isolate_sentinel):
        calls = []
        monkeypatch.setattr(M, "send_bridge_note",
                            lambda fields: calls.append(fields) or (True, "ok"))
        # seed
        _patch_probes(monkeypatch, ddragon="16.11.1", meraki="25.15", cdragon="A")
        M.main(["--bridge-note"])
        assert calls == []  # baseline seeding is not drift
        # drift now
        _patch_probes(monkeypatch, ddragon="16.12.1", meraki="25.15", cdragon="A")
        assert M.main(["--bridge-note"]) == 0
        assert len(calls) == 1

    def test_bridge_note_not_fired_without_drift(self, monkeypatch, _isolate_sentinel):
        calls = []
        monkeypatch.setattr(M, "send_bridge_note",
                            lambda fields: calls.append(fields) or (True, "ok"))
        _patch_probes(monkeypatch, ddragon="16.11.1", meraki="25.15", cdragon="A")
        M.main(["--bridge-note"])  # seed, no drift
        M.main(["--bridge-note"])  # identical, no drift
        assert calls == []

    def test_auto_refresh_fires_once_on_drift(self, monkeypatch, _isolate_sentinel):
        calls = []
        monkeypatch.setattr(M, "trigger_refresh",
                            lambda: calls.append(1) or (True, "ok"))
        _patch_probes(monkeypatch, ddragon="16.11.1", meraki="25.15", cdragon="A")
        M.main(["--auto-refresh"])  # seed
        assert calls == []
        _patch_probes(monkeypatch, ddragon="16.11.1", meraki="25.16", cdragon="A")
        assert M.main(["--auto-refresh"]) == 0
        assert len(calls) == 1

    def test_side_effect_raise_does_not_crash_main(self, monkeypatch, _isolate_sentinel):
        def _raise(*a, **k):
            raise RuntimeError("bridge exploded")

        monkeypatch.setattr(M, "send_bridge_note", _raise)
        monkeypatch.setattr(M, "trigger_refresh", _raise)
        # seed then drift
        _patch_probes(monkeypatch, ddragon="16.11.1", meraki="25.15", cdragon="A")
        M.main(["--bridge-note", "--auto-refresh"])
        _patch_probes(monkeypatch, ddragon="16.12.1", meraki="25.15", cdragon="A")
        # main must still return 0 despite both side effects raising.
        assert M.main(["--bridge-note", "--auto-refresh"]) == 0


# --------------------------------------------------------------------------- ASCII guard
def test_source_is_ascii():
    src = (_TOOLS / "upstream_drift_check.py").read_text(encoding="utf-8")
    src.encode("ascii")  # raises if any non-ASCII byte slipped in
