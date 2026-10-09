"""Credential-shape detector for RC's write-time hook. VALUES ARE NEVER EMITTED.

Closes defect D1/D2 of
`docs/specs/2026-09-20-shared-git-root-bucket-rc-share-scan.md`, which measured
that RC evaluates NO credential pattern against ANY file population: not the
staged set, not the push range, not the working tree. This module supplies the
patterns; `tools/edit_lint_check.py` (PostToolUse `Edit|Write`, registered at
`.claude/settings.json:32`) supplies the only RC population that already
includes UNTRACKED files - the exact file an agent just wrote.

THE CONTRACT, in order of importance:

1. **A matched value NEVER leaves this module.** A `Finding` has three fields -
   line number, pattern class, arm - and no field in which a value could be
   carried. `format_findings` renders those three and nothing else. A gate that
   prints the secret it caught has copied that secret somewhere new, which is
   strictly worse than not catching it.
2. **O(file), no I/O beyond one read, no subprocess, no network.** This runs on
   every agent write. One combined regex is applied per line, plus a narrow
   second pass over wrapped lines.
3. **Shape only.** Nothing here proves a literal is live, and nothing here
   probes anything. A hit means "this looks like a credential", which is the
   right signal for a write-time advisory.

LINE-WRAP EVASION - the deliberate decision, recorded rather than assumed.
A literal split across a wrap is invisible to a whole-token search, and that
class has already bitten this repository in a different guard (the sibling
name sweep needed a split-form positive control). So this module DOES dewrap,
but NARROWLY: only a backslash continuation, and only a quote-to-quote
adjacency where a line ends on a quote and the next line begins with the SAME
quote character. Those two forms are how a secret actually survives a wrap in
source, and neither can splice two unrelated lines into a false positive - an
ordinary pair of neighbouring statements does not pair its quotes that way.
A wider "strip all newlines" dewrap was rejected: on a write-time hook it would
manufacture false hits from adjacent unrelated lines, and a noisy gate is a
gate that gets disabled.

PRAGMA. A line carrying `rc-credential-scan: allow-fixture` is exempt. It is
line-scoped, never file-scoped, so an exemption cannot silently widen, and it
is visible in the source it exempts. It exists for test fixtures and for docs
that must show a credential SHAPE.

LEAK CLASSES (MAIN 2246 ORDER sections 3-4). Network and machine identity -
private-LAN IPv4, tailnet addresses and DNS names, Windows host names, the
per-host values in the gitignored `ops/local_hosts.json`, user-profile and
checkout paths - live behind a SEPARATE entry point, `scan_leaks`, so
`scan_text` (the write-time credential arm and the `--all` history audit)
keeps its exact population. `tools/credential_history_scan.py --pre-push`
runs both. Same contract: a leak finding carries line, class and arm only.
"""
from __future__ import annotations

import ipaddress
import re
from bisect import bisect_right
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

PRAGMA = "rc-credential-scan: allow-fixture"

# Above this the head is scanned and the caller is told it was truncated. The
# hook budget is 15s; an uncapped scan of a multi-hundred-MB write would eat it.
MAX_SCAN_BYTES = 8_000_000

# Bound on a dewrapped join, so a pathological file of quote-paired lines
# cannot turn the join into quadratic work.
_MAX_JOIN_CHARS = 4096


class Finding(NamedTuple):
    """A hit. Deliberately has NO field able to carry the matched value."""

    line_no: int
    pattern_class: str
    arm: str


# Ordered: the most specific family first, because alternation resolves
# left-to-right at a given start position. `anthropic_admin` MUST precede
# `anthropic` so an admin key is reported under its own name. The report
# recorded that RC's only prior admin coverage was accidental prefix-sharing
# inside an output redactor, and that accidental coverage is not coverage.
_FAMILIES = (
    ("anthropic_admin", r"sk-ant-admin[A-Za-z0-9_\-]{8,}"),
    ("anthropic", r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    ("openai", r"sk-(?!ant-)(?:proj-)?[A-Za-z0-9_\-]{24,}"),
    (
        "aws_access_key_id",
        r"(?<![A-Z0-9])(?:AKIA|ASIA|AROA|AIDA|ANPA|ANVA|APKA)[A-Z0-9]{16}(?![A-Z0-9])",
    ),
    ("github_pat", r"(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{40,}"),
    ("github_token", r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{30,}"),
    (
        "google_api_key",
        r"(?<![A-Za-z0-9_\-])AIza[A-Za-z0-9_\-]{35}(?![A-Za-z0-9_\-])",
    ),
    ("google_oauth", r"(?<![A-Za-z0-9_\-])ya29\.[A-Za-z0-9._\-]{20,}"),
    ("slack_token", r"(?<![A-Za-z0-9_\-])xox[abprsoe]-[A-Za-z0-9\-]{10,}"),
    ("riot_api_key", r"(?<![A-Za-z0-9_\-])RGAPI-[A-Za-z0-9\-]{20,}"),
    ("private_key_pem", r"-----BEGIN (?:[A-Z0-9 ]{1,32} )?PRIVATE KEY-----"),
    (
        "jwt",
        r"(?<![A-Za-z0-9_\-])eyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\."
        r"[A-Za-z0-9_\-]{8,}",
    ),
    ("bearer_token", r"[Bb]earer[ \t]+[A-Za-z0-9._~+/=\-]{24,}"),
    (
        "connection_string_password",
        r"[A-Za-z][A-Za-z0-9+.\-]{1,31}://[^\s:/@\"']{1,64}:[^\s:/@\"']{1,128}@",
    ),
    (
        "generic_secret_assignment",
        # The inner (?: ) is NOT redundant and must not be "tidied" away.
        # A scoped case-insensitive group whose body starts with a backslash
        # escape puts a letter, a colon and a backslash next to each other, and
        # the sibling-name sweep's STRUCT_DRIVE_ROOT arm reads that trio as a
        # Windows drive root and HALTS the push. That is a false positive in the
        # sweep, but erring toward firing is correct for a structural arm, so
        # the fix belongs here rather than in the guard. The extra group keeps
        # the scoped case-insensitivity and the semantics identical while
        # putting an open paren after the colon instead of a backslash.
        # Do NOT write the offending trio into this comment to explain it - the
        # first version of this note did, and the comment then tripped the very
        # arm it was describing.
        r"(?i:(?:\b(?:api[_\-]?key|secret[_\-]?key|secret|password|passwd|pwd"
        r"|access[_\-]?token|auth[_\-]?token|token)\b))"
        r"[ \t]*[:=][ \t]*[\"'][^\"'\s]{16,}[\"']",
    ),
)

PATTERN_CLASSES = tuple(name for name, _ in _FAMILIES)

_COMBINED = re.compile(
    "|".join(f"(?P<{name}>{pattern})" for name, pattern in _FAMILIES)
)

_COMPILED = tuple((name, re.compile(pattern)) for name, pattern in _FAMILIES)

# Cheap prefilter. Each entry is a set of LOWERCASE literals of which at least
# one MUST appear inside any possible match of that family - so a family whose
# literals are all absent cannot match, and its regex can be skipped outright.
# `str.lower` plus `in` are C-speed substring searches; the lookbehind-bearing
# regexes are not. Measured on a clean 1 MB buffer: prefilter about 9 ms,
# full regex sweep about 280 ms. Getting one of these literals WRONG silently
# blinds a whole family, so widening a pattern means revisiting its row here.
_TRIGGERS = {
    "anthropic_admin": ("sk-ant-admin",),
    "anthropic": ("sk-ant-",),
    "openai": ("sk-",),
    "aws_access_key_id": ("akia", "asia", "aroa", "aida", "anpa", "anva", "apka"),
    "github_pat": ("github_pat_",),
    "github_token": ("ghp_", "gho_", "ghu_", "ghs_", "ghr_"),
    "google_api_key": ("aiza",),
    "google_oauth": ("ya29.",),
    "slack_token": ("xox",),
    "riot_api_key": ("rgapi-",),
    "private_key_pem": ("private key-----",),
    "jwt": ("eyj",),
    "bearer_token": ("bearer",),
    "connection_string_password": ("://",),
    "generic_secret_assignment": (
        "key",
        "secret",
        "password",
        "passwd",
        "pwd",
        "token",
    ),
}

# Only the generic-assignment family gets a placeholder filter. The prefixed
# families carry their own evidence in the prefix, so filtering them on body
# shape would just punch a hole in the detector.
_PLACEHOLDER_MARKERS = (
    "example",
    "changeme",
    "change_me",
    "placeholder",
    "redacted",
    "your_",
    "your-",
    "yourkey",
    "insert_",
    "replace_",
    "dummy",
    "notarealkey",
    "xxxx",
    "<",
    ">",
    "...",
)

_GENERIC = "generic_secret_assignment"


def _is_placeholder(matched: str) -> bool:
    low = matched.lower()
    if any(marker in low for marker in _PLACEHOLDER_MARKERS):
        return True
    quote = max(low.rfind('"'), low.rfind("'"))
    if quote <= 0:
        return False
    opener = max(low.rfind('"', 0, quote), low.rfind("'", 0, quote))
    body = low[opener + 1 : quote]
    return bool(body) and len(set(body)) <= 1


def _classes_in(text: str) -> list[str]:
    """Pattern classes present in `text`. The matched text never escapes here."""
    found: list[str] = []
    for match in _COMBINED.finditer(text):
        name = match.lastgroup
        if name is None:
            continue
        if name == _GENERIC and _is_placeholder(match.group()):
            continue
        if name not in found:
            found.append(name)
    return found


def _line_starts(text: str) -> list[int]:
    starts = [0]
    position = text.find("\n")
    while position != -1:
        starts.append(position + 1)
        position = text.find("\n", position + 1)
    return starts


def _join_step(current: str, following: str) -> str | None:
    """Join `current` onto `following` if and only if `current` is WRAPPED.

    Two narrow forms, and nothing else:
      - a trailing backslash continuation;
      - a trailing quote whose partner opens the next line (an adjacent or
        `+`-concatenated string literal).
    """
    head = current.rstrip()
    if head.endswith("\\"):
        return head[:-1] + following.strip()
    if head.endswith("+"):
        head = head[:-1].rstrip()
    if not head:
        return None
    quote = head[-1]
    if quote not in ('"', "'"):
        return None
    tail = following.lstrip()
    if not tail.startswith(quote):
        return None
    return head[:-1] + tail[1:]


def _wrapped_blocks(lines: list[str]) -> list[tuple[int, int, str]]:
    """Return (start_index, end_index, joined_text) for each wrapped run."""
    blocks: list[tuple[int, int, str]] = []
    total = len(lines)
    index = 0
    while index < total:
        joined: str | None = None
        last = index
        while last + 1 < total:
            step = _join_step(lines[index] if joined is None else joined, lines[last + 1])
            if step is None or len(step) > _MAX_JOIN_CHARS:
                break
            joined = step
            last += 1
        if joined is None:
            index += 1
            continue
        blocks.append((index, last, joined))
        index = last + 1
    return blocks


def scan_text(text: str) -> list[Finding]:
    """Scan `text`. Returns line/class/arm records only - never a value.

    The per-line arm is run as ONE pass over the whole buffer, not one regex
    call per line: no family here can span a newline (every whitespace class
    in `_FAMILIES` is a literal space, `[ \\t]`, or excludes `\\s`), so the two
    are equivalent. The prefilter then drops every family whose trigger
    literals are absent. Measured on a clean 1 MB buffer: 314 ms for the naive
    combined sweep, 18 ms for this path.
    """
    findings: list[Finding] = []
    seen: set[tuple[int, str]] = set()

    lowered = text.lower()
    armed = [
        (name, rx)
        for name, rx in _COMPILED
        if any(literal in lowered for literal in _TRIGGERS[name])
    ]
    if armed:
        starts = _line_starts(text)
        total = len(text)
        for name, rx in armed:
            for match in rx.finditer(text):
                if name == _GENERIC and _is_placeholder(match.group()):
                    continue
                index = bisect_right(starts, match.start()) - 1
                end = starts[index + 1] if index + 1 < len(starts) else total
                if PRAGMA in text[starts[index] : end]:
                    continue
                key = (index + 1, name)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(Finding(index + 1, name, "line"))
        findings.sort(key=lambda f: (f.line_no, f.pattern_class))

    lines = text.splitlines()
    exempt = {i for i, line in enumerate(lines) if PRAGMA in line}
    for start, end, joined in _wrapped_blocks(lines):
        if any(i in exempt for i in range(start, end + 1)):
            continue
        for name in _classes_in(joined):
            if (start + 1, name) in seen:
                continue
            findings.append(Finding(start + 1, name, "dewrap"))
    return findings


def scan_file(path: Path | str) -> list[Finding]:
    """Scan one file. Any read or decode problem yields no findings, not a raise."""
    target = Path(path)
    try:
        data = target.read_bytes()
    except OSError:
        return []
    truncated = len(data) > MAX_SCAN_BYTES
    if truncated:
        data = data[:MAX_SCAN_BYTES]
    text = data.decode("utf-8", errors="replace")
    findings = scan_text(text)
    if truncated and not findings:
        return []
    return findings


def was_truncated(path: Path | str) -> bool:
    """True when the file is larger than the scan budget. Advisory only."""
    try:
        return Path(path).stat().st_size > MAX_SCAN_BYTES
    except OSError:
        return False


def format_findings(label: str, findings: list[Finding]) -> list[str]:
    """Render findings as file:line + class + arm. NO VALUE, BY CONSTRUCTION."""
    return [
        f"  {label}:{f.line_no}  class={f.pattern_class} arm={f.arm}"
        for f in findings
    ]


# ---------------------------------------------------------------------------
# LEAK CLASSES - network and machine identity, not credentials.
#
# MAIN 2246 ORDER section 3 finding 1 ("add the class to the pre-push leak
# sweep") and section 4's replace list (the home-network IPv4 class and the
# machine host name class). HEAD was scrubbed in LEDGER 1699; this is the
# prevention half, so the count cannot regrow.
#
# GATE classes halt a push. ADVISORY classes are reported and never halt:
# HEAD still carries them in files other work is rewriting or moving, and the
# push diff runs `--no-renames`, so a halting class would block the very
# commits that remove them. Promote one to GATE once its HEAD count is 0.
#
# Shapes are written so the pattern SOURCE never matches itself, and no
# drive-rooted literal appears in this file (the sibling-name sweep's
# structural arm reads one as an undeclared project).
# ---------------------------------------------------------------------------

_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
# A digit or dot on the left, or a digit / dot-digit on the right, means the
# text is a longer dotted number (a version, a five-part string), not an IPv4.
_IP_LEFT = r"(?<![0-9.])"
_IP_RIGHT = r"(?![0-9]|\.[0-9])"
_HOST_LEFT = r"(?<![A-Za-z0-9_\-])"
_HOST_RIGHT = r"(?![A-Za-z0-9_\-])"

_LEAK_FAMILIES = (
    (
        # RFC 1918: 10/8, 172.16/12, 192.168/16.
        "private_lan_ipv4",
        _IP_LEFT
        + r"(?:10\."
        + _OCTET
        + r"|192\.168|172\.(?:1[6-9]|2[0-9]|3[01]))\."
        + _OCTET
        + r"\."
        + _OCTET
        + _IP_RIGHT,
    ),
    (
        # 100.64.0.0/10 (shared address space; every tailnet node address).
        # 100.64.0.0/24 is the tree's documented placeholder block and is
        # excluded, as RFC 5737 is for the LAN class.
        "tailnet_ipv4",
        _IP_LEFT
        + r"100\.(?!64\.0\.)(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\."
        + _OCTET
        + r"\."
        + _OCTET
        + _IP_RIGHT,
    ),
    (
        # The tailnet DNS name the coordination server generates. A custom
        # tailnet name has no shape; it is caught by the values arm instead.
        "tailnet_dns_name",
        r"(?i:" + _HOST_LEFT + r"tail[0-9a-f]{6}\.ts\.net" + _HOST_RIGHT + r")",
    ),
    (
        # Windows-generated computer names. At least one digit is required in
        # the random part, which keeps all-letter words (a WIN- prefixed
        # feature name, say) out.
        "windows_host_name",
        r"(?i:"
        + _HOST_LEFT
        + r"(?:(?:desktop|laptop)-(?=[a-z]{0,6}[0-9])[a-z0-9]{7}"
        + r"|win-(?=[a-z]{0,10}[0-9])[a-z0-9]{11})"
        + _HOST_RIGHT
        + r")",
    ),
    (
        # ADVISORY. A profile path names the account. Drive form, forward-slash
        # form and the POSIX-shell form; the stock non-account profiles and
        # any placeholder (<user>, %USERNAME%, $USER) are not a hit.
        "user_profile_path",
        r"(?i:(?<![A-Za-z0-9_])(?:[a-z]:[\\/]{1,2}|/mnt/[a-z]/|/[a-z]/)users[\\/]{1,2}"
        r"(?!(?:public|default|default user|all users)(?![A-Za-z0-9_.\-])"
        r"|example|your)"
        r"[A-Za-z0-9_.\-]*[A-Za-z0-9])",
    ),
)

LEAK_PATTERN_CLASSES = (
    "private_lan_ipv4",
    "tailnet_ipv4",
    "tailnet_dns_name",
    "windows_host_name",
    "local_host_value",
)
ADVISORY_LEAK_CLASSES = ("user_profile_path", "checkout_path")

_LEAK_COMPILED = tuple((name, re.compile(pattern)) for name, pattern in _LEAK_FAMILIES)

# Same prefilter idea as _TRIGGERS: a LOWERCASE literal that must occur inside
# any match of the family. Getting one wrong blinds the family.
_LEAK_TRIGGERS = {
    "private_lan_ipv4": ("10.", "192.168.", "172."),
    "tailnet_ipv4": ("100.",),
    "tailnet_dns_name": (".ts.net",),
    "windows_host_name": ("desktop-", "laptop-", "win-"),
    "user_profile_path": ("users/", "users\\"),
}

# Values arm. Placeholders the tree already uses, loopback, the unspecified
# address and the documentation blocks are never a leak, so a config that
# carries one cannot turn every doc in the tree into a hit.
_PLACEHOLDER_HOSTS = frozenset(
    {"localhost", "rc-host", "peer-host", "work-host", "windows-host"}
)
_NON_LEAK_NETS = tuple(
    ipaddress.ip_network(net)
    for net in (
        "192.0.2.0/24",  # RFC 5737 TEST-NET-1
        "198.51.100.0/24",  # RFC 5737 TEST-NET-2
        "203.0.113.0/24",  # RFC 5737 TEST-NET-3
        "100.64.0.0/24",  # the tree's tailnet placeholder block
        "127.0.0.0/8",
        "0.0.0.0/8",
    )
)
_MIN_VALUE_CHARS = 4
_VALUE_LEFT = r"(?<![A-Za-z0-9_\-])(?<![0-9]\.)"
_VALUE_RIGHT = r"(?![A-Za-z0-9_\-]|\.[0-9])"
_PATH_LEFT = r"(?<![A-Za-z0-9_])"
_PATH_RIGHT = r"(?![A-Za-z0-9_\-])"

# Test code and fixtures are exempt (the order's acceptance is "outside
# tests/fixtures"). A directory component, a test-file name, or one named
# pytest package that lives outside tests/ and carries its own conftest.py.
LEAK_EXEMPT_DIRS = frozenset({"tests", "test", "fixtures", "testdata", "__tests__"})
LEAK_EXEMPT_PREFIXES = ("agents/agent3_testing/suite/",)
_TEST_FILE = re.compile(
    r"(?:test_.*\.py|.*_test\.py|conftest\.py|.*\.(?:test|spec)\.[cm]?[jt]sx?)$"
)


def usable_leak_value(value: object) -> bool:
    """True when ``value`` may be searched for as a literal host value."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if len(text) < _MIN_VALUE_CHARS or any(ch.isspace() for ch in text):
        return False
    low = text.lower()
    if low in _PLACEHOLDER_HOSTS or "example" in low:
        return False
    try:
        addr = ipaddress.ip_address(low.split("/", 1)[0])
    except ValueError:
        return True
    if addr.is_loopback or addr.is_unspecified:
        return False
    return not any(addr in net for net in _NON_LEAK_NETS if net.version == addr.version)


def checkout_path_variants(path: str) -> tuple[str, ...]:
    """The spellings an absolute checkout path takes in text.

    Native (backslash), forward-slash, and the POSIX-shell drive form. Values
    shorter than the minimum are dropped, so a root of "/" never matches.
    """
    base = str(path).strip().rstrip("\\/")
    forward = base.replace("\\", "/")
    out: list[str] = []
    candidates = [base.replace("/", "\\"), forward]
    if len(base) >= 2 and base[1] == ":" and base[0].isalpha():
        candidates.append("/" + base[0].lower() + forward[2:])
    else:
        candidates = [forward]
    for item in candidates:
        if len(item) >= _MIN_VALUE_CHARS and item not in out:
            out.append(item)
    return tuple(out)


def is_leak_exempt(path: str) -> bool:
    """True for test code and fixtures, the one population allowed a leak shape."""
    norm = str(path).replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    parts = [p for p in norm.lower().split("/") if p]
    if not parts:
        return False
    if any(part in LEAK_EXEMPT_DIRS for part in parts[:-1]):
        return True
    if "/".join(parts).startswith(LEAK_EXEMPT_PREFIXES):
        return True
    return bool(_TEST_FILE.match(parts[-1]))


def is_advisory(finding: Finding) -> bool:
    """True when the finding is reported but never halts."""
    return finding.pattern_class in ADVISORY_LEAK_CLASSES


@lru_cache(maxsize=256)
def _value_rx(value: str) -> re.Pattern:
    return re.compile(_VALUE_LEFT + re.escape(value) + _VALUE_RIGHT, re.IGNORECASE)


@lru_cache(maxsize=64)
def _checkout_rx(value: str) -> tuple[str, re.Pattern] | None:
    """(prefilter literal, regex) for one checkout path, or None.

    The drive is NOT part of the identity: a checkout that moved drives is
    still cited under its old drive in older text, so any drive letter (and
    the POSIX-shell drive form) matches, with either separator.
    """
    norm = value.strip().replace("\\", "/").rstrip("/")
    has_drive = False
    if len(norm) >= 2 and norm[1] == ":" and norm[0].isalpha():
        has_drive, norm = True, norm[2:]
    elif re.match(r"/[A-Za-z](?:/|$)", norm):
        has_drive, norm = True, norm[2:]
    segments = [seg for seg in norm.split("/") if seg]
    if not segments or len("/".join(segments)) < _MIN_VALUE_CHARS:
        return None
    head = r"(?:[A-Za-z]:|/[A-Za-z])" if has_drive else ""
    body = "".join(r"[\\/]{1,2}" + re.escape(seg) for seg in segments)
    return segments[-1].lower(), re.compile(
        _PATH_LEFT + head + body + _PATH_RIGHT, re.IGNORECASE
    )


def scan_leaks(
    text: str,
    values: tuple[str, ...] | list[str] = (),
    checkout_paths: tuple[str, ...] | list[str] = (),
) -> list[Finding]:
    """Scan ``text`` for the leak classes. Line/class/arm records only.

    ``values`` are this host's literal identity values (gitignored config plus
    the live computer name), reported as ``local_host_value``.
    ``checkout_paths`` are the absolute checkout path spellings, reported as
    the advisory ``checkout_path``. Arms: ``leak`` (shape), ``value`` (literal).
    The line PRAGMA exempts a line, as for credentials. Path exemption is the
    CALLER's job (``is_leak_exempt``): this function sees text, not paths.
    """
    lowered = text.lower()
    jobs: list[tuple[str, str, re.Pattern]] = []
    for name, rx in _LEAK_COMPILED:
        if any(literal in lowered for literal in _LEAK_TRIGGERS[name]):
            jobs.append((name, "leak", rx))
    for value in values:
        if usable_leak_value(value) and value.strip().lower() in lowered:
            jobs.append(("local_host_value", "value", _value_rx(value.strip())))
    path_patterns: set[str] = set()
    for path in checkout_paths:
        compiled = _checkout_rx(path) if isinstance(path, str) else None
        if compiled is None or compiled[1].pattern in path_patterns:
            continue
        path_patterns.add(compiled[1].pattern)
        if compiled[0] in lowered:
            jobs.append(("checkout_path", "value", compiled[1]))
    if not jobs:
        return []
    starts = _line_starts(text)
    total = len(text)
    findings: list[Finding] = []
    seen: set[tuple[int, str]] = set()
    for name, arm, rx in jobs:
        for match in rx.finditer(text):
            index = bisect_right(starts, match.start()) - 1
            end = starts[index + 1] if index + 1 < len(starts) else total
            if PRAGMA in text[starts[index] : end]:
                continue
            key = (index + 1, name)
            if key in seen:
                continue
            seen.add(key)
            findings.append(Finding(index + 1, name, arm))
    findings.sort(key=lambda f: (f.line_no, f.pattern_class))
    return findings
