# Riot Commander - Pengu Loader plugin (Surface C)

Electron Phase 6 stub. A [Pengu Loader](https://pengu.lol) plugin that renders
a compact Riot Commander coach panel directly inside the League client UX,
fed by the local dashboard at `RC_ORIGIN/api/state`.

This is a CODE-ONLY STUB. Live in-client validation is OWED (it needs a
running League client with Pengu Loader installed; not available in the
headless run). The file/structure contract is pinned by
`tests/test_pengu_plugin_skeleton.py`.

## What it does

- Injects the dashboard design tokens (`RC_ORIGIN/css/tokens.css`) plus the
  sibling `panel.css` so the panel matches the dashboard look.
- Fetches `RC_ORIGIN/api/state` every 2 seconds and shows mode / champion /
  coach action.
- Fails soft: if the dashboard is unreachable it shows "RC offline - retrying"
  and never throws a raw error into the client UX.

## CORS

The client UX origin (`https://127.0.0.1:<port>`) is cross-origin to
`RC_ORIGIN`. The dashboard echoes that loopback Origin in
`Access-Control-Allow-Origin` via the OVL2 gate in `dashboard/_handler.py`
(`_cors_allowed_origin`). The gate is loopback-only (never wildcard); add a
non-loopback client origin with the `RC_CORS_ALLOW_ORIGINS` env allowlist
(comma-separated) on the dashboard process.

## Install

1. Install Pengu Loader and locate its `plugins` folder.
2. Copy this `pengu/` folder into it, renamed `riot-commander`
   (so `plugins/riot-commander/index.js` is the entry).
3. Reload the client (Pengu picks up `index.js` automatically).

## Configure RC_ORIGIN

Default is `https://127.0.0.1:8888`. Override from the client console:

```js
window.localStorage.setItem("rc_origin", "https://legion-rc:8888");
```

Reload to apply.
