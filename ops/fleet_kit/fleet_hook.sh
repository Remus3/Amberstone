# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
# Fleet kit v26 - deny-hook launcher (ruling CS-815, MAIN
# docs/rulings/2026-10-26-cs-815-hook-launcher.md). Vendored byte-for-byte at
# ops/fleet_kit/ and pinned by MANIFEST.json. Do NOT edit a vendored copy.
#
#   bash "$CLAUDE_PROJECT_DIR/ops/fleet_kit/fleet_hook.sh" fleet_subagent_first.py
#   bash "$CLAUDE_PROJECT_DIR/ops/fleet_kit/fleet_hook.sh" fleet_claims.py hook
#
# Runs python ONCE on the named kit script (beside this file) with
# `--fleet-nonce <nonce>` appended and stdin passed through, and requires the
# LAST stdout line to be `FLEET-NONCE <nonce>`. A match: that line is stripped
# and the rest of stdout, stderr and the exit code pass through unchanged. No
# match (a python stub that ignores its arguments, no interpreter / 127, a
# crash before the line, empty output): one stderr line
# `fleet hook: interpreter check failed (<script>)` and exit 2 = block (fail
# closed). FLEET_HOOK_PYTHON names another interpreter (default `python`);
# the nonce check applies to it the same way. POSIX sh, ASCII, LF.

script="$1"
case "$script" in
  fleet_*.py) ;;
  *) echo "fleet hook: interpreter check failed (no kit script named)" >&2; exit 2 ;;
esac
shift
case "$script" in
  */*|*\\*) echo "fleet hook: interpreter check failed ($script)" >&2; exit 2 ;;
esac
dir=$(dirname -- "$0")
nonce="$$-${RANDOM:-0}-$(date +%s 2>/dev/null)"
py="${FLEET_HOOK_PYTHON:-python}"
nl='
'
out=$("$py" "$dir/$script" "$@" --fleet-nonce "$nonce"; rc=$?; printf '\n%s' "$rc")
rc=${out##*"$nl"}
out=${out%"$nl"*}
out=${out%"$nl"}
case "$out" in
  *"$nl"*) last=${out##*"$nl"}; body=${out%"$nl"*} ;;
  *) last=$out; body= ;;
esac
last=${last%"$(printf '\r')"}
if [ "$last" != "FLEET-NONCE $nonce" ]; then
  echo "fleet hook: interpreter check failed ($script)" >&2
  exit 2
fi
if [ -n "$body" ]; then
  printf '%s\n' "$body"
fi
case "$rc" in
  ''|*[!0-9]*) exit 2 ;;
esac
exit "$rc"
