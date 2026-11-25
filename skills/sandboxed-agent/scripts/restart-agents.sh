#!/usr/bin/env bash
# Restart the sandboxed agents running in this tmux session: stop each agent launcher (<name>-agent, installed by the
# sandboxed-agent skill) in its pane with stop-agents.sh, then start it again in that pane with start-agents.sh --pane.
#
#   restart-agents.sh                    restart every agent pane in this session (never the pane you run it from)
#   restart-agents.sh alpha beta        only those names (the part before -agent)
#   restart-agents.sh --dry-run          list what would be restarted, change nothing
#   restart-agents.sh --session NAME     another tmux session (default: the one this runs in, else the only one)
#
# A pane counts as an agent only when its foreground child is the launcher script (`bash <dir>/<name>-agent`, an executable in
# $BIN, default ~/.local/bin). Timing: Ctrl-C usually stops a remote-control agent within a few seconds (three agents restarted in
# about 30 s including the 5 s settle after each start); an agent that rides out INT_WAIT (20 s) is stopped by SIGTERM instead.
# Why a restart: hooks and settings load when the agent starts (ask rules apply at once, hooks do not).
# Stopping: Ctrl-C in the pane, then SIGTERM to the launcher's own process tree if it is still there after 20 s. Never SIGKILL: an
# agent that will not stop is reported and left alone. In-flight work in that agent is lost; the session reconnects under
# the same --name when it comes back.
# Test hooks: TMUX_SOCKET=<name> uses `tmux -L <name>` (the test script uses an isolated server); BIN; INT_WAIT and TERM_WAIT
# (seconds, default 20 and 10) shorten the waits; SANDBOXES and SANDBOX_HOSTNAME reach start-agents.sh, which checks the agent exists.
set -uo pipefail

T() { tmux ${TMUX_SOCKET:+-L "$TMUX_SOCKET"} "$@"; }
BIN=${BIN:-$HOME/.local/bin}
dry=0; sess=""; want=()
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry=1 ;;
    --session) sess=${2:?--session needs a name}; shift ;;
    -h|--help) sed -n 2,14p "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option $1" >&2; exit 2 ;;
    *) want+=("$1") ;;
  esac
  shift
done

T has-session 2>/dev/null || { echo "no tmux server running" >&2; exit 1; }
if [ -z "$sess" ]; then
  if [ -n "${TMUX_PANE:-}" ]; then sess=$(T display-message -p -t "$TMUX_PANE" '#{session_name}')
  elif [ "$(T list-sessions -F x | wc -l)" = 1 ]; then sess=$(T list-sessions -F '#{session_name}')
  else echo "several tmux sessions: pass --session NAME" >&2; exit 2; fi
fi

# launcher_of PANE_PID -> "<launcher-pid> <name>" when the pane's foreground child IS the launcher script: a shell running
# <dir>/<name>-agent whose file is an executable in $BIN. A command that merely mentions a path ending in -agent does not count.
launcher_of() {
  local pid args name
  while read -r pid args; do
    if [[ "$args" =~ ^(/[^[:space:]]*/)?bash[[:space:]]+[^[:space:]]*/([a-z0-9][a-z0-9-]*)-agent([[:space:]]|$) ]]; then
      name=${BASH_REMATCH[2]}
      [ -x "$BIN/$name-agent" ] && { echo "$pid $name"; return 0; }
    fi
  done < <(ps -o pid=,args= --ppid "$1" 2>/dev/null)
  return 1
}
wanted() { [ ${#want[@]} -eq 0 ] && return 0; local w; for w in "${want[@]}"; do [ "$w" = "$1" ] && return 0; done; return 1; }

P_ID=(); P_NAME=(); P_LPID=()
while IFS=' ' read -r pane ppid; do
  [ "$pane" = "${TMUX_PANE:-}" ] && continue                       # never the pane we run from
  l=$(launcher_of "$ppid") || continue
  name=${l#* }; wanted "$name" || continue
  P_ID+=("$pane"); P_NAME+=("$name"); P_LPID+=("${l%% *}")
done < <(T list-panes -s -t "$sess" -F '#{pane_id} #{pane_pid}')

if [ ${#P_ID[@]} -eq 0 ]; then echo "no agent panes to restart in session '$sess'"; exit 0; fi
for i in "${!P_ID[@]}"; do echo "${P_NAME[$i]}-agent  pane ${P_ID[$i]}  launcher pid ${P_LPID[$i]}"; done
[ "$dry" = 1 ] && { echo "(dry run: nothing changed)"; exit 0; }

# Stop and start go through stop-agents.sh and start-agents.sh, so there is one stop path and one start path. start-agents.sh --pane
# types the launcher back into the same pane with a fresh one-time token (a launcher refuses any other start).
H=$(cd "$(dirname "$0")" && pwd)
bad=0
for i in "${!P_ID[@]}"; do
  pane=${P_ID[$i]}; name=${P_NAME[$i]}
  out=$(bash "$H/stop-agents.sh" --pane "$pane" 2>&1); rc=$?
  if [ "$rc" != 0 ] || ! grep -q "^$name: stopping... stopped$" <<<"$out"; then
    echo "$name: $(tail -n 1 <<<"$out" | sed "s/^$name: stopping... //"), not restarted"; bad=1; continue
  fi
  sleep 1
  out=$(bash "$H/start-agents.sh" ${sess:+--session "$sess"} --pane "$pane" "$name" 2>&1); rc=$?
  if [ "$rc" = 0 ]; then echo "$name: restarted"; else echo "$name: stopped, but the start failed: $(tail -n 1 <<<"$out")"; bad=1; fi
done
exit $bad
