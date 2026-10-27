"""The RM-600 rule for reading the wiki's raw ``Module:ChampionData/data`` text.

The module is a Lua table, and two traits of the live text defeat a naive
regex / brace scan (measured 2026-10-27, RM-787):

- it carries Lua comments: a trailing ``--see his passive ...`` after Gnar's
  ``["range"] = 175,`` and a whole commented-out ``--["aram"] = { ... --},``
  table inside the second Kled block;
- one apiname has TWO blocks: "Kled" (id 240, the primary record) and
  "Kled & Skaarl" (id 240.1).

So comments are stripped first, and when two blocks share an apiname the
integer-id record wins in either order; between two records of the same kind
the FIRST is kept, and a lone non-integer-id record (GnarBig) is still used.

This is the library copy of the rule that ``tools/daemon_slayer_wiki_stats_extract.py``
(``_strip_lua_comments`` / ``_is_primary_record`` / ``_parse_lua_table``)
implements for the DS sidecar; ``lib/game_data/sources.py`` cannot import a
script from ``tools/``.
"""
from __future__ import annotations

import re

_BLOCK_OPEN_RE = re.compile(r'\["([^"]+)"\]\s*=\s*\{')
_APINAME_RE = re.compile(r'\["apiname"\]\s*=\s*"([^"]+)"')
_ID_RE = re.compile(r'\["id"\]\s*=\s*(-?[0-9.]+)')
# A champion block names its id and apiname at its head; a nested subtable
# (stats, skills, mode blocks) does not.
_HEAD_CHARS = 400


def _long_bracket_level(text: str, i: int) -> int:
    """Level of a Lua long bracket opening at ``text[i]`` (``[`` ``=``* ``[``), else -1."""
    n = len(text)
    if i >= n or text[i] != "[":
        return -1
    j = i + 1
    while j < n and text[j] == "=":
        j += 1
    return j - i - 1 if (j < n and text[j] == "[") else -1


def strip_lua_comments(text: str) -> str:
    """Remove every Lua comment from ``text``; string literals stay verbatim.

    ``--`` line comments run to the end of the line (the newline is kept);
    ``--[[ ... ]]`` / ``--[==[ ... ]==]`` block comments become one space.
    ``-- [[`` (a space before the brackets) is a LINE comment, as in Lua. A
    ``--`` inside a ``"..."`` / ``'...'`` string (backslash escapes honoured) or
    a ``[[ ... ]]`` long string is data. Fail-soft: an unterminated block
    comment drops the rest of the text, an unterminated short string ends at
    the newline.
    """
    out: list[str] = []
    n = len(text)
    i = 0
    seg = 0  # start of the verbatim segment not yet copied to ``out``
    while i < n:
        c = text[i]
        if c == "-" and text.startswith("--", i):
            out.append(text[seg:i])
            lvl = _long_bracket_level(text, i + 2)
            if lvl >= 0:
                close = "]" + "=" * lvl + "]"
                end = text.find(close, i + lvl + 4)
                i = n if end < 0 else end + len(close)
                out.append(" ")
            else:
                nl = text.find("\n", i)
                i = n if nl < 0 else nl
            seg = i
            continue
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            i = j + 1 if (j < n and text[j] == c) else min(j, n)
            continue
        if c == "[":
            lvl = _long_bracket_level(text, i)
            if lvl >= 0:
                close = "]" + "=" * lvl + "]"
                end = text.find(close, i + lvl + 2)
                i = n if end < 0 else end + len(close)
                continue
        i += 1
    out.append(text[seg:])
    return "".join(out)


def is_primary_record(block: str) -> bool:
    """True when a champion block's ``["id"]`` is an integer (the live record)."""
    m = _ID_RE.search(block)
    if m is None:
        return False
    try:
        val = float(m.group(1))
    except ValueError:
        return False
    return val == int(val)


def block_end(text: str, open_idx: int) -> int:
    """Index just past the ``}`` matching the ``{`` at ``open_idx``.

    Raises ``ValueError`` when the braces never balance.
    """
    depth = 0
    for k in range(open_idx, len(text)):
        ch = text[k]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return k + 1
    raise ValueError("unbalanced braces")


def champion_blocks(text: str) -> dict[str, str]:
    """``{apiname: block text}`` for every champion record, under the RM-600 rule.

    ``text`` is the raw module; comments are stripped here, so a returned block
    never carries one. Raises ``ValueError`` on unbalanced braces.
    """
    text = strip_lua_comments(text)
    out: dict[str, str] = {}
    primary: set[str] = set()
    for m in _BLOCK_OPEN_RE.finditer(text):
        open_idx = text.index("{", m.start())
        block = text[m.start():block_end(text, open_idx)]
        head = block[:_HEAD_CHARS]
        if '["id"]' not in head or '["apiname"]' not in head:
            continue  # a nested subtable, not a champion block
        api = _APINAME_RE.search(block)
        if api is None:
            continue
        name = api.group(1)
        is_primary = is_primary_record(block)
        if name in out and (name in primary or not is_primary):
            continue  # a later duplicate never displaces the record kept
        if is_primary:
            primary.add(name)
        out[name] = block
    return out
