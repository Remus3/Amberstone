# LF writer direct-test coverage census (RM-410 slice 2)

Date: 2026-09-11. Measured in worktree
`C:\Riot Commander\.claude\worktrees\agent-a06a1360ddc13c2f7` at HEAD
`8ad4b66780c3aa0ea2f8bc48dae1fb9b1cb36e44` (`8ad4b6678`), then every citation
was RE-RESOLVED by an independent verifier against the merge target
`ca6f42554`. Two `docs/ORCHESTRATION_PLAN.md` line numbers moved by +1 between
those two commits (`23c1bca31` inserted one line, 924 -> 925) and carry their
corrected values below; the quoted text was byte-identical at both.

Scope: the six tracked-JSON/text producers enumerated by
`tests/test_tracked_json_producers_emit_lf_bytes.py` `_PRODUCERS` (`:63-79`).
Nothing outside that table is in scope, by instruction.

## The instance count is SIX, measured

```
python -c "import ast; t=ast.parse(open('tests/test_tracked_json_producers_emit_lf_bytes.py',encoding='utf-8').read()); print([len(n.value.elts) for n in ast.walk(t) if isinstance(n,ast.Assign) and getattr(n.targets[0],'id','')=='_PRODUCERS'])"
-> [6]
```

Corroborated by collection, which yields 3 parametrised tests x 6 rows plus 2
unparametrised tests = 20:

```
python -m pytest tests/test_tracked_json_producers_emit_lf_bytes.py --collect-only -q -p no:randomly
-> 20 tests collected in 0.15s
```

The table's own anchor pins the same number: `:123` `assert len(_PRODUCERS) == 6`.

All six are disposed of below. None is left open.

## The guard's behavioural half DOES run every producer

This is the correction that drives the whole census. The class guard is NOT
attributes-only:

- `:113-117` `_invoke` calls the real function - `:115` `fn(target, _PAYLOAD)`.
- `:129-150` `test_producer_writes_lf_bytes` is parametrised over all six rows
  (`:129-130`), reads the real bytes at `:137` `raw = out.read_bytes()`, and
  asserts `:141` `pairs == 0` and `:146` `assert b"\r" not in raw`.
- `:132` docstring: "The behavioural half - run the real function, read the
  real bytes."

Measured this run:

```
python -m pytest tests/test_tracked_json_producers_emit_lf_bytes.py -q -p no:randomly -k fetch
-> 3 passed, 17 deselected in 0.67s
```

So every one of the six producers already has direct, behavioural CRLF
coverage. The open question per row is only what the guard is blind to.

## The guard's real limit, in one sentence

It asserts zero CRLF for a payload it chooses, plus source shape
(`:155-171`, no `.write_text(` in the executable body) and target git
attributes (`:176-194`, `git ls-files --error-unmatch` plus
`git check-attr eol` = lf) - so it is blind to encoding or formatting changes
that still parse (its only content check is `:148` `json.loads(...) == _PAYLOAD`),
to tmp-file and atomicity behaviour, and to any defect a compact-separator
payload cannot express.

## Census

| # | Producer `file:line` | Representative tracked target | CRLF coverage (guard row) | Additional direct test | Disposition |
|---|---|---|---|---|---|
| 1 | `tools/ddragon_mirror_refresh.py:188` `_atomic_write_json` | `data/meta_build/ddragon/_index.json` (`tests/test_tracked_json_producers_emit_lf_bytes.py:65`) | id `ddragon_mirror_refresh._atomic_write_json`, `tests/test_tracked_json_producers_emit_lf_bytes.py:129-150` | `tests/test_ddragon_mirror_writes_bytes.py:21,33,42,51` | COVERED |
| 2 | `lib/ddragon/fetch.py:33` `_atomic_write_json` | `data/meta_build/ddragon/16.18.1/champion.json` (`:67`) | id `fetch._atomic_write_json`, same `:129-150` | `tests/test_ddragon_fetch_writer_emits_lf.py:101,110,119,136,159,166` (lands in the SAME commit as this audit - see note) | COVERED |
| 3 | `tools/daemon_slayer_extract.py:121` `_atomic_write_json` | `data/daemon_slayer/16.15.1/champions.json` (`:69`) | id `daemon_slayer_extract._atomic_write_json`, same `:129-150` | NONE | PARTIAL - CRLF only |
| 4 | `tools/daemon_slayer_extract.py:137` `_atomic_write_text` | `data/daemon_slayer/current.txt` (`:71`) | id `daemon_slayer_extract._atomic_write_text`, same `:129-150` | NONE | PARTIAL - CRLF only |
| 5 | `tools/daemon_slayer_abilities_extract.py:283` `_atomic_write_json` | `data/daemon_slayer/16.15.1/champion_abilities.json` (`:73`) | id `daemon_slayer_abilities_extract._atomic_write_json`, same `:129-150` | NONE | PARTIAL - CRLF only |
| 6 | `core/polled_json.py:113` `atomic_write_json` | `data/daemon_slayer/16.15.1/items.json` (`:78`) | id `polled_json.atomic_write_json`, same `:129-150` | `tests/test_polled_json_lane8_cycle24.py:61,68`; `tests/test_p2w1_core_f.py:45,67` | PARTIAL - no byte pin |

The parametrised ids are generated at `:130` / `:154` / `:175` as
`f"{m.split('.')[-1]}.{a}"` and were read back from the collection output
above, not inferred.

### Row notes

**Row 1 - COVERED.** `tests/test_ddragon_mirror_writes_bytes.py` imports the
writer at `:21` and drives it directly in three tests: `:33` CRLF count zero
plus no bare CR, `:42` exact byte pin against
`json.dumps(..., indent=2, sort_keys=True) + "\n"` encoded utf-8, `:51`
`st_size` equals the encoded length. That covers the guard's blind spot on
encoding and formatting for this producer.

**Row 2 - COVERED, with a provenance note.**
`tests/test_ddragon_fetch_writer_emits_lf.py` holds 6 tests (measured:
`grep -c "^def test_"` -> 6) adding the five properties the guard does not
assert: exact compact-encoding byte pin (`:110-116`), the measured
no-literal-LF-in-a-compact-dump finding (`:119-133`), the `indent=2` positive
control (`:136-156`), no surviving `.tmp` (`:159-163`), and an `os.replace`
fault injection proving a pre-existing target keeps its bytes (`:166-187`).
PROVENANCE, verified rather than assumed: at the moment this audit was written
that file was absent from the audit's worktree and unreachable from any git ref
(`git log --all --oneline -- tests/test_ddragon_fetch_writer_emits_lf.py`
returned empty at `8ad4b6678`) - it existed only as an uncommitted file in the
operator's main checkout, 8760 bytes. It is committed together with this audit,
so the `:NN` citations resolve at that commit and later, not before it.

**Rows 3, 4, 5 - PARTIAL, CRLF only.** No test anywhere in `tests/`,
`tools/tests/` or `agents/daemon_slayer/tests/` imports or calls
`tools.daemon_slayer_extract._atomic_write_json`,
`tools.daemon_slayer_extract._atomic_write_text` or
`tools.daemon_slayer_abilities_extract._atomic_write_json`. The nearest hits
are both static source scans rather than calls:
`agents/daemon_slayer/tests/test_artifact_patch_marker_guard.py:372-383`
`read_text`s `tools/daemon_slayer_extract.py` and matches the STRING
`"_atomic_write_json"` inside its source lines to check each write site is
stamped, and `tests/test_atomic_write_fault_injection_is_portable.py:71-81`
names `"_atomic_write_json"` / `"_atomic_write_text"` in an `_ATOMIC_WRITERS`
frozenset that an `ast` guard matches against - that file imports only
`ast`/`pathlib`/`pytest`, so it never calls a writer. Neither proves anything
about bytes. Other DS tests import unrelated symbols from the abilities
extractor (`agents/daemon_slayer/tests/test_abilities_content_freshness.py:25`,
`agents/daemon_slayer/tests/test_nested_hp_parser_s223.py:39`,
`agents/daemon_slayer/tests/test_unit_variants_s224.py:40`) and never the
writer. Missing for these three: an exact byte pin, tmp-file / atomicity
behaviour, and fault injection - the same five properties row 2 added.

**Row 6 - PARTIAL, no byte pin.** `core/polled_json.atomic_write_json` has
dedicated direct tests, but not for bytes.
`tests/test_polled_json_lane8_cycle24.py:61-71` round-trips through
`read_text`, which is precisely the call that hides a CRLF defect; its only
byte-level assertion (`:84`) is against `atomic_write_bytes`, a different
function, and `:74` likewise drives `atomic_write_text`, so neither pins this
row's writer. `tests/test_p2w1_core_f.py:45-77` drives the `os.replace` retry
and re-raise. So atomicity and retry are directly covered, CRLF is covered by
the class guard alone, and the exact-encoding pin
(`json.dumps(payload, indent=2, ensure_ascii=False)` per
`core/polled_json.py:123-124`) is asserted nowhere. No test file in the tree
asserts a raw CRLF count against this writer - the only two files that assert
a CRLF count on real writer bytes at all are
`tests/test_ddragon_mirror_writes_bytes.py:37-38` and
`tests/test_base_coach_rm287_lf_bytes.py:83`, and the latter drives
`coaches/_base_coach.safe_write` (`:51-55` `_write_artifact`), not
`polled_json`.

## `data/meta_build/ddragon/16.18.1/_assets_manifest.json` - disposition

OUT OF SCOPE for the tracked-LF guard, and left byte-for-byte alone by this
audit. All three facts re-measured here, not copied, and each re-measured a
second time by the verifier with identical results:

- UNTRACKED. `git ls-files -- data/meta_build/ddragon/16.18.1/_assets_manifest.json`
  returns nothing; `git ls-files --error-unmatch <same>` exits 1 with
  "did not match any file(s) known to git".
- GITIGNORED. `git check-ignore -v` exits 0 and names the rule:
  `.gitignore:160:data/meta_build/ddragon/*/_assets_manifest.json`.
- 42318 CRLF pairs, from a pre-fix run. Measured on the only copy that exists
  (`C:\Riot Commander\data\meta_build\ddragon\16.18.1\_assets_manifest.json`;
  the file is absent from the audit worktree, as an untracked path must be):
  1839391 bytes, `raw.count(b"\r\n")` = 42318, `raw.count(b"\r")` = 42318,
  `raw.count(b"\n")` = 42318 - every newline in the file is a CRLF, none bare.

Because it is untracked, git never normalizes it, so it is outside the
universe of `test_no_tracked_eol_pinned_file_currently_carries_crlf`
(`tests/test_tracked_json_producers_emit_lf_bytes.py:197-229`), which filters
to `git check-attr text` = set. It is regenerable by
`tools/ddragon_mirror_refresh.py:309` (`_assets_manifest.json` path helper) on
the next mirror run, and its bytes are NOT to be rewritten by hand.

## What the ORCHESTRATION_PLAN tail gets wrong

`docs/ORCHESTRATION_PLAN.md:916-919` (at `ca6f42554`; `:915-918` at
`8ad4b6678`) still reads:

> **KNOWN AND NOT CLOSED, stated rather than buried.** `lib/ddragon/fetch.py`
> now ships its writer as bytes but is still exercised by no test of its own -
> the four tests that import it drive `_pull` and pruning, never the writer - so
> it is carried in the new class guard's table and nowhere else.

Refuted by the guard the same commit added. `c00b9af89` created both
`tests/test_tracked_json_producers_emit_lf_bytes.py` (+229 lines, per
`git show --stat c00b9af89`) and this sentence. The row at
`tests/test_tracked_json_producers_emit_lf_bytes.py:66-67` is consumed by a
BEHAVIOURAL test, not a static table: `:115` `fn(target, _PAYLOAD)` calls the
writer, `:137` `raw = out.read_bytes()` reads what it produced, `:141` and
`:146` assert on those bytes. The sentence therefore SELF-STALED inside its
own commit - the author treated a table row as inert data when it is a call
site. "Carried in the class guard's table and nowhere else" is true as
bookkeeping and false as coverage.

Second half of the same paragraph (`:920-923` at `ca6f42554`, running to
`:925`; `:919-922` at `8ad4b6678`) is the `_assets_manifest.json` claim. It is
CORRECT and re-measured above: untracked, 42318 CRLF pairs.

Correction APPLIED by the merger in the same commit as this audit (the audit
slice itself owned exactly one new file and could not touch the plan): the
struck sentence now says the writer is exercised behaviourally by the class
guard's `fetch._atomic_write_json` row, and that the dedicated file adds the
byte pin, tmp and fault-injection properties the guard cannot assert. That
edit shifts the `:916-925` line numbers quoted above, which are pinned to
`ca6f42554` on purpose - they are where the stale text lived, not where the
correction lives.

## Defect-class census - process-wide destructive stdlib patches (R230, 2026-09-11)

RM-410's fault-injection arm patched `os.replace` PROCESS-WIDE for the duration
of one test. R230 retargeted that one site and then censused the class, because
a single scoped fix is worth nothing if the shape is common.

### The exact command

```
grep -rn "monkeypatch.setattr(" --include=*.py tests/ agents/daemon_slayer/tests/ tools/tests/ agents/agent3_testing/suite | grep -E "os, \"(replace|remove|rename|unlink)\"|\.os, \"|shutil|builtins, \"open\""
```

Run twice: once by the orchestrator BEFORE the edit, once by the verifier AFTER.

### The counts, and why they differ by one

- PRE-EDIT: **29 lines, all 29 real call sites.**
- POST-EDIT: **30 lines, of which 29 are real call sites and 1 is PROSE.**

The extra line is `tests/test_ddragon_fetch_writer_emits_lf.py:188`, a net-new
DOCSTRING line that names the pattern it is documenting. The census grep matched
its own documentation. Worth stating plainly rather than reconciling silently:
**a census whose pattern appears in the prose describing the census will drift
upward every time someone documents it**, and the drift is indistinguishable
from a real new call site by count alone. Read the matched line, never the
tally.

### The DESTRUCTIVE subset - 8 call sites across 6 files

Narrowing to patches of a destructive filesystem primitive
(`replace` / `remove` / `rename` / `unlink`):

| # | Site | Patch target | Disposition |
|---|---|---|---|
| 1 | `tests/test_ddragon_fetch_writer_emits_lf.py:222` | `fetch_mod.os, "replace"` | **FIXED this cycle** - destination-scoped shim that delegates to a pre-captured `_real_replace` |
| 2 | `tests/test_inbox_responder_export.py:276` | `export_mod.os, "rename"` | OUT OF SCOPE - filed RM-411 |
| 3 | `tests/test_p2w1_core_f.py:58` | `polled_json.os, "replace"` | OUT OF SCOPE - filed RM-411 |
| 4 | `tests/test_p2w1_core_f.py:73` | `polled_json.os, "replace"` | OUT OF SCOPE - filed RM-411 |
| 5 | `tests/test_p2w1_core_f.py:93` | `polled_json.os, "replace"` | OUT OF SCOPE - filed RM-411 |
| 6 | `tests/test_p2w2_ds_h.py:296` | `common.os, "replace"` | OUT OF SCOPE - filed RM-411 |
| 7 | `tests/test_polled_json_lane8_cycle24.py:224` | `polled_json.os, "replace"` | OUT OF SCOPE - filed RM-411 |
| 8 | `tests/test_rofl_archive_lane8_download_bounds.py:259` | `os, "replace"` - the STDLIB module object directly, no handle at all | OUT OF SCOPE - filed RM-411 |

Every one of the eight has a disposition. Seven remain, across five files.

### Why the remainder was filed rather than swept

The directive's threshold routes a class to a filed id once the instance count
exceeds 5. The destructive subset is **8**, above that line, so sweeping it
in-cycle would have meant seven unrelated test files in a wrap slice. Filed as
RM-411 under BACKLOG "Reliability / hardening" instead.

### A module-attribute handle is NOT containment

`setattr(mod.os, "replace", ...)` LOOKS narrower than `setattr(os, "replace",
...)`. It is not. `mod.os` is a reference to the one stdlib `os` module object,
so rebinding an attribute on it rebinds it for every importer in the process.
Proved by identity, not argued:

- `lib.ddragon.fetch.os is os` -> `True`
- `core.polled_json.os is os` -> `True`
- `agents._supervisor_common.os is os` -> `True`
- `tools.inbox_responder_export.os is os` -> `True`

Four of four. The handle spelling is cosmetic. Site 8 in the table above drops
the pretence entirely and patches `os` itself.

The exposure is not theoretical in these files: **`tests/test_p2w1_core_f.py:30`,
`tests/test_polled_json_lane8_cycle24.py:49` and `tests/test_p2w2_ds_h.py:47`
each `import threading`**, so same-process concurrent callers exist in the very
files doing the patching.

### REFUTED: the directive's stated reason for this work

R230 justified the retarget with "Serial run contains it; this repo runs `-n 8`".
**That mechanism is WRONG and is recorded here so nobody re-files it.**
pytest-xdist workers are separate PROCESSES, and each worker runs its own tests
SERIALLY. `-n 8` therefore does not widen the exposure at all - it gives you
eight independent processes, each with its own `os` module object.

The real exposure window is other callers **inside the SAME process** during the
patched interval, background threads above all. The fix is still correct and was
still worth shipping. The reason given for it was not. A directive can order the
right work for a refuted reason, and the refutation has to be written down or
the wrong mechanism propagates into the next filing.

### The proven-safe remedies

1. **Destination-scoped delegating shim** -
   `tests/test_ddragon_fetch_writer_emits_lf.py:211-222`. Capture
   `_real_replace = os.replace` BEFORE patching; raise only when the resolved
   destination is `tmp_path` or under it; delegate everything else. The armed
   window carries a CONTROL assertion - an `os.replace` into a
   `tempfile.mkdtemp()` directory OUTSIDE `tmp_path` must still succeed, torn
   down in a `finally` with `shutil.rmtree`.
2. **Better, where the fault can be provoked for real: patch nothing.**
   `test_atomic_write_json_surfaces_a_real_replace_failure` (`:247`) uses ZERO
   patching - it pre-creates the destination as a non-empty directory and
   asserts the genuine `OSError`. Caught broadly, because the concrete subclass
   is platform-dependent: Windows raised `PermissionError [WinError 5]`.

### Red-before-green, OBSERVED not asserted

With the shim reverted to its unconditional form:
`1 failed, 6 passed in 1.31s`, and the FIRST failure was the control
`os.replace`. With the scoped form restored: `7 passed in 1.10s`. The control is
the proof; the ordering was observed this run, not reasoned about.

### Characterization, not a fix: the `.tmp` sibling LEAKS

Advisory 2 landed as CHARACTERIZATION. Both fault arms assert that the `.tmp`
sibling SURVIVES. `lib/ddragon/fetch.py:33-44` `_atomic_write_json` is four
statements with no `try` / `finally` and no unlink, so a failed `os.replace`
strands `runesReforged.json.tmp` holding the full compact payload.
`lib/ddragon/fetch.py` was deliberately NOT edited this cycle. **A future
`finally` must flip those assertions deliberately** - they are pinned to
today's behaviour on purpose, so the flip is a decision and not a surprise.

### Gate observed

`pytest tests/test_ddragon_fetch_writer_emits_lf.py tests/test_tracked_json_producers_emit_lf_bytes.py -q -p no:randomly` -> **27 passed in 3.09s**.
ruff clean, `py_compile` clean, 0 non-ASCII bytes in 13954.
