"""Per-host network identity is CONFIG, never a tracked literal (MAIN 2246 sec 3/4).

The machine's tailnet node name, tailnet name and addresses, its LAN address
and the extra TLS SANs live in the gitignored ``ops/local_hosts.json``
(template ``ops/local_hosts.example.json``), read by ``core/local_hosts.py``.
An absent or malformed file means loopback only: nothing binds or names a
non-loopback address by default.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import local_hosts  # noqa: E402


def test_absent_file_is_empty_config(tmp_path):
    assert local_hosts.load(tmp_path / "nope.json") == {}


def test_malformed_file_is_empty_config(tmp_path):
    p = tmp_path / "local_hosts.json"
    p.write_text("{not json", encoding="ascii")
    assert local_hosts.load(p) == {}
    p.write_text("[1, 2]", encoding="ascii")
    assert local_hosts.load(p) == {}


def test_load_reads_a_dict(tmp_path):
    p = tmp_path / "local_hosts.json"
    p.write_text(json.dumps({"tailnet_ipv4": "100.64.0.1"}), encoding="ascii")
    assert local_hosts.load(p) == {"tailnet_ipv4": "100.64.0.1"}


def test_tailnet_ipv4_accepts_only_the_cgnat_range():
    assert local_hosts.tailnet_ipv4({"tailnet_ipv4": "100.64.0.1"}) == "100.64.0.1"
    assert local_hosts.tailnet_ipv4({"tailnet_ipv4": " 100.127.255.254 "}) == "100.127.255.254"
    for bad in ("", None, 5, "0.0.0.0", "::", "127.0.0.1", "192.0.2.10", "10.0.0.5",
                "100.128.0.1", "100.63.255.255", "rc-host", "100.64.0.1/24"):
        assert local_hosts.tailnet_ipv4({"tailnet_ipv4": bad}) is None, bad
    assert local_hosts.tailnet_ipv4({}) is None


def test_cert_sans_keeps_strings_only_and_dedupes():
    cfg = {"cert_sans": ["rc-host", "", "rc-host", 7, " 100.64.0.1 ", None]}
    assert local_hosts.cert_sans(cfg) == ["rc-host", "100.64.0.1"]
    assert local_hosts.cert_sans({}) == []
    assert local_hosts.cert_sans({"cert_sans": "rc-host"}) == []


def test_example_template_is_tracked_and_carries_no_real_value():
    ex = REPO / "ops" / "local_hosts.example.json"
    doc = json.loads(ex.read_text(encoding="ascii"))
    for key in ("tailnet_name", "tailnet_fqdn", "tailnet_ipv4", "lan_ipv4", "lan_subnet", "cert_sans"):
        assert key in doc, key
    assert doc["cert_sans"] == []
    for key in ("tailnet_name", "tailnet_fqdn", "tailnet_ipv4", "lan_ipv4", "lan_subnet"):
        assert doc[key] == "", key


def test_real_config_is_gitignored_and_untracked():
    rel = "ops/local_hosts.json"
    ignored = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", "--", rel])
    assert ignored.returncode == 0, "ops/local_hosts.json must be gitignored"
    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "--error-unmatch", "--", rel],
                             capture_output=True)
    assert tracked.returncode != 0, "ops/local_hosts.json must never be tracked"


# ---- mission control bind scope reads it ----------------------------------------

def test_mc_bind_addresses_default_is_loopback_only():
    from mc import server
    assert server.bind_addresses({}) == ["127.0.0.1"]


def test_mc_bind_addresses_adds_only_a_valid_tailnet_address():
    from mc import server
    assert server.bind_addresses({"tailnet_ipv4": "100.64.0.1"}) == ["127.0.0.1", "100.64.0.1"]
    for bad in ("192.0.2.10", "0.0.0.0", "::", "", "10.0.0.5", "rc-host"):
        assert server.bind_addresses({"tailnet_ipv4": bad}) == ["127.0.0.1"], bad
