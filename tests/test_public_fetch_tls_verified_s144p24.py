"""RM-1175: scripts that fetch from a PUBLIC host verify its certificate.

scripts/fetch_cdragon_pbe.py (raw.communitydragon.org, a public CDN with a
valid certificate) and scripts/fetch_external_tft_meta.py (the operator's
configured external TFT meta source) both built
``ssl.create_default_context()`` and then switched it off
(``check_hostname = False``, ``verify_mode = CERT_NONE``). The CommunityDragon
download feeds the TRACKED data/meta/tft_set17_champion_codes.json, so anyone
on the path could plant planner codes. Measured 2026-10-31: a verified
handshake to raw.communitydragon.org:443 succeeds (TLSv1.3, CERT_REQUIRED,
check_hostname True), so verification costs the script nothing.

Both now take ``core.tls_policy.client_context_verified()``: the system trust
store, hostname check on, the RM-752 protocol floor. The three LCU scripts
keep a no-verify context on purpose - the LCU serves Riot's self-signed
certificate on loopback - and the sweep below allows no-verify in scripts/
ONLY there, so a new public fetch cannot quietly turn verification off.
"""
from __future__ import annotations

import ast
import importlib
import ssl
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import tls_policy  # noqa: E402

# scripts/ files allowed a no-verify TLS context, with the reason. Each one
# talks only to the LCU on loopback, which presents Riot's self-signed cert.
_NOVERIFY_ALLOWED = {
    "discover_champion_codes.py": "LCU on 127.0.0.1 (Riot self-signed cert)",
    "probe_missing_codes.py": "LCU on 127.0.0.1 (Riot self-signed cert)",
    "team_planner_sync.py": "LCU on 127.0.0.1 (Riot self-signed cert)",
}


class _Stop(Exception):
    """Raised by the fake urlopen once it has recorded the context."""


def _assert_verified(ctx) -> None:
    assert isinstance(ctx, ssl.SSLContext), ctx
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    assert ctx.minimum_version == tls_policy.TLS_MIN_VERSION


def _recording_urlopen(seen: list):
    def fake(req, *args, context=None, **kwargs):
        seen.append(context)
        raise _Stop("test refuses network access")
    return fake


def _fresh(name: str):
    sys.modules.pop(name, None)
    return importlib.import_module(name)


# --- the factory ------------------------------------------------------------

def test_client_context_verified_shape():
    _assert_verified(tls_policy.client_context_verified())


def test_client_context_verified_loads_a_trust_store():
    """CERT_REQUIRED with no CA loaded would refuse every peer."""
    ctx = tls_policy.client_context_verified()
    assert ctx.cert_store_stats()["x509_ca"] > 0


def test_client_context_verified_reads_the_floor_at_call_time(monkeypatch):
    monkeypatch.setattr(tls_policy, "TLS_MIN_VERSION", ssl.TLSVersion.TLSv1_3)
    ctx = tls_policy.client_context_verified()
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3


# --- the two public fetchers ------------------------------------------------

def test_fetch_cdragon_pbe_fetches_with_a_verified_context(monkeypatch):
    mod = _fresh("scripts.fetch_cdragon_pbe")
    try:
        seen: list = []
        # The fetch opens through the consent opener (RM-1441), which takes
        # the context as `context=`: record it there, module-scoped (RM-801).
        monkeypatch.setattr(mod, "open_consented", _recording_urlopen(seen))
        with pytest.raises(_Stop):
            mod.fetch(mod.TFT_EN_US_URL)
        assert len(seen) == 1
        _assert_verified(seen[0])
    finally:
        sys.modules.pop("scripts.fetch_cdragon_pbe", None)


class _Sources:
    """A stand-in for core.external_sources with one synthetic data URL."""

    @staticmethod
    def value(key):
        return None if key == "tft_meta_graphql" else "https://example.invalid"

    @staticmethod
    def values(key):
        return ["https://example.invalid/data.json"] if (
            key == "tft_meta_data_urls") else []


def test_fetch_external_tft_meta_fetches_with_a_verified_context(
        monkeypatch, tmp_path, capsys):
    mod = _fresh("scripts.fetch_external_tft_meta")
    try:
        seen: list = []
        monkeypatch.setattr(mod, "external_sources", _Sources)
        monkeypatch.setattr(mod, "RAW_OUT", tmp_path / "raw.json")
        # The fetch opens through the consent opener (RM-1564, the RM-1441
        # shape), which takes the context as `context=`: record it there.
        monkeypatch.setattr(mod, "open_consented", _recording_urlopen(seen))
        assert mod.main() == 1  # every fetch failed, nothing written
        assert len(seen) == 1
        _assert_verified(seen[0])
        assert list(tmp_path.iterdir()) == []
        assert "DATA FAILED" in capsys.readouterr().out
    finally:
        sys.modules.pop("scripts.fetch_external_tft_meta", None)


# --- the scripts/ sweep -----------------------------------------------------

def _noverify_sites(path: Path) -> list[str]:
    """Every statement in PATH that turns certificate verification off."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if not isinstance(tgt, ast.Attribute):
                    continue
                val = ast.unparse(node.value)
                if tgt.attr == "verify_mode" and val.endswith("CERT_NONE"):
                    hits.append(f"{path.name}:{node.lineno} verify_mode")
                if tgt.attr == "check_hostname" and val == "False":
                    hits.append(f"{path.name}:{node.lineno} check_hostname")
        elif isinstance(node, ast.Call):
            name = ast.unparse(node.func).rsplit(".", 1)[-1]
            if name in ("client_context_noverify",
                        "_create_unverified_context"):
                hits.append(f"{path.name}:{node.lineno} {name}")
    return hits


def _scripts() -> list[Path]:
    found = sorted((ROOT / "scripts").glob("*.py"))
    assert len(found) > 10, "scripts/ enumeration came back empty"
    return found


def test_no_script_turns_verification_off_outside_the_lcu_allowlist():
    bad = [hit for p in _scripts() if p.name not in _NOVERIFY_ALLOWED
           for hit in _noverify_sites(p)]
    assert bad == [], (
        "a scripts/ fetcher turns certificate verification off; use "
        f"core.tls_policy.client_context_verified() for a public host: {bad}")


@pytest.mark.parametrize("name", sorted(_NOVERIFY_ALLOWED))
def test_each_allowlisted_script_still_needs_its_entry(name):
    """No stale entry: each allowed script still builds a no-verify context,
    and its only HTTPS peer is loopback."""
    path = ROOT / "scripts" / name
    assert _noverify_sites(path), f"{name} no longer needs the allowlist"
    src = path.read_text(encoding="utf-8")
    assert "https://127.0.0.1:" in src
    peers = {seg.split("/", 1)[0] for seg in src.split("https://")[1:]}
    assert {p.split(":", 1)[0] for p in peers} == {"127.0.0.1"}, peers
