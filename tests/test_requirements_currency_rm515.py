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

Amendment (session 111 merger, 2026-10-12, self-adjudicated): a module under
a `tests/` directory that loads one of these ONLY behind
`pytest.importorskip("<pkg>")` adds no RC dependency - it skips wherever the
package is absent (CI has no cryptography) - so it is exempt. First case:
`tests/test_mc_server_tls_accept_rm739.py` builds a throwaway self-signed
cert with cryptography. Alternatives rejected: pinning cryptography (freezes
the user-tool environment this decision protects, and regenerates the hashed
CI requirement sets for a test that skips there); a committed test key pair
(a PEM private key in a public tree is what tools/credential_patterns.py
`private_key_pem` exists to stop); an `openssl` subprocess (an unpinned host
tool, the same problem one level down). Reverses if: non-test RC code imports
one of these, or a test imports one without the importorskip (both still
fail - pinned by test_the_optional_test_import_exemption_is_narrow).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath

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


_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(" + "|".join(UNPINNED_BY_DECISION) + r")\b", re.M)


def _optional_test_import(rel: str, text: str, pkg: str) -> bool:
    """True when rel is under a tests/ directory and loads pkg only behind
    ``pytest.importorskip("pkg")`` (see the session 111 amendment above)."""
    if "tests" not in PurePosixPath(rel.replace("\\", "/")).parts[:-1]:
        return False
    return re.search(r"pytest\.importorskip\(\s*['\"]" + re.escape(pkg) + r"['\"]",
                     text) is not None


def _unpinned_hits(files, pins) -> list[str]:
    """['<rel>: <pkg>'] for every import of an UNPINNED_BY_DECISION package in
    files ((rel, text) pairs) that requirements.txt does not pin and that is
    not an optional test-only import."""
    hits = []
    for rel, text in files:
        for m in _IMPORT.finditer(text):
            pkg = m.group(1)
            if pkg in pins or _optional_test_import(rel, text, pkg):
                continue
            hits.append(f"{rel}: {pkg}")
    return hits


def test_unpinned_transitives_are_not_imported_by_rc_source():
    files = []
    for path in _tracked_py():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files.append((path.relative_to(ROOT).as_posix(), text))
    unpinned = _unpinned_hits(files, _pins())
    assert not unpinned, ("RC now imports a dependency requirements.txt does not "
                          f"pin - pin it in the same change: {unpinned}")


def test_the_optional_test_import_exemption_is_narrow():
    guarded = 'pytest.importorskip("cryptography")\nfrom cryptography import x509\n'
    bare = "from cryptography import x509\n"
    assert _unpinned_hits([("tests/test_x.py", guarded)], {}) == []
    assert _unpinned_hits([("agents/daemon_slayer/tests/test_x.py", guarded)], {}) == []
    # No importorskip: still a dependency.
    assert _unpinned_hits([("tests/test_x.py", bare)], {}) == ["tests/test_x.py: cryptography"]
    # Outside a tests/ directory the importorskip does not exempt it.
    assert _unpinned_hits([("mc/server.py", guarded)], {}) == ["mc/server.py: cryptography"]
    assert _unpinned_hits([("tools/tests_helper.py", guarded)], {}) == [
        "tools/tests_helper.py: cryptography"]
    # importorskip of a DIFFERENT package does not exempt this one.
    other = 'pytest.importorskip("requests")\nimport cryptography\n'
    assert _unpinned_hits([("tests/test_x.py", other)], {}) == ["tests/test_x.py: cryptography"]
    # A pin still clears it anywhere.
    assert _unpinned_hits([("mc/server.py", bare)], {"cryptography": "46.0.0"}) == []
