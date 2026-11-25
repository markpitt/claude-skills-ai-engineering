#!/usr/bin/env bash
# Probe new-agent.sh's project memory folder: a new agent starts with projects/<key>/memory/ in its home, keyed the way
# carry-project.sh and Claude key it, and nothing an agent already has is changed. Needs no bwrap.
# Run: bash scripts/test-new-agent-memory.sh
set -uo pipefail
H=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
pass=0 fail=0
check() { if eval "$2"; then pass=$((pass + 1)); echo "ok    $1"; else fail=$((fail + 1)); echo "FAIL  $1"; fi; }
key() { printf '%s' "${1//[^A-Za-z0-9]/-}"; }
install_agent() {  # install_agent <name> <profile lines...>: install into a throwaway base; output in $out, exit status in $rc
  local name=$1; shift
  mkdir -p "$T/src"; printf '%s\n' "NAME=$name" "$@" "NET=none" "BLANK=( )" > "$T/src/$name.profile"
  out=$(SANDBOX_BASE=$T/base SANDBOX_BIN=$T/bin HOME=$T/home XDG_CONFIG_HOME=$T/home/.config \
        bash "$H/new-agent.sh" "$name" "$T/src/$name.profile" 2>&1); rc=$?
  AH="$T/base/$name/home"
}

R="$T/work/repo.one"; mkdir -p "$R"
install_agent fresh "ROOT=$R"
check "a new agent gets projects/<key of ROOT>/memory/" '[ $rc = 0 ] && [ -d "$AH/projects/$(key "$R")/memory" ]'
check "the memory folder is the agent's own (mode 700)" '[ "$(stat -c %a "$AH/projects/$(key "$R")/memory")" = 700 ]'
check "only that one project folder is made" '[ "$(ls "$AH/projects" | wc -l)" = 1 ]'
check "it says where the memory folder is" 'grep -q "memory:.*projects/$(key "$R")/memory" <<<"$out"'

W="$T/work/repo.one/sub dir"; mkdir -p "$W"
install_agent wd "ROOT=$R" "WORKDIR=\"$W\""
check "WORKDIR, when set, names the key, not ROOT" '[ -d "$AH/projects/$(key "$W")/memory" ] && [ ! -e "$AH/projects/$(key "$R")" ]'

ln -s "$R" "$T/link"
install_agent linked "ROOT=$T/link"
check "the key is of the real path, as carry-project.sh keys it" '[ -d "$AH/projects/$(key "$R")/memory" ] && [ ! -e "$AH/projects/$(key "$T/link")" ]'

install_agent again "ROOT=$R"; echo "- [a](a.md)" > "$AH/projects/$(key "$R")/memory/MEMORY.md"
install_agent again "ROOT=$R"
check "a re-run keeps the memory the agent wrote" '[ $rc = 0 ] && [ "$(cat "$AH/projects/$(key "$R")/memory/MEMORY.md")" = "- [a](a.md)" ]'

# The agent last ran in another folder: carry-project.sh moves that folder to the new key on the next start, and only
# when the new key does not exist yet. Making it here would strand the agent's history.
O="$T/work/old"; mkdir -p "$O"
install_agent moved "ROOT=$O"; echo "$O" > "$AH/.workdir"; echo note > "$AH/projects/$(key "$O")/memory/n.md"
install_agent moved "ROOT=$R"
check "a changed folder is left for carry-project.sh: no new key, the old one untouched" \
  '[ $rc = 0 ] && [ ! -e "$AH/projects/$(key "$R")" ] && [ "$(cat "$AH/projects/$(key "$O")/memory/n.md")" = note ]'
check "and it says so" 'grep -q "carry-project" <<<"$out"'

install_agent elsewhere "ROOT=$T/not/on/this/host"
check "a ROOT not on this host: installed, no project folder, and it says so" \
  '[ $rc = 0 ] && [ ! -e "$AH/projects" ] && grep -q "does not exist" <<<"$out"'

echo "---"; echo "$pass passed, $fail failed"; [ "$fail" = 0 ]
