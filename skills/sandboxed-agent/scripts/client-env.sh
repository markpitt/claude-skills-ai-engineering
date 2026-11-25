#!/usr/bin/env bash
# Merge the client settings a sandboxed agent should always have into <config-dir>/settings.json.
# Idempotent; a value the user already set in "env" or as crossSessionInbound wins, and the user's own
# deny rules are kept.
#   client-env.sh <agent-config-dir> [keep-connectors] [allow-messaging]
# keep-connectors: leave the account's connectors and plugin MCP servers on (new-agent.sh passes it for NET=host, where the
# network is shared anyway and the user may want them).
# allow-messaging: do not block messaging, and remove the block an earlier run added (new-agent.sh passes it
# when the profile sets ALLOW_MESSAGING=1 or SANDBOX_ALLOW_MESSAGING=1).
# ENABLE_CLAUDEAI_MCP_SERVERS=false  do not load the logged-in account's claude.ai connectors (each one is
#                                    a connection attempt and an error in the UI, and a way out of the sandbox)
# CLAUDE_CODE_SKIP_PLUGIN_MCP_SERVERS=1  nor the MCP servers of plugins claude.ai syncs to the account
#                                    (plugins/synced/*/.mcp.json): the switch above does not cover them, and
#                                    each session start tried ~55 hosts (measured 17/11/2026 on 2.1.325)
# DISABLE_ERROR_REPORTING           stop the error-report traffic at the source (DISABLE_TELEMETRY is not set: Remote Control needs it off)
# DISABLE_AUTOUPDATER               the install directory is read-only in the sandbox
# crossSessionInbound=refuse        an agent on Remote Control is a message target for every session on the
#                                   account, so refuse messages from other sessions; the sender is told the
#                                   session "can't receive cross-session messages". The user's own typing over
#                                   Remote Control is not a message from another session.
# permissions.deny SendMessage, ListAgents   it cannot send to or list other sessions either
# (docs: https://code.claude.com/docs/en/cross-session-messaging, "Turn off cross-session messaging")
set -euo pipefail
CFG=${1:?agent config dir}
command -v jq >/dev/null || { echo "client-env: jq is needed" >&2; exit 1; }
f=$CFG/settings.json
[ -f "$f" ] || echo '{}' > "$f"
tmp=$(mktemp "$CFG/.settings.XXXXXX"); trap 'rm -f "$tmp"' EXIT
want='{"DISABLE_ERROR_REPORTING":"1","DISABLE_AUTOUPDATER":"1"}'
keep=no msg=block
for a in "${@:2}"; do
  case "$a" in
    keep-connectors) keep=yes ;;
    allow-messaging) msg=allow ;;
    *) echo "client-env: unknown option '$a'" >&2; exit 2 ;;
  esac
done
[ "$keep" = yes ] || want=$(jq -c '. + {"ENABLE_CLAUDEAI_MCP_SERVERS":"false","CLAUDE_CODE_SKIP_PLUGIN_MCP_SERVERS":"1"}' <<<"$want")
jq --argjson want "$want" '.env = ($want + (.env // {}))' "$f" > "$tmp"
if [ "$msg" = block ]; then
  jq '.crossSessionInbound = (.crossSessionInbound // "refuse")
      | (.permissions.deny // []) as $d
      | .permissions.deny = ($d + (["SendMessage","ListAgents"] - $d))' "$tmp" > "$tmp.2"
else
  # allow-messaging is reversible: remove exactly what the block adds, so an agent re-installed with it
  # recovers from an earlier install without it. A "refuse" or either deny entry the user wrote
  # themselves is indistinguishable from ours and goes too; "hold" and the user's other rules stay.
  jq 'if .crossSessionInbound == "refuse" then del(.crossSessionInbound) else . end
      | if .permissions.deny then .permissions.deny -= ["SendMessage","ListAgents"] else . end
      | if (.permissions.deny // [1]) == [] then del(.permissions.deny) else . end
      | if .permissions == {} then del(.permissions) else . end' "$tmp" > "$tmp.2"
fi
mv "$tmp.2" "$tmp"
chmod 600 "$tmp"; mv "$tmp" "$f"
echo "client env: $f"
