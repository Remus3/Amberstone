"""
tests/snapshot_panels/_webfont_stub.py
RM-1078: a local stand-in for the Lato webfont, so a test that needs a
real webfont swap does not depend on reaching Google Fonts.

web/css/dashboard.css @imports the Lato CSS from fonts.googleapis.com
(display=swap), which then fetches the face from fonts.gstatic.com. A test
calls route_stub_webfont(page, hold) before navigating: the CSS request is
answered with STUB_CSS (one Lato @font-face, every weight, served from a
fixed gstatic URL), and each face request is passed to `hold`, which
answers it later with fulfill_stub_font(route). No byte leaves the box.

build_stub_ttf() writes a minimal TrueType font in pure Python (fontTools
is not a test dependency): glyph 0 is .notdef and U+0020..U+007E map one
to one onto glyphs 1..95, each a plain box with one advance width. The
vertical metrics (ascent + descent = 1.2 em, about Lato's normal line
height) and a text-face advance keep a swap close to the real one. Every
glyph sharing one advance is the stub's signature: STUB_APPLIED is true
only while an element set in 'Lato' is drawn by the stub, not a fallback.
"""
import struct

STUB_FONT_URL = "https://fonts.gstatic.com/s/rc-stub/lato-stub.ttf"

STUB_CSS = (
    "@font-face {\n"
    "  font-family: 'Lato';\n"
    "  font-style: normal;\n"
    "  font-weight: 100 900;\n"
    "  font-display: swap;\n"
    f"  src: url({STUB_FONT_URL}) format('truetype');\n"
    "}\n"
)

UPM = 1000
ASCENT = 950
DESCENT = 250
ADVANCE = 520
_FIRST, _LAST = 0x20, 0x7E

# "iiiiiiii" and "MMMMMMMM" are the same width only in a face whose glyphs
# share one advance; every sans or serif fallback draws i far narrower.
STUB_APPLIED = """() => {
  const s = document.createElement('span');
  s.style.cssText = "font: 400 40px 'Lato'; position: absolute; white-space: pre";
  document.body.appendChild(s);
  s.textContent = 'iiiiiiii';
  const narrow = s.getBoundingClientRect().width;
  s.textContent = 'MMMMMMMM';
  const wide = s.getBoundingClientRect().width;
  s.remove();
  return narrow > 0 && Math.abs(wide - narrow) < 0.5;
}"""


def _checksum(data):
    data += b"\0" * (-len(data) % 4)
    return sum(struct.unpack(f">{len(data) // 4}I", data)) & 0xFFFFFFFF


def _box_glyph():
    # One contour, four on-curve points, int16 deltas (flag 0x01 only).
    x0, x1, y1 = 50, ADVANCE - 50, 700
    return (
        struct.pack(">hhhhh", 1, x0, 0, x1, y1)
        + struct.pack(">HH", 3, 0)
        + bytes([0x01] * 4)
        + struct.pack(">4h", x0, 0, x1 - x0, 0)
        + struct.pack(">4h", 0, y1, 0, -y1)
    )


def _name_table():
    names = {1: "Lato", 2: "Regular", 4: "Lato Regular", 6: "Lato-Regular"}
    records, strings = b"", b""
    for name_id, text in names.items():
        raw = text.encode("utf-16-be")
        records += struct.pack(">6H", 3, 1, 0x409, name_id, len(raw), len(strings))
        strings += raw
    return struct.pack(">3H", 0, len(names), 6 + len(records)) + records + strings


def _cmap_table():
    count = _LAST - _FIRST + 1
    seg_x2, search, selector, shift = 4, 4, 1, 0
    sub = struct.pack(">7H", 4, 16 + 8 * 2, 0, seg_x2, search, selector, shift)
    sub += struct.pack(">2H", _LAST, 0xFFFF) + b"\0\0"
    sub += struct.pack(">2H", _FIRST, 0xFFFF)
    sub += struct.pack(">2H", (1 - _FIRST) & 0xFFFF, 1)
    sub += struct.pack(">2H", 0, 0)
    assert len(sub) == 32 and count == 95
    return struct.pack(">HHHHI", 0, 1, 3, 1, 12) + sub


def build_stub_ttf():
    """The stub font's bytes, deterministic across runs."""
    num_glyphs = 1 + (_LAST - _FIRST + 1)
    glyph = _box_glyph()
    glyf = glyph * num_glyphs
    loca = struct.pack(f">{num_glyphs + 1}H",
                       *(i * len(glyph) // 2 for i in range(num_glyphs + 1)))
    x_max = ADVANCE - 50
    tables = {
        b"head": struct.pack(
            ">IIIIHHqqhhhhHHhhh", 0x00010000, 0x00010000, 0, 0x5F0F3CF5,
            0x000B, UPM, 0, 0, 50, 0, x_max, 700, 0, 8, 2, 0, 0),
        b"hhea": struct.pack(
            ">Ihhh H hhh hhh 4h hH".replace(" ", ""), 0x00010000, ASCENT,
            -DESCENT, 0, ADVANCE, 50, 50, x_max, 1, 0, 0, 0, 0, 0, 0, 0,
            num_glyphs),
        b"maxp": struct.pack(">IHHHHHHHHHHHHHH", 0x00010000, num_glyphs,
                             4, 1, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0),
        b"OS/2": struct.pack(
            ">HhHHH10hh10s4I4sHHHhhhHH2IhhHHH", 4, ADVANCE, 400, 5, 0,
            650, 600, 0, 75, 650, 600, 0, 350, 50, 300, 0, b"\0" * 10,
            1, 0, 0, 0, b"RCST", 0x40, _FIRST, _LAST, ASCENT, -DESCENT, 0,
            ASCENT, DESCENT, 1, 0, 500, 700, 0, 0x20, 1),
        b"hmtx": struct.pack(f">{num_glyphs * 2}h",
                             *([ADVANCE, 50] * num_glyphs)),
        b"cmap": _cmap_table(),
        b"loca": loca,
        b"glyf": glyf,
        b"name": _name_table(),
        b"post": struct.pack(">IIhhIIIII", 0x00030000, 0, -100, 50,
                             0, 0, 0, 0, 0),
    }
    tags = sorted(tables)
    count = len(tags)
    search = 1 << (count.bit_length() - 1)
    header = struct.pack(">IHHHH", 0x00010000, count, search * 16,
                         search.bit_length() - 1, count * 16 - search * 16)
    offset = 12 + 16 * count
    directory, body = b"", b""
    for tag in tags:
        data = tables[tag]
        directory += struct.pack(">4sIII", tag, _checksum(data),
                                 offset + len(body), len(data))
        body += data + b"\0" * (-len(data) % 4)
    font = bytearray(header + directory + body)
    adjust = (0xB1B0AFBA - _checksum(bytes(font))) & 0xFFFFFFFF
    head_at = 12 + 16 * count + sum(
        len(tables[t]) + (-len(tables[t]) % 4) for t in tags[:tags.index(b"head")])
    font[head_at + 8:head_at + 12] = struct.pack(">I", adjust)
    return bytes(font)


def fulfill_stub_font(route):
    """Answer a held face request with the stub (CORS-open, as gstatic is)."""
    route.fulfill(status=200, body=build_stub_ttf(), content_type="font/ttf",
                  headers={"Access-Control-Allow-Origin": "*"})


def route_stub_webfont(page, hold):
    """Serve STUB_CSS for the Google Fonts CSS and pass every face request
    to `hold(route)`. Call before the page navigates. Playwright tags each
    handler with an attribute, so `hold` must be a Python function or
    lambda, not a bound builtin such as `list.append`."""
    page.route(lambda url: "fonts.googleapis.com" in url,
               lambda route: route.fulfill(
                   status=200, body=STUB_CSS, content_type="text/css",
                   headers={"Access-Control-Allow-Origin": "*"}))
    page.route(lambda url: "fonts.gstatic.com" in url, hold)
