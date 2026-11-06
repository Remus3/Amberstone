"""tools/gated_rm869_vision_fields.py - the RM-869 read-back (s144 lane gated cycle 10).

Read-only plumbing for the next ARAM Mayhem / Nexus Blitz game; nothing here
ticks a row. Source pins first (the seeds are the coaches' blank artifacts, the
readers go direct, URF fields have no consumer; FIX_COMMITTED_UTC is the git
committer time of bfa4bbfbe, read by hand - a git-history test would break in a
shallow clone), then the predicates and the CLI. All data is synthetic.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from tools import gated_rm869_vision_fields as g

ROOT = Path(__file__).resolve().parent.parent
CUT = datetime(2026, 10, 27, 13, 0, 0, tzinfo=timezone.utc)
AFTER = datetime(2026, 10, 27, 13, 30, 0, tzinfo=timezone.utc).timestamp()
BEFORE = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc).timestamp()


def _class_func(path: str, cls: str, func: str) -> ast.FunctionDef:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == func:
                    return item
    raise AssertionError(f"{cls}.{func} not found in {path}")


def _blank(path: str, cls: str) -> dict:
    fn = _class_func(path, cls, "_blank_artifact_data")
    ret = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
    assert len(ret) == 1
    return ast.literal_eval(ret[0].value)


def _class_attr(path: str, cls: str, name: str):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for item in node.body:
                if isinstance(item, ast.Assign) and any(
                        getattr(t, "id", "") == name for t in item.targets):
                    return ast.literal_eval(item.value)
                # RM-1719: the shared tables carry a ClassVar annotation.
                if (isinstance(item, ast.AnnAssign) and item.value is not None
                        and getattr(item.target, "id", "") == name):
                    return ast.literal_eval(item.value)
    raise AssertionError(f"{cls}.{name} not found in {path}")


def _coach(tmp_path: Path, mode: str, data: dict, mtime: float) -> Path:
    rel = g.MODES[mode][0]
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")
    os.utime(p, (mtime, mtime))
    return p


def _health(tmp_path: Path, started: str = "2026-10-27T13:00:00+00:00") -> None:
    p = tmp_path / "ops" / "runtime" / "health.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"started_at": started}), encoding="utf-8")


# -- source pins ---------------------------------------------------------------

def test_aram_seeds_are_the_blank_artifact():
    blank = _blank("coaches/aram_coach.py", "Coach")
    _rel, mode_value, seeds = g.MODES["aram"]
    assert blank["mode"] == mode_value
    assert {f: blank.get(f) for f in seeds} == seeds


def test_nb_seeds_are_the_blank_artifact():
    blank = _blank("coaches/brawl_coach.py", "Coach")
    _rel, mode_value, seeds = g.MODES["nb"]
    assert blank["mode"] == mode_value
    assert {f: blank.get(f) for f in seeds} == seeds


def _subscript_keys(fn: ast.FunctionDef, name: str) -> set[str]:
    """Constant keys of ``<name>[<key>] = ...`` assignments inside ``fn``."""
    keys = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if (isinstance(t, ast.Subscript) and getattr(t.value, "id", "") == name
                        and isinstance(t.slice, ast.Constant)):
                    keys.add(t.slice.value)
    return keys


def test_run_vision_writes_exactly_the_tracked_fields():
    # ARAM writes its four fields through a (key, value) loop into cur[k].
    fn = _class_func("coaches/aram_coach.py", "Coach", "_run_vision")
    loop = next(n for n in ast.walk(fn) if isinstance(n, ast.For)
                and isinstance(n.iter, ast.List) and getattr(n.target, "elts", None))
    keys = {ast.literal_eval(e.elts[0]) for e in loop.iter.elts}
    assert keys == set(g.MODES["aram"][2])
    fn = _class_func("coaches/brawl_coach.py", "Coach", "_run_vision")
    assert _subscript_keys(fn, "current") == set(g.MODES["nb"][2])


def test_both_readers_go_direct():
    assert _class_attr("coaches/brawl_coach.py", "BrawlVisionReader", "USE_RELAY") is False
    src = ast.unparse(_class_func("coaches/aram_coach.py", "Coach", "_build_vision_reader"))
    assert "USE_RELAY = False" in src


def test_urf_fields_have_no_consumer_outside_the_reader():
    src = (ROOT / "coaches/brawl_coach.py").read_text(encoding="utf-8")
    urf = _class_attr("coaches/brawl_coach.py", "BrawlVisionReader", "_URF_TIERED_FIELDS")
    reader = next(n for n in ast.parse(src).body
                  if isinstance(n, ast.ClassDef) and n.name == "BrawlVisionReader")
    lines = src.splitlines()
    outside = lines[:reader.lineno - 1] + lines[reader.end_lineno:]
    for f in urf:
        if f != "timer":
            assert not any(f in ln for ln in outside), f
    assert "urf" in g.UNOBSERVABLE


def test_fix_time_pins_the_hand_read_committer_time():
    # A pin, not a derivation: the value was read by hand from bfa4bbfbe.
    assert datetime(2026, 10, 25, 7, 1, 1, tzinfo=timezone.utc) == g.FIX_COMMITTED_UTC


# -- predicates ----------------------------------------------------------------

def _snap(mode_value: str, fields: dict, ts: float) -> dict:
    return {"present": True, "mode": mode_value,
            "mtime_utc": datetime.fromtimestamp(ts, timezone.utc).isoformat(), "fields": fields}


def test_restart_before_fix_fails():
    early = datetime(2026, 10, 24, 0, 0, 0, tzinfo=timezone.utc)
    rep = g.report("aram", [], early, "--since")
    assert rep["verdict"] == "FAIL"


def test_no_fresh_sample_is_no_game():
    seeds = g.MODES["aram"][2]
    old = _snap("aram", {**seeds, "wave_pct": 30}, BEFORE)
    other = _snap("sr", {**seeds, "wave_pct": 30}, AFTER)
    rep = g.report("aram", [old, other], CUT, "--since")
    assert rep["verdict"] == "NO_GAME"
    assert rep["checks"]["fields"]["fresh"] == 0


def test_seed_only_is_not_a_pass():
    seeds = g.MODES["aram"][2]
    rep = g.report("aram", [_snap("aram", dict(seeds), AFTER)] * 3, CUT, "--since")
    assert rep["verdict"] == "SEED_ONLY"


def test_non_seed_value_passes_and_is_listed_once():
    seeds = g.MODES["aram"][2]
    s1 = _snap("aram", {**seeds, "wave_pct": 62}, AFTER)
    s2 = _snap("aram", {**seeds, "wave_pct": 62, "hp_packs": [False, True]}, AFTER)
    rep = g.report("aram", [s1, s2], CUT, "--since")
    assert rep["verdict"] == "PASS"
    assert rep["checks"]["fields"]["non_seed"] == {"wave_pct": [62], "hp_packs": [[False, True]]}


def test_null_and_empty_reads_are_not_hits():
    seeds = g.MODES["nb"][2]
    s = _snap("brawl", {**seeds, "event_location": "", "my_nexus_hp": None}, AFTER)
    assert g.report("nb", [s], CUT, "--since")["verdict"] == "SEED_ONLY"
    s = _snap("brawl", {**seeds, "event_name": "EventA", "event_location": "top"}, AFTER)
    assert g.report("nb", [s], CUT, "--since")["verdict"] == "PASS"


def test_urf_is_never_passed():
    rep = g.report("urf", [], CUT, "--since")
    assert rep["verdict"] == "UNOBSERVABLE"


def test_no_cutoff_is_incomplete(tmp_path, capsys):
    seeds = g.MODES["aram"][2]
    _coach(tmp_path, "aram", {"mode": "aram", **seeds, "wave_pct": 70}, AFTER)
    assert g.main(["--mode", "aram", "--data-root", str(tmp_path), "--json"]) == 1
    rep = json.loads(capsys.readouterr().out)
    assert rep["verdict"] == "INCOMPLETE"
    assert rep["checks"]["fields"]["fresh"] == 0


# -- CLI -----------------------------------------------------------------------

def test_cli_reads_without_writing(tmp_path, capsys):
    seeds = g.MODES["aram"][2]
    p = _coach(tmp_path, "aram", {"mode": "aram", "game_id": "SYNTH-0001",
                                  **seeds, "my_tower_hp": 40}, AFTER)
    _health(tmp_path)

    def digest() -> dict:
        return {str(q): hashlib.sha256(q.read_bytes()).hexdigest()
                for q in sorted(tmp_path.rglob("*")) if q.is_file()}

    before = digest()
    rc = g.main(["--mode", "aram", "--data-root", str(tmp_path), "--interval", "0"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PASS" in out and "my_tower_hp" in out
    assert "SYNTH-0001" not in out and str(tmp_path) not in out
    assert digest() == before
    assert p.stat().st_mtime == AFTER


def test_cli_json_and_exit_codes(tmp_path, capsys):
    seeds = g.MODES["nb"][2]
    _coach(tmp_path, "nb", {"mode": "brawl", **seeds}, AFTER)
    _health(tmp_path)
    rc = g.main(["--mode", "nb", "--data-root", str(tmp_path), "--json"])
    rep = json.loads(capsys.readouterr().out)
    assert rc == 1 and rep["verdict"] == "SEED_ONLY"
    _health(tmp_path, "2026-10-20T00:00:00+00:00")
    assert g.main(["--mode", "nb", "--data-root", str(tmp_path)]) == 2
    capsys.readouterr()
    assert g.main(["--mode", "aram", "--data-root", str(tmp_path)]) == 2
