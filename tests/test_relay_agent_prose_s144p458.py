"""The relay prose names the service-host service, not a task (S144-P-458).

The 2026-10-31 launcher cutover unregistered RC-LiveClientRelay
(docs/OPERATIONS.md, "Moved to the app") and the rc-shell service host runs
``tools/liveclient_relay.py`` itself (ops/launcher/services.json, service
``liveclient_relay``). Four passages still called the relay by its old task
name, "the RC-LiveClientRelay agent", so a reader looked for a Task Scheduler
entry:

- game_reader/poller.py: the module docstring and the RELAY_URL comment;
- vision_server/_relay.py: the module docstring and handle_upload_liveclient.

Each now names ``tools/liveclient_relay.py`` and the service host.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FILES = ("game_reader/poller.py", "vision_server/_relay.py")
OLD_NAME = re.compile(r"RC-LiveClientRelay")
NEW_NAME = re.compile(r"tools/liveclient_relay\.py")
HOST = re.compile(r"service[\s#]+host")


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_no_file_still_calls_the_relay_by_its_task_name():
    bad = []
    for rel in FILES:
        text = _text(rel)
        for hit in OLD_NAME.finditer(text):
            no = text.count("\n", 0, hit.start()) + 1
            bad.append(f"{rel}:{no}")
    assert not bad, "old task name still used: " + ", ".join(bad)


def test_each_file_names_the_relay_module_and_the_service_host():
    for rel in FILES:
        text = _text(rel)
        assert NEW_NAME.search(text), f"{rel} does not name tools/liveclient_relay.py"
        assert HOST.search(text), f"{rel} does not name the service host"


def test_the_patterns_match_the_old_prose_and_not_the_new():
    """Positive control for the patterns."""
    assert OLD_NAME.search("so the RC-LiveClientRelay agent is an")
    assert OLD_NAME.search("# Relay endpoint: the RC-LiveClientRelay agent pushes")
    new = "the relay (tools/liveclient_relay.py, run by the service\n# host) is an"
    assert not OLD_NAME.search(new)
    assert NEW_NAME.search(new)
    assert HOST.search(new)


def test_premise_the_service_host_runs_the_relay():
    manifest = json.loads(
        (REPO / "ops/launcher/services.json").read_text(encoding="utf-8"))
    services = manifest["services"] if isinstance(manifest, dict) else manifest
    entry = {s["name"]: s for s in services}["liveclient_relay"]
    assert entry["argv"] == ["tools/liveclient_relay.py"]
    ops = _text("docs/OPERATIONS.md")
    assert "UNREGISTERED `RC-Supervisor`, `RC-LCUAgent`, `RC-LiveClientRelay`" in ops
