# ADR-005: Cross-Claude bridge uses Tailscale MagicDNS hostnames, not LAN IPs

**Date:** 2026-05-02  
**Status:** Accepted

## Context

The cross-Claude bridge (Legion <-> Peer; Game-PC retired from the pipeline 2026-06-20, ADR-011) needs stable addressing across reboots and potential network changes. Options:

1. **LAN IPs** (`192.0.2.x`) - static on the home network, but break outside LAN and require manual update if the router changes.
2. **Tailscale IPs** (`100.x.x.x`) - stable across reboots and networks, but numeric and hard to remember.
3. **Tailscale MagicDNS hostnames** (`rc-host`, `peer-host`; `peer-host` retired from the pipeline 2026-06-20, ADR-011) - human-readable, stable, auto-resolve via Tailscale DNS.

## Decision

All cross-machine HTTP calls use Tailscale MagicDNS hostnames. These are configured in `ops/local_paths.json` (gitignored, per-machine). Tailnet is `example-tailnet.ts.net`.

## Consequences

**Good:** Readable config, works from anywhere on the tailnet, no manual IP maintenance.  
**Trade-off:** Renaming a node in the Tailscale admin instantly de-registers the old hostname - the tailnet IP is stable but the hostname is not. `tailscale status` is the authoritative source; `nslookup` can mislead (bypasses the Tailscale resolver).  
**Watch for:** Any node rename in Tailscale admin must be followed by updating `ops/local_paths.json` on both live machines (Legion + Peer). See `CLAUDE.md` reference_tailscale_magicdns_rename memory.
