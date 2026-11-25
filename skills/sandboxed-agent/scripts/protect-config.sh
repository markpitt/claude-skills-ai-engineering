#!/usr/bin/env bash
# Make every route to an agent's own Claude config ask the user first. Idempotent: merges into an
# existing settings.json, never removes anything of the user's (bar the obsolete Write rules it once wrote).
#   protect-config.sh <agent-config-dir> [path-the-agent-sees]
# The rules must name the path as the agent's tools see it. When the sandbox mounts the config dir at a
# different path than it has on the host, pass that mount path as the second argument.
#
# Why: the config dir must be writable, so the agent could otherwise edit its settings (permissions,
# hooks), instructions, MCP servers, skills, plugins or tools and loosen its own limits. This keeps the
# user in the loop without making the agent unable to propose edits.
#   1. Edit ask rules (they cover Write and every other file-editing tool) for the config dir's top-level
#      files (*.*: settings.json, .claude.json ...), skills/, plugins/, tools/, agents/, commands/, hooks/,
#      rules/, output-styles/ (everything that loads as instructions).
#      Rules use gitignore matching, so a bare * also matches everything under projects/ and would ask on every
#      memory write; ask rules beat allow rules, so projects/**/memory could not be allowed back. *.* leaves it free.
#   2. a PreToolUse Bash hook that asks when the command text names the config. The Edit rules do
#      not cover shell writes such as `sed -i` or `cat >`. Inline in settings.json on purpose: it is then
#      protected by the same rules. It extracts .tool_input.command first; grepping all of stdin would
#      match transcript_path (inside the config dir) and prompt on every command.
# Limits: the hook matches text, so a deliberately disguised path can pass; the blanked state/backups/memory
# directories are blind spots by design (a script that builds the path at run time is not seen). Only a read-only mount makes
# edits impossible. The real boundaries are bwrap, the proxy and the scoped credentials.
set -euo pipefail
CFG=${1:?agent config dir}
CFG=$(cd "$CFG" && pwd -P)
command -v jq >/dev/null || { echo "protect-config: jq is needed (also inside the sandbox)" >&2; exit 1; }
SEEN=${2:-$CFG}
# STATE_DIRS (extra directories the agent writes freely) comes from the environment, else from the installed
# profile next to the config dir, so a later run from new-agent.sh keeps them. The profile is parsed, never
# sourced: only a plain `STATE_DIRS=(a b)` line is read, and each name is validated below.
if [ -z "${STATE_DIRS+x}" ] && [ -f "$CFG/../profile" ]; then
  STATE_DIRS=$(sed -nE 's/^STATE_DIRS=\(([^)]*)\)[[:space:]]*(#.*)?$/\1/p' "$CFG/../profile" | head -1 | tr -d "\"'")
  if [ -z "$STATE_DIRS" ] && grep -qE '^STATE_DIRS=' "$CFG/../profile" && ! grep -qE '^STATE_DIRS=\([[:space:]]*\)' "$CFG/../profile"; then
    echo "protect-config: $CFG/../profile has a STATE_DIRS line that is not a single-line array STATE_DIRS=(a b); ignored" >&2
  fi
fi
export STATE_DIRS="${STATE_DIRS:-}"
python3 -I - "$CFG" "$SEEN" <<'PY'
import json, os, sys
cfg = sys.argv[1]
seen = sys.argv[2]
p = os.path.join(cfg, "settings.json")
d = json.load(open(p)) if os.path.exists(p) else {}
name = os.path.basename(seen)
rules = []
# Edit rules cover every file-editing tool; Claude Code ignores Write rules and reports them as errors.
SUBS = ("*.*", "skills/**", "plugins/**", "tools/**", "agents/**", "commands/**", "hooks/**", "rules/**", "output-styles/**")
for sub in SUBS:
    rules.append(f"Edit(/{seen}/{sub})")             # a leading // means an absolute path
ask = d.setdefault("permissions", {}).setdefault("ask", [])
# drop the Write rules an earlier version of this script added (only those: exact strings), so a re-run fixes them
# and the bare Edit(.../*) of the previous version, which also asked on every write under projects/ (memory)
stale = {f"Write(/{seen}/{sub})" for sub in ("*", "skills/**", "plugins/**", "tools/**")} | {f"Edit(/{seen}/*)"}
ask[:] = [r for r in ask if r not in stale]
for r in rules:
    if r not in ask: ask.append(r)
marker = "Claude config - needs your approval"
# Paths the agent writes freely are blanked before matching, so a command that only cites them (a change-log
# line, a backup path) does not prompt. The directory list is explicit: STATE_DIRS=(dokploy-state) in the
# profile (or STATE_DIRS="a b" in the environment) adds to the default "state backups"; projects/*/memory is
# always included.
import re
state = ["state", "backups"] + os.environ.get("STATE_DIRS", "").split()
bad = [x for x in state if not re.fullmatch(r"[A-Za-z0-9._-]+", x)]
if bad: sys.exit(f"protect-config: bad STATE_DIRS entry {bad}")
esc = name.replace(".", "\\.")
blank = "|".join(re.escape(x) for x in state) + "|projects/[^/]+/memory"
ask_json = ('{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask",'
            '"permissionDecisionReason":"Bash command touches ' + marker + '"}}')
# Blanking drops the directory name from the text, so a command that can leave the blanked directory
# (.. component, cd, ln, symlink) is never blanked: it asks as soon as the config dir is named.
# A missing sed fails closed.
cmd = ("c=$(jq -r '.tool_input.command // empty'); a='" + ask_json + "'; "
       "if ! command -v sed >/dev/null; then echo \"$a\"; "
       "elif printf '%s\\n' \"$c\" | grep -qE '" + esc + "' && printf '%s\\n' \"$c\" | grep -qE "
       "'(^|[/[:space:]])\\.\\.($|[/[:space:]])|(^|[^[:alnum:]_])(cd|pushd|ln)([[:space:]]|$)|symlink'; then echo \"$a\"; "
       "elif printf '%s\\n' \"$c\" | sed -E 's#" + esc + "/(" + blank + ")/#X/#g' | grep -qE "
       "'settings\\.json|" + esc + "|CLAUDE_CONFIG_DIR'; then echo \"$a\"; fi")
pre = d.setdefault("hooks", {}).setdefault("PreToolUse", [])
old = [hk for h in pre for hk in h.get("hooks", []) if marker in json.dumps(hk)]
for hk in old: hk["command"] = cmd          # a re-run upgrades an older hook in place
if not old:
    pre.append({"matcher": "Bash", "hooks": [{"type": "command", "command": cmd}]})
json.dump(d, open(p, "w"), indent=2); open(p, "a").write("\n")
os.chmod(p, 0o600)
print("protected:", p)
PY
