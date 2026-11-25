#!/usr/bin/env bash
# Start the sandboxed agents that are not running, each in its own pane of the "agents" window of a tmux session. This is the ONE way an
# agent starts: the launcher (<name>-agent) refuses to run unless this script handed it a one-time token (new-agent.sh writes that check).
# An agent is a folder ~/sandboxes/<name> that has a `profile` and an installed launcher ~/.local/bin/<name>-agent
# (both made by the sandboxed-agent skill). When ~/sandboxes is a shared repo with a hosts/map, the agents are in
# ~/sandboxes/hosts/<host>/<name>, where <host> is what the map lists against this machine's hostname (uname -n); an unlisted
# hostname is an error, not "nothing to start".
#
#   start-agents.sh                    start every agent that starts at boot (see GROUPS) and is not running
#   start-agents.sh alpha beta        only those names; an explicit name starts even with .no-autostart or in an on-request group
#   start-agents.sh --group NAME       every agent of that group (repeatable), in the order the groups file lists them
#   start-agents.sh --pane ID NAME     start the one agent NAME in that tmux pane, which must be an idle shell (restart-agents.sh uses it)
#   start-agents.sh --status           one line per agent: name, group, when it starts, running or stopped; changes nothing
#   start-agents.sh --dry-run          list what would be started and what is skipped, change nothing
#   start-agents.sh --layout windows   one window per agent, named after the agent (default: panes of one "agents" window;
#                                      START_AGENTS_LAYOUT=windows sets it for a host)
#   start-agents.sh --session NAME     tmux session to use (default: the one this runs in, else the only one; created
#                                      detached, with an "agents" window, when it does not exist or no tmux runs)
#
# GROUPS. An optional file `groups` in the agents' folder, one group a line:  <group> <boot> <agent>...   (# starts a comment)
# <boot> is a number (the group starts at boot, lowest number first) or `no` (it starts only when named, with --group or by name).
# An agent is in at most one group. An agent in no group starts at boot unless its folder holds .no-autostart, after the groups.
#
# PACING. Agents start one at a time. After each start it waits START_AGENTS_STAGGER_S seconds (default 5, the least) before the next.
# START_AGENTS_GATE names an executable run before EVERY start (a memory check, say): while it exits non-zero the start waits,
# polling every START_AGENTS_GATE_POLL_S (15) seconds; after START_AGENTS_GATE_WAIT_S (600) the rest are left out, reported as
# "deferred", and the exit status is 3. The gate's last line of output is the reason given.
#
# "Running" means a <name>-agent launcher process exists anywhere on the machine, in tmux or not, so it never starts a
# second copy. The launcher is typed into a fresh pane of a shell, as START_AGENTS_TOKEN=<token> <name>-agent; the token is also
# written to $XDG_RUNTIME_DIR/start-agents/<name>.token (mode 600), and the launcher checks the two match and deletes the file.
# In the windows layout an agent whose window already exists is started in that window when its pane is an idle shell; a busy
# window is left alone and reported.
# Exit: 0 all started (or nothing to do), 1 a start failed, 2 a usage error, 3 some were deferred by the gate.
# Test hooks: TMUX_SOCKET=<name> (tmux -L), SANDBOXES=<dir>, BIN=<dir>, SANDBOX_HOSTNAME=<name> (stands in for uname -n),
# START_AGENTS_SETTLE_S (seconds to wait for a launcher to show, default 5).
set -uo pipefail

T() { tmux ${TMUX_SOCKET:+-L "$TMUX_SOCKET"} "$@"; }
SANDBOXES=${SANDBOXES:-$HOME/sandboxes}; BIN=${BIN:-$HOME/.local/bin}
dry=0; sess=""; want=(); groups_want=(); layout=${START_AGENTS_LAYOUT:-panes}; status=0; one_pane=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry=1 ;;
    --status) status=1 ;;
    --session) sess=${2:?--session needs a name}; shift ;;
    --layout) layout=${2:?--layout needs panes or windows}; shift ;;
    --group) groups_want+=("${2:?--group needs a name}"); shift ;;
    --pane) one_pane=${2:?--pane needs a pane id}; shift ;;
    -h|--help) sed -n 2,34p "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option $1" >&2; exit 2 ;;
    *) want+=("$1") ;;
  esac
  shift
done

case "$layout" in panes|windows) ;; *) echo "--layout must be panes or windows" >&2; exit 2 ;; esac
num() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; }
STAGGER=${START_AGENTS_STAGGER_S:-5}; SETTLE=${START_AGENTS_SETTLE_S:-5}
POLL=${START_AGENTS_GATE_POLL_S:-15}; GATE_WAIT=${START_AGENTS_GATE_WAIT_S:-600}; GATE=${START_AGENTS_GATE:-}
for v in "$STAGGER" "$SETTLE" "$POLL" "$GATE_WAIT"; do num "$v" || { echo "the START_AGENTS_*_S settings must be whole seconds" >&2; exit 2; }; done
[ -z "$GATE" ] || [ -x "$GATE" ] || { echo "START_AGENTS_GATE is not an executable: $GATE" >&2; exit 2; }
if [ -n "$one_pane" ] && { [ ${#want[@]} -ne 1 ] || [ ${#groups_want[@]} -gt 0 ]; }; then echo "--pane takes exactly one agent name" >&2; exit 2; fi

if [ -f "$SANDBOXES/hosts/map" ]; then                                         # a shared repo: use this machine's host folder
  host=${SANDBOX_HOSTNAME:-$(uname -n)}
  mapped=$(awk -v h="$host" '$1 !~ /^#/ && $1 == h { print $2; exit }' "$SANDBOXES/hosts/map")
  [ -n "$mapped" ] && [ -d "$SANDBOXES/hosts/$mapped" ] || {
    echo "hostname '$host' has no host folder in $SANDBOXES/hosts/map" >&2; exit 2; }
  SANDBOXES=$SANDBOXES/hosts/$mapped
fi

running() { pgrep -f "^bash [^ ]*/$1-agent( |\$)" >/dev/null; }   # the launcher script, however it was started
is_agent() { [ -f "$SANDBOXES/$1/profile" ] && [ -x "$BIN/$1-agent" ]; }
in_list() { local x=$1 w; shift; for w in "$@"; do [ "$w" = "$x" ] && return 0; done; return 1; }

# the groups file: G_NAME[i] G_BOOT[i] G_AGENTS[i]; AGENT_GROUP[name] for the lookup. Malformed lines are an error, not skipped.
declare -A AGENT_GROUP=() AGENT_BOOT=()
G_NAME=(); G_BOOT=(); G_AGENTS=()
GF=$SANDBOXES/groups
if [ -f "$GF" ]; then
  ln=0
  while read -r line; do
    ln=$((ln + 1)); line=${line%%#*}; read -r g b rest <<<"$line"; [ -n "${g:-}" ] || continue
    [ -n "${rest:-}" ] && { num "$b" || [ "$b" = no ]; } || { echo "$GF line $ln: want <group> <number|no> <agent>..." >&2; exit 2; }
    in_list "$g" ${G_NAME[@]+"${G_NAME[@]}"} && { echo "$GF line $ln: group $g is listed twice" >&2; exit 2; }
    for a in $rest; do
      [ -z "${AGENT_GROUP[$a]:-}" ] || { echo "$GF line $ln: $a is already in group ${AGENT_GROUP[$a]}" >&2; exit 2; }
      AGENT_GROUP[$a]=$g; AGENT_BOOT[$a]=$b
    done
    G_NAME+=("$g"); G_BOOT+=("$b"); G_AGENTS+=("$rest")
  done < "$GF"
fi
for g in ${groups_want[@]+"${groups_want[@]}"}; do in_list "$g" ${G_NAME[@]+"${G_NAME[@]}"} || { echo "no such group: $g${G_NAME[0]:+ (groups: ${G_NAME[*]})}" >&2; exit 2; }; done
for n in ${want[@]+"${want[@]}"}; do is_agent "$n" || { echo "no such agent: $n" >&2; exit 2; }; done

# every agent folder, in start order: boot groups by number then file order, then on-request groups, then ungrouped by name
order=()
for i in $(for i in "${!G_NAME[@]}"; do b=${G_BOOT[$i]}; [ "$b" = no ] && b=999999; printf '%s %s\n' "$b" "$i"; done | sort -n -s -k1,1 | awk '{print $2}'); do
  for a in ${G_AGENTS[$i]}; do is_agent "$a" && order+=("$a"); done
done
for d in "$SANDBOXES"/*/; do n=$(basename "$d"); is_agent "$n" && [ -z "${AGENT_GROUP[$n]:-}" ] && order+=("$n"); done

if [ "$status" = 1 ]; then
  for n in ${order[@]+"${order[@]}"}; do
    g=${AGENT_GROUP[$n]:--}; b=${AGENT_BOOT[$n]:-}
    if [ -n "$b" ]; then [ "$b" = no ] && when=on-request || when="boot($b)"; elif [ -e "$SANDBOXES/$n/.no-autostart" ]; then when=on-request; else when=boot; fi
    running "$n" && st=running || st=stopped
    printf '%-28s %-14s %-12s %s\n' "$n" "$g" "$when" "$st"
  done
  exit 0
fi

todo=(); skipped=()
for n in ${order[@]+"${order[@]}"}; do
  if [ ${#want[@]} -gt 0 ] || [ ${#groups_want[@]} -gt 0 ]; then
    in_list "$n" ${want[@]+"${want[@]}"} || in_list "${AGENT_GROUP[$n]:-}" ${groups_want[@]+"${groups_want[@]}"} || continue
    explicit=1
  else explicit=0; fi
  if running "$n"; then skipped+=("$n: already running"); continue; fi
  if [ "$explicit" = 0 ]; then
    if [ "${AGENT_BOOT[$n]:-}" = no ]; then skipped+=("$n: group ${AGENT_GROUP[$n]} starts on request"); continue; fi
    if [ -z "${AGENT_GROUP[$n]:-}" ] && [ -e "$SANDBOXES/$n/.no-autostart" ]; then skipped+=("$n: .no-autostart"); continue; fi
  fi
  todo+=("$n")
done

for s in ${skipped[@]+"${skipped[@]}"}; do echo "skip   $s"; done
if [ ${#todo[@]} -eq 0 ]; then echo "nothing to start"; [ ${#skipped[@]} -gt 0 ] || echo "(no agents found in $SANDBOXES)"; exit 0; fi
for n in "${todo[@]}"; do echo "start  $n-agent"; done
[ "$dry" = 1 ] && { echo "(dry run: nothing changed)"; exit 0; }

# gate_ok: true when there is no gate or it passes within GATE_WAIT; otherwise REASON holds its last line
REASON=""
gate_ok() {
  [ -n "$GATE" ] || return 0
  local waited=0 out
  while :; do
    out=$("$GATE" 2>&1) && return 0
    REASON=$(printf '%s\n' "$out" | tail -n 1)
    [ "$waited" -ge "$GATE_WAIT" ] && return 1
    [ "$waited" = 0 ] && echo "waiting: ${REASON:-the gate failed}"
    sleep "$POLL"; waited=$((waited + POLL))
  done
}
# launch PANE NAME: type the launcher with a fresh one-time token
TOKDIR=${XDG_RUNTIME_DIR:-/tmp}/start-agents
launch() {
  local pane=$1 n=$2 tok
  mkdir -p -m 700 "$TOKDIR" && [ -O "$TOKDIR" ] || { echo "$n: cannot use the token folder $TOKDIR"; return 1; }
  tok=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
  ( umask 077; printf '%s\n' "$tok" > "$TOKDIR/$n.token" ) || { echo "$n: cannot write its token"; return 1; }
  T send-keys -t "$pane" "START_AGENTS_TOKEN=$tok $n-agent" Enter
}
settled() { sleep "$SETTLE"; running "$1"; }
pace() { [ "$1" -lt $((${#todo[@]} - 1)) ] && [ "$STAGGER" -gt "$SETTLE" ] && sleep $((STAGGER - SETTLE)); return 0; }
deferred() { local i; for ((i = $1; i < ${#todo[@]}; i++)); do echo "deferred ${todo[$i]}: ${REASON:-the gate failed}"; done; exit 3; }

if [ -n "$one_pane" ]; then
  n=${todo[0]}
  cmd=$(T display-message -p -t "$one_pane" '#{pane_current_command}' 2>/dev/null) || { echo "$n: no pane $one_pane" >&2; exit 2; }
  case $cmd in bash|zsh|sh|fish|dash) ;; *) echo "$n: pane $one_pane is busy ($cmd), left alone"; exit 1 ;; esac
  gate_ok || deferred 0
  launch "$one_pane" "$n" || exit 1
  if settled "$n"; then echo "$n: started in $one_pane"; exit 0; else echo "$n: launcher not seen after $SETTLE s, check pane $one_pane"; exit 1; fi
fi

if [ -z "$sess" ]; then
  if ! T has-session 2>/dev/null; then sess=agents
  elif [ -n "${TMUX_PANE:-}" ]; then sess=$(T display-message -p -t "$TMUX_PANE" '#{session_name}')
  elif [ "$(T list-sessions -F x | wc -l)" = 1 ]; then sess=$(T list-sessions -F '#{session_name}')
  else echo "several tmux sessions: pass --session NAME" >&2; exit 2; fi
fi
first=0
if ! T has-session -t "$sess" 2>/dev/null; then
  T new-session -d -s "$sess" -n agents "bash --norc" || { echo "cannot create tmux session $sess" >&2; exit 1; }
  first=1                                                                       # its first agent takes the new session's own shell pane
fi
if [ "$layout" = panes ]; then
  win=$(T list-windows -t "$sess" -F '#{window_name}' | grep -x agents >/dev/null && echo "$sess:agents" || echo "")
  if [ -z "$win" ]; then T new-window -d -t "$sess" -n agents "bash --norc"; win="$sess:agents"; first=1; fi
fi

bad=0
for i in "${!todo[@]}"; do
  n=${todo[$i]}
  gate_ok || deferred "$i"
  if [ "$layout" = windows ]; then
    wid=$(T list-windows -t "$sess" -F '#{window_name} #{window_id}' | awk -v n="$n" '$1==n{print $2; exit}')
    if [ -n "$wid" ]; then                                                      # a window of that name exists: reuse it when idle
      pane=$(T list-panes -t "$wid" -F '#{pane_id} #{pane_current_command}' | head -1)
      case ${pane#* } in bash|zsh|sh|fish|dash) pane=${pane%% *} ;; *) echo "$n: window exists and is busy (${pane#* }), left alone"; bad=1; continue ;; esac
    elif [ "$first" = 1 ]; then pane=$(T list-panes -t "$sess" -F '#{pane_id}' | head -1); T rename-window -t "$pane" "$n"; first=0
    else pane=$(T new-window -d -t "$sess:" -n "$n" -P -F '#{pane_id}' "bash --norc") || { echo "$n: no window"; bad=1; continue; }
    fi
    where="window $n"
  else
    if [ "$first" = 1 ]; then pane=$(T list-panes -t "$win" -F '#{pane_id}' | head -1); first=0   # the shell the new window came with
    else
      pane=$(T split-window -d -t "$win" -P -F '#{pane_id}' "bash --norc" 2>/dev/null) || pane=$(T new-window -d -t "$sess" -n "$n-agent" -P -F '#{pane_id}' "bash --norc") || { echo "$n: no pane"; bad=1; continue; }
      T select-layout -t "$win" tiled >/dev/null 2>&1
    fi
    T select-pane -t "$pane" -T "$n-agent"
    where=$pane
  fi
  launch "$pane" "$n" || { bad=1; continue; }
  if settled "$n"; then echo "$n: started in $where"; else echo "$n: launcher not seen after $SETTLE s, check $where"; bad=1; fi
  pace "$i"
done
exit $bad
