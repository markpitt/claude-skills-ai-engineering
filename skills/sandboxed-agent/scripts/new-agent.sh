#!/usr/bin/env bash
# Install a sandboxed agent from a finished profile: launchers on PATH, env template.
#   new-agent.sh <name> <profile-file> [launch command...]
# Default launch command: claude remote-control --name <name>
set -euo pipefail
NAME=${1:?name}; SRC=${2:?profile file}; shift 2 || true
HERE=$(cd "$(dirname "$0")" && pwd)
BASE=${SANDBOX_BASE:-$HOME/sandboxes}        # everything for one agent lives under $BASE/<name>/
DIR=$BASE/$NAME
BIN=${SANDBOX_BIN:-$HOME/.local/bin}
PROFILE=$DIR/profile
AGENT_HOME=$DIR/home                         # the agent's Claude config dir on the host
ENVF=$DIR/env
SHARE=$BASE/runner                           # stable copy: launchers must not depend on a checkout or branch
MOUNT=$HOME/.$NAME-agent                     # where the agent sees AGENT_HOME inside the sandbox
LAUNCH=("$@"); [ ${#LAUNCH[@]} -gt 0 ] || LAUNCH=(claude remote-control --name "$NAME")

mkdir -p "$SHARE" "$DIR" "$AGENT_HOME" "$BIN"
chmod 700 "$DIR" "$AGENT_HOME"
# installed profile = where things live, then the source profile (its own AGENT_HOME/ENV_FILE are dropped)
{
  printf 'AGENT_HOME=%q\nENV_FILE=%q\n' "$AGENT_HOME" "$ENVF"
  grep -vE '^(AGENT_HOME|ENV_FILE)=' "$SRC"
} > "$PROFILE"
chmod 644 "$PROFILE"
install -m 755 "$HERE/sandbox.sh" "$SHARE/sandbox.sh"
# carry-project, start and restart helpers, kept beside the runner as stable copies (run them from there, e.g. a boot unit or a login hook)
for f in carry-project.sh start-agents.sh stop-agents.sh restart-agents.sh; do install -m 755 "$HERE/$f" "$SHARE/$f"; done

# the agent must not be able to loosen its own limits without asking (see protect-config.sh)
bash "$HERE/protect-config.sh" "$AGENT_HOME" "$MOUNT" >/dev/null
# client settings every sandboxed agent wants: no account connectors, no telemetry, no self-update
( . "$PROFILE"; opts=()
  [ "$NET" = host ] && opts+=(keep-connectors)
  # ALLOW_MESSAGING=1 in the profile persists across re-runs; the environment variable is a one-off
  { [ "${ALLOW_MESSAGING:-}" = 1 ] || [ "${SANDBOX_ALLOW_MESSAGING:-}" = 1 ]; } && opts+=(allow-messaging)
  bash "$HERE/client-env.sh" "$AGENT_HOME" ${opts[@]+"${opts[@]}"} >/dev/null )

# env file: names only, every value commented out; the user fills it in
if [ ! -e "$ENVF" ]; then
  {
    echo "# Sourced by $NAME-agent. chmod 600, keep out of git. Use a scoped credential, never an admin one."
    ( . "$PROFILE"; for v in "${PASS_ENV[@]:-}"; do [ -z "$v" ] || echo "#export $v=\"\""; done )   # not `&&`: under set -e an empty PASS_ENV would end the script here
  } > "$ENVF"
  chmod 600 "$ENVF"
fi

# The agent's project memory folder, made empty here so a new agent has its live store from the start, not a seed copy.
# Claude keys a project by its working directory (WORKDIR, else ROOT, real path, every character but [A-Za-z0-9] as '-'),
# as carry-project.sh does. Not when the agent last ran in another folder: carry-project.sh moves that folder to the new
# key on the next start, and leaves both alone if the new key already exists.
wd=$( . "$PROFILE"; printf '%s' "${WORKDIR:-${ROOT:-}}" )
if ! real=$(realpath -e -- "$wd" 2>/dev/null); then
  MEM="$wd does not exist on this host; no project folder made"
elif [ -f "$AGENT_HOME/.workdir" ] && [ "$(cat "$AGENT_HOME/.workdir")" != "$real" ]; then
  MEM="left for carry-project.sh, which moves $(cat "$AGENT_HOME/.workdir")'s folder to this one on the next start"
else
  MEM=$AGENT_HOME/projects/${real//[^A-Za-z0-9]/-}/memory
  mkdir -p "$MEM"; chmod 700 "$AGENT_HOME/projects" "$MEM"
fi

# tmux-persist must NOT re-run agent launchers: start-agents.sh is the one way an agent starts (the launcher refuses anything else).
# Older installs added <name>-agent to TMUX_SESSION_PROGRAMS; say so, and leave the edit to the user.
CFG=${XDG_CONFIG_HOME:-$HOME/.config}
TE=$CFG/tmux-session/env
if [ -f "$TE" ] && grep -q -- "-agent" "$TE"; then
  echo "note: $TE lists an agent launcher in TMUX_SESSION_PROGRAMS; remove it, start-agents.sh starts agents"
fi

printf '#!/usr/bin/env bash\n# Sandboxed helper: %s shell|test|show|run -- <cmd>\nexec "%s/sandbox.sh" "%s" "${@:-shell}"\n' "$NAME-sandbox" "$SHARE" "$PROFILE" > "$BIN/$NAME-sandbox"
q=$(printf '%q ' "${LAUNCH[@]}")
# The launcher refuses to run unless start-agents.sh started it: a one-time token in its environment that matches the file
# start-agents.sh wrote (and this deletes). A guard against other start routes and habit, not a security boundary.
{
  printf '#!/usr/bin/env bash\n'
  printf '# Start the agent for %s inside its sandbox. Only start-agents.sh runs this (start-agents.sh %s). Not exec'"'"'d on purpose:\n' "$NAME" "$NAME"
  printf '# this script stays the pane'"'"'s foreground command, which is how start-agents.sh and restart-agents.sh find the agent.\n'
  printf 't="${XDG_RUNTIME_DIR:-/tmp}/start-agents/%s.token"\n' "$NAME"
  printf 'if [ -z "${START_AGENTS_TOKEN:-}" ] || [ ! -O "$t" ] || [ "$(cat "$t" 2>/dev/null)" != "$START_AGENTS_TOKEN" ]; then\n'
  printf '  echo "%s-agent: refused. Start it with start-agents.sh %s, the one way an agent starts." >&2; exit 2\n' "$NAME" "$NAME"
  printf 'fi\nrm -f "$t"; unset START_AGENTS_TOKEN\n'
  printf 'command -v tmux-session >/dev/null && tmux-session wait-dns\n'
  printf '"%s/sandbox.sh" "%s" run -- %s"$@"\n' "$SHARE" "$PROFILE" "$q"
} > "$BIN/$NAME-agent"
chmod +x "$BIN/$NAME-sandbox" "$BIN/$NAME-agent"

echo "installed: $BIN/$NAME-agent  $BIN/$NAME-sandbox"
echo "profile:   $PROFILE"
echo "env:       $ENVF  (fill in, then: $NAME-sandbox test)"
echo "home:      $AGENT_HOME  (seen inside as $MOUNT)"
echo "memory:    $MEM"
( . "$PROFILE"; [ "$NET" = proxy ] && ! (exec 3<>"/dev/tcp/${PROXY_ADDR%:*}/${PROXY_ADDR##*:}") 2>/dev/null \
    && echo "proxy:     nothing listens on $PROXY_ADDR: run scripts/install-proxy.sh (see references/proxy.md)" ) || true
