# win32-atomic-io

Atomic file writes and a tolerant JSON read, for files that one process writes
and other processes poll. Stdlib only, no dependencies, no configuration.

```python
from win32_atomic_io import atomic_write_json, read_json_dict

atomic_write_json(path, {"state": "running", "pid": 1234})
state = read_json_dict(path, default={"state": "unknown"})
```

## The problem

A plain `open(path, "w")` truncates the destination in place. A reader that
arrives during the write parses a half-written file, so a polling consumer sees
a `JSONDecodeError` at random. The standard fix is write-to-scratch-then-rename,
because `os.replace` is atomic: a reader sees either the whole old file or the
whole new one.

That is the easy half. The hard half is that three details are load-bearing on
Windows, all three are easy to get wrong, and each one fails intermittently
rather than loudly.

## What this package actually gets right

**1. `os.replace` is not reliable on Windows, it is USUALLY reliable.**
It raises `PermissionError` (WinError 5) when a concurrent reader holds the
destination open - the share-lock window is normally well under 100 ms. On a
file that is polled by design, that contention is routine rather than
exceptional, so the correct handling is a bounded retry with backoff
(`0.025 / 0.05 / 0.2` seconds, about 275 ms worst case) and then a re-raise.
Without it the writer crashes occasionally, under load, and never in a test.

**2. The scratch file name has to be PER WRITER.**
The obvious name is `path.with_suffix(path.suffix + ".tmp")` - derived from the
destination alone. Every writer of a given file then opens the *same* scratch
file, and two concurrent writers interleave inside it: B truncates and renames
the scratch while A is still filling it, and A's remaining bytes land in the
published destination. The result is a torn file, which is the exact failure a
tmp+rename writer exists to prevent. So the scratch name carries the process id
and a random suffix: the pid because the competing writers are often separate
*processes*, which is the case no in-process lock can serialize, and the random
suffix for concurrent writers inside one process.

Worth knowing when you go looking for this bug: the DETECTION is probabilistic
even though the defect is not. Two threads writing one file produced a handful
of torn reads across a few hundred writes; the same experiment run again may
see zero. That is why the tests here assert the *structural* property - two
calls yield distinct names - rather than trying to observe tearing.

**3. The scratch file is a SIBLING of the destination, not a temp-dir file.**
`os.replace` is only atomic within one filesystem. A scratch file under the
system temp directory may sit on another volume, and the rename then degrades
into a copy that is not atomic at all.

**4. Encoding happens before the write, never via `Path.write_text`.**
On Windows `write_text` rewrites LF as CRLF, so an indented JSON payload puts
more bytes on disk than the caller serialized. `read_text` undoes it on the way
back, which is what makes this so easy to miss: the round-trip looks perfect and
only a byte count, a size cap, or a digest disagrees. Every writer here encodes
to `bytes` and writes bytes.

**5. No RAISED exception leaves the scratch file behind.**
An exhausted retry re-raises, and the cleanup runs first. This matters more with
a per-writer name than without one: a fixed scratch name is reused by the next
write, but a per-writer orphan is unbounded litter. The handler catches
`BaseException`, not `Exception`, so a `KeyboardInterrupt` mid-write does not
leave a stray file either.

The honest scope is exactly that, and no wider: cleanup is a `finally`-shaped
guarantee, so it covers every path that unwinds the stack and none that does
not. A `SIGKILL`, a `taskkill /F`, or a power loss between the
`write_bytes` and the rename strands a `<name>.<pid>.<hex>.tmp` sibling
permanently - the process is gone before any handler runs. This package ships
no orphan sweep, so nothing removes such a file later, and because the name
carries a pid and a random suffix, no subsequent write will reuse it either.
If your deployment is killed hard as a matter of routine, sweep the
destination's directory for that pattern yourself.

**6. `read_json_dict` returns the default for EVERY degraded input.**
Missing file, a directory in the file's place, non-UTF-8 bytes, malformed JSON,
and valid JSON that is not an object all yield the default. The non-UTF-8 case
needs its own handler and is the one usually missed: decoding raises
`UnicodeDecodeError`, which is a `ValueError` and **not** an `OSError`, so a
single `except OSError` lets a corrupt file crash the caller instead of
degrading.

Returning the default is not the same as reporting it, and the split is worth
knowing before you rely on the logs. **Three of those five log a warning** to
the `win32_atomic_io` logger: non-UTF-8 bytes (`_atomic.py:168`), malformed
JSON (`:173`), and valid JSON that is not an object (`:176`). **Two are
silent** - the missing file and the directory in the file's place, which share
the one `except OSError` branch at `:160-162`.

That branch is the operational blind spot, and it is wider than "absence is
normal" suggests. Absence genuinely is normal for a polled file, which is why
the branch does not log - but `OSError` is also what you get for a directory
sitting where the file should be, for a file locked by another process, and for
a permissions failure. None of those are normal, and all three are swallowed
with no record, presenting to the caller as an indistinguishable "no data yet".
A reader that silently returns its default forever is therefore a real possible
state. If you need to tell "not written yet" from "cannot be read", check for
the file yourself before calling, or watch for a default that never resolves.

**7. The default is returned as a DEEP copy.**
A shallow `dict(default)` shares every nested mutable with the caller's own
default object and with every later call, so appending to a returned
`{"log": []}` silently poisons every subsequent read. One consequence is
deliberate and worth stating plainly: `deepcopy` raises `TypeError` on a default
holding an uncopyable value such as a lock or a socket, where the old shallow
copy quietly succeeded. This is a JSON module - such a default is a programming
error, and surfacing it beats copying a live handle into what callers treat as
inert data.

## API

| Function | Behaviour |
| --- | --- |
| `atomic_write_json(path, payload, *, indent=2)` | `json.dumps` then atomic byte write. `ensure_ascii=False`. |
| `atomic_write_bytes(path, data)` | Atomic byte write. Use this whenever the byte count matters. |
| `atomic_write_text(path, content)` | UTF-8 encode then atomic byte write. |
| `read_json_dict(path, default=None) -> dict` | Always returns a `dict`; a deep copy of `default` (or `{}`) on any degraded input. |

Every writer creates parent directories on demand.

## Portability, and what the retry actually costs

None of this is Windows-only in the sense of failing elsewhere. It runs
correctly on POSIX, and the CRLF concern genuinely does not arise there. The
name records where the sharp edges are, not where it runs.

**The retry is not Windows-gated, though, and it is worth being precise about
that rather than claiming it "never fires" off Windows.** `_atomic.py:51`
catches a bare `PermissionError` and inspects neither `winerror` nor `errno`,
so any `PermissionError` from `os.replace` enters the backoff loop on every
platform. On POSIX an `EACCES` or `EPERM` - a read-only parent directory, a
sticky-bit directory owned by someone else, a mandatory-lock setup - raises
`PermissionError` and therefore DOES fire the retry.

The cost is the same on both platforms and applies to genuine denials as much
as to transient contention: a permission error that will never clear costs four
attempts and about 275 ms of `time.sleep` (`0.025 + 0.05 + 0.2`) before the
original exception is re-raised. On Windows a real ACL denial pays exactly that
before surfacing. It is bounded and it is not silent - the error still reaches
the caller unchanged - but a caller in a tight write loop against a directory
it may not write to will spend most of its time asleep, and it will not look
like a permissions problem from the outside.

Narrowing the catch to the transient sharing-violation case is the obvious
refinement, and it is not done here: it is a behaviour change rather than a
documentation fix, so it needs its own decision and its own tests instead of
arriving as a side effect of correcting this paragraph. Until then, treat the
paragraph above as the contract - bounded retry on any `PermissionError`, about
275 ms, then the real error.

## What is deliberately NOT here

A thread-safe wrapper class - one object owning a path, a default and a lock,
with `read` / `write` / `write_field` / `update` methods - exists in the
original module and is **excluded from this package on purpose**. It has zero
production instantiations in its home codebase: measured by grep over every
tracked `.py` file, nothing outside its own test module constructs it, and the
decision to adopt or remove it is still open. An unadopted surface is not
something to publish; the three module-level writers and the reader carry all
the real traffic. It also carries a caveat that only bites once it is adopted:
its lock is per-instance, not per-path, so two instances built for the same
path do not serialize against each other, which makes it easy to mistake for a
cross-process guarantee that it never provided.

## Status

Extracted, in-tree, not yet published to an index. It sits here as a package
*shaped* so that it could be. It is licensed and redistributable today - see
the License section below.

## Tests

```
python -m pytest tests -q
```

Covers round-trips and parent creation, exact byte counts on payloads
containing newlines (asserted on bytes, not on round-tripped text - text hides
the CRLF rewrite), distinct-and-sibling scratch names, the retry succeeding on
a later attempt and re-raising once the delays are exhausted, no scratch file
left behind when a write raises, every degraded read yielding the default, the
deep copy not aliasing, and the deliberate `TypeError`.

## License

**Apache License 2.0.** This package is part of a repository that is licensed
under the Apache License, Version 2.0, and it is distributed under those terms.
The full text is in the `LICENSE` file beside this README.

That file is a byte-for-byte copy of the repository root's `LICENSE`, kept here
so the directory is self-contained: a `tar` or `cp -r` of this directory alone
carries its own grant rather than arriving with none. The copy is verbatim,
including its copyright line, which names a real grantor - an unrendered
template reading `Copyright (c) {{ year }} {{ organization }}` would be a grant
with no grantor, which passes a naive SPDX grep while conveying nothing.

### What you must do to redistribute

Taken from the conditions in section 4 of the accompanying `LICENSE`, which is
the authority if this summary and that text ever disagree:

- **Give recipients a copy of the License** (section 4a). Ship the `LICENSE`
  file with whatever you distribute, in source or object form.
- **Mark what you changed** (section 4b). Any file you modify must carry a
  prominent notice stating that you changed it.
- **Keep the attribution notices** (section 4c). In the source form of a
  derivative work, retain the copyright, patent, trademark and attribution
  notices found in the source you started from, except those that do not
  pertain to any part of your derivative work.
- **Carry the NOTICE text forward** (section 4d). Where the work you took
  includes a `NOTICE` file, a readable copy of the attribution notices in it
  must travel with your derivative work - in your own `NOTICE`, in the source
  or documentation, or in a display the work generates. Again you may drop the
  entries that do not pertain to any part of what you are distributing.

You get a patent grant under section 3, and it terminates if you bring a patent
suit alleging the work infringes. The work is provided **as is**, with no
warranties or conditions of any kind (sections 7 and 8).

### About the repository NOTICE file

The repository root ships a `NOTICE` file. **No entry in it covers any content
of this package.** Every third-party entry in that file concerns bundled *data
files*, which live in a directory this package does not contain and does not
read; this package is authored source and documentation only, with a stdlib-only
dependency set. The `NOTICE` also carries a general product attribution line and
a trademark disclaimer for the surrounding project - neither describes anything
in this directory.

That is exactly the "excluding those notices that do not pertain" clause in
section 4d doing its work, so no copy of that `NOTICE` is kept here. It is a
deliberate omission rather than an oversight: copying in attribution for data
this package does not ship would be misleading in the other direction.

### If this package is ever split out to stand alone

It must keep the `LICENSE` file that is already beside this README - a
standalone copy with the license stripped out would ship with no grant at all,
which is the failure this section exists to prevent. If the surrounding
repository's `NOTICE` has by then grown an entry that genuinely does pertain to
this package's own content, that entry must come along too, as a `NOTICE` file
in the split-out tree. As of this writing there is no such entry.
