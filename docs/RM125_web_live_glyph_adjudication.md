# RM-125 - adjudication of the LIVE-span glyph residue in `web/`

**Status:** RM-125 comment half DONE. Live half DEFERRED to RM-122 (operator-present).
**Measured:** 2026-07-28, at commit `35c6730f`.

RM-125 is the ASCII-hygiene sweep of `web/`. The tree carried 3153 non-ASCII
characters across 31 `.js` / `.css` / `.html` files. Slice A (`35c6730f`,
`tools/web_ascii_sweep.py`) swept the **comment** half - the subset that renders
no pixels - and left the rest alone by design.

This document covers **only the deferred live half**. Nothing here is a
work order to strip anything. Stripping a rendered glyph is headless-forbidden:
it changes rendered pixels, and a large share of these glyphs ARE the Terminal
theme's iconography. The entire set is routed to RM-122 for operator-present,
rendered-pixel judgement.

---

## 1. Method

The LIVE / COMMENT split is taken from the Slice A tokeniser itself, not
re-derived:

```
python tools/web_ascii_sweep.py --dry-run --root web
  -> comment-span glyphs: 0 across 0 files
  -> live-span residue (left alone by design): 320
```

Per-instance data came from importing that module and walking
`scan(text, lang)`, keeping every character with `ord(c) > 127` that falls in a
span whose `kind` is `LIVE`. The tool classifies spans only as LIVE or COMMENT,
so the **span sub-kind** column (string / template / regex / CSS value / HTML
text node) was derived by a walker built on that module's own tokeniser
primitives (`_scan_string`, `_scan_template`, `_scan_regex`,
`_regex_may_start`), so the sub-kind cannot disagree with the tool about where a
literal begins. Sub-classification coverage was total: 0 characters landed in an
`UNCLASSIFIED` bucket.

Every `file:line -> codepoint` triple asserted below was re-read off disk and
checked to actually contain that codepoint: **261 of 261 verified, 0 mismatches.**

### Notation

This file is the one place in the repo where naming a non-ASCII codepoint is
unavoidable. Per the repo's 7-bit-ASCII rule and the hygiene guards
(`tests/test_smart_quote_hygiene.py`, `tests/test_u2500_hygiene.py`,
`tests/test_mojibake_hygiene.py`), **no raw glyph is pasted anywhere in this
document.** Every glyph appears as `U+XXXX` plus its Unicode name, and source
snippets are shown with the glyph rewritten as a Python-style `\uXXXX` escape
(`\UXXXXXXXX` for the non-BMP emoji). The source on disk holds the literal
character; the escapes are this document's rendering, not the file's bytes.

One snippet is worth reading carefully: `'\u00814'` in section 5.3 is the four
hex digits `0081` followed by a literal ASCII `4`, i.e. two characters, not a
five-digit escape.

---

## 2. MEASURED TOTALS

The tool's headline number of **320** is an over-count of the rendered set. Two
distinct classes inside it render nothing, and both are tokeniser blind spots
rather than deliberate UI:

| Bucket | Count | Renders? |
|---|---:|---|
| Tool-reported "live-span residue" | 320 | - |
| less: JS comment glyphs unreachable through a tokeniser defect (see 3) | -59 | no |
| less: CSS comment glyphs inside an inline `<style>` block (by-design under-sweep) | -26 | no |
| **TRUE rendered live residue** | **235** | yes |

Both subtractions were measured, not estimated:

- The 59 are all `U+2500 BOX DRAWINGS LIGHT HORIZONTAL` in a single banner
  comment at `web/js/panels/last_match.js:1569`. Measured by re-running
  `comment_spans()` with a corrected `_scan_template_subst` and diffing against
  the shipped one. **This half is now CLOSED:** the desync was root-caused and
  fixed in the same cycle (`c0c6e97e`), and those 59 are swept, which is why the
  tool-reported residue now reads **261**, not 320. The rendered census below is
  unchanged by that fix - the 59 were never part of the rendered set.
- The 26 sit in comments inside `web/legacy_index.html`'s inline blocks - 20 in
  CSS comments inside `<style>` and 6 in JS comments inside `<script>` (lines
  1975, 1979, 2047 twice, 2642, 2667).
  `_scan_html` handles only `<!-- -->` and deliberately leaves embedded
  `<script>` / `<style>` comments LIVE; its docstring records that
  `web/index.html`'s inline scripts are clean, but does not cover
  `legacy_index.html`'s inline style block. Measured at 26 there and 0 in
  `web/index.html`.

### Per file (the true 235)

| File | Count |
|---|---:|
| `web/js/main.js` | 97 |
| `web/js/panels/right_now.js` | 31 |
| `web/index.html` | 22 |
| `web/legacy_index.html` | 19 |
| `web/js/panels/next.js` | 15 |
| `web/js/lib/helpers.js` | 10 |
| `web/js/panels/dev.js` | 10 |
| `web/js/panels/item_build.js` | 10 |
| `web/js/panels/map_state.js` | 8 |
| `web/css/panels/header.css` | 3 |
| `web/css/panels/map_state.css` | 3 |
| `web/js/panels/last_match.js` | 2 |
| `web/js/panels/team_context.js` | 2 |
| `web/css/panels/input_activity.css` | 1 |
| `web/js/lib/items_index.js` | 1 |
| `web/js/panels/augment_reco.js` | 1 |

16 files. 51 distinct codepoints.

### Per span kind

| Span kind | Count |
|---|---:|
| JS template literal | 84 |
| JS string literal | 75 |
| HTML text node | 41 |
| JS regex literal | 28 |
| CSS `content:` value (quoted string) | 7 |

No live glyph sits in an HTML attribute value or in bare JS code.

### Per codepoint

| Codepoint | Name | Count |
|---|---|---:|
| U+00B7 | MIDDLE DOT | 107 |
| U+2192 | RIGHTWARDS ARROW | 22 |
| U+2713 | CHECK MARK | 9 |
| U+26A0 | WARNING SIGN | 8 |
| U+2191 | UPWARDS ARROW | 7 |
| U+00D7 | MULTIPLICATION SIGN | 5 |
| U+2193 | DOWNWARDS ARROW | 5 |
| U+25B6 | BLACK RIGHT-POINTING TRIANGLE | 5 |
| U+2715 | MULTIPLICATION X | 4 |
| U+25BA | BLACK RIGHT-POINTING POINTER | 4 |
| U+26D4 | NO ENTRY | 4 |
| U+1F507 | SPEAKER WITH CANCELLATION STROKE | 3 |
| U+25C9 | FISHEYE | 3 |
| U+2022 | BULLET | 3 |
| U+26A1 | HIGH VOLTAGE SIGN | 3 |
| U+2212 | MINUS SIGN | 2 |
| U+2665 | BLACK HEART SUIT | 2 |
| U+2795 | HEAVY PLUS SIGN | 2 |
| U+22EF | MIDLINE HORIZONTAL ELLIPSIS | 2 |
| U+FE0F | VARIATION SELECTOR-16 | 2 |
| U+1F6A8 | POLICE CARS REVOLVING LIGHT | 2 |
| U+2733 | EIGHT SPOKED ASTERISK | 2 |
| U+27F3 | CLOCKWISE GAPPED CIRCLE ARROW | 1 |
| U+203A | SINGLE RIGHT-POINTING ANGLE QUOTATION MARK | 1 |
| U+27E8 | MATHEMATICAL LEFT ANGLE BRACKET | 1 |
| U+27E9 | MATHEMATICAL RIGHT ANGLE BRACKET | 1 |
| U+25BE | BLACK DOWN-POINTING SMALL TRIANGLE | 1 |
| U+21BB | CLOCKWISE OPEN CIRCLE ARROW | 1 |
| U+0394 | GREEK CAPITAL LETTER DELTA | 1 |
| U+2697 | ALEMBIC | 1 |
| U+03A3 | GREEK CAPITAL LETTER SIGMA | 1 |
| U+2726 | BLACK FOUR POINTED STAR | 1 |
| U+2261 | IDENTICAL TO | 1 |
| U+25E7 | SQUARE WITH LEFT HALF BLACK | 1 |
| U+265B | BLACK CHESS QUEEN | 1 |
| U+2B06 | UPWARDS BLACK ARROW | 1 |
| U+25B2 | BLACK UP-POINTING TRIANGLE | 1 |
| U+25BC | BLACK DOWN-POINTING TRIANGLE | 1 |
| U+2190 | LEFTWARDS ARROW | 1 |
| U+2605 | BLACK STAR | 1 |
| U+1F50A | SPEAKER WITH THREE SOUND WAVES | 1 |
| U+2717 | BALLOT X | 1 |
| U+0081 | (C1 control, no Unicode name) | 1 |
| U+231B | HOURGLASS | 1 |
| U+1F3AF | DIRECT HIT | 1 |
| U+1F6AB | NO ENTRY SIGN | 1 |
| U+2694 | CROSSED SWORDS | 1 |
| U+1F4CA | BAR CHART | 1 |
| U+1F33F | HERB | 1 |
| U+2728 | SPARKLES | 1 |
| U+1F4DD | MEMO | 1 |

---

## 3. DEFECT FOUND IN THE SLICE A TOKENISER (read before any future sweep)

`_scan_template_subst` (`tools/web_ascii_sweep.py:225-248`) walks a `${...}`
substitution handling backslash escapes, quoted strings, nested backticks and
brace depth. **It has no regex-literal case.** A regex holding a quote character
inside a substitution therefore desyncs it: the quote is read as a string
opener, brace counting goes wrong, and the enclosing template scan runs away.

Trigger, at `web/js/panels/last_match.js:1497`:

```js
return `<li data-tt-html="${safeWhy.replace(/"/g, "&quot;")}">${safeText}</li>`;
```

The `"` inside the regex `/"/g` is treated as the start of a string literal.
The template "ends" 141 lines later, at line 1638, so everything between is
reported LIVE - including the genuine block comment at line 1569 and its 59
`U+2500` characters.

Three runaway templates exist in the tree, all from the same
`replace(/"/g, ...)`-inside-a-substitution shape:

| File | Runaway span | Lines swallowed |
|---|---|---:|
| `web/js/panels/historical_pgr.js` | lines 57-494 | 437 |
| `web/js/panels/champ_select.js` | lines 2951-3119 | 168 |
| `web/js/panels/last_match.js` | lines 1497-1638 | 141 |

Only `last_match.js` has non-ASCII inside its runaway region, which is why the
visible cost is 59 characters and not more.

**Direction of the bug is safe, and this was verified rather than assumed.**
Every glyph that Slice A actually rewrote (both commits `b43423f0` and
`35c6730f`, 56 changed files) was re-checked against a corrected tokeniser:

```
mis-swept glyphs (stripped from a LIVE span): 0
```

So Slice A did **not** damage rendered output. The defect costs an under-sweep
(59 comment glyphs left unswept and miscounted as live residue), never a
mis-sweep. Under-sweeping is the recoverable direction and matches the tool's
own stated doctrine.

Consequences for whoever picks this up:

1. The residue counter in `tools/web_ascii_sweep.py:470-473` reports 320. The
   rendered figure is 235. Do not quote 320 as "rendered glyphs".
2. Fixing `_scan_template_subst` would let the sweeper reach those 59 comment
   glyphs. That is a `tools/` change and belongs to its own slice, not to
   RM-122's pixel judgement.
3. `_scan_html` leaves embedded `<script>` / `<style>` comments LIVE by design.
   That is documented and deliberate, but its docstring's measurement covers
   `web/index.html` only; `web/legacy_index.html` has 26 such characters.

---

## 4. LOAD-BEARING instances (highest-priority callout)

These glyphs are **functionally significant, not decorative**. They are matched
by a regex or feed a regex that matches them. Stripping any of them breaks
behaviour, not looks. A naive future sweep that treats "live glyph" as
"cosmetic" will silently break these.

**31 characters across 4 regex sites and 1 coupled producer site.**

### 4.1 Arrow-splitting regex - `web/js/lib/items_index.js:62`

```js
const sep = splitArrow ? /\s*(?:,|\u2192|->)\s*/ : /\s*,\s*/;
```

`U+2192 RIGHTWARDS ARROW` is an alternation branch. It is how a build string
written with a real arrow gets split into items. Remove it and arrow-separated
build strings stop splitting - they collapse into one item name. The ASCII `->`
branch beside it does **not** make the glyph redundant: it is the fallback for
strings that use the ASCII form, and both spellings occur in the data.

### 4.2 Leading-glyph strip - `web/js/main.js:7114`

```js
const txt = (actionEl.textContent || "").replace(/^[\u25b6\u25ba\u26a0\ufe0f\s]+/, "").trim();
```

4 characters: `U+25B6`, `U+25BA`, `U+26A0`, `U+FE0F VARIATION SELECTOR-16`.
This strips the priority-glyph prefix back off rendered action text before
re-use. The variation selector is easy to miss and is genuinely part of the
class - dropping it leaves a stray invisible codepoint on the stripped string.

### 4.3 DEAD-state detection - `web/js/panels/right_now.js:468`

```js
if (p.is_dead && /^\s*[\u26a0\u2713\u25ba\u2022\u26a1\u26d4\U0001f6a8\u2733\u25b6\u25c9\u2192\u26d4]?\s*DEAD\b/i.test(rawAction)) {
```

12 characters in an optional character class guarding the DEAD-headline rewrite.
Note `U+26D4 NO ENTRY` appears **twice** in this class - a harmless duplicate in
the source, but it means the naive instance count is 12 while the distinct set
is 11.

### 4.4 Already-glyphed test - `web/js/panels/right_now.js:566`

```js
const alreadyGlyphed = hasAction && /^[\u26a0\u2713\u25ba\u2022\u26a1\u26d4\U0001f6a8\u2733\u25b6\u25c9\u2192]/.test(rawAction);
```

11 characters. Prevents double-prefixing an action string that already starts
with a priority glyph.

### 4.5 The coupled producers - `web/js/panels/right_now.js:563-565`

```js
const glyph = klass === "urgent" ? "\u26a0 "
            : klass === "good"   ? "\u2713 "
            :                      "\u25ba ";
```

3 characters: `U+26A0`, `U+2713`, `U+25BA`. These look like plain rendered UI,
and in isolation they are - but they are the exact glyphs the line-566 regex
must recognise. **Producer and matcher are coupled.** Change one side only and
the dedup silently breaks: the panel starts rendering a doubled prefix
(the comment at line 562 names the failure mode, "double `! ! DEFEAT`").

Any RM-122 decision on these three must move line 566's character class in the
same edit. The same coupling holds between these producers and the line-468
class.

---

## 5. THE TABLE

Grouped by `file` + `codepoint` + `span kind`, because most of these glyphs
repeat identically within a file (`U+00B7` alone accounts for 107 of 235) and a
per-instance table would be 235 rows of the same three judgements. Grouping is
by span kind as well as codepoint so that a glyph appearing in both a regex and
a string in the same file does not get collapsed into one disposition - that
distinction is exactly what separates LOAD-BEARING from the rest. **104 groups.**
`n` is the instance count in that group. Line lists are truncated at 5 with
`...`; the full set is reproducible from the method in section 1.

### 5.1 LOAD-BEARING (31)

| file:line | Codepoint | Span kind | Rendered context | n |
|---|---|---|---|---:|
| `web/js/lib/items_index.js:62` | U+2192 RIGHTWARDS ARROW | JS regex literal | not rendered - splits build strings | 1 |
| `web/js/main.js:7114` | U+25B6 BLACK RIGHT-POINTING TRIANGLE | JS regex literal | not rendered - strips action prefix | 1 |
| `web/js/main.js:7114` | U+25BA BLACK RIGHT-POINTING POINTER | JS regex literal | not rendered - strips action prefix | 1 |
| `web/js/main.js:7114` | U+26A0 WARNING SIGN | JS regex literal | not rendered - strips action prefix | 1 |
| `web/js/main.js:7114` | U+FE0F VARIATION SELECTOR-16 | JS regex literal | not rendered - strips action prefix | 1 |
| `web/js/panels/right_now.js:468,566` | U+1F6A8 POLICE CARS REVOLVING LIGHT | JS regex literal | not rendered - DEAD / already-glyphed tests | 2 |
| `web/js/panels/right_now.js:468,566` | U+2022 BULLET | JS regex literal | not rendered - DEAD / already-glyphed tests | 2 |
| `web/js/panels/right_now.js:468,566` | U+2192 RIGHTWARDS ARROW | JS regex literal | not rendered - DEAD / already-glyphed tests | 2 |
| `web/js/panels/right_now.js:468,566` | U+25B6 BLACK RIGHT-POINTING TRIANGLE | JS regex literal | not rendered - DEAD / already-glyphed tests | 2 |
| `web/js/panels/right_now.js:468,566` | U+25BA BLACK RIGHT-POINTING POINTER | JS regex literal | not rendered - DEAD / already-glyphed tests | 2 |
| `web/js/panels/right_now.js:468,566` | U+25C9 FISHEYE | JS regex literal | not rendered - DEAD / already-glyphed tests | 2 |
| `web/js/panels/right_now.js:468,566` | U+26A0 WARNING SIGN | JS regex literal | not rendered - DEAD / already-glyphed tests | 2 |
| `web/js/panels/right_now.js:468,566` | U+26A1 HIGH VOLTAGE SIGN | JS regex literal | not rendered - DEAD / already-glyphed tests | 2 |
| `web/js/panels/right_now.js:468,566` | U+26D4 NO ENTRY | JS regex literal | not rendered - DEAD / already-glyphed tests (dup in the 468 class) | 3 |
| `web/js/panels/right_now.js:468,566` | U+2713 CHECK MARK | JS regex literal | not rendered - DEAD / already-glyphed tests | 2 |
| `web/js/panels/right_now.js:468,566` | U+2733 EIGHT SPOKED ASTERISK | JS regex literal | not rendered - DEAD / already-glyphed tests | 2 |
| `web/js/panels/right_now.js:563` | U+26A0 WARNING SIGN | JS string literal | urgent-priority prefix on the Right Now headline; ALSO matched by line 566 | 1 |
| `web/js/panels/right_now.js:564` | U+2713 CHECK MARK | JS string literal | good-priority prefix on the Right Now headline; ALSO matched by line 566 | 1 |
| `web/js/panels/right_now.js:565` | U+25BA BLACK RIGHT-POINTING POINTER | JS string literal | default-priority prefix on the Right Now headline; ALSO matched by line 566 | 1 |

### 5.2 KEEP-deliberate-UI-glyph (52)

The glyph IS the UI. An ASCII stand-in costs real meaning or real width.

| file:line | Codepoint | Span kind | Rendered context | n |
|---|---|---|---|---:|
| `web/css/panels/header.css:808` | U+2715 MULTIPLICATION X | CSS `content:` | empty lane-pref slot marker, coloured `--bad` | 1 |
| `web/css/panels/header.css:3413` | U+26A0 WARNING SIGN | CSS `content:` | warning pill prefix | 1 |
| `web/css/panels/header.css:3440` | U+27F3 CLOCKWISE GAPPED CIRCLE ARROW | CSS `content:` | refresh affordance | 1 |
| `web/index.html:55` | U+25BE BLACK DOWN-POINTING SMALL TRIANGLE | HTML text node | title dropdown caret | 1 |
| `web/index.html:71` | U+21BB CLOCKWISE OPEN CIRCLE ARROW | HTML text node | "Auto (clear manual)" menu item icon | 1 |
| `web/index.html:107` | U+2665 BLACK HEART SUIT | HTML text node | heartbeat indicator | 1 |
| `web/index.html:739` | U+0394 GREEK CAPITAL LETTER DELTA | HTML text node | "Session Delta" stat label | 1 |
| `web/index.html:1006` | U+2795 HEAVY PLUS SIGN | HTML text node | "Add to Top 8" button | 1 |
| `web/index.html:1351` | U+2715 MULTIPLICATION X | HTML text node | close / clear control | 1 |
| `web/index.html:2343` | U+1F507 SPEAKER WITH CANCELLATION STROKE | HTML text node | voice TTS toggle (muted state) | 1 |
| `web/js/lib/helpers.js:130` | U+26A0 WARNING SIGN | JS string literal | activity icon for "advisory" | 1 |
| `web/js/lib/helpers.js:131` | U+2697 ALEMBIC | JS string literal | activity icon for "analyze" | 1 |
| `web/js/lib/helpers.js:132` | U+03A3 GREEK CAPITAL LETTER SIGMA | JS string literal | activity icon for "summary" | 1 |
| `web/js/lib/helpers.js:133` | U+2726 BLACK FOUR POINTED STAR | JS string literal | activity icon for "prime" | 1 |
| `web/js/lib/helpers.js:134` | U+2261 IDENTICAL TO | JS string literal | activity icon for "digest" | 1 |
| `web/js/lib/helpers.js:135` | U+25C9 FISHEYE | JS string literal | activity icon for "vision" / "screen" | 1 |
| `web/js/lib/helpers.js:136` | U+25B6 BLACK RIGHT-POINTING TRIANGLE | JS string literal | activity icon for "game" | 1 |
| `web/js/lib/helpers.js:137` | U+25E7 SQUARE WITH LEFT HALF BLACK | JS string literal | activity icon for "file" / "ingest" | 1 |
| `web/js/lib/helpers.js:138` | U+265B BLACK CHESS QUEEN | JS string literal | activity icon for "champ" / "pick" | 1 |
| `web/js/lib/helpers.js:139` | U+2022 BULLET | JS string literal | activity icon fallback | 1 |
| `web/js/main.js:3005` | U+2713 CHECK MARK | JS string literal | "Saved" form status | 1 |
| `web/js/main.js:4743` | U+2B06 UPWARDS BLACK ARROW | JS template literal | lobby "promote" button icon | 1 |
| `web/js/main.js:4749,5542` | U+2715 MULTIPLICATION X | JS template literal | lobby "kick" / Top-8 "remove" button icon | 2 |
| `web/js/main.js:5537` | U+2795 HEAVY PLUS SIGN | JS template literal | "Invite to lobby" button icon | 1 |
| `web/js/main.js:5539` | U+25B2 BLACK UP-POINTING TRIANGLE | JS template literal | Top-8 reorder-up button | 1 |
| `web/js/main.js:5540` | U+25BC BLACK DOWN-POINTING TRIANGLE | JS template literal | Top-8 reorder-down button | 1 |
| `web/js/main.js:6285` | U+2665 BLACK HEART SUIT | JS template literal | heartbeat text | 1 |
| `web/js/main.js:6356` | U+26A0 WARNING SIGN | JS template literal | toast warning prefix | 1 |
| `web/js/main.js:7047` | U+2605 BLACK STAR | JS string literal | default-voice marker in the voice picker | 1 |
| `web/js/main.js:7075,7081` | U+1F507 SPEAKER WITH CANCELLATION STROKE | JS string literal | voice toggle, muted | 2 |
| `web/js/main.js:7081` | U+1F50A SPEAKER WITH THREE SOUND WAVES | JS string literal | voice toggle, unmuted | 1 |
| `web/js/panels/item_build.js:448` | U+2713 CHECK MARK | JS string literal | build-variant saved status | 1 |
| `web/js/panels/map_state.js:452` | U+26A0 WARNING SIGN | JS string literal | "ENEMY ZONE" label | 1 |
| `web/js/panels/map_state.js:452` | U+26D4 NO ENTRY | JS string literal | "DEEP ENEMY" label | 1 |
| `web/js/panels/map_state.js:456` | U+2713 CHECK MARK | JS string literal | "SAFE" label | 1 |
| `web/js/panels/next.js:62` | U+25B6 BLACK RIGHT-POINTING TRIANGLE | JS template literal | current-wave marker | 1 |
| `web/js/panels/next.js:150` | U+2713 CHECK MARK | JS string literal | boolean true tag | 1 |
| `web/js/panels/next.js:150` | U+2717 BALLOT X | JS string literal | boolean false tag | 1 |
| `web/legacy_index.html:1473` | U+231B HOURGLASS | HTML text node | champ-select "Hovering" state | 1 |
| `web/legacy_index.html:1473,2925` | U+2713 CHECK MARK | HTML text node | champ-select "Locked" state | 2 |
| `web/legacy_index.html:1653` | U+1F3AF DIRECT HIT | HTML text node | "Pick advice" button | 1 |
| `web/legacy_index.html:1654` | U+1F6AB NO ENTRY SIGN | HTML text node | ban-advice button | 1 |
| `web/legacy_index.html:1655` | U+2694 CROSSED SWORDS | HTML text node | matchup button | 1 |
| `web/legacy_index.html:1655` | U+FE0F VARIATION SELECTOR-16 | HTML text node | emoji presentation selector for the above | 1 |
| `web/legacy_index.html:1656` | U+1F4CA BAR CHART | HTML text node | stats button | 1 |
| `web/legacy_index.html:1657` | U+1F33F HERB | HTML text node | jungle/objective button | 1 |
| `web/legacy_index.html:1658` | U+2728 SPARKLES | HTML text node | augment button | 1 |
| `web/legacy_index.html:1659` | U+26A1 HIGH VOLTAGE SIGN | HTML text node | power-spike button | 1 |
| `web/legacy_index.html:1660` | U+1F4DD MEMO | HTML text node | notes button | 1 |

### 5.3 STRIP-candidate-deferred (152)

A plausible ASCII equivalent exists at low visual cost. **Still deferred** - the
cost is a pixel judgement, and `U+00B7` alone is 107 instances of inline
separator whose replacement changes the rhythm of nearly every meta line on the
dashboard. Proposed replacements below are recommendations for RM-122, not
decisions.

| file:line | Codepoint | Span kind | Rendered context | Proposed ASCII | n |
|---|---|---|---|---|---:|
| `web/css/panels/input_activity.css:224` | U+203A SINGLE RIGHT-POINTING ANGLE QUOTATION MARK | CSS `content:` | user-turn prefix in the input log | `>` | 1 |
| `web/css/panels/map_state.css:202` | U+27E8 MATHEMATICAL LEFT ANGLE BRACKET | CSS `content:` | "ZEN" hotkey hint bracket | `<` | 1 |
| `web/css/panels/map_state.css:202` | U+27E9 MATHEMATICAL RIGHT ANGLE BRACKET | CSS `content:` | "ZEN" hotkey hint bracket | `>` | 1 |
| `web/css/panels/map_state.css:374` | U+2212 MINUS SIGN | CSS `content:` | no-data placeholder | `-` | 1 |
| `web/index.html:373,572,581,604,1021...` | U+00B7 MIDDLE DOT | HTML text node | inline separator in sub-labels | ` - ` | 7 |
| `web/index.html:82,2314,2375,2395` | U+00D7 MULTIPLICATION SIGN | HTML text node | dismiss / clear buttons | `x` | 4 |
| `web/index.html:794,1345` | U+2191 UPWARDS ARROW | HTML text node | "hot streak" label, "pick a champion above" | `^` | 2 |
| `web/index.html:795` | U+2193 DOWNWARDS ARROW | HTML text node | "cold streak" label | `v` | 1 |
| `web/index.html:1957` | U+2192 RIGHTWARDS ARROW | HTML text node | "Review" button trailing arrow | `->` | 1 |
| `web/js/main.js:564,847,1131,1265,1589...` | U+00B7 MIDDLE DOT | JS string literal | inline separator | ` - ` | 23 |
| `web/js/main.js:274,1310,1625,1674,1861...` | U+00B7 MIDDLE DOT | JS template literal | inline separator | ` - ` | 39 |
| `web/js/main.js:1831` | U+00D7 MULTIPLICATION SIGN | JS template literal | "grade x count" tally | `x` | 1 |
| `web/js/main.js:6125` | U+22EF MIDLINE HORIZONTAL ELLIPSIS | JS string literal | "chars elided" truncation marker | `...` | 2 |
| `web/js/main.js:6653` | U+2190 LEFTWARDS ARROW | JS template literal | dev-mode keyboard hint | `<-` | 1 |
| `web/js/main.js:353,535,545,1530,6653` | U+2192 RIGHTWARDS ARROW | JS template literal | status transitions, keyboard hint | `->` | 5 |
| `web/js/main.js:1653,1672,1688,1696,2508` | U+2191 UPWARDS ARROW | JS string literal | trend-up indicator | `^` | 5 |
| `web/js/main.js:1654,1672,1688,1696` | U+2193 DOWNWARDS ARROW | JS string literal | trend-down indicator | `v` | 4 |
| `web/js/panels/augment_reco.js:142` | U+00B7 MIDDLE DOT | JS string literal | inline separator | ` - ` | 1 |
| `web/js/panels/dev.js:303,304,575,628` | U+00B7 MIDDLE DOT | JS template literal | dev record meta separator | ` - ` | 10 |
| `web/js/panels/item_build.js:178` | U+00B7 MIDDLE DOT | JS string literal | inline separator | ` - ` | 1 |
| `web/js/panels/item_build.js:185,186,209,210,214...` | U+00B7 MIDDLE DOT | JS template literal | inline separator | ` - ` | 7 |
| `web/js/panels/item_build.js:156` | U+2192 RIGHTWARDS ARROW | JS string literal | build-step arrow | `->` | 1 |
| `web/js/panels/last_match.js:614` | U+00B7 MIDDLE DOT | JS template literal | inline separator | ` - ` | 1 |
| `web/js/panels/last_match.js:616` | U+00B7 MIDDLE DOT | JS string literal | inline separator | ` - ` | 1 |
| `web/js/panels/map_state.js:439,440,674` | U+00B7 MIDDLE DOT | JS template literal | ZOI debug meta separator | ` - ` | 4 |
| `web/js/panels/map_state.js:699` | U+00B7 MIDDLE DOT | JS string literal | inline separator | ` - ` | 1 |
| `web/js/panels/next.js:151` | U+00B7 MIDDLE DOT | JS template literal | inline separator | ` - ` | 1 |
| `web/js/panels/next.js:173` | U+00B7 MIDDLE DOT | JS string literal | inline separator | ` - ` | 1 |
| `web/js/panels/next.js:36,37,38,39,227...` | U+2192 RIGHTWARDS ARROW | JS string literal | action labels, e.g. "DISENGAGE" | `->` | 9 |
| `web/js/panels/next.js:66` | U+2192 RIGHTWARDS ARROW | JS template literal | wave-state arrow | `->` | 1 |
| `web/js/panels/right_now.js:330,362,410,423` | U+00B7 MIDDLE DOT | JS template literal | inline separator | ` - ` | 4 |
| `web/js/panels/right_now.js:441` | U+2212 MINUS SIGN | JS template literal | negative-value display | `-` | 1 |
| `web/js/panels/team_context.js:207,209` | U+00B7 MIDDLE DOT | JS string literal | inline separator | ` - ` | 2 |
| `web/legacy_index.html:951` | U+0081 (C1 control, no name) | HTML text node | **corruption, see below** | delete the control char | 1 |
| `web/legacy_index.html:1453,1456,1473,1535` | U+00B7 MIDDLE DOT | HTML text node | inline separator | ` - ` | 4 |
| `web/legacy_index.html:1318,1763` | U+2192 RIGHTWARDS ARROW | HTML text node | inline arrow | `->` | 2 |

#### `web/legacy_index.html:951` is corruption, not design

```css
.gl-mini-action:empty::before { content: '\u00814'; color: var(--dim); }
```

The `content:` value is `U+0081` (a non-printing C1 control character with no
Unicode name) followed by the ASCII digit `4`. `U+0081` has no glyph; this is
mojibake, almost certainly the surviving half of a character mangled by an
ANSI/UTF-8 round trip - the same failure class the repo's no-em-dash rule exists
to prevent. It is filed as STRIP-candidate only because it sits on a rendered
span; it is not a Terminal-theme glyph and no visual intent is being preserved
by keeping it. Whatever the original glyph was is not recoverable from the file.
RM-122 should decide what this placeholder is meant to show rather than pick an
ASCII equivalent for `U+0081`.

---

## 6. SUMMARY

| Disposition | Count | Share of 235 |
|---|---:|---:|
| STRIP-candidate-deferred | 152 | 65 pct |
| KEEP-deliberate-UI-glyph | 52 | 22 pct |
| LOAD-BEARING | 31 | 13 pct |
| **Total rendered live residue** | **235** | 100 pct |

Plus 85 characters that the tool counts as live but that render nothing
(59 via the section-3 defect, 26 via the documented `_scan_html` boundary),
reconciling to the tool's reported 320.

`U+00B7 MIDDLE DOT` is the single dominant glyph at 107 of 235 (46 pct) and is
uniformly an inline separator. If RM-122 wants one decision with maximum
coverage and minimum risk, that is it.

### ROUTING

**The whole set is deferred to RM-122.** Every remaining row needs
operator-present, rendered-pixel judgement:

- **LOAD-BEARING (31)** must not be touched as a hygiene matter at all. If any
  of these ever change, the change is a behaviour change with a regression test,
  not a sweep. The `right_now.js` producer/matcher coupling (5.5) means a
  partial edit is worse than no edit.
- **KEEP-deliberate-UI-glyph (52)** is a design call about the Terminal theme's
  iconography. These are icons standing in for affordances (close, refresh,
  mute, warning, heartbeat); the ASCII substitutes cost recognisability and, for
  the button glyphs, hit-target legibility at the dashboard's viewing distance.
- **STRIP-candidate-deferred (152)** is the only tranche with a plausible
  mechanical fix, and it is still a pixel judgement: it changes the rhythm of
  inline meta lines across nearly every panel, so it needs the 5-phase UI
  fixture audit, not a script.

Stripping any of this headless is forbidden. RM-125 stays **OPEN** solely for
this residue; its comment half is closed at `35c6730f`.

---

## 7. NOTE on `web/legacy_index.html` (19 rendered characters)

**It is not dead.** It is reachable on two live paths, both in
`dashboard/routes_static.py:23-46`:

1. Explicit opt-in: any URL carrying `ui=legacy`, i.e.
   `https://legion-rc:8888/?ui=legacy`.
2. Automatic fallback: `_serve_index` tries `web/index.html` first and, on any
   exception reading or hashing it, logs a warning and serves
   `legacy_index_html()` instead.

The file is read and cached by `dashboard/_static.py:103-111`. The in-code
comment states the intent plainly: keep the legacy inline dashboard reachable
"in case the new one misbehaves during a live match" - which is precisely the
moment a broken fallback would cost the most.

Two consequences:

- Its 19 rendered glyphs are real rendered pixels on a real code path and belong
  in the RM-122 set on the same footing as `index.html`'s. They are not
  exempt-because-legacy.
- An older note in `docs/history_notes.md:8755` describes a "dead
  `legacy_index.html` `/api/bridge` UI". That referred to a removed *section* of
  the page, not the page. Do not read it as "the file is dead" - verified
  against the routing above on 2026-07-28.

Separately, 26 further non-ASCII characters sit in CSS comments inside this
file's inline `<style>` block and render nothing (section 2). Those are a
sweeper-reach question for a `tools/` slice, not a pixel question.

**Recommendation:** whether `legacy_index.html` should still exist at all is a
worthwhile question - it is a second, drifting copy of the dashboard kept alive
only as a panic fallback - but it is a **deletion question, not a glyph
question**. It should be filed separately and decided on its own merits. Until
it is deleted, treat its glyphs as live.
