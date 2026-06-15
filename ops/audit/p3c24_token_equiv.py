"""B1b safety proof (cycle 24, item 420). For each swept DS-engine .py:

  * tokenize HEAD (git show) and the working tree;
  * token COUNT must be equal (no token added/removed -> no code restructured);
  * every NON-STRING token byte-identical (exact_type + string) -> engine logic,
    operators, names, numbers all provably untouched;
  * every STRING / FSTRING_MIDDLE token: working == transform(HEAD-token), i.e.
    the string changed ONLY by the B1b GLYPH_MAP (+ beam.py separator override),
    nothing else.

A pass means: computed quantities are byte-identical to HEAD (they live in
non-string tokens) and the only edits are the intended glyph->ASCII subs.

Run from repo root after p3c24_b1b_sweep.py. Exit 0 = PROVED.
"""

import io
import subprocess
import sys
import tokenize

from p3c24_b1b_sweep import PY_FILES, transform

STRINGY = {tokenize.STRING, tokenize.FSTRING_MIDDLE}


def toks(src: str):
    return [
        t
        for t in tokenize.generate_tokens(io.StringIO(src).readline)
        if t.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.ENCODING,
                          tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER)
    ]


def head_src(rel: str) -> str:
    out = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        capture_output=True, check=True,
    ).stdout.decode("utf-8")
    return out.replace("\r\n", "\n").replace("\r", "\n")


def main() -> int:
    ok = True
    for rel in PY_FILES:
        h = toks(head_src(rel))
        w = toks(open(rel, encoding="utf-8").read().replace("\r\n", "\n"))
        if len(h) != len(w):
            print(f"FAIL {rel}: token count {len(h)} -> {len(w)}")
            ok = False
            continue
        nonstr_ident = str_subbed = 0
        for th, tw in zip(h, w):
            if th.type in STRINGY:
                if transform(th.string, rel) != tw.string:
                    print(f"FAIL {rel}:{th.start[0]} STRING not a clean glyph-sub")
                    print(f"   HEAD={th.string!r}")
                    print(f"   WORK={tw.string!r}")
                    ok = False
                elif th.string != tw.string:
                    str_subbed += 1
            else:
                if th.exact_type != tw.exact_type or th.string != tw.string:
                    print(f"FAIL {rel}:{th.start[0]} non-string token diverged")
                    print(f"   HEAD={th.string!r} ({tokenize.tok_name[th.exact_type]})")
                    print(f"   WORK={tw.string!r} ({tokenize.tok_name[tw.exact_type]})")
                    ok = False
                else:
                    nonstr_ident += 1
        print(f"  {rel}: {nonstr_ident} non-string tokens byte-identical, "
              f"{str_subbed} string tokens glyph-subbed")
    print("PROVED" if ok else "PROOF FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
