"""One-shot setup helper for Phase 3 folder tree + state files.

Run from: C:\\Riot Commander\\
Creates:
  - agents/ tree (see S4)
  - lib/ tree
  - web/ tree
  - data/db/, data/meta_build/scraped/{site_b,site_d}, data/meta_build/curated/, data/coach_cache/
  - logs/agents/, logs/scrapers/, logs/ws/
  - agents/state/task_queue.jsonl (empty)
  - agents/state/lockfile (empty)
  - agents/state/resolved_decisions.json (atomic write)

Idempotent - safe to re-run. Existing files are left untouched. The
resolved_decisions.json register is rewritten to refresh the static blocks
(topology/agents/panels/...) but PRESERVES any accreted `decisions` array +
its version/locked_at stamps - a re-run never wipes locked decisions.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(r"C:\Riot Commander")

FOLDERS = [
    # agents tree
    "agents/state",
    "agents/agent0_gatekeeper",
    "agents/agent1_lead",
    "agents/agent2_backend/pipeline",
    "agents/agent3_testing/suite",
    "agents/agent4_coach_mentor/proposals",
    "agents/agent5_ui",
    "agents/agent6_auditor/safeguards",
    "agents/agent7_context",
    # lib tree
    "lib/ddragon",
    "lib/scrapers",
    "lib/http",
    "lib/icons",
    # web tree
    "web/assets",
    "web/js",
    "web/css",
    # data subtrees (existing data/ stays untouched)
    "data/db",
    "data/meta_build/ddragon",
    "data/meta_build/scraped/site_b",
    "data/meta_build/scraped/site_d",
    "data/meta_build/curated",
    "data/coach_cache",
    # logs
    "logs/agents",
    "logs/scrapers",
    "logs/ws",
]

RESOLVED_DECISIONS = {
    "version": "phase3-1.1",
    "locked_at": "2026-04-22",
    # The locked-decision register is the runtime source of truth (charter
    # L18) and ACCRETES via audit backfills into the runtime file, so it is
    # NOT authored here - merge_resolved_decisions() preserves an existing
    # register and only seeds this empty list on a fresh `to restore` scaffold.
    "decisions": [],
    "topology": {
        "legion_pc": "192.168.8.230",
        "game_pc": "192.168.8.237",
        "moon_pc": "decommissioned",
        "install_root": "C:\\Riot Commander\\",
    },
    "agents": {
        "0": {"role": "gatekeeper", "substrate": "python"},
        "1": {"role": "lead", "substrate": "python"},
        "2": {"role": "backend", "substrate": "ephemeral_llm", "model": "claude-sonnet-4-6"},
        "3": {"role": "testing", "substrate": "python_plus_ephemeral_llm", "model": "claude-sonnet-4-6"},
        "4": {
            "role": "coach_mentor",
            "substrate": "ephemeral_llm",
            "model_default": "claude-sonnet-4-6",
            "model_deep": "claude-opus-4-7",
        },
        "5": {"role": "ui", "substrate": "ephemeral_llm", "model": "claude-sonnet-4-6"},
        "6": {"role": "auditor", "substrate": "ephemeral_llm", "model": "claude-opus-4-7"},
        "7": {"role": "user_context", "substrate": "warm_llm_during_play", "model": "claude-haiku-4-5"},
    },
    "panels": {
        "roster": [
            "minimap_or_arena_map",
            "right_now",
            "next",
            "next_milestone",
            "item_build",
            "team_directive",
            "augments",
        ],
        "mode_visibility": {
            "sr_draft": [1, 2, 3, 4, 5, 6],
            "sr_ranked": [1, 2, 3, 4, 5, 6],
            "aram": [1, 2, 3, 4, 5, 6, 7],
            "arena": ["1A", 2, 3, 4, 5, 7],
            "brawl": [1, 2, 3, 4, 5, 6, 7],
        },
    },
    "latency_tiers": {
        "right_now": "1-2s",
        "next": "~8s",
        "next_milestone": "30-60s",
        "item_build": "event_driven",
        "team_directive": "~8s",
        "augments": "event_driven",
        "minimap": "matches_right_now",
    },
    "transport": "websocket_end_to_end",
    "sources": ["live_client", "lcu", "ddragon", "site_b", "site_d"],
    "scraper_discipline": {
        "user_agent": "Amberstone/3.0",
        "rate_limit": "<=1 req/sec per hostname",
        "respect_robots_txt": True,
        "circuit_breaker_owner": "agent6",
        "cease_and_desist_fallback": "curated_jsons",
    },
    "fallback": "last_known_greyed_plus_staleness_indicator",
    "learn_adapt": {
        "axis": "per_champion_x_per_mode_plus_matchup_modifier_at_5_games",
        "save_intervals": "event_triggered_plus_post_match_summary",
        "ingestion_trigger": "queued_idle_after_2min_idle",
        "manual_feedback": False,
        "autonomy": {
            "autonomous_data_json": True,
            "propose_and_queue_code_and_prompts": True,
        },
        "data_quality_signal_path": "agent4_files_task_to_agent6",
    },
    "db": {
        "strategy": "separate_db_per_mode",
        "files": ["sr_draft.db", "sr_ranked.db", "aram.db", "arena.db", "brawl.db"],
        "seed_source": "data/rewind_history.db",
        "seed_size": "1.62 GB",
        "seed_games": 2800,
    },
    "bypass_mode": {
        "flag": "--dangerously-skip-permissions",
        "hard_gates": [1, 7, 8],
        "soft_gate_agent0": [5],
        "ungated": [2, 3, 4, 6],
        "outbound_net_control": "blocklist_via_lib_http",
        "cross_machine_mechanism": "smb_share_cmdkey_persistent",
    },
    "cross_machine": {
        "share_unc": "\\\\192.168.8.237\\RCClient",
        "writable_zones": [
            "\\\\192.168.8.237\\RCClient\\forwarder\\",
            "\\\\192.168.8.237\\RCClient\\web\\",
        ],
        "credential_store": "cmdkey_on_legion_under_target_192.168.8.237",
        "auth_user": "Administrator",
        "forwarder_restart_signal": "\\\\192.168.8.237\\RCClient\\forwarder\\restart_trigger.txt",
    },
    "agent0_rejection": {
        "reasons_1_2_3_6": "dead_letter_immediately",
        "reasons_4_5": "auto_retry_once_then_dead_letter",
    },
    "parallelism": {
        "model": "event_loop_async_supervisor",
        "deterministic_agents": [0, 1, 3],
        "ephemeral_llm_agents": [2, 4, 5, 6],
        "warm_llm_agents": [7],
        "warm_window": "from_ui_open_or_game_start_until_30min_idle_or_ui_close",
    },
    "post_setup_first_task": "agent6_full_audit_pass",
}


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def merge_resolved_decisions(existing: dict | None) -> dict:
    """Build the resolved_decisions.json payload without wiping locked decisions.

    The static register blocks (topology/agents/panels/...) are refreshed from
    RESOLVED_DECISIONS, but the locked-decision register itself - the
    `decisions` array plus its `version`/`locked_at` stamps - is the runtime
    source of truth (charter L18) and ACCRETES via audit backfills. A re-run
    MUST preserve an existing register rather than overwrite it (idempotency
    bug fixed 2026-06-28; the prior unconditional rewrite dropped every
    accreted decision). When no file exists yet (fresh `to restore` scaffold)
    we seed an empty register from the generator defaults.
    """
    payload = dict(RESOLVED_DECISIONS)
    if existing:
        payload["decisions"] = existing.get("decisions", [])
        payload["version"] = existing.get("version", RESOLVED_DECISIONS["version"])
        payload["locked_at"] = existing.get(
            "locked_at", RESOLVED_DECISIONS["locked_at"]
        )
    else:
        payload.setdefault("decisions", [])
    return payload


def main() -> int:
    created = []
    skipped = []
    for rel in FOLDERS:
        p = ROOT / rel
        if p.exists():
            skipped.append(rel)
        else:
            p.mkdir(parents=True, exist_ok=True)
            created.append(rel)

    # Empty state files - touch without truncation if already present.
    state = ROOT / "agents" / "state"
    for name in ("task_queue.jsonl", "lockfile"):
        f = state / name
        if not f.exists():
            f.write_text("", encoding="utf-8")
            created.append(f"agents/state/{name}")
        else:
            skipped.append(f"agents/state/{name}")

    # Rewrite resolved_decisions.json, PRESERVING the accreted locked-decision
    # register if the file already exists (idempotent - never wipe decisions).
    decisions_path = state / "resolved_decisions.json"
    existing = None
    if decisions_path.exists():
        try:
            existing = json.loads(decisions_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = None
    atomic_write_json(decisions_path, merge_resolved_decisions(existing))
    created.append("agents/state/resolved_decisions.json")

    # Agent log stubs so RotatingFileHandler has a seed file.
    for i in range(8):
        log = ROOT / "logs" / "agents" / f"agent{i}.log"
        if not log.exists():
            log.write_text("", encoding="utf-8")
            created.append(f"logs/agents/agent{i}.log")

    for name in ("site_b.log", "site_d.log"):
        p = ROOT / "logs" / "scrapers" / name
        if not p.exists():
            p.write_text("", encoding="utf-8")
            created.append(f"logs/scrapers/{name}")

    for name in ("ingest.log", "push.log"):
        p = ROOT / "logs" / "ws" / name
        if not p.exists():
            p.write_text("", encoding="utf-8")
            created.append(f"logs/ws/{name}")

    print(f"[phase3_setup] created={len(created)} skipped={len(skipped)}")
    for c in created:
        print(f"  + {c}")
    for s in skipped[:5]:
        print(f"  = {s}")
    if len(skipped) > 5:
        print(f"  = ... and {len(skipped) - 5} more already present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
