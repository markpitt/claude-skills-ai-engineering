#!/usr/bin/env bash
# Probe carry-project.sh: a changed WORKDIR moves the agent's project folder, and nothing else does.
# Run: bash scripts/test-carry-project.sh
set -uo pipefail
CARRY=$(cd "$(dirname "$0")" && pwd)/carry-project.sh
T=$(mktemp -d); trap 'chmod -R u+w "$T"; rm -rf "$T"' EXIT
pass=0 fail=0
check() { if eval "$2"; then pass=$((pass + 1)); echo "ok    $1"; else fail=$((fail + 1)); echo "FAIL  $1"; fi; }
key() { printf '%s' "${1//[^A-Za-z0-9]/-}"; }
fresh() {  # fresh <name>: an agent home H and two work dirs A and B, with a transcript and a memory file under A's project folder
  H="$T/$1/home" A="$T/$1/w/repo.a" B="$T/$1/w/repo_b"; mkdir -p "$H/projects" "$A" "$B"
  PA="$H/projects/$(key "$A")" PB="$H/projects/$(key "$B")"
  mkdir -p "$PA/memory"; echo transcript > "$PA/s.jsonl"; echo note > "$PA/memory/MEMORY.md"
}

fresh first; bash "$CARRY" "$H" "$A" >/dev/null; rc=$?
check "no record: exit 0, records the dir and moves nothing" '[ $rc = 0 ] && [ "$(cat "$H/.workdir")" = "$A" ] && [ -f "$PA/s.jsonl" ]'

fresh same; echo "$A" > "$H/.workdir"; bash "$CARRY" "$H" "$A" >/dev/null; rc=$?
check "same dir: nothing moves" '[ $rc = 0 ] && [ -f "$PA/s.jsonl" ] && [ ! -e "$PB" ]'

fresh moved; echo "$A" > "$H/.workdir"; bash "$CARRY" "$H" "$B" >/dev/null; rc=$?
check "changed dir: transcript and memory move to the new key" '[ $rc = 0 ] && [ ! -e "$PA" ] && [ "$(cat "$PB/s.jsonl")" = transcript ] && [ "$(cat "$PB/memory/MEMORY.md")" = note ]'
check "changed dir: the record names the new dir" '[ "$(cat "$H/.workdir")" = "$B" ]'
check "the key turns . and _ into -, as Claude does" '[ "$(basename "$PB")" = "$(printf %s "$T/moved/w/repo_b" | tr -c "A-Za-z0-9" -)" ] && case "$(basename "$PB")" in *[._/]*) false ;; esac'

fresh both; echo "$A" > "$H/.workdir"; mkdir -p "$PB"; echo theirs > "$PB/t.jsonl"; out=$(bash "$CARRY" "$H" "$B" 2>&1); rc=$?
check "positive control: an existing new folder is not overwritten, both are kept" '[ $rc = 0 ] && [ -f "$PA/s.jsonl" ] && [ "$(cat "$PB/t.jsonl")" = theirs ] && [ ! -e "$PB/s.jsonl" ]'
check "positive control: and it says so" 'case "$out" in *"already exists"*) true ;; *) false ;; esac'

fresh nofolder; echo "$A" > "$H/.workdir"; rm -rf "$PA"; bash "$CARRY" "$H" "$B" >/dev/null; rc=$?
check "changed dir with no old folder: exit 0, record updated" '[ $rc = 0 ] && [ "$(cat "$H/.workdir")" = "$B" ] && [ ! -e "$PB" ]'

fresh failing; echo "$A" > "$H/.workdir"; chmod a-w "$H/projects"; bash "$CARRY" "$H" "$B" >/dev/null 2>&1; rc=$?; chmod u+w "$H/projects"
check "positive control: a move that fails exits 1 and keeps the old record" '[ $rc = 1 ] && [ -f "$PA/s.jsonl" ] && [ "$(cat "$H/.workdir")" = "$A" ]'

fresh missing; bash "$CARRY" "$H" "$T/missing/nowhere" >/dev/null 2>&1; rc=$?
check "positive control: a missing workdir exits 1" '[ $rc = 1 ]'

echo "---"; echo "$pass passed, $fail failed"; [ "$fail" = 0 ]
