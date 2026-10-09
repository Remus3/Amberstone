# arch: per-host network identity config | section=core
"""
core/local_hosts.py - this machine's network identity, from per-host CONFIG.

The tailnet node name, tailnet name and addresses, the LAN address and subnet,
and the extra TLS SANs are per-host values kept in the GITIGNORED
ops/local_hosts.json (template: ops/local_hosts.example.json), never as
literals in a tracked file - the public tree and its history were scrubbed of
them (MAIN 2246 ORDER sections 3-4, 2026-10-09).

An absent or malformed file is an empty config, and every caller then falls
back to loopback: nothing binds or names a non-loopback address by default.
"""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "ops" / "local_hosts.json"
_TAILNET = ipaddress.ip_network("100.64.0.0/10")


def load(path=None) -> dict:
    """The per-host config as a dict; {} when absent or malformed."""
    p = Path(path) if path is not None else PATH
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def tailnet_ipv4(cfg=None):
    """This box's tailnet IPv4 when configured AND inside 100.64.0.0/10, else None."""
    cfg = load() if cfg is None else cfg
    raw = cfg.get("tailnet_ipv4")
    if not isinstance(raw, str):
        return None
    try:
        addr = ipaddress.IPv4Address(raw.strip())
    except ValueError:
        return None
    return str(addr) if addr in _TAILNET else None


def cert_sans(cfg=None) -> list:
    """Extra TLS SAN entries (names or addresses), strings only, de-duplicated."""
    cfg = load() if cfg is None else cfg
    raw = cfg.get("cert_sans")
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, str) and item.strip() and item.strip() not in out:
            out.append(item.strip())
    return out
