"""RM-515: Python dependency currency, and the rule that decides what is pinned.

Decision (self-adjudicated, 2026-10-03): requirements.txt pins what RC's OWN
tracked source imports, exactly (`==`). `requests` / `urllib3` / `cryptography`
are NOT RC dependencies - measured, no tracked .py imports them; on Legion they
arrive with unrelated user tools (gallery_dl, mitmproxy) - so pinning them here
would freeze somebody else's environment and protect nothing RC runs. The
guard below makes that decision re-checkable: the day RC imports one of them,
it must be pinned in the same change.

certifi IS used (lib/http/client.py) and its CA bundle is security-relevant,
so it is kept current. anthropic 0.x -> 1.x and websockets 16 -> 17 are
MAJORS and stay pinned until evaluated (not done in this slice).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQ = ROOT / "requirements.txt"

UNPINNED_BY_DECISION = ("requests", "urllib3", "cryptography")


def _pins() -> dict[str, str]:
    pins = {}
    for line in REQ.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name, sep, ver = line.partition("==")
        assert sep, f"requirements.txt line is not an exact pin: {line!r}"
        pins[name.strip().lower()] = ver.strip()
    return pins


def _tracked_py() -> list[Path]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "*.py"],
                         capture_output=True, text=True, check=True).stdout
    files = [ROOT / p for p in out.split("\0") if p]
    assert len(files) > 100, "vacuous enumeration - the git index read failed"
    return files


def test_every_requirement_is_an_exact_pin():
    assert _pins()


def test_certifi_is_current_enough():
    year, month, _ = (int(x) for x in _pins()["certifi"].split("."))
    assert (year, month) >= (2026, 7), "certifi CA bundle pin went stale"


def test_unpinned_transitives_are_not_imported_by_rc_source():
    pattern = re.compile(
        r"^\s*(?:import|from)\s+(" + "|".join(UNPINNED_BY_DECISION) + r")\b", re.M)
    hits = []
    for path in _tracked_py():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in pattern.finditer(text):
            hits.append(f"{path.relative_to(ROOT)}: {m.group(1)}")
    pins = _pins()
    unpinned = [h for h in hits if h.rsplit(": ", 1)[1] not in pins]
    assert not unpinned, ("RC now imports a dependency requirements.txt does not "
                          f"pin - pin it in the same change: {unpinned}")
