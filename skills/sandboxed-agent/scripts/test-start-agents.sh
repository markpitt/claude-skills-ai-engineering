#!/usr/bin/env bash
# Test start-agents.sh on an isolated tmux server with fake sandboxes and launchers. Touches no real agent.
set -uo pipefail
H=$(cd "$(dirname "$0")" && pwd)
D=$(mktemp -d); SOCK=sa-test-$$; fail=0
T() { tmux -L "$SOCK" "$@"; }
cleanup() { T kill-server 2>/dev/null; rm -rf "$D"; }; trap cleanup EXIT
ok() { echo "ok    $1"; }; bad() { echo "FAIL  $1"; fail=1; }
mkdir -p "$D/sb" "$D/bin"
for n in alpha beta gamma; do
  mkdir -p "$D/sb/$n"; : > "$D/sb/$n/profile"
  printf '#!/usr/bin/env bash\necho x >> "%s/%s.starts"\nsleep 600\n' "$D" "$n" > "$D/bin/$n-agent"; chmod +x "$D/bin/$n-agent"
done
mkdir -p "$D/sb/notanagent"; : > "$D/sb/notanagent/profile"                      # a profile but no launcher
touch "$D/sb/gamma/.no-autostart"
export PATH="$D/bin:$PATH" TMUX_SOCKET=$SOCK SANDBOXES="$D/sb" BIN="$D/bin"   # as in real life, the launcher dir is on PATH
out=$(bash "$H/start-agents.sh" --dry-run); grep -q "start  alpha-agent" <<<"$out" && grep -q "start  beta-agent" <<<"$out" && grep -q "skip   gamma: .no-autostart" <<<"$out" && ! grep -q notanagent <<<"$out" \
  && ok "dry run: alpha and beta start, gamma skipped by .no-autostart, a folder without a launcher is ignored" || bad "dry run: $out"
[ ! -e "$D/alpha.starts" ] && ok "dry run started nothing" || bad "dry run started something"
bash "$H/start-agents.sh" >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] && [ "$(wc -l < "$D/alpha.starts")" = 1 ] && [ "$(wc -l < "$D/beta.starts")" = 1 ] && [ ! -e "$D/gamma.starts" ] && ok "no tmux server: session created, alpha and beta started once, gamma not" || bad "start: rc=$rc"
T list-windows -F '#{window_name}' | grep -qx agents && [ "$(T list-panes -t agents:agents | wc -l)" = 2 ] && ok "both agents are in panes of the agents window" || bad "layout: $(T list-panes -a -F '#{window_name}')"
out=$(bash "$H/start-agents.sh" 2>&1); grep -q "alpha: already running" <<<"$out" && grep -q "nothing to start" <<<"$out" && [ "$(wc -l < "$D/alpha.starts")" = 1 ] && ok "second run starts nothing (already running)" || bad "second run: $out"
bash "$H/start-agents.sh" gamma >/dev/null 2>&1; [ "$(wc -l < "$D/gamma.starts" 2>/dev/null || echo 0)" = 1 ] && ok "an explicit name starts despite .no-autostart" || bad "explicit gamma"
out=$(bash "$H/start-agents.sh" nosuch 2>&1); rc=$?; [ "$rc" = 2 ] && grep -q "no such agent" <<<"$out" && ok "unknown name refused" || bad "unknown: rc=$rc $out"

# windows layout: one window per agent, named after the agent
T kill-server 2>/dev/null; sleep 0.5; rm -f "$D"/*.starts
bash "$H/start-agents.sh" --layout windows >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] && [ "$(wc -l < "$D/alpha.starts")" = 1 ] && [ "$(wc -l < "$D/beta.starts")" = 1 ] && [ ! -e "$D/gamma.starts" ] && ok "windows layout: alpha and beta started once, gamma (.no-autostart) not" || bad "windows start: rc=$rc"
names=$(T list-windows -a -F '#{window_name}' | sort | paste -sd,)
[ "$names" = "alpha,beta" ] && [ "$(T list-panes -a | wc -l)" = 2 ] && ok "windows layout: one window per agent named after it, one pane each, no leftover agents window" || bad "windows layout names: $names"
out=$(bash "$H/start-agents.sh" --layout windows 2>&1); grep -q "nothing to start" <<<"$out" && ok "windows layout: second run starts nothing" || bad "windows second run: $out"
# an existing idle window of the agent's name is reused; a busy one is left alone
T kill-server 2>/dev/null; sleep 0.5; rm -f "$D"/*.starts
T new-session -d -s w -x 200 -y 50 "bash --norc"; T new-window -d -t w: -n alpha "bash --norc"; T new-window -d -t w: -n beta "sleep 600"
sleep 1
out=$(START_AGENTS_LAYOUT=windows bash "$H/start-agents.sh" --session w 2>&1)
[ "$(wc -l < "$D/alpha.starts" 2>/dev/null || echo 0)" = 1 ] && [ "$(T list-windows -t w -F '#{window_name}' | grep -c '^alpha$')" = 1 ] && ok "an idle window named alpha is reused (env START_AGENTS_LAYOUT), no duplicate window" || bad "reuse idle window: $out"
grep -q "beta: window exists and is busy" <<<"$out" && [ ! -e "$D/beta.starts" ] && ok "a busy window named beta is left alone and reported" || bad "busy window: $out"
out=$(bash "$H/start-agents.sh" --layout nonsense 2>&1); rc=$?; [ "$rc" = 2 ] && ok "bad --layout refused" || bad "bad layout rc=$rc"

# a shared repo with hosts/map: the agents are found in this machine's host folder, not at the top level
T kill-server 2>/dev/null; sleep 0.5; rm -f "$D"/*.starts
mkdir -p "$D/repo/hosts/box/alpha" "$D/repo/hosts/other/beta" "$D/repo/runner"; : > "$D/repo/hosts/box/alpha/profile"; : > "$D/repo/hosts/other/beta/profile"
printf '# hostname  host-folder\nbox-1  box\nbox-2  other\n' > "$D/repo/hosts/map"
out=$(SANDBOXES="$D/repo" SANDBOX_HOSTNAME=box-1 bash "$H/start-agents.sh" --dry-run 2>&1)
grep -q "start  alpha-agent" <<<"$out" && ! grep -q beta <<<"$out" && ok "hosts/map: the mapped host folder's agents are listed, another host's are not" || bad "hosts/map dry run: $out"
out=$(SANDBOXES="$D/repo" SANDBOX_HOSTNAME=nosuch bash "$H/start-agents.sh" --dry-run 2>&1); rc=$?
[ "$rc" = 2 ] && grep -q "has no host folder" <<<"$out" && ok "hosts/map: an unlisted hostname is an error" || bad "hosts/map unlisted: rc=$rc $out"
out=$(SANDBOXES="$D/repo/hosts/box/alpha" bash "$H/start-agents.sh" --dry-run 2>&1)
grep -q "no agents found in" <<<"$out" && ok "an empty folder says no agents were found" || bad "no agents hint: $out"
# groups: boot order, on-request groups, --group, --status, a malformed file
clear_starts() { find "${D:?}" -maxdepth 1 -name '*.starts' -delete; }
T kill-server 2>/dev/null; sleep 0.5; clear_starts
for n in delta eps; do mkdir -p "$D/sb/$n"; : > "$D/sb/$n/profile"
  printf '#!/usr/bin/env bash\necho x >> "%s/%s.starts"\nsleep 600\n' "$D" "$n" > "$D/bin/$n-agent"; chmod +x "$D/bin/$n-agent"; done
printf '# group boot agents\nlate 2 beta\nearly 1 delta # first\nkids no eps gamma\n' > "$D/sb/groups"
export START_AGENTS_SETTLE_S=1
out=$(bash "$H/start-agents.sh" --dry-run)
starts=$(grep '^start' <<<"$out" | awk '{print $2}' | paste -sd,)
[ "$starts" = "delta-agent,beta-agent,alpha-agent" ] && ok "groups: boot groups by number, then ungrouped agents" || bad "group order: $starts"
grep -q "skip   eps: group kids starts on request" <<<"$out" && grep -q "skip   gamma: group kids starts on request" <<<"$out" && ok "groups: an on-request group is skipped at boot" || bad "on request: $out"
out=$(bash "$H/start-agents.sh" --group kids 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$(wc -l < "$D/eps.starts")" = 1 ] && [ "$(wc -l < "$D/gamma.starts")" = 1 ] && [ ! -e "$D/alpha.starts" ] && ok "--group starts that group only, .no-autostart or not" || bad "--group: rc=$rc $out"
st=$(bash "$H/start-agents.sh" --status)
grep -Eq '^eps +kids +on-request +running$' <<<"$st" && grep -Eq '^delta +early +boot\(1\) +stopped$' <<<"$st" && grep -Eq '^alpha +- +boot +stopped$' <<<"$st" && ok "--status: group, when it starts, running or stopped" || bad "status: $st"
out=$(bash "$H/start-agents.sh" --group nosuch 2>&1); rc=$?; [ "$rc" = 2 ] && grep -q "no such group" <<<"$out" && ok "an unknown group is refused" || bad "unknown group: rc=$rc"
printf 'a 1 alpha\nb 2 alpha\n' > "$D/sb/groups"; out=$(bash "$H/start-agents.sh" --dry-run 2>&1); rc=$?
[ "$rc" = 2 ] && grep -q "already in group a" <<<"$out" && ok "an agent in two groups is an error" || bad "two groups: rc=$rc $out"
printf 'a soon alpha\n' > "$D/sb/groups"; out=$(bash "$H/start-agents.sh" --dry-run 2>&1); rc=$?
[ "$rc" = 2 ] && grep -q "line 1" <<<"$out" && ok "a malformed groups line is an error, not skipped" || bad "malformed: rc=$rc $out"
printf 'kids no eps gamma\n' > "$D/sb/groups"

# stop-agents.sh --group stops the group's agents and nothing else
out=$(INT_WAIT=3 TERM_WAIT=2 bash "$H/stop-agents.sh" --group kids 2>&1); rc=$?
sleep 0.5
[ "$rc" = 0 ] && ! pgrep -f "^bash [^ ]*/eps-agent" >/dev/null && ! pgrep -f "^bash [^ ]*/gamma-agent" >/dev/null && grep -q "eps: stopping... stopped" <<<"$out" && ok "stop-agents.sh --group stops that group" || bad "stop group: rc=$rc $out"
out=$(bash "$H/stop-agents.sh" 2>&1); rc=$?; [ "$rc" = 2 ] && ok "stop-agents.sh with nothing named refuses" || bad "stop nothing: rc=$rc"
rm -f "${D:?}/sb/groups"

# the gate: checked before every start; a failing gate defers the rest with its reason and exit 3
T kill-server 2>/dev/null; sleep 0.5; clear_starts
printf '#!/usr/bin/env bash\n[ -e "%s/alpha.starts" ] || exit 0\necho "memory short: 1 GiB available"; exit 1\n' "$D" > "$D/gate"; chmod +x "$D/gate"
out=$(START_AGENTS_GATE="$D/gate" START_AGENTS_GATE_POLL_S=1 START_AGENTS_GATE_WAIT_S=2 bash "$H/start-agents.sh" 2>&1); rc=$?
[ "$rc" = 3 ] && [ "$(wc -l < "$D/alpha.starts")" = 1 ] && [ ! -e "$D/beta.starts" ] && grep -q "deferred beta: memory short: 1 GiB available" <<<"$out" && grep -q "deferred delta" <<<"$out" \
  && ok "gate: the first start passes, the rest are deferred with the gate's reason, exit 3" || bad "gate: rc=$rc $out"
out=$(START_AGENTS_GATE="$D/nosuch" bash "$H/start-agents.sh" 2>&1); rc=$?; [ "$rc" = 2 ] && ok "a gate that is not an executable is refused" || bad "bad gate rc=$rc"

# stagger: the wait between two starts is START_AGENTS_STAGGER_S
T kill-server 2>/dev/null; sleep 0.5; clear_starts
t0=$(date +%s); START_AGENTS_STAGGER_S=4 bash "$H/start-agents.sh" alpha beta >/dev/null 2>&1; t1=$(date +%s)
[ $((t1 - t0)) -ge 5 ] && [ $((t1 - t0)) -le 8 ] && ok "stagger: two starts took $((t1 - t0)) s with a 4 s stagger and a 1 s settle" || bad "stagger took $((t1 - t0)) s"

# the token: a launcher written by new-agent.sh's template starts only with the token start-agents.sh wrote
T kill-server 2>/dev/null; sleep 0.5; clear_starts
export XDG_RUNTIME_DIR="$D/run"; mkdir -p -m 700 "$XDG_RUNTIME_DIR"
mkdir -p "$D/sb/tok"; : > "$D/sb/tok/profile"
cat > "$D/bin/tok-agent" <<EOF
#!/usr/bin/env bash
t="\${XDG_RUNTIME_DIR:-/tmp}/start-agents/tok.token"
if [ -z "\${START_AGENTS_TOKEN:-}" ] || [ ! -O "\$t" ] || [ "\$(cat "\$t" 2>/dev/null)" != "\$START_AGENTS_TOKEN" ]; then echo refused >&2; exit 2; fi
rm -f "\$t"; unset START_AGENTS_TOKEN
echo x >> "$D/tok.starts"; sleep 600
EOF
chmod +x "$D/bin/tok-agent"
grep -q 'START_AGENTS_TOKEN' "$H/new-agent.sh" && grep -q 'start-agents/%s.token' "$H/new-agent.sh" && ok "new-agent.sh writes the token check into the launcher" || bad "new-agent.sh has no token check"
out=$(bash "$D/bin/tok-agent" 2>&1); rc=$?; [ "$rc" = 2 ] && [ ! -e "$D/tok.starts" ] && ok "a launcher run by hand is refused" || bad "by hand: rc=$rc"
out=$(START_AGENTS_TOKEN=guess bash "$D/bin/tok-agent" 2>&1); rc=$?; [ "$rc" = 2 ] && ok "a launcher with a made-up token is refused" || bad "guess: rc=$rc"
bash "$H/start-agents.sh" tok >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] && [ "$(wc -l < "$D/tok.starts")" = 1 ] && [ ! -e "$XDG_RUNTIME_DIR/start-agents/tok.token" ] && ok "start-agents.sh starts it, and the token is used up" || bad "token start: rc=$rc"

# --pane: one agent into an idle pane; a busy pane is left alone
T kill-server 2>/dev/null; sleep 0.5; clear_starts
T new-session -d -s p -x 200 -y 50 "bash --norc"; idle=$(T list-panes -t p -F '#{pane_id}'); busy=$(T split-window -d -t p -P -F '#{pane_id}' "sleep 600"); sleep 1
out=$(bash "$H/start-agents.sh" --pane "$idle" alpha 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$(wc -l < "$D/alpha.starts")" = 1 ] && grep -q "started in $idle" <<<"$out" && ok "--pane starts the agent in that pane" || bad "--pane: rc=$rc $out"
out=$(bash "$H/start-agents.sh" --pane "$busy" beta 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "is busy" <<<"$out" && [ ! -e "$D/beta.starts" ] && ok "--pane leaves a busy pane alone" || bad "--pane busy: rc=$rc $out"
out=$(bash "$H/start-agents.sh" --pane "$idle" alpha beta 2>&1); rc=$?; [ "$rc" = 2 ] && ok "--pane takes exactly one name" || bad "--pane two names rc=$rc"
[ "$fail" = 0 ] && echo "ALL PASSED" || { echo "FAILURES"; exit 1; }
