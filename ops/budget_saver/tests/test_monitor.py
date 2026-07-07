import importlib.util
import pathlib
import json
base = pathlib.Path(__file__).resolve().parents[1]
def _load(n):
    s = importlib.util.spec_from_file_location(n, base / f"{n}.py"); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def test_render_status_shape(tmp_path, monkeypatch):
    mon = _load("monitor"); state = _load("state"); dq = _load("defer_queue")
    monkeypatch.setattr(state, "STATE_PATH", tmp_path/"s.json"); state.write("main","rc-main")
    monkeypatch.setattr(dq, "QUEUE_PATH", tmp_path/"q.jsonl"); dq.append({"task":"x","tier":3})
    monkeypatch.setattr(mon, "state", state); monkeypatch.setattr(mon, "defer_queue", dq)
    s = mon.render_status()
    assert s["profile"]=="main" and s["model"]=="rc-main" and s["defer_depth"]==1 and "proxy_up" in s
