#!/usr/bin/env bash
# Probe the runner's WORKDIR: where the agent starts. Uses `sandbox.sh <profile> show`, which prints the bwrap arguments and runs nothing.
# Run: bash scripts/test-workdir.sh
set -uo pipefail
RUNNER=$(cd "$(dirname "$0")" && pwd)/sandbox.sh
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/root/repo" "$T/rootx" "$T/home"
pass=0 fail=0
case_() {  # case_ <description> <want: chdir path, or REFUSED> <profile lines>
  local d=$1 want=$2 p="$T/profile.$((pass + fail))" out got
  printf 'NAME=probe\nROOT=%s\nAGENT_HOME=%s\n%s\n' "$T/root" "$T/home" "$3" > "$p"
  # Judged by output, not exit status: `show` exits non-zero after printing (its last test is the profile's own).
  out=$(bash "$RUNNER" "$p" show 2>&1)
  case "$out" in
    *"is not a directory under ROOT"*) got=REFUSED ;;
    *--chdir*) got=$(printf '%s\n' "$out" | grep -o -- '--chdir [^ ]*' | cut -d' ' -f2) ;;
    *) got="no --chdir and no refusal" ;;
  esac
  if [ "$got" = "$want" ]; then pass=$((pass + 1)); echo "ok    $d"; else fail=$((fail + 1)); echo "FAIL  $d: want $want, got $got ($out)"; fi
}
case_ "no WORKDIR starts in ROOT"                          "$T/root"      ''
case_ "WORKDIR equal to ROOT starts in ROOT"               "$T/root"      "WORKDIR=$T/root"
case_ "WORKDIR under ROOT starts there"                    "$T/root/repo" "WORKDIR=$T/root/repo"
case_ "positive control: WORKDIR outside ROOT is refused"  REFUSED        "WORKDIR=$T/home"
case_ "positive control: a sibling sharing ROOT's prefix is refused" REFUSED "WORKDIR=$T/rootx"
case_ "positive control: a missing WORKDIR is refused"     REFUSED        "WORKDIR=$T/root/absent"
case_ "positive control: .. out of ROOT is refused"        REFUSED        "WORKDIR=$T/root/../home"
echo "---"; echo "$pass passed, $fail failed"; [ "$fail" = 0 ]
