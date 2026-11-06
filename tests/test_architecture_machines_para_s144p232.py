"""Guard (RM-710 (a), RM-1735): the ARCHITECTURE.md "Machines" paragraph
states the current topology fact.

It used to say the canonical topology table (Legion + Peer; tailnet
names/IPs) lived in CLAUDE.md "Topology". That was stale twice over: the Peer
is decommissioned (ADR-011 / ADR-012), and the tailnet and LAN names are
per-host config in gitignored `ops/local_hosts.json` (reader
`core/local_hosts.py`), scrubbed from every tracked file. A doc that sends a
reader to CLAUDE.md for them points at nothing.

Pinned: the paragraph names the config file and its reader, both of which
must exist (the example template is tracked), and the old claim is absent.
ASCII only.
"""
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ARCH = _REPO_ROOT / "docs" / "ARCHITECTURE.md"


def _machines_section() -> str:
    text = _ARCH.read_text(encoding="utf-8")
    start = text.index("## Machines")
    end = text.find("\n## ", start + 1)
    assert end > start, "ARCHITECTURE.md lost the heading after Machines"
    return text[start:end]


def test_machines_section_is_anchored():
    sec = _machines_section()
    assert "1-PC" in sec
    assert len(sec) > 200


def test_machines_section_no_longer_sends_tailnet_names_to_claude_md():
    flat = " ".join(_machines_section().split())
    assert "tailnet names/IPs" not in flat
    assert "ADR-011 + Peer" not in flat


def test_machines_section_names_the_per_host_config_and_its_reader():
    flat = " ".join(_machines_section().split())
    assert "ops/local_hosts.json" in flat
    assert "core/local_hosts.py" in flat
    assert (_REPO_ROOT / "core" / "local_hosts.py").is_file()
    assert (_REPO_ROOT / "ops" / "local_hosts.example.json").is_file()
