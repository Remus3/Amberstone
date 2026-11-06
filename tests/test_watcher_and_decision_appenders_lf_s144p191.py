"""RM-481 residual (s144, RM-1702): the watcher verdict log and the decision log append LF.

Three modules appended jsonl rows with a text-mode ``open(..., "a",
encoding="utf-8")`` and no ``newline=``, so on Windows every row carried CRLF:

- tools/lcu_push_watcher.py ``_emit`` appended ops/runtime/lcu_push_verdict.jsonl
  and, in the same ``try``, wrote lcu_push_verdict.md with ``newline="\\n"``;
- tools/live_flip_watcher.py ``_emit`` did the same pair (the .md written LF, the
  .jsonl appended CRLF) for live_verdict.jsonl;
- core/decision_detector.py ``DecisionStore`` appended the decisions log twice
  (``record_coach_choice`` and ``record_choice``).

One sibling pair per watcher already said LF; the jsonl half now agrees. CI is
Linux, where the text layer does not translate, so the behaviour tests run
under a harness that forces CRLF on any text-mode write that passes no
``newline=``; positive controls prove the harness bites before a writer is
trusted. The AST scan is the OS-independent half.
"""
from __future__ import annotations

import builtins
import io
import json

import pytest

from tests._repo_walk import REPO_ROOT
from tests.test_shadow_appenders_lf_s144p190 import _append_offenders

_MODULES = (
    "tools/lcu_push_watcher.py",
    "tools/live_flip_watcher.py",
    "core/decision_detector.py",
)


@pytest.mark.parametrize("rel", _MODULES)
def test_no_bare_text_mode_append(rel):
    path = REPO_ROOT / rel
    assert path.is_file(), f"{rel} missing - the scan would be vacuous"
    found = _append_offenders(path.read_bytes().decode("utf-8"))
    assert found == [], (
        f'{rel}: text-mode append without newline="\\n" writes CRLF rows on '
        f"Windows (lines {found})")


@pytest.fixture
def crlf_text_layer(monkeypatch):
    """Reproduce the Windows LF -> CRLF text translation on every OS."""
    orig_open = builtins.open

    def _open(file, mode="r", *args, **kwargs):
        if ("b" not in mode and any(c in mode for c in "wax+")
                and len(args) < 3 and kwargs.get("newline") is None):
            kwargs["newline"] = "\r\n"
        return orig_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _open)
    monkeypatch.setattr(io, "open", _open)


def test_positive_control_path_open_append_produces_crlf(tmp_path,
                                                         crlf_text_layer):
    target = tmp_path / "control.jsonl"
    with target.open("a", encoding="utf-8") as fh:
        fh.write("a\nb\n")
    assert target.read_bytes() == b"a\r\nb\r\n", "harness failed to force CRLF"


def test_lcu_push_watcher_emit_appends_lf(tmp_path, monkeypatch,
                                          crlf_text_layer):
    from core import operator_notify
    from tools import lcu_push_watcher as w
    monkeypatch.setattr(operator_notify, "notify",
                        lambda *a, **k: (True, "stub"))
    monkeypatch.setattr(w, "_VERDICT_MD", tmp_path / "v.md")
    monkeypatch.setattr(w, "_VERDICT_JSONL", tmp_path / "v.jsonl")
    for port in (1111, 2222):
        w._emit({"verdict": "PASS", "champion": "Ahri", "mode": "sr",
                 "port_before": port, "port_after": port + 1})
    raw = (tmp_path / "v.jsonl").read_bytes()
    assert b"\r" not in raw
    assert [json.loads(r)["port_before"]
            for r in raw.decode("utf-8").split("\n") if r] == [1111, 2222]
    assert b"\r" not in (tmp_path / "v.md").read_bytes()


def test_live_flip_watcher_emit_appends_lf(tmp_path, monkeypatch,
                                           crlf_text_layer):
    from core import operator_notify
    from tools import live_flip_watcher as w
    monkeypatch.setattr(operator_notify, "notify",
                        lambda *a, **k: (True, "stub"))
    monkeypatch.setattr(w, "_VERDICT_MD", tmp_path / "v.md")
    monkeypatch.setattr(w, "_VERDICT_JSONL", tmp_path / "v.jsonl")
    verdict = {"flip_ready": [], "check": [], "n_moved": 0}
    for champ in ("Ahri", "Zed"):
        w._emit(champ, "sr", "ad", verdict, ["Lux"])
    raw = (tmp_path / "v.jsonl").read_bytes()
    assert b"\r" not in raw
    assert [json.loads(r)["champ"]
            for r in raw.decode("utf-8").split("\n") if r] == ["Ahri", "Zed"]
    assert b"\r" not in (tmp_path / "v.md").read_bytes()


def test_decision_store_coach_choice_appends_lf(tmp_path, crlf_text_layer):
    from core.decision_detector import DecisionStore
    log = tmp_path / "decisions_log.jsonl"
    store = DecisionStore(pending_path=tmp_path / "pending.json", log_path=log)
    for key in ("a", "b"):
        entry = store.record_coach_choice(
            choice_key=key, choice_label=key.upper(), confidence="high",
            source_tag="synthetic")
        assert entry is not None
    raw = log.read_bytes()
    assert b"\r" not in raw
    assert [json.loads(r)["choice_key"]
            for r in raw.decode("utf-8").split("\n") if r] == ["a", "b"]
