#!/usr/bin/env bash
# Test restart-agents.sh on an isolated tmux server with fake <name>-agent launchers. Touches no real agent.
set -uo pipefail
H=$(cd "$(dirname "$0")" && pwd)
D=$(mktemp -d); SOCK=ra-test-$$; fail=0
T() { tmux -L "$SOCK" "$@"; }
split() { local p; p=$(T split-window -d -t s -P -F '#{pane_id}' "bash --norc"); T select-layout -t s tiled >/dev/null; echo "$p"; }   # a new pane, tiled so the next split has room
cleanup() { T kill-server 2>/dev/null; rm -rf "$D"; }; trap cleanup EXIT
ok() { echo "ok    $1"; }; bad() { echo "FAIL  $1"; fail=1; }
mkdir -p "$D/bin"
for n in foo bar stuck; do mkdir -p "$D/sb/$n"; : > "$D/sb/$n/profile"; done     # start-agents.sh checks the agent exists
for n in foo bar; do  # a launcher records its start count and waits; it exits on Ctrl-C like the real one
  printf '#!/usr/bin/env bash\necho x >> "%s/%s.starts"\nsleep 600\n' "$D" "$n" > "$D/bin/$n-agent"; chmod +x "$D/bin/$n-agent"
done
printf '#!/usr/bin/env bash\necho x >> "%s/stuck.starts"\ntrap "" INT TERM\nwhile :; do sleep 1; done\n' "$D" > "$D/bin/stuck-agent"; chmod +x "$D/bin/stuck-agent"
export PATH="$D/bin:$PATH" BIN="$D/bin"
T new-session -d -s s -x 200 -y 60 "bash --norc"                       # pane 0: the caller, not an agent
for n in foo bar; do p=$(split); T send-keys -t "$p" "$n-agent" Enter; done
EMPTY=$(split)                                                            # a pane with no agent in it (the stuck agent goes here later)
# decoys: a command that only mentions a path ending in -agent, and a launcher-shaped script that is not an installed agent
p=$(split); T send-keys -t "$p" "bash -c 'sleep 600; true' /x/decoy-agent" Enter   # stays alive and carries the path unparsed (GNU sleep rejects an extra operand)
printf '#!/usr/bin/env bash\nsleep 600\n' > "$D/stray-agent"; chmod +x "$D/stray-agent"
p=$(split); T send-keys -t "$p" "$D/stray-agent" Enter
sleep 1
export TMUX_SOCKET=$SOCK INT_WAIT=3 TERM_WAIT=2 SANDBOXES="$D/sb" START_AGENTS_SETTLE_S=2
pgrep -f "sleep 600; true" >/dev/null && pgrep -f "bash $D/stray-agent" >/dev/null && ok "both decoys are alive before any restart (so the later check is not vacuous)" || bad "a decoy never started"
out=$(bash "$H/restart-agents.sh" --session s --dry-run); echo "$out" | grep -q 'foo-agent' && echo "$out" | grep -q 'bar-agent' && [ "$(echo "$out" | grep -c -- '-agent  pane')" = 2 ] && ! grep -q -e decoy -e stray <<<"$out" \
  && ok "dry run lists the two agent panes only" || bad "dry run: $out"
[ ! -e "$D/foo.starts.2" ] && [ "$(wc -l < "$D/foo.starts")" = 1 ] && ok "dry run changed nothing" || bad "dry run restarted something"
bash "$H/restart-agents.sh" --session s foo >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] && [ "$(wc -l < "$D/foo.starts")" = 2 ] && [ "$(wc -l < "$D/bar.starts")" = 1 ] && ok "named restart: foo restarted, bar untouched" || bad "named restart (rc=$rc foo=$(wc -l < "$D/foo.starts") bar=$(wc -l < "$D/bar.starts"))"
bash "$H/restart-agents.sh" --session s >/dev/null 2>&1
[ "$(wc -l < "$D/foo.starts")" = 3 ] && [ "$(wc -l < "$D/bar.starts")" = 2 ] && ok "no names: both restarted once" || bad "restart all"
pgrep -f "sleep 600; true" >/dev/null && pgrep -f "bash $D/stray-agent" >/dev/null && ok "decoys (a command that only mentions x-agent; a launcher-shaped script not in BIN) were not listed and got no Ctrl-C" || bad "a decoy pane was stopped"
T send-keys -t "$EMPTY" "stuck-agent" Enter; sleep 1
out=$(bash "$H/restart-agents.sh" --session s stuck 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "left alone" <<<"$out" && [ "$(wc -l < "$D/stuck.starts")" = 1 ] && ok "an agent that ignores Ctrl-C and SIGTERM is reported, not killed, not started twice" || bad "stuck agent: rc=$rc out=$out"
out=$(bash "$H/restart-agents.sh" --session s nosuch 2>&1); rc=$?; [ "$rc" = 0 ] && grep -q "no agent panes" <<<"$out" && ok "unknown name: nothing to do" || bad "unknown name: rc=$rc out=$out"
[ "$fail" = 0 ] && echo "ALL PASSED" || { echo "FAILURES"; exit 1; }
