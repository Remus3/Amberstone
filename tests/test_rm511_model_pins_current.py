"""RM-511: Claude model pins in the loop / supervisor / charter tree are current.

The pins named by the row (plus their same-file siblings) had drifted to
retired ids (claude-sonnet-4-6, claude-opus-4-7, claude-opus-5), to an undated
alias the cost tracker cannot price (agent 7 `claude-haiku-4-5`), and, for the
loop adjudicator, to `opus` while the fleet kit actually runs that call on
sonnet (writes_code=False) and no longer reads the block's `cmd` key.

Scope is deliberately the orchestration tree. Live coaching / vision model
choices (coaches/, modes/shared_vision.py) and the responder agreement model
(tools/inbox_responder_runner.py, bound into the armed agreement id) are OUT of
scope and are not enumerated here.

Every enumeration asserts it found its sites, so an empty walk cannot pass.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The ONE place the current id set lives for this guard.
CURRENT_MODEL_IDS = frozenset({
    "claude-fable-5-1",
    "claude-opus-5-5",
    "claude-sonnet-5-5",
    "claude-haiku-4-5-20251001",
})

_ID_RE = re.compile(r"claude-[a-z]+-[0-9][a-z0-9-]*")


def _module_literal(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


def _agent_model_values(agents: dict) -> dict:
    out = {}
    for key, row in agents.items():
        for field in ("model", "model_default", "model_deep"):
            if field in row:
                out[f"{key}.{field}"] = row[field]
    return out


def test_loop_configs_adjudicator_and_executor_pins_are_current():
    adj_seen = 0
    exe_seen = 0
    for cfg_path in sorted((REPO_ROOT / "ops" / "loop").glob("config*.json")):
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        blk = cfg.get("claude_adjudicator")
        if blk is not None:
            adj_seen += 1
            assert blk.get("model") in CURRENT_MODEL_IDS, (
                f"{cfg_path.name} claude_adjudicator.model={blk.get('model')!r}")
            # FLEET-KIT-v1: the kit resolves the binary; a `cmd` key is dead
            # config that reads as if it were honoured.
            assert "cmd" not in blk, f"{cfg_path.name} carries the unread cmd key"
        if "executor_model" in cfg:
            exe_seen += 1
            assert cfg["executor_model"] in CURRENT_MODEL_IDS, (
                f"{cfg_path.name} executor_model={cfg['executor_model']!r}")
    assert adj_seen >= 3, f"expected >= 3 adjudicator blocks, found {adj_seen}"
    assert exe_seen >= 3, f"expected >= 3 executor_model pins, found {exe_seen}"


def test_adjudicator_default_model_is_current():
    val = _module_literal(REPO_ROOT / "ops" / "loop" / "adjudicator.py",
                          "DEFAULT_CLAUDE_MODEL")
    assert val in CURRENT_MODEL_IDS, val


def test_supervisor_agent_models_are_current():
    models = _module_literal(REPO_ROOT / "agents" / "_supervisor_common.py",
                             "AGENT_MODELS")
    assert set(models) >= {"2", "3", "4", "5", "6", "7"}, sorted(models)
    stale = {k: v for k, v in models.items() if v not in CURRENT_MODEL_IDS}
    assert not stale, f"stale AGENT_MODELS pins: {stale}"


def test_resolved_decisions_and_phase3_seed_agent_models_are_current():
    runtime = json.loads((REPO_ROOT / "agents" / "state" / "resolved_decisions.json")
                         .read_text(encoding="utf-8"))
    seed = _module_literal(REPO_ROOT / "ops" / "phase3_setup.py", "RESOLVED_DECISIONS")
    for label, doc in (("resolved_decisions.json", runtime), ("phase3_setup", seed)):
        vals = _agent_model_values(doc["agents"])
        assert len(vals) >= 7, f"{label}: only {len(vals)} model fields found"
        stale = {k: v for k, v in vals.items() if v not in CURRENT_MODEL_IDS}
        assert not stale, f"{label} stale agent model pins: {stale}"
    assert _agent_model_values(runtime["agents"]) == _agent_model_values(seed["agents"]), \
        "runtime resolved_decisions agents models drifted from the phase3 seed"


def test_agent_models_match_resolved_decisions():
    models = _module_literal(REPO_ROOT / "agents" / "_supervisor_common.py",
                             "AGENT_MODELS")
    runtime = json.loads((REPO_ROOT / "agents" / "state" / "resolved_decisions.json")
                         .read_text(encoding="utf-8"))
    for key, model in models.items():
        row = runtime["agents"][key]
        assert model == row.get("model", row.get("model_default")), (key, model, row)


def test_agent_charter_model_lines_are_current():
    charters = sorted((REPO_ROOT / "agents").glob("agent*/charter.md"))
    with_ids = 0
    for path in charters:
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:8])
        ids = _ID_RE.findall(head)
        if not ids:
            continue
        with_ids += 1
        stale = [i for i in ids if i not in CURRENT_MODEL_IDS]
        assert not stale, f"{path.relative_to(REPO_ROOT)} stale ids: {stale}"
    assert with_ids >= 6, f"expected >= 6 charters with a model line, found {with_ids}"


def test_powershell_runner_model_defaults_are_current():
    sites = {
        REPO_ROOT / "ops" / "loop" / "run_lane.ps1": r'^\$model = "([^"]+)"',
        REPO_ROOT / "tools" / "weekly_hygiene_run.ps1": r'\[string\]\$Model = "([^"]+)"',
    }
    for path, pat in sites.items():
        m = re.search(pat, path.read_text(encoding="utf-8"), re.MULTILINE)
        assert m, f"model default not found in {path.name}"
        assert m.group(1) in CURRENT_MODEL_IDS, f"{path.name}: {m.group(1)!r}"


def test_adjudicator_swap_doc_does_not_claim_cmd_is_invoked():
    text = (REPO_ROOT / "docs" / "ADJUDICATOR_SWAP.md").read_text(encoding="utf-8")
    rows = [ln for ln in text.splitlines() if ln.startswith("| `claude_adjudicator.cmd`")]
    assert rows, "cmd row missing from the config-key table"
    assert "not read" in rows[0], rows[0]
    model_rows = [ln for ln in text.splitlines()
                  if ln.startswith("| `claude_adjudicator.model`")]
    assert model_rows and "pric" in model_rows[0], model_rows
