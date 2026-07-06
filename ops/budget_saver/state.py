import json
import os
import time
import pathlib
STATE_PATH = pathlib.Path(__file__).resolve().parent / "state.json"

def write(profile: str, model: str, extra: dict | None = None) -> None:
    data = {"profile": profile, "model": model, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "pid": os.getpid()}
    if extra: data.update(extra)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)

def read() -> dict:
    try: return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError: return {}
