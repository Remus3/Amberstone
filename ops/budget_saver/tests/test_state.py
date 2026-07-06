import json
import pathlib
import importlib.util
spec = importlib.util.spec_from_file_location("state", pathlib.Path(__file__).resolve().parents[1] / "state.py")
state = importlib.util.module_from_spec(spec); spec.loader.exec_module(state)

def test_state_roundtrip_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "STATE_PATH", tmp_path / "state.json")
    state.write(profile="main", model="rc-main")
    got = json.loads((tmp_path / "state.json").read_text())
    assert got["profile"] == "main" and got["model"] == "rc-main" and "started_at" in got
    assert not list(tmp_path.glob("*.tmp"))  # tmp cleaned by atomic replace
