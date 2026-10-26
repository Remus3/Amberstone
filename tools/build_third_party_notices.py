"""Generate THIRD_PARTY_NOTICES for a packaged Amberstone build (PKG-8).

docs/PACKAGING_PLAN.md slice PKG-8, MUST-FIX M7 + M10. The notices describe
what a packaged build SHIPS, read from local metadata only:

- Python: the `requirements.txt` pins (environment markers evaluated for the
  packaged target: Windows, embedded CPython, `--python-version`) resolved
  against the bundle's site-packages `*.dist-info` (METADATA, licence files,
  RECORD). A dist installed there but not pinned ships unaudited, so it is
  listed AND reported.
- npm: the production (non-dev) entries of `rc-shell/package-lock.json`, with
  licence texts from the installed package dirs (`npm ci` output). A package
  that ships no licence file but declares MIT / ISC gets a generated
  attribution from the SPDX template (lazy-val, M10).
- Electron runtime: `node_modules/electron/dist` LICENSE, ffmpeg.dll and
  LICENSES.chromium.html (shipped verbatim beside the executable; Chromium
  products whose licence text names a copyleft licence are listed).
- CPython embeddable runtime (`--python-embed`): its LICENSE.txt.

It decides nothing about shipping. Every component is classified allowed /
copyleft / restricted / unknown; anything but allowed FAILS unless a recorded
ruling id covers it (`RULINGS` below or `--ruling GLOB=ID`). The M10 ruling
(Electron's LGPL ffmpeg.dll, opencv's ffmpeg DLL, certifi MPL-2.0) is
operator-gated, so `RULINGS` ships empty and those components are reported
loudly until the ruling is recorded.

Never fetches anything and never copies a third-party file into the tree: the
one write is `--out` (default `dist/THIRD_PARTY_NOTICES.txt`, gitignored build
output, never tracked). Output is deterministic 7-bit ASCII with LF endings.
A missing input source is a problem, not a skip (fail closed).

Usage:
    python tools/build_third_party_notices.py --site-packages <bundle site-packages>
        [--python-embed <python-embed dir>] [--electron-dist <electron dist>]
        [--node-root rc-shell] [--out dist/THIRD_PARTY_NOTICES.txt]
        [--ruling GLOB=ID ...] [--check]

Exit: 0 = no problem; 1 = problems (notices still written unless --check,
marked INCOMPLETE); 2 = usage error.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import html
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from email.parser import HeaderParser
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "dist" / "THIRD_PARTY_NOTICES.txt"
DEFAULT_REQUIREMENTS = ROOT / "requirements.txt"
DEFAULT_NODE_ROOT = ROOT / "rc-shell"

# Recorded ruling ids, {component-id glob: ruling id}. EMPTY ON PURPOSE: the M10
# ship ruling for the copyleft runtime payload is operator-gated
# (docs/PACKAGING_PLAN.md M10). Record it here, with the ruling id the
# adjudicator / operator gave, only once it exists.
RULINGS: Dict[str, str] = {}

RULING_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

ALLOWED = "allowed"
COPYLEFT = "copyleft"
RESTRICTED = "restricted"
UNKNOWN = "unknown"
_SEVERITY = {ALLOWED: 0, COPYLEFT: 1, UNKNOWN: 2, RESTRICTED: 3}

# Permissive SPDX ids (upper-cased). BSL-1.0 is Boost (permissive); BUSL is
# Business Source (restricted) - never confuse the two.
_ALLOWED_IDS = frozenset({
    "0BSD", "APACHE-2.0", "BLUEOAK-1.0.0", "BSD-2-CLAUSE", "BSD-3-CLAUSE",
    "BSD-3-CLAUSE-CLEAR", "BSL-1.0", "CC-BY-3.0", "CC-BY-4.0", "CC0-1.0",
    "HPND", "ISC", "LICENSEREF-BSD", "LICENSEREF-PUBLIC-DOMAIN", "MIT",
    "MIT-0", "MIT-CMU", "PSF-2.0", "PYTHON-2.0", "PYTHON-2.0.1", "UNICODE-3.0",
    "UNICODE-DFS-2016", "UNLICENSE", "X11", "ZLIB",
})
_COPYLEFT_PREFIXES = (
    "GPL", "LGPL", "AGPL", "MPL", "EPL", "CDDL", "EUPL", "OSL", "CPL",
    "CC-BY-SA", "LICENSEREF-COPYLEFT",
)
# Restricted = not open for redistribution as-is (BUSL is DO-NOT-VENDOR per
# CLAUDE.md; npm's UNLICENSED means "no licence granted", unlike Unlicense).
_RESTRICTED_PREFIXES = (
    "BUSL", "SSPL", "CC-BY-NC", "COMMONS-CLAUSE", "ELASTIC", "UNLICENSED",
    "LICENSEREF-PROPRIETARY",
)

# Free-text licence names seen in METADATA `License:` fields -> SPDX.
_ALIASES = {
    "mit": "MIT", "mit license": "MIT", "the mit license": "MIT",
    "expat": "MIT",
    "bsd": "LicenseRef-BSD", "bsd license": "LicenseRef-BSD",
    "new bsd": "BSD-3-Clause", "new bsd license": "BSD-3-Clause",
    "bsd 3-clause": "BSD-3-Clause", "3-clause bsd": "BSD-3-Clause",
    "bsd-3": "BSD-3-Clause", "modified bsd": "BSD-3-Clause",
    "bsd 2-clause": "BSD-2-Clause", "simplified bsd": "BSD-2-Clause",
    "apache 2.0": "Apache-2.0", "apache 2": "Apache-2.0",
    "apache license 2.0": "Apache-2.0", "apache license, version 2.0": "Apache-2.0",
    "apache license version 2.0": "Apache-2.0", "apache software license": "Apache-2.0",
    "apache": "Apache-2.0", "apache-2": "Apache-2.0",
    "psf": "PSF-2.0", "psf license": "PSF-2.0", "psfl": "PSF-2.0",
    "python software foundation license": "PSF-2.0",
    "isc": "ISC", "isc license": "ISC",
    "mpl 2.0": "MPL-2.0", "mozilla public license 2.0": "MPL-2.0",
    "public domain": "LicenseRef-Public-Domain",
    "historical permission notice and disclaimer": "HPND",
}

# Trove `License :: ...` leaf -> SPDX (exact first, then family substrings).
_CLASSIFIER_EXACT = {
    "MIT License": "MIT",
    "MIT No Attribution License (MIT-0)": "MIT-0",
    "BSD License": "LicenseRef-BSD",
    "Apache Software License": "Apache-2.0",
    "Python Software Foundation License": "PSF-2.0",
    "ISC License (ISCL)": "ISC",
    "Historical Permission Notice and Disclaimer (HPND)": "HPND",
    "The Unlicense (Unlicense)": "Unlicense",
    "zlib/libpng License": "Zlib",
    "Public Domain": "LicenseRef-Public-Domain",
    "Boost Software License 1.0 (BSL-1.0)": "BSL-1.0",
    "CC0 1.0 Universal (CC0 1.0) Public Domain Dedication": "CC0-1.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "Mozilla Public License 1.1 (MPL 1.1)": "MPL-1.1",
    "Other/Proprietary License": "LicenseRef-Proprietary",
}
_CLASSIFIER_FAMILIES = (
    ("GNU Affero General Public License", "AGPL"),
    ("GNU Lesser General Public License", "LGPL"),
    ("GNU Library or Lesser General Public License", "LGPL"),
    ("GNU General Public License", "GPL"),
    ("Mozilla Public License", "MPL"),
    ("Eclipse Public License", "EPL"),
    ("Common Development and Distribution License", "CDDL"),
    ("European Union Public Licence", "EUPL"),
)

# Keyword scan for a long licence TEXT (METADATA body-in-header, Chromium
# credits). Copyleft markers first; any hit marks the text copyleft.
_COPYLEFT_TEXT_MARKERS = (
    (re.compile(r"GNU\s+AFFERO\s+GENERAL\s+PUBLIC\s+LICEN[CS]E", re.I), "AGPL"),
    (re.compile(r"GNU\s+(?:LESSER|LIBRARY)\s+GENERAL\s+PUBLIC\s+LICEN[CS]E", re.I), "LGPL"),
    (re.compile(r"GNU\s+GENERAL\s+PUBLIC\s+LICEN[CS]E", re.I), "GPL"),
    (re.compile(r"\bLGPL", re.I), "LGPL"),
    (re.compile(r"(?<![A-Za-z])GPL", re.I), "GPL"),
    (re.compile(r"Mozilla\s+Public\s+License", re.I), "MPL"),
    (re.compile(r"Common\s+Development\s+and\s+Distribution\s+License", re.I), "CDDL"),
    (re.compile(r"Eclipse\s+Public\s+License", re.I), "EPL"),
)
_PERMISSIVE_TEXT_MARKERS = (
    (re.compile(r"Permission is hereby granted, free of charge", re.I), "MIT"),
    (re.compile(r"Apache License,?\s+Version 2\.0", re.I), "Apache-2.0"),
    (re.compile(r"Redistribution and use in source and binary forms", re.I), "LicenseRef-BSD"),
    (re.compile(r"Permission to use, copy, modify, and(?:/or)? distribute this software", re.I), "ISC"),
)

# Bundled native binaries that carry their own (copyleft) licence whatever
# the wrapping package declares. Matched on the lower-cased basename.
BINARY_FLAGS: Tuple[Tuple[str, str, str], ...] = (
    ("*ffmpeg*.dll", "LGPL-2.1-or-later", "FFmpeg runtime library"),
    ("avcodec*.dll", "LGPL-2.1-or-later", "FFmpeg libavcodec"),
    ("avformat*.dll", "LGPL-2.1-or-later", "FFmpeg libavformat"),
    ("avutil*.dll", "LGPL-2.1-or-later", "FFmpeg libavutil"),
    ("swscale*.dll", "LGPL-2.1-or-later", "FFmpeg libswscale"),
    ("swresample*.dll", "LGPL-2.1-or-later", "FFmpeg libswresample"),
)

_LICENCE_FILE_RE = re.compile(r"^(?:licen[cs]e|copying|notice)(?:[-._].*)?$", re.I)

MIT_TEMPLATE = """MIT License

Copyright (c) {holder}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

ISC_TEMPLATE = """ISC License

Copyright (c) {holder}

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
"""
_TEMPLATES = {"MIT": MIT_TEMPLATE, "ISC": ISC_TEMPLATE}


# --------------------------------------------------------------------------
# ASCII normalisation
# --------------------------------------------------------------------------

_ASCII_MAP = {
    0x00A9: "(c)", 0x00AE: "(R)", 0x2122: "(TM)", 0x00A0: " ", 0xFEFF: "",
    0x2018: "'", 0x2019: "'", 0x201A: "'", 0x201B: "'", 0x2032: "'",
    0x201C: '"', 0x201D: '"', 0x201E: '"', 0x2033: '"',
    0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-",
    0x2015: "-", 0x2212: "-", 0x2022: "*", 0x00B7: "*", 0x2026: "...",
    0x00DF: "ss", 0x00E6: "ae", 0x00C6: "AE", 0x00F8: "o", 0x00D8: "O",
    0x0142: "l", 0x0141: "L", 0x0111: "d", 0x0110: "D", 0x00F0: "d",
    0x00FE: "th", 0x00DE: "Th", 0x0153: "oe", 0x0152: "OE", 0x0131: "i",
    0x000C: "\n",
}


def asciify(text: str) -> str:
    """Deterministic 7-bit ASCII, LF only, no trailing blanks per line."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").translate(_ASCII_MAP)
    text = unicodedata.normalize("NFKD", text)
    out: List[str] = []
    for ch in text:
        code = ord(ch)
        if code < 128:
            if ch in "\n\t" or code >= 32:
                out.append(ch)
            continue
        if unicodedata.combining(ch):
            continue
        out.append(f"[U+{code:04X}]")
    lines = "".join(out).split("\n")
    return "\n".join(line.rstrip() for line in lines)


# --------------------------------------------------------------------------
# Licence expression classification
# --------------------------------------------------------------------------

_SPDX_TOKEN_RE = re.compile(r"\s*(\(|\)|[A-Za-z0-9][A-Za-z0-9.+:-]*)")


def _classify_id(token: str) -> str:
    ident = token.upper().rstrip("+")
    for suffix in ("-OR-LATER", "-ONLY"):
        if ident.endswith(suffix):
            ident = ident[: -len(suffix)]
    if ident in _ALLOWED_IDS or token.upper() in _ALLOWED_IDS:
        return ALLOWED
    if ident.startswith(_RESTRICTED_PREFIXES):
        return RESTRICTED
    if ident.startswith(_COPYLEFT_PREFIXES):
        return COPYLEFT
    return UNKNOWN


def classify_expression(expr: Optional[str]) -> str:
    """Classify an SPDX-style expression: AND = worst term, OR = best term."""
    if not expr or not expr.strip():
        return UNKNOWN
    tokens: List[str] = []
    pos = 0
    text = expr.strip()
    while pos < len(text):
        m = _SPDX_TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            return UNKNOWN
        tokens.append(m.group(1))
        pos = m.end()
        while pos < len(text) and text[pos].isspace():
            pos += 1
    state = {"i": 0}

    def peek() -> Optional[str]:
        return tokens[state["i"]] if state["i"] < len(tokens) else None

    def take() -> str:
        tok = tokens[state["i"]]
        state["i"] += 1
        return tok

    def parse_or() -> str:
        best = parse_and()
        while (peek() or "").upper() == "OR":
            take()
            other = parse_and()
            best = min(best, other, key=_SEVERITY.__getitem__)
        return best

    def parse_and() -> str:
        worst = parse_with()
        while (peek() or "").upper() == "AND":
            take()
            other = parse_with()
            worst = max(worst, other, key=_SEVERITY.__getitem__)
        return worst

    def parse_with() -> str:
        klass = parse_atom()
        if (peek() or "").upper() == "WITH":
            take()
            if peek() in (None, "(", ")"):
                raise ValueError("WITH needs an exception id")
            take()
        return klass

    def parse_atom() -> str:
        tok = peek()
        if tok is None:
            raise ValueError("unexpected end")
        if tok == "(":
            take()
            klass = parse_or()
            if peek() != ")":
                raise ValueError("unbalanced")
            take()
            return klass
        if tok == ")" or tok.upper() in ("AND", "OR", "WITH"):
            raise ValueError("unexpected operator")
        take()
        return _classify_id(tok)

    try:
        klass = parse_or()
    except (ValueError, IndexError):
        return UNKNOWN
    if state["i"] != len(tokens):
        return UNKNOWN
    return klass


def _expression_is_clean(expr: str) -> bool:
    """True when every licence id in `expr` is recognised (no UNKNOWN atom)."""
    for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9.+:-]*", expr):
        if tok.upper() in ("AND", "OR", "WITH"):
            continue
        if _classify_id(tok) == UNKNOWN:
            return False
    return True


def _scan_text(text: str) -> Tuple[Optional[str], Optional[str]]:
    """(expression, klass) from a licence TEXT, or (None, None)."""
    families = sorted({fam for rx, fam in _COPYLEFT_TEXT_MARKERS if rx.search(text)})
    if families:
        return "LicenseRef-Copyleft-Text-" + "-".join(families), COPYLEFT
    for rx, spdx in _PERMISSIVE_TEXT_MARKERS:
        if rx.search(text):
            return spdx, ALLOWED
    return None, None


def _alias(value: str) -> Optional[str]:
    key = " ".join(value.strip().lower().split())
    if key in _ALIASES:
        return _ALIASES[key]
    if "\n" not in value.strip() and len(value) <= 120 and _expression_is_clean(value):
        return value.strip()
    return None


def _classifier_licence(classifiers: Sequence[str]) -> Optional[str]:
    found: List[str] = []
    for raw in classifiers:
        parts = [p.strip() for p in raw.split("::")]
        if not parts or parts[0] != "License":
            continue
        leaf = parts[-1]
        if leaf == "OSI Approved" and len(parts) == 2:
            continue
        spdx = _CLASSIFIER_EXACT.get(leaf)
        if spdx is None:
            for needle, fam in _CLASSIFIER_FAMILIES:
                if needle in leaf:
                    spdx = fam
                    break
        if spdx is None:
            spdx = "LicenseRef-Classifier-Unmapped"
        if spdx not in found:
            found.append(spdx)
    if not found:
        return None
    return found[0] if len(found) == 1 else "(" + " OR ".join(found) + ")"


def licence_from_metadata(headers: Mapping[str, object]) -> Tuple[str, str]:
    """(expression, source) for one METADATA header set.

    Precedence: License-Expression (PEP 639) > a License field that is a
    known name or a clean SPDX expression > Trove classifiers > a keyword
    scan of a License field that holds licence text > UNKNOWN.
    """
    expr = str(headers.get("License-Expression") or "").strip()
    if expr:
        return expr, "License-Expression"
    lic = str(headers.get("License") or "").strip()
    if lic and lic.upper() != "UNKNOWN":
        aliased = _alias(lic)
        if aliased:
            return aliased, "License field"
    classifiers = headers.get("Classifier") or []
    if isinstance(classifiers, str):
        classifiers = [classifiers]
    from_cls = _classifier_licence(list(classifiers))  # type: ignore[arg-type]
    if from_cls:
        return from_cls, "classifiers"
    if lic and lic.upper() != "UNKNOWN":
        scanned, _klass = _scan_text(lic)
        if scanned:
            return scanned, "License field text scan"
    return "UNKNOWN", "none"


# --------------------------------------------------------------------------
# Requirements + environment markers
# --------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def target_env(python_version: str = "3.14") -> Dict[str, str]:
    parts = python_version.split(".")
    full = python_version if len(parts) >= 3 else ".".join((parts + ["0", "0"])[:3])
    return {
        "sys_platform": "win32", "platform_system": "Windows", "os_name": "nt",
        "platform_machine": "AMD64", "implementation_name": "cpython",
        "platform_python_implementation": "CPython",
        "python_version": ".".join(parts[:2]), "python_full_version": full,
        "implementation_version": full,
    }


_MARKER_TOKEN_RE = re.compile(
    r"\s*(\(|\)|===|==|!=|<=|>=|~=|<|>|not\s+in\b|in\b|and\b|or\b|'[^']*'|\"[^\"]*\"|[A-Za-z_][A-Za-z0-9_.]*)"
)
_VERSION_VARS = frozenset({"python_version", "python_full_version", "implementation_version"})


def _vtuple(value: str) -> Tuple[int, ...]:
    nums = []
    for part in value.split("."):
        m = re.match(r"\d+", part)
        nums.append(int(m.group(0)) if m else 0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def eval_marker(marker: str, env: Mapping[str, str]) -> bool:
    """Evaluate a PEP 508 marker against `env`. Unknown variables raise."""
    tokens: List[str] = []
    pos = 0
    while pos < len(marker):
        if marker[pos:].strip() == "":
            break
        m = _MARKER_TOKEN_RE.match(marker, pos)
        if not m:
            raise ValueError(f"bad marker: {marker!r}")
        tokens.append(re.sub(r"\s+", " ", m.group(1)))
        pos = m.end()
    state = {"i": 0}

    def peek() -> Optional[str]:
        return tokens[state["i"]] if state["i"] < len(tokens) else None

    def take() -> str:
        tok = tokens[state["i"]]
        state["i"] += 1
        return tok

    def value() -> Tuple[str, Optional[str]]:
        tok = take()
        if tok[0] in "'\"":
            return tok[1:-1], None
        if tok not in env:
            raise ValueError(f"unknown marker variable: {tok}")
        return env[tok], tok

    def compare() -> bool:
        if peek() == "(":
            take()
            result = parse_or()
            if take() != ")":
                raise ValueError("unbalanced marker")
            return result
        left, lvar = value()
        op = take()
        right, rvar = value()
        if op in ("in", "not in"):
            hit = left in right
            return hit if op == "in" else not hit
        if (lvar in _VERSION_VARS) or (rvar in _VERSION_VARS):
            a, b = _vtuple(left), _vtuple(right)
        else:
            a, b = left, right  # type: ignore[assignment]
        if op in ("==", "==="):
            return a == b
        if op == "!=":
            return a != b
        if op == "<":
            return a < b
        if op == "<=":
            return a <= b
        if op == ">":
            return a > b
        if op == ">=":
            return a >= b
        if op == "~=":
            return a >= b and a[: max(1, len(b) - 1)] == b[: max(1, len(b) - 1)]
        raise ValueError(f"unknown marker operator: {op}")

    def parse_and() -> bool:
        result = compare()
        while peek() == "and":
            take()
            rhs = compare()
            result = result and rhs
        return result

    def parse_or() -> bool:
        result = parse_and()
        while peek() == "or":
            take()
            rhs = parse_and()
            result = result or rhs
        return result

    result = parse_or()
    if state["i"] != len(tokens):
        raise ValueError(f"trailing marker tokens: {marker!r}")
    return result


_REQ_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*"
    r"(?P<spec>[=<>!~][^;]*)?\s*(?:;\s*(?P<marker>.+))?$"
)


@dataclass(frozen=True)
class Pin:
    name: str
    version: str
    marker: str


def parse_requirements(text: str) -> Tuple[List[Pin], List[str]]:
    """Pins and problems from a hashed requirements file (continuations joined)."""
    logical: List[str] = []
    buf = ""
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        logical.append(buf + line)
        buf = ""
    if buf:
        logical.append(buf)
    pins: List[Pin] = []
    problems: List[str] = []
    for line in logical:
        line = re.sub(r"(^|\s)#.*$", "", line).strip()
        line = re.split(r"\s--", " " + line, maxsplit=1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = _REQ_RE.match(line)
        spec = (m.group("spec") or "").strip() if m else ""
        if not m or not spec.startswith("==") or spec.startswith("==="):
            problems.append(f"requirement not pinned with ==: {line}")
            continue
        pins.append(Pin(m.group("name"), spec[2:].strip(), (m.group("marker") or "").strip()))
    return pins, problems


def select_pins(pins: Iterable[Pin], env: Mapping[str, str]) -> Tuple[Dict[str, Pin], List[str]]:
    selected: Dict[str, Pin] = {}
    problems: List[str] = []
    for pin in pins:
        try:
            if pin.marker and not eval_marker(pin.marker, env):
                continue
        except ValueError as exc:
            problems.append(f"py:{normalize_name(pin.name)} marker not evaluable ({exc})")
            continue
        key = normalize_name(pin.name)
        if key in selected:
            problems.append(f"py:{key} pinned twice for the target ({selected[key].version}, {pin.version})")
            continue
        selected[key] = pin
    return selected, problems


# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------

@dataclass
class Component:
    cid: str
    name: str
    version: str
    licence: str
    source: str
    texts: List[Tuple[str, str]] = field(default_factory=list)
    klass: Optional[str] = None
    note: str = ""
    details: List[str] = field(default_factory=list)


def _read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace")


def _licence_files(directory: Path) -> List[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        (p for p in directory.iterdir() if p.is_file() and _LICENCE_FILE_RE.match(p.name)),
        key=lambda p: p.name.lower(),
    )


def _binary_flag(basename: str) -> Optional[Tuple[str, str]]:
    low = basename.lower()
    for pattern, licence, label in BINARY_FLAGS:
        if fnmatch.fnmatchcase(low, pattern):
            return licence, label
    return None


def _dist_licence_texts(dist_info: Path, files: Sequence[str]) -> List[Tuple[str, str]]:
    chosen: Dict[str, Path] = {}
    for rel in files:
        rel = rel.strip()
        if not rel:
            continue
        for cand in (dist_info / "licenses" / rel, dist_info / rel, dist_info / Path(rel).name):
            if cand.is_file():
                chosen[rel] = cand
                break
    if not chosen:
        for cand in _licence_files(dist_info) + _licence_files(dist_info / "licenses"):
            chosen.setdefault(cand.name, cand)
    return [(label, _read_text(path)) for label, path in sorted(chosen.items())]


def _site_index(site: Path) -> Dict[str, List[Tuple[str, Path, Dict[str, object]]]]:
    index: Dict[str, List[Tuple[str, Path, Dict[str, object]]]] = {}
    for dist_info in sorted(site.glob("*.dist-info")):
        meta = dist_info / "METADATA"
        if not meta.is_file():
            continue
        msg = HeaderParser().parsestr(_read_text(meta))
        headers: Dict[str, object] = {
            "Name": msg.get("Name", ""), "Version": msg.get("Version", ""),
            "License": msg.get("License", ""), "License-Expression": msg.get("License-Expression", ""),
            "Classifier": msg.get_all("Classifier") or [],
            "License-File": msg.get_all("License-File") or [],
        }
        key = normalize_name(str(headers["Name"]))
        index.setdefault(key, []).append((str(headers["Version"]), dist_info, headers))
    return index


def collect_python(requirements: Path, site: Optional[Path], env: Mapping[str, str]) -> Tuple[List[Component], List[str]]:
    problems: List[str] = []
    if not requirements.is_file():
        return [], ["python: requirements file not found - python payload NOT AUDITED"]
    pins, parse_problems = parse_requirements(_read_text(requirements))
    problems.extend(parse_problems)
    selected, sel_problems = select_pins(pins, env)
    problems.extend(sel_problems)
    if site is None or not site.is_dir():
        problems.append("python: no site-packages given (--site-packages) - python payload NOT AUDITED")
        return [], problems
    index = _site_index(site)
    comps: List[Component] = []
    for key in sorted(set(selected) | set(index)):
        pin = selected.get(key)
        entries = index.get(key, [])
        if pin is None:
            for version, dist_info, headers in entries:
                comps.extend(_python_components(key, version, dist_info, headers, site))
                problems.append(f"py:{key} {version} is installed but not pinned in requirements.txt (would ship unaudited)")
            continue
        match = [e for e in entries if e[0] == pin.version]
        if not match:
            have = ", ".join(sorted(e[0] for e in entries)) or "nothing"
            problems.append(f"py:{key} pinned {pin.version} but site-packages has {have}")
            continue
        if len(entries) > 1:
            problems.append(f"py:{key} has {len(entries)} dist-info dirs in site-packages")
        version, dist_info, headers = match[0]
        comps.extend(_python_components(key, version, dist_info, headers, site))
    return comps, problems


def _python_components(key: str, version: str, dist_info: Path, headers: Dict[str, object], site: Path) -> List[Component]:
    expr, source = licence_from_metadata(headers)
    files = headers.get("License-File") or []
    texts = _dist_licence_texts(dist_info, list(files))  # type: ignore[arg-type]
    comps = [Component("py:" + key, key, version, expr, source, texts)]
    record = dist_info / "RECORD"
    if record.is_file():
        rows = sorted({line.split(",", 1)[0].strip() for line in _read_text(record).splitlines() if line.strip()})
        for rel in rows:
            flag = _binary_flag(Path(rel).name)
            if flag and (site / rel).is_file():
                licence, label = flag
                comps.append(Component(
                    "py:{}:{}".format(key, rel.replace("\\", "/")), Path(rel).name, version, licence,
                    f"bundled binary ({label}) inside {key}",
                    note="native binary shipped inside the wheel; strip it from the bundle or cover it by a ruling",
                ))
    return comps


# --------------------------------------------------------------------------
# npm lock
# --------------------------------------------------------------------------

def _semver(value: str) -> Tuple[Tuple[int, int, int], str]:
    core, _, pre = value.strip().lstrip("v=").partition("-")
    core = core.split("+", 1)[0]
    parts = [p for p in core.split(".") if p != ""]
    nums: List[int] = []
    for p in parts[:3]:
        nums.append(int(p) if p.isdigit() else 0)
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2]), pre


def _partial(value: str) -> int:
    core = value.strip().lstrip("v=").split("-", 1)[0]
    return len([p for p in core.split(".") if p not in ("", "x", "X", "*")])


def _cmp_ok(ver: Tuple[int, int, int], op: str, bound: Tuple[int, int, int]) -> bool:
    return {
        ">=": ver >= bound, ">": ver > bound, "<=": ver <= bound,
        "<": ver < bound, "=": ver == bound,
    }[op]


def satisfies(version: str, rng: str) -> bool:
    """npm semver range check: exact, =, ^, ~, comparators, `||`, `*`, x-ranges."""
    ver, pre = _semver(version)
    for alt in rng.split("||"):
        alt = alt.strip()
        if alt in ("", "*", "x", "latest"):
            if not pre:
                return True
            continue
        ok = True
        comps = re.findall(r"(\^|~|>=|<=|>|<|=)?\s*(v?[0-9xX*][0-9A-Za-z.+*-]*)", alt)
        if not comps:
            return False
        for op, val in comps:
            base, bpre = _semver(val)
            if pre and not (bpre and base == ver):
                ok = False
                break
            n = _partial(val)
            if op == "^":
                if base[0] > 0 or n == 1:
                    upper = (base[0] + 1, 0, 0)
                elif base[1] > 0 or n == 2:
                    upper = (0, base[1] + 1, 0)
                else:
                    upper = (0, 0, base[2] + 1)
                ok = ver >= base and ver < upper
            elif op == "~":
                upper = (base[0] + 1, 0, 0) if n == 1 else (base[0], base[1] + 1, 0)
                ok = ver >= base and ver < upper
            elif op in (">=", ">", "<=", "<"):
                ok = _cmp_ok(ver, op, base)
            else:
                if n == 3:
                    ok = ver == base and pre == bpre
                elif n == 2:
                    ok = ver[:2] == base[:2]
                elif n == 1:
                    ok = ver[0] == base[0]
                else:
                    ok = True
            if not ok:
                break
        if ok:
            return True
    return False


def _lock_name(key: str, entry: Mapping[str, object]) -> str:
    if entry.get("name"):
        return str(entry["name"])
    return key.rsplit("node_modules/", 1)[-1]


def _resolve(packages: Mapping[str, Mapping[str, object]], from_key: str, name: str) -> Optional[str]:
    base = from_key
    while True:
        cand = (base + "/node_modules/" + name) if base else ("node_modules/" + name)
        if cand in packages:
            return cand
        if not base:
            return None
        idx = base.rfind("/node_modules/")
        base = base[:idx] if idx >= 0 else ""


def lock_drift(package_json: Mapping[str, object], lock: Mapping[str, object]) -> List[str]:
    """What `npm ci` would refuse, plus range / override violations. [] = in sync."""
    problems: List[str] = []
    if lock.get("lockfileVersion") not in (2, 3):
        problems.append("lockfileVersion {!r} is not 2 or 3".format(lock.get("lockfileVersion")))
    packages = lock.get("packages")
    if not isinstance(packages, dict) or "" not in packages:
        return problems + ["lock has no packages[''] root entry"]
    root = packages[""]
    if lock.get("name") != package_json.get("name") or root.get("name") != package_json.get("name"):
        problems.append("lock name {!r} / {!r} != package.json name {!r}".format(lock.get("name"), root.get("name"), package_json.get("name")))
    for fld in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        want = package_json.get(fld) or {}
        have = root.get(fld) or {}
        if want != have:
            problems.append(f"{fld} differ: package.json {json.dumps(want, sort_keys=True)}, lock {json.dumps(have, sort_keys=True)}")
    for fld in ("dependencies", "devDependencies", "optionalDependencies"):
        for name, rng in sorted((package_json.get(fld) or {}).items()):  # type: ignore[union-attr]
            entry = packages.get("node_modules/" + name)
            if entry is None:
                if fld != "optionalDependencies":
                    problems.append(f"{fld} {name} has no node_modules/{name} lock entry")
                continue
            if not satisfies(str(entry.get("version", "")), str(rng)):
                problems.append("{} {}@{} does not satisfy package.json {!r}".format(fld, name, entry.get("version"), rng))
    overrides = package_json.get("overrides") or {}
    for parent, spec in sorted(overrides.items()):  # type: ignore[union-attr]
        if isinstance(spec, str):
            for key, entry in sorted(packages.items()):
                if key and _lock_name(key, entry) == parent and not satisfies(str(entry.get("version", "")), spec):
                    problems.append("override {} {!r} violated by {}@{}".format(parent, spec, key, entry.get("version")))
            continue
        if not isinstance(spec, dict):
            continue
        for child, rng in sorted(spec.items()):
            if not isinstance(rng, str) or child == ".":
                continue
            for key, entry in sorted(packages.items()):
                if not key or _lock_name(key, entry) != parent:
                    continue
                declared = {}
                for dfld in ("dependencies", "optionalDependencies", "peerDependencies"):
                    declared.update(entry.get(dfld) or {})  # type: ignore[arg-type]
                if child not in declared:
                    continue
                target = _resolve(packages, key, child)
                if target is None:
                    continue
                version = str(packages[target].get("version", ""))
                if not satisfies(version, rng):
                    problems.append(f"override {parent} > {child} {rng!r} violated: {target}@{version}")
    return problems


def npm_production_entries(lock: Mapping[str, object]) -> List[Tuple[str, str, Mapping[str, object]]]:
    """(cid, lock key, entry) for every non-dev package that ships, sorted."""
    out = []
    packages = lock.get("packages") or {}
    for key, entry in sorted(packages.items()):  # type: ignore[union-attr]
        if not key or entry.get("link") or entry.get("dev") or entry.get("devOptional"):
            continue
        name = _lock_name(key, entry)
        out.append(("npm:{}@{}".format(name, entry.get("version", "")), key, entry))
    return out


def _npm_licence(entry: Mapping[str, object], pkg_json: Optional[Mapping[str, object]]) -> str:
    lic = entry.get("license")
    if not lic and pkg_json:
        lic = pkg_json.get("license")
        if not lic and isinstance(pkg_json.get("licenses"), list):
            names = [str(x.get("type", "")) if isinstance(x, dict) else str(x) for x in pkg_json["licenses"]]  # type: ignore[union-attr]
            lic = " OR ".join(n for n in names if n)
    if isinstance(lic, dict):
        lic = lic.get("type")
    return str(lic or "UNKNOWN")


def _author(pkg_json: Mapping[str, object]) -> str:
    author = pkg_json.get("author")
    if isinstance(author, dict):
        author = author.get("name")
    if author:
        return str(author)
    return "the {} authors".format(pkg_json.get("name", "package"))


def collect_npm(lock_path: Path, package_json_path: Path, node_root: Optional[Path]) -> Tuple[List[Component], List[str], Optional[dict]]:
    problems: List[str] = []
    if not lock_path.is_file():
        return [], ["npm: lock file not found - npm payload NOT AUDITED"], None
    lock = json.loads(_read_text(lock_path))
    if package_json_path.is_file():
        drift = lock_drift(json.loads(_read_text(package_json_path)), lock)
        problems.extend("npm lock drift: " + d for d in drift)
    else:
        problems.append("npm: package.json not found - lock agreement NOT CHECKED")
    installed = node_root is not None and (node_root / "node_modules").is_dir()
    if not installed:
        problems.append("npm: node_modules not installed (run `npm ci`) - npm licence texts NOT AUDITED")
    by_id: Dict[str, Component] = {}
    for cid, key, entry in npm_production_entries(lock):
        pkg_dir = node_root / key if node_root is not None else None
        pkg_json = None
        if installed and pkg_dir is not None and (pkg_dir / "package.json").is_file():
            pkg_json = json.loads(_read_text(pkg_dir / "package.json"))
        licence = _npm_licence(entry, pkg_json)
        name = _lock_name(key, entry)
        comp = by_id.get(cid)
        if comp is None:
            comp = Component(cid, name, str(entry.get("version", "")), licence, "lock license field", note=key)
            by_id[cid] = comp
        else:
            comp.note = ", ".join(sorted(set(comp.note.split(", ")) | {key}))
            continue
        if not installed:
            continue
        if pkg_json is None:
            if entry.get("optional"):
                del by_id[cid]  # optional and not installed for this platform: it does not ship
                continue
            problems.append(f"{cid} is in the lock but not installed at {key}")
            continue
        files = _licence_files(pkg_dir)  # type: ignore[arg-type]
        if files:
            comp.texts = [(p.name, _read_text(p)) for p in files]
            continue
        template = _TEMPLATES.get(licence.strip().strip("()").upper())
        if template is not None:
            comp.texts = [(f"generated from the SPDX {licence} template (package ships no licence file)",
                           template.format(holder=_author(pkg_json)))]
        else:
            problems.append(f"{cid} ships no licence file and {licence} has no generator template")
    return sorted(by_id.values(), key=lambda c: c.cid), problems, lock


# --------------------------------------------------------------------------
# Electron runtime + CPython embed
# --------------------------------------------------------------------------

def parse_chromium_credits(text: str) -> List[Tuple[str, str]]:
    """(title, licence text) per product in LICENSES.chromium.html."""
    out: List[Tuple[str, str]] = []
    for chunk in text.split('<div class="product">')[1:]:
        tm = re.search(r'<span class="title">(.*?)</span>', chunk, re.S)
        lm = re.search(r'<div class="license">\s*<pre>(.*?)</pre>', chunk, re.S)
        if not tm:
            continue
        title = html.unescape(re.sub(r"<[^>]+>", "", tm.group(1))).strip()
        out.append((title, html.unescape(lm.group(1)) if lm else ""))
    return out


def collect_electron(dist: Optional[Path], lock: Optional[Mapping[str, object]]) -> Tuple[List[Component], List[str], int]:
    problems: List[str] = []
    if dist is None or not dist.is_dir():
        return [], ["electron: runtime dist not found (--electron-dist) - electron payload NOT AUDITED"], 0
    version_file = dist / "version"
    version = _read_text(version_file).strip() if version_file.is_file() else ""
    lock_version = ""
    if lock:
        entry = (lock.get("packages") or {}).get("node_modules/electron") or {}  # type: ignore[union-attr]
        lock_version = str(entry.get("version", ""))
        if version and lock_version and version != lock_version:
            problems.append(f"electron: runtime dist is {version} but the lock pins {lock_version}")
    lic = dist / "LICENSE"
    comps: List[Component] = []
    electron = Component("electron-runtime:electron", "electron", version or lock_version, "MIT", "electron dist LICENSE")
    if lic.is_file():
        electron.texts = [("LICENSE", _read_text(lic))]
    else:
        problems.append("electron: dist has no LICENSE file")
    comps.append(electron)
    for child in sorted(dist.iterdir(), key=lambda p: p.name.lower()):
        flag = _binary_flag(child.name) if child.is_file() else None
        if flag:
            comps.append(Component(
                "electron-runtime:" + child.name, child.name, version, flag[0],
                f"bundled binary ({flag[1]}) in the Electron runtime",
                note="dynamically linked, shipped unmodified by Electron; source and licence via Chromium credits",
            ))
    credits = dist / "LICENSES.chromium.html"
    count = 0
    if credits.is_file():
        products = parse_chromium_credits(_read_text(credits))
        count = len(products)
        if not products:
            problems.append("electron: LICENSES.chromium.html lists no product")
        flagged: List[str] = []
        families: set = set()
        for title, text in products:
            expr, klass = _scan_text(text)
            if klass != COPYLEFT or not expr:
                continue
            fams = expr[len("LicenseRef-Copyleft-Text-"):].split("-")
            families.update(fams)
            flagged.append(f"{asciify(title).strip()} ({', '.join(fams)})")
        if flagged:
            # One component for the whole credits file: the ruling is about
            # shipping Electron's runtime, not about each Chromium product.
            comps.append(Component(
                "electron-runtime:chromium-credits", "Chromium", version or lock_version,
                "LicenseRef-Copyleft-Text-" + "-".join(sorted(families)), "Chromium credits keyword scan",
                klass=COPYLEFT,
                note=(f"{len(flagged)} of {count} Chromium products name a copyleft licence in their credits "
                      "text (keyword scan; many are dual-licensed); every text ships verbatim in "
                      "LICENSES.chromium.html"),
                details=sorted(flagged, key=str.lower),
            ))
    else:
        problems.append("electron: dist has no LICENSES.chromium.html")
    return comps, problems, count


def collect_cpython(embed: Optional[Path]) -> Tuple[List[Component], List[str]]:
    if embed is None or not embed.is_dir():
        return [], ["cpython: embedded runtime not given (--python-embed) - CPython payload NOT AUDITED"]
    version = ""
    for dll in sorted(embed.glob("python3*.dll")):
        m = re.match(r"python3(\d+)\.dll$", dll.name, re.I)
        if m:
            version = "3." + m.group(1)
    comp = Component("cpython:python", "CPython", version, "PSF-2.0", "CPython LICENSE.txt")
    lic = embed / "LICENSE.txt"
    if not lic.is_file():
        return [comp], ["cpython: embedded runtime has no LICENSE.txt"]
    comp.texts = [("LICENSE.txt", _read_text(lic))]
    return [comp], []


# --------------------------------------------------------------------------
# Evaluation + rendering
# --------------------------------------------------------------------------

def ruling_for(cid: str, rulings: Mapping[str, str]) -> Optional[str]:
    for pattern in sorted(rulings):
        if fnmatch.fnmatchcase(cid, pattern):
            return rulings[pattern]
    return None


def evaluate(comps: Sequence[Component], rulings: Mapping[str, str]) -> Tuple[List[Tuple[Component, str, Optional[str]]], List[str]]:
    rows = []
    problems = []
    for comp in sorted(comps, key=lambda c: c.cid):
        klass = comp.klass or classify_expression(comp.licence)
        ruling = ruling_for(comp.cid, rulings) if klass != ALLOWED else None
        if klass != ALLOWED and ruling is None:
            problems.append(f"{klass.upper()} WITHOUT RULING: {_label(comp)} ({comp.licence})"
                            " - operator ruling required (PACKAGING_PLAN M10)")
        rows.append((comp, klass, ruling))
    return rows, problems


def _label(comp: Component) -> str:
    if not comp.version or comp.cid.endswith("@" + comp.version):
        return comp.cid
    return f"{comp.cid} {comp.version}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"


def render(rows, problems: Sequence[str], sources: Sequence[str], chromium_count: int) -> str:
    rule = "=" * 72
    out: List[str] = [
        "THIRD-PARTY NOTICES - Amberstone packaged build",
        rule,
        "",
        "Generated by tools/build_third_party_notices.py from local package",
        "metadata only (no network). Regenerate for every build; never edit.",
        "",
        "Sources:",
    ]
    out.extend("  " + s for s in sources)
    out.append("")
    if problems:
        out.append(f"STATUS: INCOMPLETE - {len(problems)} problem(s); NOT FOR DISTRIBUTION")
        out.append("")
        out.append("Problems")
        out.append("-" * 8)
        out.extend("- " + p for p in problems)
    else:
        out.append("STATUS: COMPLETE")
    out.append("")
    flagged = [r for r in rows if r[1] != ALLOWED]
    out.append("Copyleft / restricted / unknown components")
    out.append("-" * 42)
    if not flagged:
        out.append("(none)")
    for comp, klass, ruling in flagged:
        verdict = ("ruling: " + ruling) if ruling else "ruling: PENDING (operator-gated, PACKAGING_PLAN M10)"
        out.append(f"- {_label(comp)} | {comp.licence} | {klass} | {verdict}")
        if comp.note:
            out.append("    note: " + comp.note)
        out.extend("    - " + d for d in comp.details)
    out.append("")
    out.append("Component index")
    out.append("-" * 15)
    for comp, klass, ruling in rows:
        out.append(f"- {_label(comp)} | {comp.licence} | {klass} ({comp.source})")
    out.append("")
    if chromium_count:
        out.append(f"Chromium: {chromium_count} third-party products are credited in LICENSES.chromium.html,")
        out.append("which ships verbatim beside the Electron executable; the products whose")
        out.append("licence text names a copyleft licence are listed above under")
        out.append("electron-runtime:chromium-credits.")
        out.append("")
    out.append("Licence texts")
    out.append("-" * 13)
    for comp, _klass, _ruling in rows:
        if not comp.texts:
            continue
        out.append("")
        out.append(rule)
        out.append(_label(comp))
        out.append(f"Licence: {comp.licence} ({comp.source})")
        for label, text in comp.texts:
            out.append("-" * 72)
            out.append(f"[{label}]")
            out.append(text.strip("\n"))
    out.append("")
    return asciify("\n".join(out))


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _parse_rulings(values: Sequence[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw in values:
        glob, sep, rid = raw.partition("=")
        if not sep or not glob.strip() or not RULING_ID_RE.match(rid.strip()):
            raise ValueError(f"--ruling wants GLOB=ID, got {raw!r}")
        out[glob.strip()] = rid.strip()
    return out


def build(args: argparse.Namespace) -> Tuple[str, List[str], List[Tuple[Component, str, Optional[str]]]]:
    rulings = dict(RULINGS)
    rulings.update(_parse_rulings(args.ruling or []))
    env = target_env(args.python_version)
    node_root = Path(args.node_root)
    lock_path = Path(args.lock) if args.lock else node_root / "package-lock.json"
    pkg_path = Path(args.package_json) if args.package_json else node_root / "package.json"
    electron_dist = Path(args.electron_dist) if args.electron_dist else node_root / "node_modules" / "electron" / "dist"
    site = Path(args.site_packages) if args.site_packages else None
    embed = Path(args.python_embed) if args.python_embed else None
    req = Path(args.requirements)

    py, p_py = collect_python(req, site, env)
    npm, p_npm, lock = collect_npm(lock_path, pkg_path, node_root)
    ele, p_ele, chromium_count = collect_electron(electron_dist, lock)
    cpy, p_cpy = collect_cpython(embed)
    rows, p_eval = evaluate(py + npm + ele + cpy, rulings)
    problems = sorted(set(p_py + p_npm + p_ele + p_cpy + p_eval))
    sources = [
        f"requirements.txt sha256 {_sha256(req)}",
        f"rc-shell/package-lock.json sha256 {_sha256(lock_path)}",
        "python target: sys_platform={} python={}".format(env["sys_platform"], env["python_full_version"]),
        "python site-packages: " + (f"{len(py)} components" if site else "NOT AUDITED"),
        f"npm production packages: {len(npm)}",
        "electron runtime: " + (ele[0].version if ele else "NOT AUDITED"),
        "cpython runtime: " + ((cpy[0].version or "present") if cpy else "NOT AUDITED"),
        "recorded rulings: " + (", ".join(f"{k}={v}" for k, v in sorted(rulings.items())) or "none"),
    ]
    return render(rows, problems, sources, chromium_count), problems, rows


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--requirements", default=str(DEFAULT_REQUIREMENTS))
    ap.add_argument("--site-packages", help="the BUNDLE's site-packages (pip --target output)")
    ap.add_argument("--python-embed", help="the bundle's CPython embeddable runtime dir")
    ap.add_argument("--python-version", default="3.14", help="target CPython for markers (default 3.14)")
    ap.add_argument("--node-root", default=str(DEFAULT_NODE_ROOT), help="dir holding package.json + node_modules")
    ap.add_argument("--lock", help="default <node-root>/package-lock.json")
    ap.add_argument("--package-json", help="default <node-root>/package.json")
    ap.add_argument("--electron-dist", help="default <node-root>/node_modules/electron/dist")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="notices file (build output, never tracked)")
    ap.add_argument("--ruling", action="append", metavar="GLOB=ID", help="recorded ruling id for matching components")
    ap.add_argument("--check", action="store_true", help="report only; write nothing")
    args = ap.parse_args(argv)
    try:
        text, problems, rows = build(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for p in problems:
        print(("LOUD " if "WITHOUT RULING" in p else "") + "PROBLEM: " + asciify(p), file=sys.stderr)
    counts: Dict[str, int] = {}
    for _comp, klass, _ruling in rows:
        counts[klass] = counts.get(klass, 0) + 1
    by_class = ", ".join(f"{k} {counts[k]}" for k in sorted(counts)) or "none"
    summary = f"third-party notices: {len(rows)} components ({by_class}), {len(problems)} problem(s)"
    if not args.check:
        _write_atomic(Path(args.out), text.encode("ascii"))
        summary += " -> " + Path(args.out).name
    print(summary)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
