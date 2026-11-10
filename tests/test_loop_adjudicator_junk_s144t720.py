# arch: ops/loop/adjudicator.py never raises on junk config, state or kit output | section=tests | frozen=no
"""S144-T-720: the adjudicator's `ask() -> str | None` contract holds on junk.

`loop_controller.main()` calls `director()` and `auditor()` with no try around
them, so anything `ask()` raises ends the whole loop run. Before this pass a
hot-edited config typo (`"timeout_sec": "300s"`), a price row missing a key, a
restored spend state of the wrong shape, a kit usage line that is not a
mapping, a deeply nested stdout or a locked audit-copy file each raised out of
`ask()` - several of them AFTER the call had already been answered, so the
answer was lost with the run.

The spawn is replaced at `ops.loop.fleet_route.spawn` (the attribute the
adjudicator resolves per call), so no test here can start a real child.
"""
from __future__ import annotations

import importlib.util
import math
import subprocess
from pathlib import Path

import pytest

from ops.loop import fleet_route

_ADJ = Path(__file__).resolve().parent.parent / "ops" / "loop" / "adjudicator.py"


@pytest.fixture(scope="module")
def adj():
    spec = importlib.util.spec_from_file_location("adjudicator_uut_s144t720", _ADJ)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Spawn:
    """A recording stand-in for fleet_route.spawn."""

    def __init__(self, stdout="ANSWER", line=None, exc=None, stderr=""):
        self.stdout = stdout
        self.line = {} if line is None else line
        self.exc = exc
        self.stderr = stderr
        self.calls = []

    def __call__(self, prompt, **kw):
        self.calls.append((prompt, kw))
        if self.exc is not None:
            raise self.exc
        proc = subprocess.CompletedProcess(["claude"], 0, self.stdout, self.stderr)
        return self.line, proc


@pytest.fixture
def spawn(monkeypatch):
    fake = _Spawn()
    monkeypatch.setattr(fleet_route, "spawn", fake)
    return fake


# --- F1: the claude_adjudicator block and its timeout --------------------


@pytest.mark.parametrize("raw", ["abc", "300s", float("inf"), float("nan"),
                                 True, -5, 0, [300], {"s": 1}, 1e300, "9" * 30, 86401,
                                 "9" * 5000, 10 ** 400])
def test_a_junk_timeout_falls_back_to_the_default(adj, spawn, tmp_path, raw):
    lines = []
    a = adj.ClaudeAdjudicator({"claude_adjudicator": {"timeout_sec": raw}},
                              tmp_path, log=lines.append)
    assert a.ask("b", "i") == "ANSWER"
    assert spawn.calls[-1][1]["timeout"] == adj.DEFAULT_CLAUDE_TIMEOUT_SEC
    assert any("timeout_sec" in ln for ln in lines), "a junk value must be logged"


def test_an_int_too_long_to_repr_falls_back_and_is_logged(adj, spawn, tmp_path):
    """repr() refuses an int past 4300 digits; the log line must not raise.
    Not a parametrize case: pytest cannot build an id for it either."""
    lines = []
    a = adj.ClaudeAdjudicator({"claude_adjudicator": {"timeout_sec": 10 ** 5000}},
                              tmp_path, log=lines.append)
    assert a.ask("b", "i") == "ANSWER"
    assert spawn.calls[-1][1]["timeout"] == adj.DEFAULT_CLAUDE_TIMEOUT_SEC
    assert any("timeout_sec <int>" in ln for ln in lines)


@pytest.mark.parametrize("raw,want", [(120, 120), ("90", 90), (45.0, 45), (" 60 ", 60)])
def test_a_usable_timeout_is_still_honoured(adj, spawn, tmp_path, raw, want):
    a = adj.ClaudeAdjudicator({"claude_adjudicator": {"timeout_sec": raw}}, tmp_path)
    assert a.ask("b", "i") == "ANSWER"
    assert spawn.calls[-1][1]["timeout"] == want


def test_an_absent_timeout_is_the_default_and_is_not_logged(adj, spawn, tmp_path):
    lines = []
    a = adj.ClaudeAdjudicator({}, tmp_path, log=lines.append)
    assert a.ask("b", "i") == "ANSWER"
    assert spawn.calls[-1][1]["timeout"] == adj.DEFAULT_CLAUDE_TIMEOUT_SEC
    assert not any("timeout_sec" in ln for ln in lines)


@pytest.mark.parametrize("blk", ["x", 5, ["model"], True])
def test_a_non_mapping_adjudicator_block_is_ignored(adj, spawn, tmp_path, blk):
    a = adj.ClaudeAdjudicator({"claude_adjudicator": blk}, tmp_path)
    assert a.ask("b", "i") == "ANSWER"
    assert spawn.calls[-1][1]["timeout"] == adj.DEFAULT_CLAUDE_TIMEOUT_SEC


# --- F2: the price table never loses an answer or poisons spend ----------


@pytest.mark.parametrize("table", [
    [1, 2],
    "cheap",
    {"default": {"input": 1}},
    {"default": {"input": "x", "output": 1}},
    {"default": "row"},
    {"default": {"input": True, "output": 1}},
    {"default": {"input": float("nan"), "output": 1}},
    {"default": {"input": float("inf"), "output": 1}},
    {"default": {"input": -3, "output": 1}},
])
def test_a_junk_price_table_keeps_the_answer_and_a_finite_spend(adj, spawn, tmp_path, table):
    a = adj.ClaudeAdjudicator({"price_per_mtok": table}, tmp_path)
    assert a.ask("b" * 400, "i") == "ANSWER"
    assert math.isfinite(a.usd) and a.usd >= 0.0


def test_an_overflowing_finite_price_never_makes_spend_inf(adj, spawn, tmp_path):
    """1e308 is finite and passes the row gate, but the product overflows."""
    cfg = {"price_per_mtok": {"default": {"input": 1e308, "output": 1e308}}}
    state = {"usd": {"claude": 3.0}}
    sup = adj.Adjudicator(cfg, tmp_path, state=state)
    assert sup.ask("b" * 400, "i") == "ANSWER"
    sup.save_state(state)
    assert state["usd"]["claude"] == pytest.approx(3.0)
    assert sup.total_usd() == pytest.approx(3.0)


def test_the_backend_alone_never_records_an_overflowed_spend(adj, spawn, tmp_path):
    cfg = {"price_per_mtok": {"default": {"input": 1e308, "output": 1e308}}}
    lines = []
    a = adj.ClaudeAdjudicator(cfg, tmp_path, log=lines.append)
    a.usd = 2.0
    assert a.ask("b" * 400, "i") == "ANSWER"
    assert a.usd == pytest.approx(2.0)
    assert any("not finite" in ln for ln in lines)


def test_the_wrapper_never_stores_a_non_finite_backend_spend(adj, monkeypatch, tmp_path):
    class _Backend:
        name = "claude"
        usd = 0.0
        last_stderr = ""

        def ask(self, _body, _inst):
            self.usd = float("inf")
            return "ANSWER"

    monkeypatch.setattr(adj, "resolve", lambda *_a, **_k: _Backend())
    sup = adj.Adjudicator({}, tmp_path, state={"usd": {"claude": 3.0}})
    assert sup.ask("b", "i") == "ANSWER"
    assert sup.usd == {"claude": 3.0}


def test_a_junk_model_row_falls_back_to_the_default_row(adj):
    table = {"sonnet": {"input": "x"}, "default": {"input": 1.0, "output": 2.0}}
    assert adj.model_price(table, "claude-sonnet-5-5") == {"input": 1.0, "output": 2.0}


def test_a_valid_model_row_is_still_chosen(adj):
    table = {"sonnet": {"input": 2.0, "output": 10.0, "cache_read": 0.2},
             "default": {"input": 1.0, "output": 2.0}}
    row = adj.model_price(table, "claude-sonnet-5-5")
    assert row["input"] == 2.0 and row["output"] == 10.0


def test_a_non_string_model_name_prices_by_the_default_row(adj):
    table = {"default": {"input": 1.0, "output": 2.0}}
    assert adj.model_price(table, 5) == {"input": 1.0, "output": 2.0}


# --- F3: a junk kit usage line never discards the answer -----------------


@pytest.mark.parametrize("line", [None, "usage", ["model"], {"model": 5}, {"model": ""}])
def test_a_junk_usage_line_keeps_the_answer(adj, monkeypatch, tmp_path, line):
    fake = _Spawn(line=line)
    if line is None:
        fake.line = None
    monkeypatch.setattr(fleet_route, "spawn", fake)
    a = adj.ClaudeAdjudicator({}, tmp_path)
    assert a.ask("b", "i") == "ANSWER"
    assert math.isfinite(a.usd)


# --- F4: restored spend state of the wrong shape --------------------------


@pytest.mark.parametrize("state", [
    {"usd": "abc"},
    {"usd": [1, 2]},
    {"usd": {"claude": "x"}},
    {"usd": {"claude": float("nan")}},
    {"usd": {"claude": float("inf")}},
    {"usd": {"claude": -4.0}},
    {"usd": {"claude": True}},
    {"usd": {5: 1.0}},
    [1],
    "state",
])
def test_junk_restored_state_never_raises_and_never_poisons_spend(adj, spawn, tmp_path, state):
    sup = adj.Adjudicator({}, tmp_path, state=state)
    assert math.isfinite(sup.total_usd()) and sup.total_usd() >= 0.0
    assert sup.ask("b", "i") == "ANSWER"
    assert math.isfinite(sup.total_usd()) and sup.total_usd() >= 0.0


def test_restored_entries_that_sum_past_float_range_never_make_spend_inf(adj, spawn, tmp_path):
    """Each 1.5e308 is finite on its own; together they add up to inf."""
    state = {"usd": {"claude": 1.5e308, "stale": 1.5e308, "kept": 2.0}}
    sup = adj.Adjudicator({}, tmp_path, state=state)
    assert sup.total_usd() == pytest.approx(2.0)
    assert sup.ask("b", "i") == "ANSWER"
    sup.save_state(state)
    total = sum(state["usd"].values())
    assert math.isfinite(total) and total == pytest.approx(sup.total_usd())


def test_a_junk_backend_usd_attribute_never_raises(adj, spawn, tmp_path):
    a = adj.ClaudeAdjudicator({}, tmp_path)
    a.usd = None
    assert a.ask("b", "i") == "ANSWER"
    assert math.isfinite(a.usd) and a.usd > 0.0


@pytest.mark.parametrize("junk", [float("nan"), float("inf"), -5.0, "x"])
def test_a_junk_backend_usd_is_replaced_even_when_the_spend_is_dropped(adj, spawn, tmp_path, junk):
    cfg = {"price_per_mtok": {"default": {"input": 1e308, "output": 1e308}}}
    a = adj.ClaudeAdjudicator(cfg, tmp_path)
    a.usd = junk
    assert a.ask("b" * 400, "i") == "ANSWER"
    assert a.usd == 0.0


def test_valid_restored_spend_is_kept(adj, spawn, tmp_path):
    sup = adj.Adjudicator({}, tmp_path, state={"usd": {"claude": 4.25, "old": 1}})
    assert sup.total_usd() == pytest.approx(5.25)
    sup.ask("b", "i")
    assert sup.usd["claude"] > 4.25


@pytest.mark.parametrize("junk", [None, [1, 2], "x"])
def test_a_junk_usd_attribute_set_after_load_never_raises_in_ask(adj, spawn, tmp_path, junk):
    sup = adj.Adjudicator({}, tmp_path)
    sup.usd = junk
    assert sup.ask("b", "i") == "ANSWER"
    assert sup.total_usd() > 0.0 and math.isfinite(sup.total_usd())


def test_total_usd_skips_a_junk_value_written_after_load(adj, tmp_path):
    sup = adj.Adjudicator({}, tmp_path)
    sup.usd = {"claude": 2.0, "bad": "x", "nan": float("nan")}
    assert sup.total_usd() == pytest.approx(2.0)


# --- F5: a stdout the JSON decoder cannot recurse through -----------------


def test_a_deeply_nested_stdout_never_raises(adj, monkeypatch, tmp_path):
    monkeypatch.setattr(fleet_route, "spawn", _Spawn(stdout="[" * 100000))
    out = adj.ClaudeAdjudicator({}, tmp_path).ask("b", "i")
    assert out is None or isinstance(out, str)


def test_answer_of_handles_recursion_like_any_non_object(adj):
    text = "[" * 100000
    assert adj._answer_of(text) == (text, "")


# --- F6: a raised spawn error says WHY in last_stderr ----------------------


def test_a_raised_spawn_error_is_reported_in_last_stderr(adj, monkeypatch, tmp_path):
    monkeypatch.setattr(fleet_route, "spawn", _Spawn(exc=RuntimeError("pipe broke")))
    a = adj.ClaudeAdjudicator({}, tmp_path)
    assert a.ask("b", "i") is None
    assert "RuntimeError" in a.last_stderr and "pipe broke" in a.last_stderr


def test_a_long_spawn_error_is_capped_in_last_stderr(adj, monkeypatch, tmp_path):
    monkeypatch.setattr(fleet_route, "spawn", _Spawn(exc=RuntimeError("e" * 5000)))
    a = adj.ClaudeAdjudicator({}, tmp_path)
    assert a.ask("b", "i") is None
    assert 0 < len(a.last_stderr) <= 400


class _BadStr(Exception):
    def __str__(self):
        raise RuntimeError("broken __str__")


@pytest.mark.parametrize("exc", [_BadStr(), ValueError(10 ** 5000)],
                         ids=["broken-str", "huge-int-arg"])
def test_a_spawn_error_whose_text_cannot_render_never_raises(adj, monkeypatch, tmp_path, exc):
    monkeypatch.setattr(fleet_route, "spawn", _Spawn(exc=exc))
    lines = []
    a = adj.ClaudeAdjudicator({}, tmp_path, log=lines.append)
    assert a.ask("b", "i") is None
    assert type(exc).__name__ in a.last_stderr
    assert lines, "the failure must still be logged"


@pytest.mark.parametrize("stdout,stderr", [(b"ANSWER", ""), (5, 7), ("", b"err 503")],
                         ids=["bytes-out", "int-both", "bytes-err"])
def test_non_text_child_output_never_raises(adj, monkeypatch, tmp_path, stdout, stderr):
    monkeypatch.setattr(fleet_route, "spawn", _Spawn(stdout=stdout, stderr=stderr))
    assert adj.ClaudeAdjudicator({}, tmp_path).ask("b", "i") is None


def test_the_wrapper_carries_a_spawn_error_reason(adj, monkeypatch, tmp_path):
    monkeypatch.setattr(fleet_route, "spawn", _Spawn(exc=OSError("no exe")))
    sup = adj.Adjudicator({}, tmp_path)
    assert sup.ask("b", "i") is None
    assert "no exe" in sup.last_stderr


# --- F7: a failed audit-copy write never costs the call -------------------


def test_a_locked_audit_copy_still_asks_and_logs(adj, spawn, tmp_path):
    def locked(_p, _t):
        raise PermissionError("[WinError 5] held by a reader")

    lines = []
    a = adj.ClaudeAdjudicator({}, tmp_path, log=lines.append, awrite=locked)
    assert a.ask("body", "i") == "ANSWER"
    assert spawn.calls and spawn.calls[-1][1]["stdin"] == "body"
    assert any("audit copy" in ln and "WinError 5" in ln for ln in lines)


class _BadStrOSError(OSError):
    def __str__(self):
        raise RuntimeError("broken __str__")


@pytest.mark.parametrize("exc", [_BadStrOSError(), OSError(2, "nf", 10 ** 5000)],
                         ids=["broken-str", "huge-filename"])
def test_an_audit_copy_error_whose_text_cannot_render_still_asks(adj, spawn, tmp_path, exc):
    def failing(_p, _t):
        raise exc

    lines = []
    a = adj.ClaudeAdjudicator({}, tmp_path, log=lines.append, awrite=failing)
    assert a.ask("body", "i") == "ANSWER"
    assert any("audit copy" in ln for ln in lines)


def test_an_over_long_control_dir_still_asks(adj, spawn, tmp_path):
    """Past the Windows path limit mkdir raises ValueError, not OSError; on
    other platforms the same path raises OSError. Either way: logged, asked."""
    raw = str(tmp_path / ("d" * 40000))
    lines = []
    a = adj.ClaudeAdjudicator({"control_dir": raw}, log=lines.append)
    assert a.ask("body", "i") == "ANSWER"
    assert any("audit copy" in ln for ln in lines)


def test_a_body_that_will_not_encode_still_asks(adj, spawn, tmp_path):
    lines = []
    a = adj.ClaudeAdjudicator({}, tmp_path, log=lines.append)
    assert a.ask("body \ud800", "i") == "ANSWER"
    assert any("audit copy" in ln and "UnicodeEncodeError" in ln for ln in lines)


def test_a_non_os_error_from_the_writer_still_raises(adj, spawn, tmp_path):
    """Only the expected I/O failure is absorbed; a programming error in an
    injected writer must surface, not be swallowed."""
    def broken(_p, _t):
        raise TypeError("writer bug")

    a = adj.ClaudeAdjudicator({}, tmp_path, awrite=broken)
    with pytest.raises(TypeError):
        a.ask("body", "i")


# --- F9: resolve() on a junk adjudicator name ------------------------------


def test_a_huge_int_adjudicator_name_resolves_to_claude_and_is_logged(adj):
    lines = []
    b = adj.resolve({"adjudicator": 10 ** 5000}, log=lines.append)
    assert b.name == "claude"
    assert any("<int>" in ln for ln in lines)


def test_a_null_adjudicator_name_is_unset_not_a_vendor(adj):
    lines = []
    assert adj.resolve({"adjudicator": None}, log=lines.append).name == "claude"
    assert lines == []


# --- F8: a non-path control_dir --------------------------------------------


@pytest.mark.parametrize("raw", [5, ["x"], True, {"p": 1}, "/srv/a\x00b"])
def test_a_non_path_control_dir_is_the_default(adj, raw):
    want = _ADJ.resolve().parent / "control"
    assert adj._control_dir({"control_dir": raw}, None) == want
    assert adj.ClaudeAdjudicator({"control_dir": raw}).ctl == want


def test_an_absolute_control_dir_with_a_nul_is_the_default(adj, spawn, tmp_path):
    """Absolute, so only the NUL check stands between it and every path call
    raising ValueError (not OSError) out of ask()."""
    raw = str(tmp_path) + "\x00x"
    want = _ADJ.resolve().parent / "control"
    assert adj._control_dir({"control_dir": raw}, None) == want


def test_an_absolute_path_like_control_dir_is_still_honoured(adj, tmp_path):
    assert adj._control_dir({"control_dir": tmp_path}, None) == tmp_path
    assert adj._control_dir({"control_dir": str(tmp_path)}, None) == tmp_path
