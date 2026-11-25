#!/usr/bin/env bash
# Prove new-agent.sh installs the runner and every helper it calls, into a throwaway SANDBOX_BASE.
# Run: bash scripts/test-new-agent.sh
set -uo pipefail
H=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
pass=0 fail=0
check() { if eval "$2"; then pass=$((pass + 1)); echo "ok    $1"; else fail=$((fail + 1)); echo "FAIL  $1"; fi; }
mkdir -p "$T/root" "$T/cfg/tmux-session"
printf 'TMUX_SESSION_PROGRAMS="claude btop"\n' > "$T/cfg/tmux-session/env"
printf 'NAME=tnew\nROOT=%s\nROOT_MODE=ro\nNET=none\n' "$T/root" > "$T/src.profile"
out=$(SANDBOX_BASE="$T/base" SANDBOX_BIN="$T/bin" XDG_CONFIG_HOME="$T/cfg" bash "$H/new-agent.sh" tnew "$T/src.profile" 2>&1); rc=$?
check "new-agent.sh exits 0" '[ $rc = 0 ] || { echo "$out"; false; }'
for f in sandbox.sh carry-project.sh start-agents.sh stop-agents.sh restart-agents.sh; do
  check "runner/$f is installed and executable" "[ -x '$T/base/runner/$f' ]"
  check "runner/$f matches the skill copy" "cmp -s '$H/$f' '$T/base/runner/$f'"
done
check "the launchers are installed" '[ -x "$T/bin/tnew-agent" ] && [ -x "$T/bin/tnew-sandbox" ]'
check "the restore list is left alone: no launcher added to TMUX_SESSION_PROGRAMS" '! grep -q tnew-agent "$T/cfg/tmux-session/env"'
lout=$(XDG_RUNTIME_DIR="$T/run" bash "$T/bin/tnew-agent" 2>&1); lrc=$?
check "the launcher refuses to run without start-agents.sh's token" '[ $lrc = 2 ] && grep -q "start-agents.sh tnew" <<<"$lout"'
check "positive control: a file the runner never had is absent" '[ ! -e "$T/base/runner/no-such-helper.sh" ]'
echo "---"; echo "$pass passed, $fail failed"; [ "$fail" = 0 ]
