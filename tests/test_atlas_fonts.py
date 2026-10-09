"""OFL-1.1 guards for the fonts atlas.html inlines (slice W-L, 2026-10-09).

An independent verifier found three defects in the inlined fonts: the OFL
text was linked, not bundled (OFL condition 2); NOTICE's licence URL was not
the one in the fonts' name tables; and the Orbitron face was a Google Fonts
SUBSET - a Modified Version - still presenting its Reserved Font Name
"Orbitron" (OFL condition 3). The adjudicated fix embeds the UNMODIFIED
upstream Orbitron file (WOFF 1.0 wrapper only, OFL FAQ 2.2.1) and carries
every face as WOFF 1.0 so the stdlib build and these tests can read each
face's name table. These tests pin:

(i)  every face in the page has a NOTICE entry (family, verbatim nameID 0
     copyright line, the name-table licence URL) and the bundled licence file
     LICENSES/OFL-1.1.txt exists and is the verbatim OFL-1.1 text;
(ii) no embedded face presents a Reserved Font Name it declares unless it
     rebuilds byte for byte to a pinned unmodified upstream file - and the
     build refuses one that does not;
plus the stdlib font codec the build relies on.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import re
import struct
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ATLAS = REPO_ROOT / "atlas.html"
NOTICE = REPO_ROOT / "NOTICE"
OFL_TEXT = REPO_ROOT / "LICENSES" / "OFL-1.1.txt"
BUILDER_PATH = REPO_ROOT / "tools" / "atlas_build.py"

# sha256 of https://openfontlicense.org/documents/OFL.txt as fetched 2026-10-09.
OFL_SHA256 = "1d361a8f8e8ce6e68457dcd93fb56e162e6baa3bbb7e7573a290d44399f6b57e"
ORBITRON_SHA256 = "f42db2dd16e642258e35782916eceb1dcdbea06fb958d77ad71dc5963587e8fd"
ORBITRON_COMMIT = "abf71245949027c279caff7c2cb988c97e7d0b11"


def _load_builder():
    spec = importlib.util.spec_from_file_location("atlas_build_fonts_under_test", BUILDER_PATH)
    assert spec and spec.loader, f"cannot load {BUILDER_PATH}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ab():
    return _load_builder()


@pytest.fixture(scope="module")
def page() -> str:
    return ATLAS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def faces(ab, page) -> list[dict]:
    out = ab.embedded_faces(page)
    # Anchor: an empty list would make every per-face check below pass.
    assert out, "atlas.html inlines no @font-face data: URI"
    for face in out:
        face["font"] = ab.read_font(face["data"])
    return out


@pytest.fixture(scope="module")
def notice() -> str:
    return NOTICE.read_text(encoding="utf-8")


def _face(ab, family: str, data: bytes, weight: str = "700") -> str:
    b64 = base64.b64encode(data).decode("ascii")
    return ("@font-face {\n  font-family: '" + family + "';\n  font-weight: " + weight
            + ";\n  src: url(data:font/woff;base64," + b64 + ") format('woff');\n}\n")


def _without(ab, font, tag: str):
    """A Modified Version of ``font``: one table dropped."""
    tables = {t: d for t, d in font.tables.items() if t != tag}
    sums = {t: c for t, c in font.checksums.items() if t != tag}
    return ab.Sfnt(font.flavor, tables, sums, tuple(t for t in font.order if t != tag))


# --------------------------------------------------------------------------
# what the page carries
# --------------------------------------------------------------------------

def test_every_face_is_woff1_with_the_measured_families(faces) -> None:
    assert len(faces) == 9, [f["family"] for f in faces]
    assert {f["family"] for f in faces} == {"Orbitron", "Rajdhani"}
    for face in faces:
        assert face["mime"] == "font/woff", face["mime"]
        assert face["data"][:4] == b"wOFF", face["data"][:4]


def test_page_comment_beside_the_faces_carries_copyright_and_licence(ab, faces, page) -> None:
    region = ab._region(page, "fontnotice", js=True)
    assert "SIL Open Font License, Version 1.1" in region
    assert "LICENSES/OFL-1.1.txt" in region
    for face in faces:
        assert ab.name_text(face["font"], 0) in region, face["family"]
        assert ab.name_text(face["font"], 14) in region, face["family"]


# --------------------------------------------------------------------------
# (i) NOTICE entries and the bundled licence
# --------------------------------------------------------------------------

def test_bundled_licence_is_the_verbatim_ofl_1_1_text() -> None:
    assert OFL_TEXT.is_file(), f"missing {OFL_TEXT}"
    raw = OFL_TEXT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == OFL_SHA256, "LICENSES/OFL-1.1.txt is not verbatim"
    text = raw.decode("ascii")
    assert "SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007" in text
    assert "\r" not in text


def test_every_embedded_font_has_a_notice_entry(ab, faces, notice) -> None:
    fonts_section = notice.split("THIRD-PARTY FONTS", 1)[1]
    assert "LICENSES/OFL-1.1.txt" in fonts_section
    assert "OFL-1.1" in fonts_section
    for face in faces:
        font = face["font"]
        copyright_line = ab.name_text(font, 0)
        url = ab.name_text(font, 14)
        assert copyright_line, f"{face['family']} carries no nameID 0 copyright"
        assert f"* {face['family']} - " in fonts_section, face["family"]
        assert copyright_line in fonts_section, (
            f"NOTICE lacks the verbatim copyright line of {face['family']}: {copyright_line!r}")
        assert url and url in fonts_section, f"NOTICE lacks the licence URL {url!r}"


def test_every_face_names_the_ofl_as_its_licence(ab, faces) -> None:
    for face in faces:
        font = face["font"]
        licence = ab.name_text(font, 13) + " " + ab.name_text(font, 14)
        assert "scripts.sil.org/OFL" in licence or "openfontlicense.org" in licence, face["family"]


def test_notice_names_the_pinned_upstream_file(ab, notice) -> None:
    assert list(ab.UNMODIFIED_RFN_FONTS) == [ORBITRON_SHA256]
    assert ORBITRON_SHA256 in notice
    assert ORBITRON_COMMIT in notice
    assert ORBITRON_COMMIT in ab.UNMODIFIED_RFN_FONTS[ORBITRON_SHA256]


# --------------------------------------------------------------------------
# (ii) Reserved Font Names
# --------------------------------------------------------------------------

def test_no_embedded_subset_presents_a_declared_rfn(ab, faces) -> None:
    for face in faces:
        font = face["font"]
        hits = ab.rfn_family_hits(font)
        if hits:
            assert ab.sfnt_sha256(font) in ab.UNMODIFIED_RFN_FONTS, (
                f"{face['family']} {face['weight']} presents RFN in {hits[:3]} "
                "but is not a pinned unmodified upstream file")


def test_rfn_detection_reads_the_real_name_tables(ab, faces) -> None:
    # Anchors (ii): the detector must see Orbitron's declared RFN across its
    # family, PostScript and fvar instance names, and see none for Rajdhani.
    by_family = {}
    for face in faces:
        by_family.setdefault(face["family"], face["font"])
    orbitron, rajdhani = by_family["Orbitron"], by_family["Rajdhani"]
    assert ab.declared_rfns(orbitron) == ["Orbitron"]
    hit_ids = {nid for nid, _text, _rfn in ab.rfn_family_hits(orbitron)}
    assert {1, 4, 6}.issubset(hit_ids), hit_ids
    assert any(nid >= 256 for nid in hit_ids), "fvar instance PostScript names not audited"
    assert ab.declared_rfns(rajdhani) == []
    assert ab.rfn_family_hits(rajdhani) == []


def test_the_orbitron_face_rebuilds_to_the_pinned_upstream_file(ab, faces) -> None:
    orb = [f for f in faces if f["family"] == "Orbitron"]
    assert len(orb) == 1 and orb[0]["weight"] == "600 800"
    sfnt = ab.to_sfnt(orb[0]["font"])
    assert len(sfnt) == 38576
    assert hashlib.sha256(sfnt).hexdigest() == ORBITRON_SHA256


def _name_only_font(ab, records: list[tuple[int, str]]):
    """A minimal Sfnt holding just a Windows-English name table."""
    strings = b""
    recs = b""
    for nid, text in records:
        raw = text.encode("utf-16-be")
        recs += struct.pack(">6H", 3, 1, 0x409, nid, len(raw), len(strings))
        strings += raw
    table = struct.pack(">HHH", 0, len(records), 6 + 12 * len(records)) + recs + strings
    return ab.Sfnt(0x00010000, {"name": table}, {"name": 0}, ("name",))


LQ, RQ, LSQ, RSQ = chr(0x201C), chr(0x201D), chr(0x2018), chr(0x2019)


@pytest.mark.parametrize("nid, text, expected", [
    (0, 'Copyright 2018 X (https://x.test), with Reserved Font Name: "Orbitron".', ["Orbitron"]),
    (0, f"Copyright A, with Reserved Font Names {LQ}Foo{RQ} and {LQ}Bar Sans{RQ}.", ["Foo", "Bar Sans"]),
    (0, "Copyright B, with Reserved Font Name 'Orbitron'.", ["Orbitron"]),
    (0, f"Copyright C, with Reserved Font Names {LSQ}Q One{RSQ}, {LSQ}Q2{RSQ}.", ["Q One", "Q2"]),
    (0, "Copyright D, with Reserved Font Name \"D'Amore Sans\".", ["D'Amore Sans"]),
    (0, "Copyright (c) 2010, Someone, with Reserved Font Name Quux.", ["Quux"]),
    (13, 'Licensed under the OFL with Reserved Font Name "Baz".', ["Baz"]),
    (0, "Copyright (c) 2014 Indian Type Foundry (info@indiantypefoundry.com)", []),
    (5, 'Version 1.0; Reserved Font Name "NotAClause"', []),
])
def test_declared_rfns_parses_the_clause_forms(ab, nid, text, expected) -> None:
    assert ab.declared_rfns(_name_only_font(ab, [(nid, text)])) == expected


def test_rfn_hits_match_the_postscript_form_and_skip_the_copyright(ab) -> None:
    font = _name_only_font(ab, [
        (0, 'Copyright X, with Reserved Font Name "Open Thing".'),
        (1, "Other Family"),
        (6, "OpenThing-Bold"),
    ])
    assert ab.rfn_family_hits(font) == [(6, "OpenThing-Bold", "Open Thing")]


def test_a_known_rfn_is_caught_even_when_the_clause_was_edited_out(ab, faces) -> None:
    # Verifier gap: the audit read only what nameID 0 / 13 declare. A modified
    # Orbitron whose copyright no longer states the RFN must still be refused.
    assert "Orbitron" in ab.KNOWN_RFNS
    bare = _name_only_font(ab, [(0, "Copyright 2018 The Orbitron Project Authors"),
                                (1, "Orbitron"), (6, "Orbitron-Regular")])
    assert ab.declared_rfns(bare) == []
    assert [h[0] for h in ab.rfn_family_hits(bare)] == [1, 6]
    orbitron = next(f["font"] for f in faces if f["family"] == "Orbitron")
    name = ab.name_records(orbitron)
    assert any(r[3] == 0 and "Reserved Font Name" in r[4] for r in name)
    page = _face(ab, "Orbitron", ab.encode_woff(_without(ab, orbitron, "gasp")))
    with pytest.raises(ab.BuildError, match="Reserved Font Name"):
        ab.render_fonts(page)


def test_a_single_quoted_rfn_on_a_modified_face_is_refused(ab, faces) -> None:
    # Verifier gap: an RFN in single quotes was kept with its quotes and so
    # matched no family name. Rewrite nameID 0 to the single-quote form on a
    # modified Orbitron and the build must still refuse it.
    orbitron = next(f["font"] for f in faces if f["family"] == "Orbitron")
    recs = [(nid, text) for _p, _e, _l, nid, text in ab.name_records(orbitron)]
    recs = [(nid, "Copyright X, with Reserved Font Name 'Orbitron'." if nid == 0 else text)
            for nid, text in recs]
    renamed = _name_only_font(ab, recs).tables["name"]
    tables = dict(orbitron.tables, name=renamed)
    sums = dict(orbitron.checksums, name=ab.table_checksum(renamed))
    modified = ab.Sfnt(orbitron.flavor, tables, sums, orbitron.order)
    assert ab.declared_rfns(modified) == ["Orbitron"]
    page = _face(ab, "Orbitron", ab.encode_woff(modified))
    with pytest.raises(ab.BuildError, match="Reserved Font Name 'Orbitron'"):
        ab.render_fonts(page)


def test_build_refuses_a_modified_face_that_keeps_its_rfn(ab, faces) -> None:
    orbitron = next(f["font"] for f in faces if f["family"] == "Orbitron")
    modified = _without(ab, orbitron, "DSIG")
    assert ab.rfn_family_hits(modified), "the modified copy should still carry the RFN"
    page = _face(ab, "Orbitron", ab.encode_woff(modified))
    with pytest.raises(ab.BuildError, match="Reserved Font Name 'Orbitron'"):
        ab.render_fonts(page)


def test_build_accepts_a_modified_face_without_an_rfn(ab, faces) -> None:
    rajdhani = next(f["font"] for f in faces if f["family"] == "Rajdhani")
    page = _face(ab, "Rajdhani", ab.encode_woff(_without(ab, rajdhani, "gasp")))
    assert ab.render_fonts(page) == page


# --------------------------------------------------------------------------
# the stdlib codec the build relies on
# --------------------------------------------------------------------------

def test_render_fonts_passes_the_real_page_through_unchanged(ab, page) -> None:
    assert ab.render_fonts(page) == page


def test_a_raw_ttf_face_is_wrapped_once_and_then_stable(ab, faces) -> None:
    orbitron = next(f["font"] for f in faces if f["family"] == "Orbitron")
    ttf = ab.to_sfnt(orbitron)
    b64 = base64.b64encode(ttf).decode("ascii")
    src = ("@font-face {\n  font-family: 'Orbitron';\n  font-weight: 700;\n"
           "  src: url(data:font/ttf;base64," + b64 + ") format('truetype');\n}\n")
    once = ab.render_fonts(src)
    assert "data:font/woff;base64," in once and "format('woff')" in once
    assert ab.render_fonts(once) == once
    wrapped = ab.embedded_faces(once)[0]["data"]
    assert ab.to_sfnt(ab.read_font(wrapped)) == ttf


def test_woff2_and_unknown_signatures_are_refused(ab) -> None:
    with pytest.raises(ab.BuildError, match="WOFF2"):
        ab.read_font(b"wOF2" + b"\0" * 60)
    with pytest.raises(ab.BuildError, match="unknown font signature"):
        ab.read_font(b"GIF89a" + b"\0" * 60)
    with pytest.raises(ab.BuildError, match="truncated"):
        ab.read_font(b"wOFF")


def test_corrupt_woff_is_refused(ab, faces) -> None:
    data = bytearray(faces[0]["data"])
    with pytest.raises(ab.BuildError, match="length field"):
        ab.read_font(bytes(data) + b"\0\0\0\0")
    # Flip one byte in the middle of the zlib-packed 'glyf' block.
    num = struct.unpack_from(">H", data, 12)[0]
    for i in range(num):
        tag, off, comp, orig, _csum = struct.unpack_from(">4sLLLL", data, 44 + 20 * i)
        if tag == b"glyf":
            break
    else:
        pytest.fail("no glyf table in the first face")
    assert comp < orig, "glyf should be stored compressed"
    data[off + comp // 2] ^= 0xFF
    with pytest.raises(ab.BuildError, match="inflate|checksum|length"):
        ab.read_font(bytes(data))


def test_table_checksum_zeroes_head_adjustment(ab) -> None:
    head = bytes(range(8)) + b"\xff\xff\xff\xff" + bytes(range(12, 54))
    assert ab.table_checksum(head, "head") == ab.table_checksum(
        head[:8] + b"\0\0\0\0" + head[12:])
    assert ab.table_checksum(b"\x00\x00\x00\x01\x02") == 1 + 0x02000000


def test_font_face_css_keeps_the_family_names_the_page_uses(page) -> None:
    # The fix kept the original families, so no CSS or canvas rename was needed.
    used = set(re.findall(r"font-family:\s*'([^']+)'", page))
    assert {"Orbitron", "Rajdhani"}.issubset(used)
    assert "px Orbitron, Rajdhani, sans-serif" in page
