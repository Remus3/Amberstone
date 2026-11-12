# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit v14 (range v27) - the OPERATOR-GATED history rewrite helper (GH-HYGIENE,
docs: the GH-HYGIENE ruling and approval of 2026-10-08).

Vendored byte-for-byte at ops/fleet_kit/ and pinned by MANIFEST.json. Do NOT
edit a vendored copy: report the defect to MAIN.

Each tree runs this IN ITS OWN TREE, only when MAIN's ORDER says so (operator
approval recorded), and only after it has vendored kit v13 - so the hooks of
FLEET-COMMON 17 stop the count from regrowing. MAIN never runs it in a
sibling tree. Three steps, in this order; `run` refuses out of order:

    python fleet_rewrite.py plan   [--root R] [--replace-file F]
    python fleet_rewrite.py bundle  --out DIR [--root R]
    python fleet_rewrite.py run     --confirm PLAN_ID [--root R] [--replace-file F]

plan (dry run, changes nothing): counts, over every branch and tag, the
  commits with a non-operator or Claude/bot author or committer, the commits
  carrying a forbidden attribution line (fleet_identity classes), and, per
  replace-file entry (by index, never by value), the commits that add or
  remove it plus its hits in HEAD. Writes <git common dir>/fleet-rewrite/
  plan.json and prints PLAN_ID (a hash of the ref tips, the replace file and
  the operator identity).
  v14 (ruling 2026-10-09, two tiers - fleet_identity.TRIGGER / RIDE_ALONG):
  plan also reports the distinct TRIGGER-tier commits (only these can start
  a rewrite), the ride-along-only commits (fixed only inside a triggered
  rewrite), the SHA-change count (every commit at or after a flagged commit
  in the commit graph - what a triggered rewrite rewrites; replace-file blob
  edits can add more) and the oldest depth per tier (1 = a tip, topo order).
  With no trigger-tier commit the plan says "NO REWRITE (ride-along only)";
  `run` still works only on the operator's approved ORDER.
bundle: `git bundle create <DIR>/<tree>-pre-rewrite-<stamp>.bundle --all`
  (DIR must be OUTSIDE the worktree), `git bundle verify`, records path,
  SHA-256, time and heads in <git common dir>/fleet-rewrite/backup.json.
run: REFUSES (exit 3, nothing changed) unless ALL hold - the vendored kit
  manifest is v13 or later; --confirm equals the plan's PLAN_ID and the plan
  is still current (same ref tips, same replace file) and younger than
  PLAN_MAX_H; a backup bundle younger than FRESH_H exists, matches its
  recorded SHA-256, verifies, and its heads equal every current branch and
  tag tip; the worktree has no tracked changes and no linked worktree
  exists; the local `fleet.operatorIdent` has a `Name <address>` value; `git
  filter-repo` is installed. Then it runs git filter-repo --force with a
  generated mailmap (every non-operator identity -> the operator), a message
  callback that strips the fleet_identity attribution lines, and
  --replace-text F when a replace file is given; restores the remotes that
  filter-repo drops; re-counts and writes result.json. It NEVER pushes: the
  force push is the tree's next, separately gated step.

The replace file is filter-repo's --replace-text format (`literal`,
`literal==>replacement`, `regex:...==>...`, `glob:...`), one entry per line,
`#` comments. It holds the leaked values, so it must be a LOCAL file that git
does not track and that is ignored or outside the worktree; default
ops/loop/control/rewrite-replace.txt. No value from it is ever printed.
v27 (KIT-REWRITE-RANGE, RC 2128 item 7): `plan` and `run` take
--range BASE..BRANCH (BRANCH a local branch, BASE an ancestor of it), so a
scoped identity fix stays on the kit. The plan then counts only the commits
in the range, its PLAN_ID covers the range, the mailmap names only the
identities seen in it, and filter-repo runs with `--refs BASE..BRANCH`;
`run` refuses a --range that differs from the plan's. Every other gate
(bundle of every ref, clean tree, no linked worktree, the approval) holds.
v29 (KIT-REWRITE-GAPS, RC ANSWERs 2026-11-01 0830, 0930, 1058 and the ruling
docs/rulings/2026-11-01-rc-rewrite-stale-refs.md):
- `run` refuses a whole-history rewrite while any ref sits outside heads, tags
  and stash: filter-repo would rewrite it and turn origin refs into local heads.
  `plan` reports them up front. Order: plan, bundle (it holds them), delete them
  as their own read-back step, run. A --range run is exempt: --refs implies
  --partial and filter-repo leaves other refs alone.
- `run` refuses an earlier .git/filter-repo/already_ran: under a day old it is a
  silent continuation, over a day it prompts a process with no console.
- The stash is part of the plan (filter-repo adds every refs/stash reflog sha to
  its ref list, and remaps commit-message tokens that cite them).
- `rehearse` replays the run in a scratch bare repo inside the state dir, with
  alternates to this store: the plan's heads and tags plus refs/stash with its
  reflog, the same argv. It writes rehearsal.json and moves no ref here; `run`
  then compares its tips (a difference is a non-zero exit). A mirror that drops
  the stash predicts the wrong tip.
- --replace-message F (filter-repo's --replace-message; same local-only rule as
  the replace file, explicit only, no default) on plan, rehearse and run.
- The mailmap reads every ref plus the stash reflog, what filter-repo rewrites.
- filter-repo leaves a root-level .git file per stash reflog sha it passed as a
  rev (not a ref; for-each-ref does not list it). result.json reports the count
  and the CLI prints it; they are left in place, no consumer was checked.
Pure stdlib plus the sibling kit file fleet_identity.py.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

STATE = "fleet-rewrite"
REPLACE_REL = Path("ops/loop/control/rewrite-replace.txt")
FRESH_H = 6.0
PLAN_MAX_H = 24.0
MIN_KIT = 13
REFS = ("--branches", "--tags")
STASH_REF = "refs/stash"
KEPT_PREFIXES = ("refs/heads/", "refs/tags/")  # v29: with STASH_REF, what a whole run takes
SCRATCH = "rehearsal-scratch"
SHA_NAME = re.compile(r"^[0-9a-f]{40}$")
GIT_ENV_REDIRECTS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


class Refused(RuntimeError):
    """A precondition of `run` (or of a step) does not hold."""


def _sibling(name):
    key = "fleet_kit_" + name
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, Path(__file__).with_name(name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


identity = _sibling("fleet_identity")


# ---------------------------------------------------------------- git

def git(root, *args, check=True, timeout=600):
    exe = os.environ.get("FLEET_GIT") or "git"
    r = subprocess.run([exe, "-C", str(root), *args], capture_output=True, timeout=timeout,
                       creationflags=_NO_WINDOW)
    out = r.stdout.decode("utf-8", "replace")
    if check and r.returncode != 0:
        raise Refused(f"REWRITE: git {args[0]} failed (exit {r.returncode})")
    return out if check else (r.returncode, out)


def top_of(root):
    return Path(git(root, "rev-parse", "--show-toplevel").strip())


def common_dir(root):
    d = Path(git(root, "rev-parse", "--git-common-dir").strip())
    return d if d.is_absolute() else (Path(root) / d).resolve()


def main_checkout(root):
    return common_dir(root).parent


def state_dir(root):
    d = common_dir(root) / STATE
    d.mkdir(parents=True, exist_ok=True)
    return d


def ref_tips(root):
    out = git(root, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads",
              "refs/tags")
    return dict(ln.split(" ", 1) for ln in out.splitlines() if " " in ln)


def foreign_refs(root):
    """v29: refs a whole-history filter-repo run would rewrite beyond the plan."""
    out = git(root, "for-each-ref", "--format=%(refname)")
    return sorted(r for r in out.splitlines()
                  if r and r != STASH_REF and not r.startswith(KEPT_PREFIXES))


def stash_tip(root):
    code, out = git(root, "rev-parse", "--verify", "--quiet", STASH_REF, check=False)
    return out.strip() if code == 0 else None


def stash_log(root):
    return common_dir(root) / "logs" / "refs" / "stash"


def stash_shas(root):
    """v29: the refs/stash reflog shas, read as filter-repo reads them."""
    try:
        lines = stash_log(root).read_bytes().splitlines()
    except OSError:
        return []
    return [ln.split()[1].decode("ascii") for ln in lines if len(ln.split()) >= 2]


def stray_sha_files(root):
    """v29: root-level .git files named by a full sha (filter-repo leaves them)."""
    try:
        return sorted(p.name for p in common_dir(root).iterdir()
                      if SHA_NAME.match(p.name) and p.is_file())
    except OSError:
        return []


def _sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now():
    return time.time()


# ---------------------------------------------------------------- replace file

def replace_file(root, given=None):
    """The replace file path (None when absent). Refuses a tracked file, or
    one inside the worktree that git does not ignore."""
    p = Path(given) if given else main_checkout(root) / REPLACE_REL
    if not p.is_absolute():
        p = Path(root) / p
    if not p.is_file():
        if given:
            raise Refused("REWRITE: replace file not found")
        return None
    return _local_only(root, p, "replace")


def message_file(root, given=None):
    """v29: the --replace-message file, or None. Explicit only: no default path."""
    if not given:
        return None
    p = Path(given)
    if not p.is_absolute():
        p = Path(root) / p
    if not p.is_file():
        raise Refused("REWRITE: message file not found")
    return _local_only(root, p, "message")


def _local_only(root, p, what):
    top = top_of(root)
    try:
        rel = p.resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        return p
    code, _ = git(root, "ls-files", "--error-unmatch", "--", rel, check=False)
    if code == 0:
        raise Refused("REWRITE: the {} file is TRACKED; it holds leaked values and "
                      "must stay local (git rm --cached it and ignore it)".format(what))
    code, _ = git(root, "check-ignore", "-q", "--", rel, check=False)
    if code != 0:
        raise Refused("REWRITE: the {} file is inside the worktree and not ignored; "
                      "ignore it or move it outside".format(what))
    return p


def replace_entries(path):
    """[(kind, needle)] - kind literal | regex | glob - from a replace file."""
    out = []
    if path is None:
        return out
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        needle = ln.split("==>", 1)[0]
        for kind in ("regex", "glob"):
            if needle.startswith(kind + ":"):
                out.append((kind, needle[len(kind) + 1:]))
                break
        else:
            if needle.startswith("literal:"):
                needle = needle[len("literal:"):]
            out.append(("literal", needle))
    return out


# ---------------------------------------------------------------- plan

def operator_ident(root):
    """(set of idents, the first `Name <address>` value or None)."""
    idents = identity.operator_idents(root)
    out = git(root, "config", "--local", "--get-all", identity.CONFIG_KEY, check=False)[1]
    full = None
    for v in out.splitlines():
        m = re.match(r"^\s*(.+?)\s*<([^>]+)>\s*$", v)
        if m:
            full = (m.group(1), m.group(2))
            break
    return idents, full


def plan_id(tips, rfile, full, rng=None, mfile=None, stash=None):
    h = hashlib.sha256()
    for ref in sorted(tips):
        h.update(("{} {}\n".format(ref, tips[ref])).encode("ascii"))
    h.update((_sha_file(rfile) if rfile else "-").encode("ascii"))
    h.update(repr(full).lower().encode("utf-8"))
    if rng:  # v27: a range plan never matches a whole-history id
        h.update(("range " + rng).encode("utf-8"))
    if mfile:  # v29: the message file and the stash feed filter-repo too
        h.update(("message " + _sha_file(mfile)).encode("ascii"))
    if stash and not rng:
        h.update(("stash " + stash).encode("ascii"))
    return h.hexdigest()[:12]


_RANGE = re.compile(r"^([A-Za-z0-9_][^\s:]*?)\.\.([A-Za-z0-9_][^\s:]*)$")


def check_range(root, rng):
    """v27: None, or a valid BASE..BRANCH range (BRANCH a local branch, BASE
    resolving to an ancestor of it); Refused otherwise."""
    if rng is None:
        return None
    m = _RANGE.match(str(rng))
    if not m or "..." in str(rng) or ".." in m.group(2):
        raise Refused("REWRITE: --range takes BASE..BRANCH (two dots)")
    base, tip = m.group(1), m.group(2)
    for rev in (base, tip):
        if git(root, "rev-parse", "--verify", "--quiet", rev + "^{commit}",
               check=False)[0] != 0:
            raise Refused("REWRITE: --range {} does not resolve".format(rev))
    if git(root, "show-ref", "--verify", "--quiet", "refs/heads/" + tip,
           check=False)[0] != 0:
        raise Refused("REWRITE: --range end must be a local branch")
    if git(root, "merge-base", "--is-ancestor", base, tip, check=False)[0] != 0:
        raise Refused("REWRITE: --range base is not an ancestor of the branch")
    return "{}..{}".format(base, tip)


def sha_change(root, flagged, graph=None, rng=None):
    """Commits a rewrite of the `flagged` shas changes: each flagged commit and
    every descendant of one, over every branch and tag (v27: inside rng)."""
    if not flagged:
        return 0
    revs = [rng] if rng else list(REFS)
    out = graph if graph is not None else git(
        root, "rev-list", "--topo-order", "--reverse", "--parents", *revs, check=False)[1]
    changed = set()
    for ln in out.splitlines():
        parts = ln.split()
        if not parts:
            continue
        if parts[0] in flagged or any(x in changed for x in parts[1:]):
            changed.add(parts[0])
    return len(changed)


def message_counts(root, mfile, revs):
    """v29: per message-file entry, by index, the commits whose message hits it."""
    out = []
    for i, (kind, needle) in enumerate(replace_entries(mfile), 1):
        if kind == "glob":
            out.append({"entry": i, "kind": kind, "commits": None})
            continue
        flag = "--extended-regexp" if kind == "regex" else "--fixed-strings"
        hits = git(root, "log", "--format=%H", flag, "--grep=" + needle, *revs, check=False)[1]
        out.append({"entry": i, "kind": kind,
                    "commits": len([x for x in hits.splitlines() if x.strip()])})
    return out


def count(root, rfile, idents, rng=None, mfile=None):
    revs = [rng] if rng else list(REFS)
    rows = identity.commits(root, ["--topo-order", *revs]) or []
    bad = identity.violations(rows, idents)
    tiers = identity.tier_summary(rows, idents)
    flagged = {r["sha"] for r in rows if identity.violations([r], idents)}
    classes = {}
    for _, c in bad:
        classes[c] = classes.get(c, 0) + 1
    needles = []
    for i, (kind, needle) in enumerate(replace_entries(rfile), 1):
        if kind == "glob":
            needles.append({"entry": i, "kind": kind, "commits": None, "head_hits": None})
            continue
        flag = ["-G" + needle] if kind == "regex" else ["-S" + needle]
        commits = git(root, "log", "--format=%H", *flag, *revs, check=False)[1]
        grep = ["-E" if kind == "regex" else "-F", "-e", needle]
        code, hits = git(root, "grep", "-c", *grep, "HEAD", check=False)
        n = sum(int(x.rsplit(":", 1)[1]) for x in hits.splitlines()
                if code == 0 and ":" in x and x.rsplit(":", 1)[1].isdigit())
        needles.append({"entry": i, "kind": kind,
                        "commits": len([x for x in commits.splitlines() if x.strip()]),
                        "head_hits": n})
    return {"commits": len(rows), "commits_to_rewrite": len({s for s, _ in bad}),
            "classes": classes, "replace": needles,
            "message_replace": message_counts(root, mfile, revs),
            "trigger": tiers["distinct_trigger"],
            "ride_along_only": tiers["distinct_ride_along_only"],
            "sha_change": sha_change(root, flagged, rng=rng),
            "oldest_depth": tiers["oldest_depth"]}


def plan(root, given=None, clock=_now, rng=None, msg=None):
    rng = check_range(root, rng)
    rfile = replace_file(root, given)
    mfile = message_file(root, msg)
    idents, full = operator_ident(root)
    if not idents:
        raise Refused("REWRITE: set the operator identity in LOCAL git config first: "
                      "git config --local --add {} \"Name <address>\"".format(identity.CONFIG_KEY))
    tips = ref_tips(root)
    doc = {"at": clock(), "plan_id": plan_id(tips, rfile, full, rng, mfile, stash_tip(root)),
           "tips": tips, "replace_sha256": _sha_file(rfile) if rfile else None,
           "message_sha256": _sha_file(mfile) if mfile else None, "range": rng,
           "foreign_refs": [] if rng else foreign_refs(root),
           "counts": count(root, rfile, idents, rng, mfile)}
    (state_dir(root) / "plan.json").write_text(json.dumps(doc, indent=1, sort_keys=True),
                                               encoding="ascii", newline="\n")
    return doc


# ---------------------------------------------------------------- bundle

def bundle(root, out_dir, clock=_now):
    out_dir = Path(out_dir).resolve()
    top = top_of(root).resolve()
    if out_dir == top or top in out_dir.parents:
        raise Refused("REWRITE: --out must be outside the worktree")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(clock()))
    path = out_dir / ("{}-pre-rewrite-{}.bundle".format(top.name.replace(" ", "-"), stamp))
    git(root, "bundle", "create", str(path), "--all", timeout=3600)
    git(root, "bundle", "verify", str(path), timeout=3600)
    heads = {}
    for ln in git(root, "bundle", "list-heads", str(path)).splitlines():
        sha, _, ref = ln.partition(" ")
        if ref.startswith(("refs/heads/", "refs/tags/")):
            heads[ref] = sha
    doc = {"at": clock(), "path": str(path), "sha256": _sha_file(path), "heads": heads}
    (state_dir(root) / "backup.json").write_text(json.dumps(doc, indent=1, sort_keys=True),
                                                 encoding="ascii", newline="\n")
    return doc


# ---------------------------------------------------------------- run

def _load(root, name):
    try:
        return json.loads((state_dir(root) / name).read_text(encoding="ascii"))
    except (OSError, ValueError):
        return None


def kit_version(root):
    m = main_checkout(root)
    for rel in (Path("ops/fleet_kit/MANIFEST.json"), Path("fleet-kit/MANIFEST.json")):
        try:
            return int(json.loads((m / rel).read_text(encoding="ascii"))["version"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return 0


def preflight(root, confirm, given=None, clock=_now, have_filter_repo=None, rng=None, msg=None):
    """Every refusal of `run`; returns (plan doc, backup doc, rfile, full ident)."""
    if kit_version(root) < MIN_KIT:
        raise Refused(f"REWRITE: vendor kit v{MIN_KIT} first (the hooks must land "
                      "before the rewrite)")
    pl = _load(root, "plan.json")
    if not pl:
        raise Refused("REWRITE: no plan - run `plan` (the dry-run count) first")
    if confirm != pl.get("plan_id"):
        raise Refused("REWRITE: --confirm does not match the plan id")
    rng = check_range(root, rng)
    if (pl.get("range") or None) != rng:
        raise Refused("REWRITE: --range differs from the plan's - give the plan's range "
                      "or run `plan` again")
    if clock() - float(pl.get("at", 0)) > PLAN_MAX_H * 3600:
        raise Refused(f"REWRITE: the plan is older than {int(PLAN_MAX_H)} h - "
                      "run `plan` again")
    rfile = replace_file(root, given)
    mfile = message_file(root, msg)
    idents, full = operator_ident(root)
    if full is None:
        raise Refused("REWRITE: {} needs a `Name <address>` value for the mailmap".format(identity.CONFIG_KEY))
    tips = ref_tips(root)
    if plan_id(tips, rfile, full, rng, mfile, stash_tip(root)) != pl["plan_id"]:
        raise Refused("REWRITE: refs, the stash, the replace file or the message file "
                      "changed since the plan - run `plan` again")
    bk = _load(root, "backup.json")
    if not bk:
        raise Refused("REWRITE: no backup bundle - run `bundle --out DIR` first")
    if clock() - float(bk.get("at", 0)) > FRESH_H * 3600:
        raise Refused(f"REWRITE: the backup bundle is older than {int(FRESH_H)} h - "
                      "take a fresh one")
    bpath = Path(bk.get("path", ""))
    if not bpath.is_file() or _sha_file(bpath) != bk.get("sha256"):
        raise Refused("REWRITE: the backup bundle is missing or changed")
    if bk.get("heads") != tips:
        raise Refused("REWRITE: the backup bundle does not hold every current branch and "
                      "tag tip - take a fresh one")
    git(root, "bundle", "verify", str(bpath), timeout=3600)
    foreign = [] if rng else foreign_refs(root)
    if foreign:
        raise Refused("REWRITE: {} refs outside heads, tags and stash (first: {}); filter-repo "
                      "would rewrite them and turn origin refs into local heads. The bundle "
                      "holds them: delete them as their own read-back step, one per call, "
                      "symrefs first (git symbolic-ref -d REF, then git update-ref -d REF), "
                      "then run again".format(len(foreign), ", ".join(foreign[:5])))
    if git(root, "status", "--porcelain", "--untracked-files=no").strip():
        raise Refused("REWRITE: the worktree has tracked changes - commit or stash first")
    wts = [ln for ln in git(root, "worktree", "list", "--porcelain").splitlines()
           if ln.startswith("worktree ")]
    if len(wts) > 1:
        raise Refused("REWRITE: linked worktrees exist - remove them first")
    ok = have_filter_repo if have_filter_repo is not None else \
        git(root, "filter-repo", "--version", check=False)[0] == 0
    if not ok:
        raise Refused("REWRITE: git filter-repo is not installed")
    if (common_dir(root) / "filter-repo" / "already_ran").exists():
        raise Refused("REWRITE: an earlier filter-repo run left .git/filter-repo; a new run "
                      "would continue it. Rename that directory to a new name first")
    return pl, bk, rfile, full


def mailmap_text(root, full, idents, rng=None):
    """One mailmap line per non-operator identity on what filter-repo rewrites:
    every ref plus the stash reflog (v29; v27: only inside rng when given)."""
    lines, seen = [], set()
    rows = identity.commits(root, [rng] if rng else ["--all"]) or []
    if not rng and stash_shas(root):
        rows += identity.commits(root, stash_shas(root)) or []
    for r in rows:
        for n, a in ((r["an"], r["ae"]), (r["cn"], r["ce"])):
            if identity.is_operator(n, a, idents) or (n, a) in seen:
                continue
            seen.add((n, a))
            lines.append("{} <{}> {} <{}>".format(full[0], full[1], n, a))
    return "\n".join(lines) + ("\n" if lines else "")


def message_callback():
    """git filter-repo --message-callback body: drop fleet_identity lines."""
    pats = {
        "T": identity._TRAILER.pattern, "A": identity.AI_RX.pattern,
        "B": identity.BOT_RX.pattern, "C": identity._CLAUDE_TRAILER.pattern,
        "G": identity._GENERATED.pattern, "U": identity._SESSION_URL.pattern,
    }
    body = ["import re"]
    for k, v in pats.items():
        body.append("_{} = re.compile({!r}, re.I)".format(k, v.encode("ascii")))
    body += [
        "def _bad(line):",
        "    m = _T.match(line)",
        "    if m and (_A.search(m.group(1)) or _B.search(m.group(1))):",
        "        return True",
        "    return bool(_C.match(line) or _G.search(line) or _U.match(line))",
        "lines = message.split(b'\\n')",
        "keep = [x for x in lines if not _bad(x)]",
        "if len(keep) == len(lines):",
        "    return message",
        "while keep and not keep[-1].strip():",
        "    keep.pop()",
        "return b'\\n'.join(keep) + b'\\n' if keep else b''",
    ]
    return "\n".join(body) + "\n"


def remotes(root):
    out = {}
    for name in git(root, "remote").split():
        out[name] = git(root, "remote", "get-url", name).strip()
    return out


def filter_argv(mailmap, rfile, rng=None, mfile=None):
    argv = ["git", "filter-repo", "--force", "--mailmap", str(mailmap),
            "--message-callback", message_callback()]
    if rfile is not None:
        argv += ["--replace-text", str(rfile)]
    if mfile is not None:  # v29: the CLI reaches commit messages
        argv += ["--replace-message", str(mfile)]
    if rng:  # v27: filter-repo rewrites only BASE..BRANCH
        argv += ["--refs", rng]
    return argv


def _rmtree(path):
    """A scratch tree of this tool's own; git leaves its pack files read-only."""
    if not Path(path).exists():
        return
    for base, _dirs, files in os.walk(path):
        for name in files:
            os.chmod(os.path.join(base, name), stat.S_IWRITE | stat.S_IREAD)
    shutil.rmtree(path)


def rehearse(root, given=None, clock=_now, runner=None, msg=None):
    """v29: run the planned rewrite on a scratch bare repo in the state dir, with
    alternates to this store and refs/stash + its reflog kept, and record the
    tips it gives. Nothing here moves: no ref, no reflog, no object is written
    to the real repo. Foreign refs are left out, as `run` requires them gone."""
    moved = [k for k in GIT_ENV_REDIRECTS if os.environ.get(k)]
    if moved:
        raise Refused("REWRITE: rehearse refuses while {} is set".format(moved[0]))
    pl = _load(root, "plan.json")
    if not pl:
        raise Refused("REWRITE: no plan - run `plan` (the dry-run count) first")
    if pl.get("range"):
        raise Refused("REWRITE: rehearse is for a whole-history plan, not a --range one")
    rfile, mfile = replace_file(root, given), message_file(root, msg)
    idents, full = operator_ident(root)
    if full is None:
        raise Refused("REWRITE: {} needs a `Name <address>` value for the mailmap".format(identity.CONFIG_KEY))
    tips = ref_tips(root)
    stash = stash_tip(root)
    if plan_id(tips, rfile, full, None, mfile, stash) != pl["plan_id"]:
        raise Refused("REWRITE: refs, the stash, the replace file or the message file "
                      "changed since the plan - run `plan` again")
    sd = state_dir(root)
    scratch = sd / SCRATCH
    _rmtree(scratch)
    mm = sd / "mailmap"
    mm.write_text(mailmap_text(root, full, idents), encoding="utf-8", newline="\n")
    runner = runner or (lambda a: subprocess.run(a, cwd=str(scratch), capture_output=True,
                                                 creationflags=_NO_WINDOW).returncode)
    try:
        git(sd, "init", "-q", "--bare", SCRATCH)
        info = scratch / "objects" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "alternates").write_text((common_dir(root) / "objects").as_posix() + "\n",
                                         encoding="utf-8", newline="\n")
        head = git(root, "symbolic-ref", "-q", "HEAD", check=False)
        for ref, sha in sorted(tips.items()):
            git(scratch, "update-ref", ref, sha)
        if head[0] == 0:
            git(scratch, "symbolic-ref", "HEAD", head[1].strip())
        if stash:
            git(scratch, "update-ref", STASH_REF, stash)
            log = scratch / "logs" / "refs" / "stash"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_bytes(stash_log(root).read_bytes())
        argv = filter_argv(mm.resolve(), Path(rfile).resolve() if rfile else None, None,
                           Path(mfile).resolve() if mfile else None)
        rc = runner(argv)
        if rc != 0:
            raise Refused(f"REWRITE: the rehearsal's git filter-repo failed (exit {rc}); "
                          "nothing moved in the real repo")
        after = count(scratch, rfile, idents, None, mfile)
        doc = {"at": clock(), "plan_id": pl["plan_id"], "tips": ref_tips(scratch), "after": after,
               "foreign_refs_left_out": len(foreign_refs(root))}
    finally:
        _rmtree(scratch)
    (sd / "rehearsal.json").write_text(json.dumps(doc, indent=1, sort_keys=True),
                                       encoding="ascii", newline="\n")
    return doc


def _rehearsal_verdict(root, pid):
    """v29: None with no rehearsal of this plan, else how the tips compare."""
    rh = _load(root, "rehearsal.json")
    if not rh or rh.get("plan_id") != pid:
        return None
    want, have = rh.get("tips") or {}, ref_tips(root)
    differs = [r for r in set(want) | set(have) if want.get(r) != have.get(r)]
    return {"equal": not differs, "differs": len(differs)}


def run(root, confirm, given=None, clock=_now, runner=None, have_filter_repo=None,
        rng=None, msg=None):
    pl, _bk, rfile, full = preflight(root, confirm, given, clock, have_filter_repo, rng, msg)
    mfile = message_file(root, msg)
    rng = pl.get("range") or None
    idents, _ = operator_ident(root)
    sd = state_dir(root)
    mm = sd / "mailmap"
    mm.write_text(mailmap_text(root, full, idents, rng), encoding="utf-8", newline="\n")
    saved = remotes(root)
    argv = filter_argv(mm, rfile, rng, mfile)
    top = top_of(root)
    runner = runner or (lambda a: subprocess.run(a, cwd=str(top),
                                                 creationflags=_NO_WINDOW).returncode)
    rc = runner(argv)
    if rc != 0:
        raise Refused(f"REWRITE: git filter-repo failed (exit {rc}); restore from the "
                      "bundle if the tree is damaged")
    have = remotes(root)
    for name, url in saved.items():
        if name not in have:
            git(root, "remote", "add", name, url)
    after = count(root, rfile, idents, rng, mfile)
    doc = {"at": clock(), "plan_id": pl["plan_id"], "before": pl["counts"], "after": after,
           "range": rng, "stray_sha_files": len(stray_sha_files(root)),
           "rehearsal": _rehearsal_verdict(root, pl["plan_id"])}
    (sd / "result.json").write_text(json.dumps(doc, indent=1, sort_keys=True),
                                    encoding="ascii", newline="\n")
    return doc


# ---------------------------------------------------------------- CLI

def _summary(counts):
    parts = [f"{counts['commits']} commits scanned",
             f"{counts['commits_to_rewrite']} to rewrite"]
    if "trigger" in counts:
        od = counts.get("oldest_depth") or {}
        parts += [f"trigger {counts['trigger']}",
                  f"ride-along only {counts['ride_along_only']}",
                  f"SHA change {counts['sha_change']}",
                  "oldest depth trigger {} ride-along {}".format(
                      od.get("trigger") or "-", od.get("ride-along") or "-")]
        if not counts["trigger"]:
            parts.append("NO REWRITE (ride-along only)")
    parts += [f"{k} {v}" for k, v in sorted(counts["classes"].items())]
    for n in counts["replace"]:
        parts.append(f"replace #{n['entry']}: {n['commits']} commits, "
                     f"{n['head_hits']} HEAD hits")
    for n in counts.get("message_replace") or ():
        parts.append(f"message #{n['entry']}: {n['commits']} commits")
    return "; ".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fleet_rewrite.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "bundle", "rehearse", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--root", default=".")
        if name != "bundle":
            sp.add_argument("--replace-file")
            sp.add_argument("--replace-message")  # v29: the CLI reaches messages
        if name in ("plan", "run"):
            sp.add_argument("--range", dest="rng")  # v27: BASE..BRANCH
        if name == "bundle":
            sp.add_argument("--out", required=True)
        if name == "run":
            sp.add_argument("--confirm", required=True)
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    try:
        if args.cmd == "plan":
            doc = plan(args.root, args.replace_file, rng=args.rng, msg=args.replace_message)
            scope = "; range {}".format(doc["range"]) if doc.get("range") else ""
            if doc["foreign_refs"]:
                scope += "; {} refs outside heads, tags and stash: `run` refuses until they " \
                         "are gone".format(len(doc["foreign_refs"]))
            print("PLAN {}: {}{}".format(doc["plan_id"], _summary(doc["counts"]), scope))
        elif args.cmd == "bundle":
            doc = bundle(args.root, args.out)
            print(f"BUNDLE ok: {len(doc['heads'])} refs, sha256 {doc['sha256'][:16]}")
        elif args.cmd == "rehearse":
            doc = rehearse(args.root, args.replace_file, msg=args.replace_message)
            print("REHEARSAL {}: after {}; {} tips in rehearsal.json; {} foreign refs left out; "
                  "no real ref moved".format(doc["plan_id"], _summary(doc["after"]),
                                             len(doc["tips"]), doc["foreign_refs_left_out"]))
            return 0 if doc["after"]["commits_to_rewrite"] == 0 else 1
        else:
            doc = run(args.root, args.confirm, args.replace_file, rng=args.rng,
                      msg=args.replace_message)
            print("REWRITE done: before {} | after {} - NOT pushed".format(_summary(doc["before"]), _summary(doc["after"])))
            if doc["stray_sha_files"]:
                print("{} root-level .git files named by a sha left in place (filter-repo, "
                      "stash reflog)".format(doc["stray_sha_files"]))
            rh = doc["rehearsal"]
            if rh:
                print("rehearsal tips: {}".format(
                    "equal" if rh["equal"] else "DIFFER on {} refs - STOP".format(rh["differs"])))
            return 0 if doc["after"]["commits_to_rewrite"] == 0 and (not rh or rh["equal"]) else 1
    except Refused as exc:
        sys.stderr.write(str(exc) + "\n")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
