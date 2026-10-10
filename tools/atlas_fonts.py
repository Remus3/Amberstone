"""OFL-1.1 audit of the fonts ``atlas.html`` inlines (stdlib only).

Why this exists
---------------
atlas.html inlines Orbitron and Rajdhani as ``data:`` URIs. Both are under the
SIL Open Font License 1.1, and Orbitron declares the Reserved Font Name
"Orbitron": a subset (a Modified Version) may not keep that name (OFL
condition 3). Slice W-L (cf72989eb, 2026-10-09) fixed the page by embedding
the UNMODIFIED upstream Orbitron in a WOFF 1.0 wrapper and carrying every face
as WOFF 1.0, so the standard library can read each face's name table.

This module is that font codec and Reserved Font Name audit, copied verbatim
from the retired generator ``tools/atlas_build.py`` when the operator reverted
the atlas to the hand-built pre-2026-10-07 page (chat order 2026-10-10). The
page is no longer generated; only the font compliance check survives.
``tests/test_atlas_fonts.py`` is the gate - nothing else imports this file.

Usage
-----
    python -m pytest tests/test_atlas_fonts.py -q    # the gate, from the repo root

``audit_page(page_text)`` returns the opened faces or raises ``BuildError``.
"""
from __future__ import annotations

import base64
import hashlib
import re
import struct
import zlib
from typing import Any, NamedTuple


class BuildError(RuntimeError):
    """The audit refuses rather than pass a face it cannot stand behind."""


# --------------------------------------------------------------------------
# fonts: the inlined @font-face faces (SIL Open Font License 1.1)
# --------------------------------------------------------------------------
#
# The page inlines its web fonts as data: URIs. Every face is carried as WOFF
# 1.0 (zlib per table), the one compressed font container the standard
# library can open, so this build and its tests read each face's name table
# without fontTools or brotli. A WOFF2 face is refused, never guessed at.
#
# A face already in WOFF form is validated and passed through byte for byte,
# so a re-run is identical whatever zlib the interpreter links. A raw
# TrueType / OpenType face is wrapped once, "WOFF compression only" in the
# sense of OFL FAQ 2.2.1: table data, table checksums and the physical table
# order are kept, and there is no WOFF metadata or private block, so
# ``to_sfnt`` rebuilds the original font file byte for byte.
#
# Reserved Font Names (OFL condition 3): a face whose family or PostScript
# names carry an RFN its own name table declares is accepted only when the
# sfnt it rebuilds to is a pinned, unmodified upstream file
# (UNMODIFIED_RFN_FONTS). A subset or any other Modified Version that kept an
# RFN is refused. Adjudicated 2026-10-09 (slice W-L): embed the unmodified
# upstream Orbitron rather than rename the Google subset.

_SFNT_FLAVORS = (0x00010000, 0x4F54544F, 0x74727565)  # TrueType, 'OTTO', 'true'
_WOFF_SIG = 0x774F4646   # 'wOFF'
_WOFF2_SIG = 0x774F4632  # 'wOF2'
_WOFF_HEADER = struct.Struct(">LLLHHLHHLLLLL")  # 44 bytes
_WOFF_ENTRY = struct.Struct(">4sLLLL")          # 20 bytes per table
_SFNT_ENTRY = struct.Struct(">4sLLL")           # 16 bytes per table
FONT_MIME = "font/woff"
FONT_FORMAT = "woff"

# sha256 of the rebuilt sfnt -> where that exact file is published upstream.
UNMODIFIED_RFN_FONTS: dict[str, str] = {
    "f42db2dd16e642258e35782916eceb1dcdbea06fb958d77ad71dc5963587e8fd":
        "Orbitron[wght].ttf v2.001, 38576 bytes, google/fonts "
        "ofl/orbitron at abf71245949027c279caff7c2cb988c97e7d0b11",
}


class Sfnt(NamedTuple):
    """An OpenType font: flavor word, tables, directory checksums, data order.

    A NamedTuple, not a dataclass: the tests load this file by path without
    registering it in sys.modules, which a dataclass with postponed
    annotations cannot survive."""
    flavor: int
    tables: dict[str, bytes]
    checksums: dict[str, int]
    order: tuple[str, ...]


def _pad4(n: int) -> int:
    return (n + 3) & ~3


def table_checksum(data: bytes, tag: str = "") -> int:
    """OpenType table checksum; ``head`` is summed with checkSumAdjustment zeroed."""
    if tag == "head" and len(data) >= 12:
        data = data[:8] + b"\0\0\0\0" + data[12:]
    data += b"\0" * (_pad4(len(data)) - len(data))
    return sum(struct.unpack(f">{len(data) // 4}L", data)) & 0xFFFFFFFF


def _read_sfnt(data: bytes) -> Sfnt:
    flavor, num = struct.unpack_from(">LH", data)
    if len(data) < 12 + _SFNT_ENTRY.size * num:
        raise BuildError("sfnt table directory is truncated")
    tables: dict[str, bytes] = {}
    sums: dict[str, int] = {}
    offsets: dict[str, int] = {}
    for i in range(num):
        tag_b, csum, off, length = _SFNT_ENTRY.unpack_from(data, 12 + _SFNT_ENTRY.size * i)
        tag = tag_b.decode("latin-1")
        if off + length > len(data):
            raise BuildError(f"sfnt table {tag!r} runs past the end of the font")
        tables[tag] = data[off:off + length]
        sums[tag] = csum
        offsets[tag] = off
    return Sfnt(flavor, tables, sums, tuple(sorted(tables, key=lambda t: (offsets[t], t))))


def to_sfnt(font: Sfnt) -> bytes:
    """The TrueType / OpenType file a WOFF decoder rebuilds from ``font``."""
    n = len(font.tables)
    power = 1 << (n.bit_length() - 1) if n else 0
    search = power * 16
    header = struct.pack(">LHHHH", font.flavor, n, search,
                         power.bit_length() - 1 if n else 0, n * 16 - search)
    offset = 12 + _SFNT_ENTRY.size * n
    where: dict[str, int] = {}
    body: list[bytes] = []
    for tag in font.order:
        data = font.tables[tag]
        where[tag] = offset
        body.append(data + b"\0" * (_pad4(len(data)) - len(data)))
        offset += _pad4(len(data))
    entries = [_SFNT_ENTRY.pack(tag.encode("latin-1"), font.checksums[tag], where[tag],
                                len(font.tables[tag])) for tag in sorted(font.tables)]
    return header + b"".join(entries) + b"".join(body)


def _read_woff(data: bytes) -> Sfnt:
    if len(data) < _WOFF_HEADER.size:
        raise BuildError("WOFF header is truncated")
    (_sig, flavor, length, num, reserved, total_sfnt, _major, _minor,
     meta_off, meta_len, meta_orig, priv_off, priv_len) = _WOFF_HEADER.unpack_from(data)
    if length != len(data):
        raise BuildError("WOFF length field does not match the data")
    if reserved:
        raise BuildError("WOFF reserved field is not zero")
    if meta_off or meta_len or meta_orig or priv_off or priv_len:
        raise BuildError("WOFF metadata and private blocks are not carried by this page")
    if len(data) < _WOFF_HEADER.size + _WOFF_ENTRY.size * num:
        raise BuildError("WOFF table directory is truncated")
    tables: dict[str, bytes] = {}
    sums: dict[str, int] = {}
    offsets: dict[str, int] = {}
    expect_total = 12 + 16 * num
    for i in range(num):
        tag_b, off, comp, orig, csum = _WOFF_ENTRY.unpack_from(
            data, _WOFF_HEADER.size + _WOFF_ENTRY.size * i)
        tag = tag_b.decode("latin-1")
        if off % 4 or off + comp > len(data) or comp > orig:
            raise BuildError(f"WOFF table {tag!r} has a bad offset or length")
        blob = data[off:off + comp]
        if comp < orig:
            try:
                blob = zlib.decompress(blob)
            except zlib.error as exc:
                raise BuildError(f"WOFF table {tag!r} does not inflate: {exc}") from exc
        if len(blob) != orig:
            raise BuildError(f"WOFF table {tag!r} inflates to the wrong length")
        if csum not in (table_checksum(blob, tag), table_checksum(blob)):
            raise BuildError(f"WOFF table {tag!r} fails its checksum")
        tables[tag] = blob
        sums[tag] = csum
        offsets[tag] = off
        expect_total += _pad4(orig)
    if total_sfnt != expect_total:
        raise BuildError("WOFF totalSfntSize does not match its tables")
    return Sfnt(flavor, tables, sums, tuple(sorted(tables, key=lambda t: (offsets[t], t))))


def read_font(data: bytes) -> Sfnt:
    """Open a raw TrueType / OpenType font or a WOFF 1.0 wrapper; refuse WOFF2."""
    if len(data) < 12:
        raise BuildError("font data is truncated")
    sig = struct.unpack_from(">L", data)[0]
    if sig == _WOFF_SIG:
        return _read_woff(data)
    if sig in _SFNT_FLAVORS:
        return _read_sfnt(data)
    if sig == _WOFF2_SIG:
        raise BuildError(
            "a WOFF2 face cannot be audited by the standard library; inline it as "
            "TTF (fontTools: f = TTFont(path); f.flavor = None; f.save(out)) and re-run")
    raise BuildError(f"unknown font signature 0x{sig:08x}")


def encode_woff(font: Sfnt) -> bytes:
    """WOFF 1.0 of ``font``: directory in tag order, data in the font's own
    physical order, original checksums, zlib per table where it is smaller,
    no metadata or private block."""
    n = len(font.tables)
    head = font.tables.get("head", b"")
    major, minor = struct.unpack_from(">HH", head, 4) if len(head) >= 8 else (0, 0)
    offset = _WOFF_HEADER.size + _WOFF_ENTRY.size * n
    total_sfnt = 12 + 16 * n
    where: dict[str, tuple[int, int]] = {}
    blobs: list[bytes] = []
    for tag in font.order:
        raw = font.tables[tag]
        packed = zlib.compress(raw, 9)
        blob = packed if len(packed) < len(raw) else raw
        where[tag] = (offset, len(blob))
        blob += b"\0" * (_pad4(len(blob)) - len(blob))
        blobs.append(blob)
        offset += len(blob)
        total_sfnt += _pad4(len(raw))
    entries = [_WOFF_ENTRY.pack(tag.encode("latin-1"), where[tag][0], where[tag][1],
                                len(font.tables[tag]), font.checksums[tag])
               for tag in sorted(font.tables)]
    header = _WOFF_HEADER.pack(_WOFF_SIG, font.flavor, offset, n, 0, total_sfnt,
                               major, minor, 0, 0, 0, 0, 0)
    return header + b"".join(entries) + b"".join(blobs)


def sfnt_sha256(font: Sfnt) -> str:
    return hashlib.sha256(to_sfnt(font)).hexdigest()


def name_records(font: Sfnt) -> list[tuple[int, int, int, int, str]]:
    """(platform, encoding, language, nameID, text) for every name record."""
    data = font.tables.get("name")
    if not data or len(data) < 6:
        return []
    _fmt, count, str_off = struct.unpack_from(">HHH", data)
    out = []
    for i in range(count):
        if 6 + 12 * (i + 1) > len(data):
            raise BuildError("name table record array is truncated")
        pid, eid, lid, nid, length, off = struct.unpack_from(">6H", data, 6 + 12 * i)
        raw = data[str_off + off:str_off + off + length]
        codec = "utf-16-be" if pid in (0, 3) else "latin-1"
        out.append((pid, eid, lid, nid, raw.decode(codec, errors="replace")))
    return out


def name_text(font: Sfnt, name_id: int) -> str:
    """The Windows English (else first) string for ``name_id``; "" if absent."""
    recs = [r for r in name_records(font) if r[3] == name_id]
    recs.sort(key=lambda r: (r[0] != 3, r[2] != 0x409, r[:3]))
    return recs[0][4] if recs else ""


# nameIDs that present the font to a user or a font menu: family (1), unique
# id (3), full name (4), PostScript name (6), typographic family and
# subfamily (16, 17), compatible full (18), WWS family and subfamily (21, 22),
# variations PostScript prefix (25). fvar instance PostScript names are added
# per font.
FAMILY_NAME_IDS = frozenset({1, 3, 4, 6, 16, 17, 18, 21, 22, 25})
# Curly quotes are built with chr() to keep this source 7-bit ASCII.
_LQ, _RQ, _LSQ, _RSQ = chr(0x201C), chr(0x201D), chr(0x2018), chr(0x2019)
_QUOTED = re.compile(
    rf"\"([^\"]+)\"|'([^']+)'|{_LQ}([^{_RQ}]+){_RQ}|{_LSQ}([^{_RSQ}]+){_RSQ}")
_QUOTE_CHARS = "\"'" + _LQ + _RQ + _LSQ + _RSQ
_RFN_CLAUSE = re.compile(
    r"Reserved\s+Font\s+Names?\s*:?\s*"
    rf"((?:(?:{_QUOTED.pattern})(?:\s*(?:,|and|&)\s*)?)+|[^.,;{_QUOTE_CHARS}]+)", re.I)

# RFNs known from the upstream OFL.txt headers of the fonts this page has
# carried. A face is checked against these as well as against what its own
# name table declares, so a copy whose RFN clause was edited out of nameID 0
# is still caught.
KNOWN_RFNS: tuple[str, ...] = ("Orbitron",)


def _fvar_ps_name_ids(font: Sfnt) -> set[int]:
    data = font.tables.get("fvar")
    if not data or len(data) < 16:
        return set()
    (_maj, _min, axes_off, _res, axis_count, axis_size,
     inst_count, inst_size) = struct.unpack_from(">8H", data)
    if inst_size < 6 + 4 * axis_count:
        return set()
    base = axes_off + axis_count * axis_size
    out = set()
    for i in range(inst_count):
        at = base + i * inst_size + 4 + 4 * axis_count
        if at + 2 > len(data):
            raise BuildError("fvar instance array is truncated")
        ps_id = struct.unpack_from(">H", data, at)[0]
        if ps_id != 0xFFFF:
            out.add(ps_id)
    return out


def declared_rfns(font: Sfnt) -> list[str]:
    """Reserved Font Names declared in the copyright (0) or licence (13) strings."""
    found: list[str] = []
    for _p, _e, _l, nid, text in name_records(font):
        if nid not in (0, 13):
            continue
        for m in _RFN_CLAUSE.finditer(text):
            clause = m.group(1)
            quoted = [next(g for g in q.groups() if g) for q in _QUOTED.finditer(clause)]
            for name in quoted or [clause]:
                name = name.strip().strip(_QUOTE_CHARS).strip()
                if name and name not in found:
                    found.append(name)
    return found


def family_names(font: Sfnt) -> list[tuple[int, str]]:
    """Sorted distinct (nameID, text) pairs that name the family to a user."""
    ids = FAMILY_NAME_IDS | _fvar_ps_name_ids(font)
    return sorted({(r[3], r[4]) for r in name_records(font) if r[3] in ids})


def rfn_family_hits(font: Sfnt) -> list[tuple[int, str, str]]:
    """(nameID, text, RFN) for every family name that carries an RFN the
    face declares or one listed in KNOWN_RFNS."""
    hits = []
    rfns = declared_rfns(font)
    rfns += [r for r in KNOWN_RFNS if r not in rfns]
    for rfn in rfns:
        forms = {rfn.lower(), rfn.replace(" ", "").lower()}
        for nid, text in family_names(font):
            if any(f in text.lower() for f in forms):
                hits.append((nid, text, rfn))
    return hits


_FONT_FACE = re.compile(r"@font-face\s*\{[^{}]*\}")
_FACE_SRC = re.compile(
    r"url\(data:([\w.+/-]+);base64,([A-Za-z0-9+/=]+)\)(?:\s*format\(['\"]?[\w-]+['\"]?\))?")
_FACE_FAMILY = re.compile(r"font-family\s*:\s*(['\"]?)([^;'\"]+?)\1\s*;")
_FACE_WEIGHT = re.compile(r"font-weight\s*:\s*([^;]+?)\s*;")


def _b64decode(text: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)
    except ValueError as exc:
        raise BuildError(f"an @font-face data: URI is not valid base64: {exc}") from exc


def embedded_faces(page: str) -> list[dict[str, Any]]:
    """Every @font-face with a data: source: CSS family, weight, mime, bytes."""
    out = []
    for block in _FONT_FACE.findall(page):
        src = _FACE_SRC.search(block)
        if src is None:
            continue
        fam = _FACE_FAMILY.search(block)
        weight = _FACE_WEIGHT.search(block)
        out.append({
            "family": fam.group(2).strip() if fam else "",
            "weight": weight.group(1) if weight else "",
            "mime": src.group(1),
            "data": _b64decode(src.group(2)),
        })
    return out


def check_reserved_names(font: Sfnt, label: str) -> None:
    """Refuse a Modified Version that still presents a declared RFN."""
    hits = rfn_family_hits(font)
    if hits and sfnt_sha256(font) not in UNMODIFIED_RFN_FONTS:
        nid, text, rfn = hits[0]
        raise BuildError(
            f"{label}: name {nid} {text!r} carries the Reserved Font Name {rfn!r} "
            "but the face is not a pinned unmodified upstream file "
            "(UNMODIFIED_RFN_FONTS); OFL-1.1 condition 3 forbids an RFN on a "
            "Modified Version - embed the unmodified file or rename the family")


def audit_page(page: str) -> list[dict[str, Any]]:
    """Open every inlined face and enforce the RFN rule on each.

    Returns the faces (family, weight, mime, data, and the opened ``font``);
    raises BuildError on the first face that cannot be read or that is a
    Modified Version still presenting a Reserved Font Name."""
    faces = embedded_faces(page)
    for face in faces:
        label = f"@font-face {face['family'] or '?'} {face['weight'] or '?'}"
        face["font"] = read_font(face["data"])
        check_reserved_names(face["font"], label)
    return faces
