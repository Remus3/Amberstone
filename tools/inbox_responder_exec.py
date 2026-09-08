r"""The responder's deterministic executor: harden, pre-check, exec, scrub, assemble, filter.

WHAT THIS IS FOR. `tools/inbox_responder.py` decides whether a proposed action
is ON the allowlist. This module decides whether an allowlisted action can
actually be RUN, and what may be said about the result. The split is deliberate
and each half is refutable on its own.

The validator judges argv[:2], shell metacharacters and output-redirecting
flags (inbox_responder.py:259-276). That is a correct allowlist of VERBS and it
is provably not a licence to execute: `git diff --no-index API-Key-Claude.txt
README.md` reads a gitignored file and `git ls-remote <url>` reaches the
network, and both pass it. `harden_measure_argv` closes that without touching
the validator - a per-verb EXACT flag allowlist, a positional character
allowlist, and a rule for the only flags that consume a following element, so
the `1` in `-n 1` is never mistaken for a revision or a pathspec.

THE PUBLIC-PROJECTION PRINCIPLE, and why a character allowlist cannot serve it.
Every byte a measure prints must be a projection of bytes already reachable
from `origin/main`. The checkout is not such a set: it carries reflog-only
commits, `refs/stash`, local branches and gitignored files, and a regex that
admits `deadbeef` admits every one of them equally. So `precheck_measure` does
not guess - it ASKS GIT, through the SAME injected runner that executes the
measures. One recorder therefore sees both kinds of call, which is what lets an
arm prove that a HELD measure cost zero measurement processes rather than
merely asserting it.

TWO ENCODE-SITE HANDLERS, BOTH LOAD-BEARING. `scrub_text` encodes with
`surrogatepass`, not `surrogateescape`: the latter covers only U+DC80..U+DCFF
and RAISES on any other lone surrogate, and a model can emit `"\ud800"` as a
JSON escape. Under the wrong handler a model-tainted `Decision.reason` would
turn the scrub into an unhandled UnicodeEncodeError, the cycle into
`runner-failed`, and the note would re-cycle on every tick forever.

NO LITERAL SPAWN LIVES HERE. Every child process goes through
`inbox_responder_procs.popen_capture`, which is the one file the console-flash
guard holds. A census arm in the test file asserts the absence.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Tuple

from tools import inbox_responder_procs as procs

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Grammar names as they appear in the metrics row and in the tag line.
GRAMMAR_A5 = "A5-measurement-only"
GRAMMAR_LATENCY_ONLY = "LATENCY-ONLY"

# A credential helper can raise a GUI prompt under an S4U scheduled task that a
# timeout kills without dismissing, so every interactive path is closed by
# environment rather than by hope. The repo is public, so `ls-remote` needs no
# credential to begin with.
MEASURE_ENV_EXTRA = {
    "GIT_TERMINAL_PROMPT": "0",
    "LC_ALL": "C",
    "GCM_INTERACTIVE": "never",
    "GIT_ASKPASS": "",
    "SSH_ASKPASS": "",
    "GIT_SSH_COMMAND": "ssh -oBatchMode=yes",
    "GIT_CONFIG_NOSYSTEM": "1",
}

# At most two pre-check processes per measure. This is what makes the section
# 11 summed-timeout figure a BOUND rather than an estimate: a measure that
# would need a third is held before any process starts.
PRECHECK_CALLS_PER_MEASURE = 2

MEASURE_STDOUT_CAP = 16384
MEASURE_STDERR_CAP = 2048

# `Decision.reason` is model-tainted; it travels into a row and into a body, so
# it is both scrubbed and bounded.
SCRUB_TEXT_LIMIT = 300

# The output filter's own ceiling. The validator recomputes bytes on the model
# reply (inbox_responder.py:363); this one covers the ASSEMBLED body, which the
# validator never sees.
MAX_ASSEMBLED_BYTES = 200_000

# Verbs that pass the validator's list and are held by the executor THIS BUILD.
# `status --porcelain` prints untracked names; `check-ignore` is vacuous on a
# tracked path and prints a private one on an untracked path.
HELD_VERBS = frozenset({"status", "check-ignore"})

# Per-verb EXACT flag allowlist. Exact strings, never prefixes: a prefix match
# is how `--format=%h %s` quietly becomes `--format=%ae`.
_VERB_FLAGS: Mapping[str, frozenset] = {
    "log": frozenset({"--format=%h %s", "--oneline", "--stat", "--name-only", "--date=iso"}),
    "diff": frozenset({"--stat", "--name-only", "--name-status"}),
    "ls-files": frozenset(),
    "show": frozenset({"--stat", "--name-only", "--format=%h %s"}),
    "cat-file": frozenset({"-t", "-s", "-e", "-p"}),
    "rev-parse": frozenset({"--verify", "--short", "--abbrev-ref"}),
    "for-each-ref": frozenset({"--format=%(refname)"}),
    "ls-remote": frozenset({"--heads", "--tags"}),
}

# The ONLY flags that consume a following element, per verb.
_VALUE_FLAGS: Mapping[str, frozenset] = {
    "log": frozenset({"-n", "--max-count"}),
    "for-each-ref": frozenset({"--count"}),
}
# Their inline forms. `-n` deliberately has none - it was not measured and an
# unlisted spelling is an unknown flag, not a convenience.
_INLINE_VALUE_FLAGS: Mapping[str, frozenset] = {
    "log": frozenset({"--max-count"}),
    "for-each-ref": frozenset({"--count"}),
}
_FLAG_VALUE_RE = re.compile(r"^[1-9][0-9]{0,2}$")

_POSITIONAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@^~-]{0,199}$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_LS_REMOTE_REF_RE = re.compile(r"^refs/[A-Za-z0-9._/*-]+$")

# Verbs that must name at least one revision. A bare `git log` walks HEAD,
# which may be unpushed.
_REV_REQUIRED_VERBS = frozenset({"log", "show", "diff", "cat-file", "rev-parse"})
# Verbs whose FIRST positional is a revision and whose remaining positionals
# are pathspecs. `diff` is excluded: all of its positionals are revisions.
_REV_THEN_PATHS_VERBS = frozenset({"log", "show", "cat-file", "rev-parse"})
_PATHS_ONLY_VERBS = frozenset({"ls-files"})

_PUBLIC_REF_PREFIXES = ("refs/remotes/origin/", "refs/tags/")

FILTER_GATES = {
    "tag-forged", "fence-leak", "traceback", "home-path", "email", "secret",
    "non-ascii", "control-char", "oversize", "grammar-question",
    "target-not-named", "empty-body", "tag-missing", "tag-hop-word",
}

_TAG_MARK = "[RC-RESPONDER]"
_MEASUREMENTS_HEADING = "## Measurements executed by the responder"
_HELD_HEADING = "## Proposed and held"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_HOME_RE = re.compile(
    r"[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}[^\\/\s'\"<>|]+"
    r"|/home/[^/\s'\"<>|]+"
    r"|/Users/[^/\s'\"<>|]+",
    re.IGNORECASE,
)
_SECRET_RE = re.compile(r"sk-ant-[A-Za-z0-9_-]+|ghp_[A-Za-z0-9]+|AKIA[0-9A-Z]{16}")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_QUESTION_RE = re.compile(r"\?\s*$")
_HOP_RE = re.compile(r"\bhop\b")


@dataclass(frozen=True)
class MeasureResult:
    """One executed measure, capped and flagged. Never raises for a process fault."""

    exit_code: Optional[int]
    stdout: bytes
    stderr: bytes
    timed_out: bool
    survived_kill: bool
    kill_skipped: bool
    wall_ms: int
    stdout_truncated: bool
    exc: Optional[str]


# ---------------------------------------------------------------------------
# argv shape - shared by the hardening and the pre-check so the two can never
# disagree about which element is a revision.
# ---------------------------------------------------------------------------


def _split_argv(argv: Sequence[str]) -> Tuple[Optional[str], list, Optional[str]]:
    """Return (verb, positionals, rule) walking flags and their consumed values.

    `rule` is the first hardening refusal encountered, or None. Positionals
    EXCLUDE any element consumed as a value-taking flag's value, which is the
    whole reason this walk is shared: `git log origin/main -n 1` has exactly one
    positional, and `1` is never asked of `merge-base`.
    """
    if isinstance(argv, str) or not isinstance(argv, (list, tuple)):
        return None, [], "executor:argv-shape"
    items = list(argv)
    if len(items) < 2 or not all(isinstance(x, str) for x in items):
        return None, [], "executor:argv-shape"
    if items[0] != "git":
        return None, [], "executor:argv-shape"
    verb = items[1]
    # Spelled against argv so the section 12 mutant needle
    # `if argv[1] in HELD_VERBS:` reaches this branch verbatim.
    if argv[1] in HELD_VERBS:
        return verb, [], "executor:verb-held-this-build"
    if verb not in _VERB_FLAGS:
        return verb, [], "executor:verb"

    allowed = _VERB_FLAGS[verb]
    value_flags = _VALUE_FLAGS.get(verb, frozenset())
    inline_flags = _INLINE_VALUE_FLAGS.get(verb, frozenset())
    positionals: list = []

    i = 2
    while i < len(items):
        item = items[i]
        if not item.startswith("-"):
            positionals.append(item)
            i += 1
            continue
        # Value-taking flag, separated form.
        if item in value_flags:
            if i + 1 >= len(items) or not _FLAG_VALUE_RE.match(items[i + 1]):
                return verb, positionals, "executor:flag-value"
            i += 2
            continue
        # Value-taking flag, inline form.
        if "=" in item and item.split("=", 1)[0] in inline_flags:
            if not _FLAG_VALUE_RE.match(item.split("=", 1)[1]):
                return verb, positionals, "executor:flag-value"
            i += 1
            continue
        # The ls-files pair is ONE entry: `--others` alone lists untracked
        # names, which is exactly what the pre-check exists to prevent.
        if verb == "ls-files" and item == "--others":
            if i + 1 >= len(items) or items[i + 1] != "--exclude-standard":
                return verb, positionals, "executor:flag"
            i += 2
            continue
        if item in allowed:
            i += 1
            continue
        return verb, positionals, "executor:flag"

    return verb, positionals, None


def _positional_rule(verb: str, value: str) -> Optional[str]:
    if ".." in value:
        return "executor:positional"
    if _DRIVE_RE.match(value) or value.startswith("/") or value.startswith("\\"):
        return "executor:positional"
    if not _POSITIONAL_RE.match(value):
        return "executor:positional"
    if verb == "ls-remote" and value != "origin" and not _LS_REMOTE_REF_RE.match(value):
        return "executor:positional"
    return None


def harden_measure_argv(argv: Sequence[str]) -> Optional[str]:
    """Judge a validator-allowed measure argv. None when it may run.

    Returns the rule id (`executor:<rule>`) that HELD it otherwise. Held rules
    this build: `argv-shape`, `verb`, `verb-held-this-build`, `flag`,
    `flag-value`, `positional`.
    """
    verb, positionals, rule = _split_argv(argv)
    if rule is not None:
        return rule
    for value in positionals:
        hit = _positional_rule(verb or "", value)
        if hit is not None:
            return hit
    return None


# ---------------------------------------------------------------------------
# Public-revision pre-check
# ---------------------------------------------------------------------------


def _classify_positionals(verb: str, positionals: Sequence[str]) -> Tuple[list, list]:
    """Split positionals into (revisions, pathspecs) by git's own convention.

    `<rev>... [--] [<path>...]`: for log/show/cat-file/rev-parse the first
    positional is the revision and the rest are pathspecs; `diff` names only
    revisions (a working-tree or index diff is never public); `ls-files` names
    only pathspecs; `for-each-ref` and `ls-remote` name ref patterns, which
    rules 4 and the hardening cover with no process at all.
    """
    values = list(positionals)
    if verb == "diff":
        return values, []
    if verb in _PATHS_ONLY_VERBS:
        return [], values
    if verb in _REV_THEN_PATHS_VERBS:
        return values[:1], values[1:]
    return [], []


def _proc_ok(res: Any) -> bool:
    if res is None:
        return False
    if getattr(res, "timed_out", False):
        return False
    if getattr(res, "exc", None):
        return False
    return getattr(res, "exit_code", None) == 0


def precheck_measure(
    argv: Sequence[str],
    *,
    runner: Callable[..., Any],
    timeout_s: float,
    ref: str = "origin/main",
) -> Optional[str]:
    """Hold any measure that could print a byte not reachable from `ref`.

    Every git process goes through `runner` - the SAME injected callable that
    executes measures - so one recorder sees pre-checks and measures alike and
    an arm can prove a held measure ran no measurement process.
    """
    verb, positionals, rule = _split_argv(argv)
    if rule is not None:
        return rule
    verb = verb or ""

    revisions, pathspecs = _classify_positionals(verb, positionals)

    if verb in _REV_REQUIRED_VERBS and not revisions:
        return "executor:rev-required"
    if verb == "diff" and len(revisions) != 2:
        return "executor:diff-needs-two-revs"
    if verb == "for-each-ref":
        for pattern in positionals:
            if not pattern.startswith(_PUBLIC_REF_PREFIXES):
                return "executor:ref-pattern-not-public"
        return None

    # The cap is checked BEFORE any process, so a capped measure costs zero.
    if len(revisions) + len(pathspecs) > PRECHECK_CALLS_PER_MEASURE:
        return "executor:positional-cap"

    for rev in revisions:
        res = runner(["git", "merge-base", "--is-ancestor", rev, ref], timeout_s=timeout_s)
        if not _proc_ok(res):
            return "executor:rev-not-public"
    for path in pathspecs:
        res = runner(["git", "ls-files", "--error-unmatch", "--", path], timeout_s=timeout_s)
        if not _proc_ok(res):
            return "executor:path-not-tracked"
    return None


# ---------------------------------------------------------------------------
# Exec
# ---------------------------------------------------------------------------


def build_git_argv(argv: Sequence[str], git_exe) -> list:
    """The real argv for one measure.

    The verb stays FIRST after the prefix and the executor's own diff flags
    follow it, because `--no-ext-diff` is an option OF log/show/diff and not of
    `git` itself - `git --no-ext-diff log` is an unknown-option error.
    """
    items = list(argv)
    verb = items[1]
    out = [str(git_exe), "--no-pager", "-c", "diff.external=", verb]
    if verb in {"log", "show", "diff"}:
        out.append("--no-ext-diff")
    if verb in {"show", "diff"}:
        out.append("--no-textconv")
    out.extend(items[2:])
    return out


def measure_env(env: Mapping[str, str]) -> dict:
    """The child environment for a measure: the injected mapping plus the extras.

    `ANTHROPIC_API_KEY` is popped here as well as in `child_env`. A measure is
    a git process and has no business holding the key even for the microseconds
    a CreateProcess block exists.
    """
    out = dict(env)
    out.pop("ANTHROPIC_API_KEY", None)
    out.update(MEASURE_ENV_EXTRA)
    return out


def default_measure_runner(
    argv: Sequence[str],
    *,
    timeout_s: float,
    git_exe,
    repo_root,
    env: Mapping[str, str],
    kill_budget,
) -> MeasureResult:
    """Run ONE git process for a measure or a pre-check, capped both ways.

    `run_once` binds `git_exe`, `repo_root`, `env` and the cycle's
    `kill_budget` and passes the partially applied callable as `measure_runner`,
    so pre-checks and measures share one seam and one kill allowance.
    """
    res = procs.popen_capture(
        build_git_argv(argv, git_exe),
        cwd=repo_root,
        env=measure_env(env),
        stdin_bytes=b"",
        timeout_s=timeout_s,
        kill_budget=kill_budget,
    )
    stdout = res.stdout or b""
    truncated = len(stdout) > MEASURE_STDOUT_CAP
    if truncated:
        stdout = stdout[:MEASURE_STDOUT_CAP]
    return MeasureResult(
        exit_code=res.exit_code,
        stdout=stdout,
        stderr=(res.stderr or b"")[:MEASURE_STDERR_CAP],
        timed_out=res.timed_out,
        survived_kill=res.survived_kill,
        kill_skipped=res.kill_skipped,
        wall_ms=res.wall_ms,
        stdout_truncated=truncated,
        exc=res.exc,
    )


# ---------------------------------------------------------------------------
# Scrub
# ---------------------------------------------------------------------------


def scrub_output(raw: bytes) -> Tuple[str, int]:
    """Bytes in, 7-bit ASCII out, with the number of replacements made.

    The ascii/backslashreplace decode comes FIRST and is what makes the result
    deterministic: every byte above 0x7E becomes `\\xNN`, one escape per byte.
    Decoding as UTF-8 first cannot do that - a codepoint above 0xFF has no
    `\\xNN` form - so the order is a decision, not a preference.
    """
    if isinstance(raw, str):
        raw = raw.encode("utf-8", "surrogatepass")
    count = sum(1 for b in raw if b > 0x7E)
    text = raw.decode("ascii", "backslashreplace")
    text = text.replace("\r\n", "\n")

    def _escape(m):
        return f"\\x{ord(m.group(0)):02x}"

    text, n = _CONTROL_RE.subn(_escape, text)
    count += n
    text, n = _EMAIL_RE.subn("<email>", text)
    count += n
    text, n = _HOME_RE.subn("<home>", text)
    count += n
    text, n = _SECRET_RE.subn("<secret>", text)
    count += n
    return text, count


def scrub_text(value: str, *, limit: int = SCRUB_TEXT_LIMIT) -> str:
    """The `Decision.reason` convenience over the same bytes path.

    `surrogatepass`, never `surrogateescape`: the latter maps only
    U+DC80..U+DCFF and RAISES on anything else, and `json.loads` turns a model's
    `"\\ud800"` into exactly such a lone surrogate.
    """
    if not isinstance(value, str):
        value = str(value)
    text, _ = scrub_output(value.encode("utf-8", "surrogatepass"))
    return text[:limit]


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _tag_line(grammar: str, delivery_number: int, budget: int, note_filename: str, cycle_id: str) -> str:
    line = (
        f"{_TAG_MARK} auto-authored under {grammar}; "
        f"delivery {int(delivery_number)} of budget {int(budget)} (budget counter, not M1); "
        f"answering {note_filename}; cycle {cycle_id}"
    )
    if grammar == GRAMMAR_LATENCY_ONLY:
        line += "; M1 not measured under this grammar"
    return line


def _get(entry: Mapping[str, Any], key: str, default=None):
    return entry.get(key, default) if isinstance(entry, Mapping) else getattr(entry, key, default)


def _measurement_block(entry: Mapping[str, Any]) -> list:
    argv = _get(entry, "argv", []) or []
    stdout = _get(entry, "stdout", "") or ""
    if isinstance(stdout, bytes):
        stdout, _ = scrub_output(stdout)
    lines = [
        f"- argv: {json.dumps(list(argv))}",
        f"  exit code: {_get(entry, 'exit_code')}",
        "  timed_out: {}".format("true" if _get(entry, "timed_out") else "false"),
        f"  wall ms: {_get(entry, 'wall_ms')}",
        "",
        "```",
        stdout.rstrip("\n"),
        "```",
    ]
    if _get(entry, "stdout_truncated"):
        lines.append(f"  [truncated] output reached the {MEASURE_STDOUT_CAP} byte cap")
    lines.append("")
    return lines


def assemble_body(
    *,
    grammar: str,
    cycle_id: str,
    note_filename: str,
    delivery_number: int,
    budget: int,
    model_body: str = "",
    measurements: Iterable[Mapping[str, Any]] = (),
    held: Iterable[Mapping[str, Any]] = (),
    arrived_iso: Optional[str] = None,
) -> str:
    """Build the reply body for BOTH grammars at one call site.

    A LATENCY-ONLY cycle reaches this with no measures and no held actions and
    gets the fixed receipt, so the receipt passes the same filter an A5 body
    does rather than a laxer path invented for it. The word `hop` appears in
    neither: M1 lives in the row, and a body carrying `hop <k>` would read as
    M1 in the artifact the counterparty parses.
    """
    lines = [_tag_line(grammar, delivery_number, budget, note_filename, cycle_id), ""]

    if grammar == GRAMMAR_LATENCY_ONLY:
        arrived = arrived_iso or "unknown"
        lines.append(
            f"Receipt: note {note_filename} arrived {arrived} on RC disk; "
            "no measurement performed under LATENCY-ONLY."
        )
        lines.append("")
        return "\n".join(lines)

    if model_body:
        lines.append(model_body.rstrip("\n"))
        lines.append("")

    lines.append(_MEASUREMENTS_HEADING)
    lines.append("")
    blocks = [_measurement_block(entry) for entry in measurements]
    if blocks:
        for block in blocks:
            lines.extend(block)
    else:
        lines.extend(["- none", ""])

    lines.append(_HELD_HEADING)
    lines.append("")
    held_entries = list(held)
    if held_entries:
        for entry in held_entries:
            kind = _get(entry, "kind", "other")
            rule = _get(entry, "rule", "")
            reason = scrub_text(str(_get(entry, "reason", "")))
            lines.append(f"- {kind} / {rule} / {reason}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output filter
# ---------------------------------------------------------------------------


def filter_body(
    assembled: str,
    model_body: str,
    targets: Sequence[str],
    reply_targets: Sequence[str],
    grammar: str,
) -> list:
    """The last gate before bytes leave RC. Returns every gate id that fired.

    An empty body is reported ALONE. Every other gate would also fire on
    whitespace (there is no tag line to find, no target named), and a refusal
    detail listing four gates for one defect names none of them.
    """
    if not assembled or not assembled.strip():
        return ["empty-body"]

    hits = []
    model = model_body or ""

    first_line = assembled.splitlines()[0]
    if _TAG_MARK not in first_line:
        hits.append("tag-missing")
    if _TAG_MARK in model:
        hits.append("tag-forged")
    if "=== BEGIN NOTE" in model or "=== END NOTE" in model:
        hits.append("fence-leak")
    if "Traceback" in assembled:
        hits.append("traceback")
    if _HOME_RE.search(assembled):
        hits.append("home-path")
    if _EMAIL_RE.search(assembled):
        hits.append("email")
    if _SECRET_RE.search(assembled):
        hits.append("secret")
    if not assembled.isascii():
        hits.append("non-ascii")
    if any(ch in assembled for ch in ("\r", "\x0b", "\x0c", "\x00")):
        hits.append("control-char")
    if len(assembled.encode("utf-8", "surrogatepass")) > MAX_ASSEMBLED_BYTES:
        hits.append("oversize")
    for line in model.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        if _QUESTION_RE.search(stripped):
            hits.append("grammar-question")
            break
    named = set(reply_targets or ())
    proposed = list(targets or ())
    if not proposed or set(proposed) - named:
        hits.append("target-not-named")
    if grammar == GRAMMAR_LATENCY_ONLY and _HOP_RE.search(assembled):
        hits.append("tag-hop-word")
    return hits
