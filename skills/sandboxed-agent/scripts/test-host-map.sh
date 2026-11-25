#!/usr/bin/env bash
# Probe the runner's host-map check: a profile at <repo>/hosts/<host>/<agent>/profile runs only where <repo>/hosts/map maps the
# hostname to <host>. Uses `sandbox.sh <profile> show`, which runs nothing. SANDBOX_HOSTNAME stands in for the hostname.
# Run: bash scripts/test-host-map.sh
set -uo pipefail
RUNNER=$(cd "$(dirname "$0")" && pwd)/sandbox.sh
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/repo/hosts/alpha/agent" "$T/repo/hosts/beta/agent" "$T/nomap/hosts/alpha/agent" "$T/flat/agent" "$T/root" "$T/home"
printf '# hostname  host-folder\nbox-a   alpha\nbox-a2  alpha\n\nbox-b   beta\n' > "$T/repo/hosts/map"
for p in repo/hosts/alpha/agent repo/hosts/beta/agent nomap/hosts/alpha/agent flat/agent; do
  printf 'NAME=probe\nROOT=%s\nAGENT_HOME=%s\n' "$T/root" "$T/home" > "$T/$p/profile"
done
pass=0 fail=0
case_() {  # case_ <description> <want: RUNS or REFUSED> <hostname> <profile path under $T>
  local d=$1 want=$2 out got
  # Judged by output, not exit status: `show` exits non-zero after printing.
  out=$(SANDBOX_HOSTNAME=$3 bash "$RUNNER" "$T/$4" show 2>&1)
  case "$out" in
    *"sandbox: hostname"*) got=REFUSED ;;
    *--chdir*) got=RUNS ;;
    *) got="neither ($out)" ;;
  esac
  if [ "$got" = "$want" ]; then pass=$((pass + 1)); echo "ok    $d"; else fail=$((fail + 1)); echo "FAIL  $d: want $want, got $got"; fi
}
case_ "a mapped hostname runs its own host's profile"             RUNS    box-a  repo/hosts/alpha/agent/profile
case_ "a second hostname mapped to the same folder runs it"       RUNS    box-a2 repo/hosts/alpha/agent/profile
case_ "a profile outside a hosts/ tree is not checked"            RUNS    nobody flat/agent/profile
case_ "a hosts/ tree with no map is not checked"                  RUNS    nobody nomap/hosts/alpha/agent/profile
case_ "positive control: an unlisted hostname is refused"         REFUSED box-z  repo/hosts/alpha/agent/profile
case_ "positive control: another host's profile is refused"       REFUSED box-b  repo/hosts/alpha/agent/profile
case_ "positive control: a hostname prefix is not a match"        REFUSED box    repo/hosts/alpha/agent/profile
case_ "positive control: a folder name is not a hostname"         REFUSED alpha  repo/hosts/alpha/agent/profile
echo "---"; echo "$pass passed, $fail failed"; [ "$fail" = 0 ]
