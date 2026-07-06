import importlib.util
import pathlib
spec = importlib.util.spec_from_file_location("dq", pathlib.Path(__file__).resolve().parents[1] / "defer_queue.py")
dq = importlib.util.module_from_spec(spec); spec.loader.exec_module(dq)

def test_append_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr(dq, "QUEUE_PATH", tmp_path / "q.jsonl")
    dq.append({"task": "rewrite DS scorer", "tier": 3})
    dq.append({"task": "arch refactor", "tier": 3})
    items = dq.load()
    assert len(items) == 2 and items[0]["task"] == "rewrite DS scorer"
def test_drain_empties(tmp_path, monkeypatch):
    monkeypatch.setattr(dq, "QUEUE_PATH", tmp_path / "q.jsonl")
    dq.append({"task": "x", "tier": 3})
    drained = dq.drain()
    assert len(drained) == 1 and dq.load() == []
