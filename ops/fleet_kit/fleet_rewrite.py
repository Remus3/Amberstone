# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit v13 - the OPERATOR-GATED history rewrite helper (GH-HYGIENE,
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
Pure stdlib plus the sibling kit file fleet_identity.py.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
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
    top = top_of(root)
    try:
        rel = p.resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        return p
    code, _ = git(root, "ls-files", "--error-unmatch", "--", rel, check=False)
    if code == 0:
        raise Refused("REWRITE: the replace file is TRACKED; it holds leaked values and "
                      "must stay local (git rm --cached it and ignore it)")
    code, _ = git(root, "check-ignore", "-q", "--", rel, check=False)
    if code != 0:
        raise Refused("REWRITE: the replace file is inside the worktree and not ignored; "
                      "ignore it or move it outside")
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


def plan_id(tips, rfile, full):
    h = hashlib.sha256()
    for ref in sorted(tips):
        h.update(("{} {}\n".format(ref, tips[ref])).encode("ascii"))
    h.update((_sha_file(rfile) if rfile else "-").encode("ascii"))
    h.update(repr(full).lower().encode("utf-8"))
    return h.hexdigest()[:12]


def count(root, rfile, idents):
    rows = identity.commits(root, list(REFS)) or []
    bad = identity.violations(rows, idents)
    classes = {}
    for _, c in bad:
        classes[c] = classes.get(c, 0) + 1
    needles = []
    for i, (kind, needle) in enumerate(replace_entries(rfile), 1):
        if kind == "glob":
            needles.append({"entry": i, "kind": kind, "commits": None, "head_hits": None})
            continue
        flag = ["-G" + needle] if kind == "regex" else ["-S" + needle]
        commits = git(root, "log", "--format=%H", *flag, *REFS, check=False)[1]
        grep = ["-E" if kind == "regex" else "-F", "-e", needle]
        code, hits = git(root, "grep", "-c", *grep, "HEAD", check=False)
        n = sum(int(x.rsplit(":", 1)[1]) for x in hits.splitlines()
                if code == 0 and ":" in x and x.rsplit(":", 1)[1].isdigit())
        needles.append({"entry": i, "kind": kind,
                        "commits": len([x for x in commits.splitlines() if x.strip()]),
                        "head_hits": n})
    return {"commits": len(rows), "commits_to_rewrite": len({s for s, _ in bad}),
            "classes": classes, "replace": needles}


def plan(root, given=None, clock=_now):
    rfile = replace_file(root, given)
    idents, full = operator_ident(root)
    if not idents:
        raise Refused("REWRITE: set the operator identity in LOCAL git config first: "
                      "git config --local --add {} \"Name <address>\"".format(identity.CONFIG_KEY))
    tips = ref_tips(root)
    doc = {"at": clock(), "plan_id": plan_id(tips, rfile, full), "tips": tips,
           "replace_sha256": _sha_file(rfile) if rfile else None,
           "counts": count(root, rfile, idents)}
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


def preflight(root, confirm, given=None, clock=_now, have_filter_repo=None):
    """Every refusal of `run`; returns (plan doc, backup doc, rfile, full ident)."""
    if kit_version(root) < MIN_KIT:
        raise Refused(f"REWRITE: vendor kit v{MIN_KIT} first (the hooks must land "
                      "before the rewrite)")
    pl = _load(root, "plan.json")
    if not pl:
        raise Refused("REWRITE: no plan - run `plan` (the dry-run count) first")
    if confirm != pl.get("plan_id"):
        raise Refused("REWRITE: --confirm does not match the plan id")
    if clock() - float(pl.get("at", 0)) > PLAN_MAX_H * 3600:
        raise Refused(f"REWRITE: the plan is older than {int(PLAN_MAX_H)} h - "
                      "run `plan` again")
    rfile = replace_file(root, given)
    idents, full = operator_ident(root)
    if full is None:
        raise Refused("REWRITE: {} needs a `Name <address>` value for the mailmap".format(identity.CONFIG_KEY))
    tips = ref_tips(root)
    if plan_id(tips, rfile, full) != pl["plan_id"]:
        raise Refused("REWRITE: refs or the replace file changed since the plan - "
                      "run `plan` again")
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
    return pl, bk, rfile, full


def mailmap_text(root, full, idents):
    """One mailmap line per non-operator identity seen on any branch or tag."""
    lines, seen = [], set()
    for r in identity.commits(root, list(REFS)) or []:
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


def filter_argv(mailmap, rfile):
    argv = ["git", "filter-repo", "--force", "--mailmap", str(mailmap),
            "--message-callback", message_callback()]
    if rfile is not None:
        argv += ["--replace-text", str(rfile)]
    return argv


def run(root, confirm, given=None, clock=_now, runner=None, have_filter_repo=None):
    pl, _bk, rfile, full = preflight(root, confirm, given, clock, have_filter_repo)
    idents, _ = operator_ident(root)
    sd = state_dir(root)
    mm = sd / "mailmap"
    mm.write_text(mailmap_text(root, full, idents), encoding="utf-8", newline="\n")
    saved = remotes(root)
    argv = filter_argv(mm, rfile)
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
    after = count(root, rfile, idents)
    doc = {"at": clock(), "plan_id": pl["plan_id"], "before": pl["counts"], "after": after}
    (sd / "result.json").write_text(json.dumps(doc, indent=1, sort_keys=True),
                                    encoding="ascii", newline="\n")
    return doc


# ---------------------------------------------------------------- CLI

def _summary(counts):
    parts = [f"{counts['commits']} commits scanned",
             f"{counts['commits_to_rewrite']} to rewrite"]
    parts += [f"{k} {v}" for k, v in sorted(counts["classes"].items())]
    for n in counts["replace"]:
        parts.append(f"replace #{n['entry']}: {n['commits']} commits, "
                     f"{n['head_hits']} HEAD hits")
    return "; ".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fleet_rewrite.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "bundle", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--root", default=".")
        if name != "bundle":
            sp.add_argument("--replace-file")
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
            doc = plan(args.root, args.replace_file)
            print("PLAN {}: {}".format(doc["plan_id"], _summary(doc["counts"])))
        elif args.cmd == "bundle":
            doc = bundle(args.root, args.out)
            print(f"BUNDLE ok: {len(doc['heads'])} refs, sha256 {doc['sha256'][:16]}")
        else:
            doc = run(args.root, args.confirm, args.replace_file)
            print("REWRITE done: before {} | after {} - NOT pushed".format(_summary(doc["before"]), _summary(doc["after"])))
            return 0 if doc["after"]["commits_to_rewrite"] == 0 else 1
    except Refused as exc:
        sys.stderr.write(str(exc) + "\n")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
