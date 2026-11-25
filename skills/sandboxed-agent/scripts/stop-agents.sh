#!/usr/bin/env bash
# Stop sandboxed agents running in tmux: Ctrl-C in the agent's pane, then SIGTERM to the launcher's own process tree if it is still
# there after INT_WAIT (20) seconds. Never SIGKILL: an agent that will not stop is reported and left alone. The pane stays, as an
# idle shell, so start-agents.sh --pane can start the agent there again (restart-agents.sh does exactly that).
#
#   stop-agents.sh alpha beta          stop those agents (the part before -agent)
#   stop-agents.sh --group NAME        stop every agent of that group in the groups file (repeatable; see start-agents.sh)
#   stop-agents.sh --pane ID           stop the agent in that one pane
#   stop-agents.sh --dry-run ...       list what would be stopped, change nothing
#   stop-agents.sh --session NAME ...  look only in that tmux session (default: every session)
#
# With no name, group or pane it refuses: stopping everything is not a default. Never the pane it runs from.
# A pane counts as an agent only when its foreground child is the launcher script (`bash <dir>/<name>-agent`, an executable in
# $BIN, default ~/.local/bin). In-flight work in that agent is lost; the session reconnects under the same --name when it comes back.
# Exit: 0 stopped (or nothing running), 1 one would not stop, 2 a usage error.
# Test hooks: TMUX_SOCKET=<name> (tmux -L), BIN, SANDBOXES and SANDBOX_HOSTNAME (passed to start-agents.sh --status for groups),
# INT_WAIT and TERM_WAIT (seconds, default 20 and 10).
set -uo pipefail

T() { tmux ${TMUX_SOCKET:+-L "$TMUX_SOCKET"} "$@"; }
H=$(cd "$(dirname "$0")" && pwd)
BIN=${BIN:-$HOME/.local/bin}
dry=0; sess=""; want=(); groups_want=(); only_pane=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry=1 ;;
    --session) sess=${2:?--session needs a name}; shift ;;
    --group) groups_want+=("${2:?--group needs a name}"); shift ;;
    --pane) only_pane=${2:?--pane needs a pane id}; shift ;;
    -h|--help) sed -n 2,17p "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option $1" >&2; exit 2 ;;
    *) want+=("$1") ;;
  esac
  shift
done
[ ${#want[@]} -gt 0 ] || [ ${#groups_want[@]} -gt 0 ] || [ -n "$only_pane" ] || { echo "name the agents, a --group or a --pane to stop" >&2; exit 2; }

if [ ${#groups_want[@]} -gt 0 ]; then                    # the group's members, from the one parser of the groups file
  st=$(bash "$H/start-agents.sh" --status) || { echo "cannot read the groups (start-agents.sh --status failed)" >&2; exit 2; }
  for g in "${groups_want[@]}"; do
    members=$(awk -v g="$g" '$2 == g { print $1 }' <<<"$st")
    grp=$(bash "$H/start-agents.sh" --dry-run --group "$g" 2>&1 >/dev/null) || { echo "$grp" >&2; exit 2; }
    for m in $members; do want+=("$m"); done
  done
  [ ${#want[@]} -gt 0 ] || { echo "no installed agents in group(s) ${groups_want[*]}"; exit 0; }
fi

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

T has-session 2>/dev/null || { echo "no tmux server running: nothing to stop"; exit 0; }
if [ -n "$sess" ]; then panes=$(T list-panes -s -t "$sess" -F '#{pane_id} #{pane_pid}') || { echo "no tmux session $sess" >&2; exit 2; }
else panes=$(T list-panes -a -F '#{pane_id} #{pane_pid}'); fi

P_ID=(); P_NAME=(); P_LPID=()
while IFS=' ' read -r pane ppid; do
  [ -n "$pane" ] || continue
  [ "$pane" = "${TMUX_PANE:-}" ] && continue                       # never the pane we run from
  [ -n "$only_pane" ] && [ "$pane" != "$only_pane" ] && continue
  l=$(launcher_of "$ppid") || continue
  name=${l#* }; wanted "$name" || continue
  P_ID+=("$pane"); P_NAME+=("$name"); P_LPID+=("${l%% *}")
done <<<"$panes"

if [ ${#P_ID[@]} -eq 0 ]; then echo "no running agent panes to stop"; exit 0; fi
for i in "${!P_ID[@]}"; do echo "${P_NAME[$i]}-agent  pane ${P_ID[$i]}  launcher pid ${P_LPID[$i]}"; done
[ "$dry" = 1 ] && { echo "(dry run: nothing changed)"; exit 0; }

alive() { kill -0 "$1" 2>/dev/null; }
tree() { local p; for p in $(pgrep -P "$1"); do tree "$p"; echo "$p"; done; }
bad=0
for i in "${!P_ID[@]}"; do
  pane=${P_ID[$i]}; name=${P_NAME[$i]}; lp=${P_LPID[$i]}
  printf '%s: stopping... ' "$name"
  T send-keys -t "$pane" C-c
  for _ in $(seq "${INT_WAIT:-20}"); do alive "$lp" || break; sleep 1; done
  if alive "$lp"; then
    for p in $(tree "$lp") "$lp"; do kill -TERM "$p" 2>/dev/null; done
    for _ in $(seq "${TERM_WAIT:-10}"); do alive "$lp" || break; sleep 1; done
  fi
  if alive "$lp"; then echo "still running, left alone"; bad=1; else echo "stopped"; fi
done
exit $bad
