import json
import pathlib
import time
QUEUE_PATH = pathlib.Path(__file__).resolve().parent / "defer_queue.jsonl"

def append(item: dict) -> None:
    item = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **item}
    with QUEUE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item) + "\n")

def load() -> list[dict]:
    if not QUEUE_PATH.exists(): return []
    return [json.loads(l) for l in QUEUE_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]

def drain() -> list[dict]:
    items = load()
    QUEUE_PATH.write_text("", encoding="utf-8")
    return items
