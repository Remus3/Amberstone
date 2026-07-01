"""OQ2 bridge-decommission drift guard.

The RC<->Peer cross-Claude bridge was removed in ADR-012 (2026-06-24). OQ2
(2026-07-01) is the completeness-sweep follow-up: it removes the residue that
survived that first pass - the dead `BridgeMetrics` Prometheus namespace, the
stale panel-codegen import, the inert peer-bridge-health tooltip render, and
the orphaned bridge contract docs.

This test pins the whole subsystem as PERMANENTLY gone so a future refactor (or
a re-extract) cannot silently resurrect a bridge module, metric, route, panel,
scheduled-task manifest, or contract doc. Do NOT re-pitch a bridge or a
lessons-sync subsystem - see ADR-012 + CLAUDE.md "Settled".
"""
from __future__ import annotations

import importlib
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent

# Source modules / routes / manifests / docs that MUST stay deleted.
_DELETED_BRIDGE_PATHS: tuple[str, ...] = (
    # tools/ bridge daemons + watcher + CLI + MCP set
    "tools/bridge_watcher.py",
    "tools/bridge_watcher_actions.py",
    "tools/bridge_watcher_history.py",
    "tools/bridge_watcher_classify.py",
    "tools/bridge_watcher_health_publisher.py",
    "tools/bridge_post_result.py",
    "tools/bridge_pull_tasks.py",
    "tools/bridge_post.py",
    "tools/bridge_task.py",
    "tools/bridge_cli.py",
    "tools/bridge_mcp_server.py",
    "tools/bridge_fetch.py",
    "tools/bridge_heartbeat.py",
    "tools/bridge_ping.py",
    "tools/peer_bridge_daemon.py",
    "tools/gamepc_bridge_daemon.py",
    "tools/legion_bridge_daemon.py",
    "tools/verify_bridge_roundtrip.py",
    "tools/bridge_dispatch_enable_lanes.py",
    "tools/start_bridge_mcp.py",
    "tools/process-bridge-tasks.md",
    # core/ bridge primitives
    "core/bridge.py",
    "core/bridge_envelope.py",
    "core/bridge_monitor.py",
    "ops/rc_file_bridge.py",
    # dashboard/ bridge routes + log
    "dashboard/routes_bridge.py",
    "dashboard/routes_bridge_pending.py",
    "dashboard/routes_bridge_pending_actions.py",
    "dashboard/routes_bridge_cadence.py",
    "dashboard/_bridge_log.py",
    # web panel + scheduled-task manifest
    "web/js/panels/bridge_pending.js",
    "ops/RC-BridgeWatcher.xml",
    # orphaned bridge contract docs (OQ2 sweep)
    "docs io RC peer/RC_BRIDGE_CONTRACT.md",
    "docs io RC peer/PEER_VIP_BRIDGE_MONITOR_FOR_RC_2026-05-02.md",
    # bridge overview doc (removed at ADR-012)
    "docs/BRIDGE.md",
)


class BridgeDecommissionGuardTests(unittest.TestCase):
    def test_bridge_source_and_docs_stay_deleted(self):
        offenders = [
            rel for rel in _DELETED_BRIDGE_PATHS if (_PROJECT_ROOT / rel).exists()
        ]
        self.assertEqual(
            offenders,
            [],
            f"bridge artifacts resurrected (must stay deleted per ADR-012 / OQ2): {offenders}",
        )

    def test_prom_metrics_has_no_bridge_namespace(self):
        prom = importlib.import_module("core.prom_metrics")
        self.assertFalse(
            hasattr(prom, "BridgeMetrics"),
            "core.prom_metrics.BridgeMetrics is dead bridge residue - remove it (OQ2)",
        )

    def test_no_rc_bridge_metric_names_declared(self):
        src = (_PROJECT_ROOT / "core" / "prom_metrics.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "rc_bridge_",
            src,
            "rc_bridge_* Prometheus metric names are dead bridge residue (OQ2)",
        )

    def test_panel_codegen_drops_bridge_pending_import(self):
        src = (_PROJECT_ROOT / "tools" / "extract_panels.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "bridge_pending.js",
            src,
            "extract_panels.py PANEL_IMPORTS still imports the deleted bridge_pending.js panel (OQ2)",
        )

    def test_live_main_js_has_no_peer_bridge_health_render(self):
        src = (_PROJECT_ROOT / "web" / "js" / "main.js").read_text(encoding="utf-8")
        # The peer-bridge-health tooltip block read `j.peers`; no route emits it.
        self.assertNotIn(
            "const peers = j.peers",
            src,
            "web/js/main.js still renders the inert peer-bridge-health tooltip block (OQ2)",
        )


if __name__ == "__main__":
    unittest.main()
