# Proposal M-01 - resolved_decisions.json topology drift (ADR-011 / ADR-012)

**Filed:** 2026-07-27 by agent6 during `t-f19b4cb85b1d` full-audit-pass
**Owner:** Agent 1 (queue) -> Agent 2 (backend), operator approval on the JSON edit
**Severity:** high (documentation truth-source drift)

## What
`agents/state/resolved_decisions.json` still describes the 2-PC Legion +
Game-PC topology as active, in two places:

1. **Decision `phase3-d008`** (line ~89): summary reads Game-PC as a live
   peer machine. Superseded by ADR-011 (`phase3-d011`, 2026-05-29).
2. **Appendix `cross_machine`** (lines ~384-393): keys `share_unc`,
   `writable_zones`, `credential_store`, `forwarder_restart_signal` and
   the meta `cross_machine_mechanism` all describe the retired
   `\\192.168.8.237\RCClient` SMB pipeline as an operating parameter.
   Superseded by `phase3-d020` (2026-06-28, defer-delete deadcode).

## Why
Charter line 19: `agents/state/resolved_decisions.json` is the source of
truth for locked decisions; any code that drifts from it is a finding.
Symmetric: if the truth-source itself drifts from the ADRs, downstream
readers (this auditor, future agents, humans) will treat a retired
pipeline as live.

## Fix (unified diff sketch, NOT applied autonomously)

```
--- a/agents/state/resolved_decisions.json
+++ b/agents/state/resolved_decisions.json
@@ line ~89 (phase3-d008 summary)
-      "summary": "Legion (legion-rc / 100.70.22.55 / LAN 192.168.8.230) runs RC + supervisor + vision server + web dashboard. Game-PC (gamepc-rc / 100.95.66.128 / LAN 192.168.8.237) runs League + Chrome on secondary monitor (panel 1920x1280 native at 100% scale). Peer (peer-host / <peer-tailnet-ip>) is cross-Claude peer for RC<->Peer bridge. All three in tailnet tailc150de.ts.net. Prefer tailnet hostnames over LAN IPs (MagicDNS old hostname de-registers instantly on rename). Vision runs in-process at 127.0.0.1:8889.",
+      "summary": "Legion (legion-rc / 100.70.22.55 / LAN 192.168.8.230) is the ONLY runtime host (ADR-011 2026-05-29 1-PC): runs League + Vanguard + RC + supervisor + vision + dashboard + OBS. Game-PC retired from pipeline (ADR-011); do not treat as a live peer. Peer (peer-host / <peer-tailnet-ip>) is now a SEPARATE private-project machine; RC<->Peer bridge decommissioned 2026-06-24 (ADR-012). Both remaining nodes in tailnet tailc150de.ts.net; MagicDNS old hostnames de-register instantly on rename. Vision runs in-process at 127.0.0.1:8889.",

@@ lines ~381-393 (appendix)
-    "cross_machine_mechanism": "smb_share_cmdkey_persistent"
+    "cross_machine_mechanism": "decommissioned_see_phase3-d020"
   },
   "cross_machine": {
-    "share_unc": "\\\\192.168.8.237\\RCClient",
-    "writable_zones": [
-      "\\\\192.168.8.237\\RCClient\\forwarder\\",
-      "\\\\192.168.8.237\\RCClient\\web\\"
-    ],
-    "credential_store": "cmdkey_on_legion_under_target_192.168.8.237",
-    "auth_user": "Administrator",
-    "forwarder_restart_signal": "\\\\192.168.8.237\\RCClient\\forwarder\\restart_trigger.txt"
+    "status": "decommissioned",
+    "deprecated_by": "phase3-d020",
+    "note": "Retained for historical audit only. Do not use these paths - Game-PC retired ADR-011 2026-05-29.",
+    "share_unc_historical": "\\\\192.168.8.237\\RCClient",
+    "writable_zones_historical": [
+      "\\\\192.168.8.237\\RCClient\\forwarder\\",
+      "\\\\192.168.8.237\\RCClient\\web\\"
+    ],
+    "credential_store_historical": "cmdkey_on_legion_under_target_192.168.8.237",
+    "auth_user_historical": "Administrator",
+    "forwarder_restart_signal_historical": "\\\\192.168.8.237\\RCClient\\forwarder\\restart_trigger.txt"
   },
```

## Test / verification
- After edit, `python -c "import json; json.load(open(r'agents/state/resolved_decisions.json'))"` still parses.
- Grep `git grep -n "cross_machine\.share_unc\|cross_machine\.writable_zones"` under `agents/` and `dashboard/` to catch any consumer that reads these keys unqualified; the appendix rename to `*_historical` will force any such consumer to fail loudly (that IS the point - flush dead consumers).

## Not autonomously applied
Charter puts `resolved_decisions.json` outside the agent6 autonomous-edit
list (only `blocklist.json`, `safeguards/*`, `source_quality.json`,
rotating-log retention, `ops/` firewall scripts are autonomous). This
proposal is filed for operator + Agent 1 dispatch to Agent 2.
