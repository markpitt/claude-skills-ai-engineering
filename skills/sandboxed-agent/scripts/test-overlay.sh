#!/usr/bin/env bash
# Probe the runner's OVERLAY: instruction layers shown read-only at a folder's own paths. Scratch folders only.
# Run: bash scripts/test-overlay.sh   (needs bwrap). SANDBOX_SH=<copy of sandbox.sh> runs the cases against that copy.
set -uo pipefail
H=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d); trap 'chmod -R u+w "$T" 2>/dev/null; rm -rf "$T"' EXIT
export XDG_RUNTIME_DIR=$T
# The runner under test, beside the helper it calls.
mkdir -p "$T/runner"; cp "${SANDBOX_SH:-$H/sandbox.sh}" "$T/runner/sandbox.sh"; cp "$H/carry-project.sh" "$T/runner/"
RUNNER=$T/runner/sandbox.sh
pass=0 fail=0
ok() { pass=$((pass + 1)); echo "ok    $1"; }
no() { fail=$((fail + 1)); echo "FAIL  $1${2:+  ($2)}"; }
check() { local d=$1; shift; if "$@"; then ok "$d"; else no "$d"; fi; }

# Layers: one per repo, one per agent on top.
LR=$T/layers/repo LA=$T/layers/agent
mkdir -p "$LR/.claude/rules" "$LR/.agents/skills/s" "$LR/.claude/skills" "$LR/sub" "$LR/newdir" "$LA/.claude"
echo repo-layer > "$LR/CLAUDE.md"; echo agents > "$LR/AGENTS.md"; echo rule > "$LR/.claude/rules/r.md"
echo repo-settings > "$LR/.claude/settings.json"; echo skill > "$LR/.agents/skills/s/SKILL.md"
ln -s ../../.agents/skills/s "$LR/.claude/skills/s"; echo sub-layer > "$LR/sub/CLAUDE.md"; echo new-layer > "$LR/newdir/CLAUDE.md"
echo agent-settings > "$LA/.claude/settings.json"
layer_sums() { (cd "$T/layers" && find . -type f -print0 | sort -z | xargs -0 sha256sum); }
# shellcheck disable=SC2034  # read inside the eval checks
LAYERS_BEFORE=$(layer_sums)

mkrepo() {  # mkrepo <dir>: a repository that has retired its instruction files
  mkdir -p "$1/sub"; echo one > "$1/a.txt"; echo x > "$1/sub/x.txt"
}
profile() {  # profile <file> <root> <mode> <OVERLAY lines...>
  local f=$1 root=$2 mode=$3; shift 3
  { printf 'NAME=tov\nROOT=%s\nROOT_MODE=%s\nNET=none\nAGENT_HOME=%s\n' "$root" "$mode" "$T/home-$(basename "$f")"
    printf 'OVERLAY=('; printf ' %q' "$@"; printf ' )\n'; } > "$f"
}
inside() { bash "$RUNNER" "$1" run -- sh -c "$2" 2>&1; }

echo "== retired repository, rw"
R1=$T/r1; mkrepo "$R1"; profile "$T/p1" "$R1" rw "$R1|$LA|$LR"
out=$(inside "$T/p1" "cd $R1; cat CLAUDE.md AGENTS.md sub/CLAUDE.md newdir/CLAUDE.md .claude/settings.json .claude/rules/r.md .claude/skills/s/SKILL.md")
check "the layers' files show at the repository's paths" [ "$out" = "$(printf 'repo-layer\nagents\nsub-layer\nnew-layer\nagent-settings\nrule\nskill')" ]
[ "$out" = "$(printf 'repo-layer\nagents\nsub-layer\nnew-layer\nagent-settings\nrule\nskill')" ] || echo "      got: $out"
out=$(inside "$T/p1" "cd $R1; echo x >> CLAUDE.md && echo WROTE")
check "a layer file cannot be written" eval '! grep -q WROTE <<<"$out"'
out=$(inside "$T/p1" "cd $R1; /usr/bin/rm -f CLAUDE.md && echo GONE1; /usr/bin/rm -f .claude/rules/r.md && echo GONE2; mv sub/CLAUDE.md sub/moved && echo MOVED")
check "a layer file cannot be deleted or renamed" eval '! grep -qE "GONE|MOVED" <<<"$out"'
out=$(inside "$T/p1" "cd $R1; touch .claude/new && echo MADE1; mkdir .claude/d && echo MADE2; touch newdir/n && echo MADE3")
check "nothing can be added inside a folder the layers provide" eval '! grep -q MADE <<<"$out"'
inside "$T/p1" "cd $R1; echo two > a.txt; echo n > new.txt; echo y > sub/y.txt" >/dev/null
check "the agent's writes to the repository land on the host" eval '[ "$(cat "$R1/a.txt" "$R1/new.txt" "$R1/sub/y.txt" 2>&1)" = "$(printf "two\nn\ny")" ]'
check "the layers are unchanged on the host" eval '[ "$(layer_sums)" = "$LAYERS_BEFORE" ]'
stubs=$(cd "$R1" && find . -mindepth 1 \( -name a.txt -o -name new.txt -o -path ./sub/x.txt -o -path ./sub/y.txt \) -prune -o -print | LC_ALL=C sort | tr '\n' ' ')
check "the repository holds only empty mount points for the layer paths" [ "$stubs" = "./.agents ./.claude ./AGENTS.md ./CLAUDE.md ./newdir ./sub ./sub/CLAUDE.md " ]
[ "$stubs" = "./.agents ./.claude ./AGENTS.md ./CLAUDE.md ./newdir ./sub ./sub/CLAUDE.md " ] || echo "      got: $stubs"
check "the mount points are empty" eval '[ ! -s "$R1/CLAUDE.md" ] && [ ! -s "$R1/sub/CLAUDE.md" ] && [ -z "$(ls -A "$R1/.claude")$(ls -A "$R1/newdir")" ]'
before=$(cd "$R1" && find . | sort); inside "$T/p1" true >/dev/null; after=$(cd "$R1" && find . | sort)
check "a second run adds nothing to the repository" [ "$before" = "$after" ]

echo "== repository that still holds its own copies (phases 2 to 5)"
R2=$T/r2; mkrepo "$R2"; mkdir -p "$R2/.claude/rules" "$R2/.claude/skills" "$R2/.agents/skills/s"
echo repo-own > "$R2/CLAUDE.md"; echo old-rule > "$R2/.claude/rules/r.md"; echo local > "$R2/.claude/settings.local.json"
ln -s ../../.agents/skills/s "$R2/.claude/skills/s"; echo old-skill > "$R2/.agents/skills/s/SKILL.md"
profile "$T/p2" "$R2" rw "$R2|$LA|$LR"
out=$(inside "$T/p2" "cd $R2; cat CLAUDE.md .claude/rules/r.md .claude/settings.json .claude/skills/s/SKILL.md")
check "the layers' copies win over the repository's own" [ "$out" = "$(printf 'repo-layer\nrule\nagent-settings\nskill')" ]
[ "$out" = "$(printf 'repo-layer\nrule\nagent-settings\nskill')" ] || echo "      got: $out"
out=$(inside "$T/p2" "cd $R2; cat .claude/settings.local.json; echo more >> .claude/settings.local.json && echo APPENDED")
check "a file only the repository has stays visible and writable" eval 'grep -q "^local$" <<<"$out" && grep -q APPENDED <<<"$out"'
check "the repository's own copies are left as they were" eval '[ "$(cat "$R2/CLAUDE.md" "$R2/.claude/rules/r.md" "$R2/.agents/skills/s/SKILL.md")" = "$(printf "repo-own\nold-rule\nold-skill")" ]'
check "a path the repository lacks gets an empty mount point, and nothing else is added" eval '[ "$(ls -A "$R2/.claude" | LC_ALL=C sort | tr "\n" " ")" = "rules settings.json settings.local.json skills " ] && [ ! -s "$R2/.claude/settings.json" ] && [ ! -s "$R2/AGENTS.md" ]'

echo "== read-only root"
R3=$T/r3; mkrepo "$R3"; profile "$T/p3" "$R3" ro "$R3|$LA|$LR"
out=$(inside "$T/p3" "cd $R3; cat CLAUDE.md .claude/settings.json; echo z > a.txt && echo WROTE")
check "a read-only root shows the layers and stays read-only" eval 'grep -q repo-layer <<<"$out" && grep -q agent-settings <<<"$out" && ! grep -q WROTE <<<"$out"'
[ "$(cat "$R3/a.txt")" = one ] || no "the read-only root's file changed"

echo "== a destination below ROOT"
R4=$T/r4; mkrepo "$R4"; mkdir -p "$R4/agent"; profile "$T/p4" "$R4" rw "$R4/agent|$LR"
out=$(inside "$T/p4" "cat $R4/agent/CLAUDE.md; test -e $R4/CLAUDE.md && echo ROOT-TOO")
check "a destination below ROOT gets the layer there and nowhere else" eval '[ "$out" = repo-layer ]'

echo "== changes made on the host while the agent runs"
R5=$T/r5; mkrepo "$R5"; profile "$T/p5" "$R5" rw "$R5|$LR"
( inside "$T/p5" "cd $R5; cat a.txt >/dev/null; test -e late.txt; sleep 2; cat a.txt late.txt" > "$T/fresh.out" ) &
sleep 1; echo renamed > "$R5/a.tmp" && mv "$R5/a.tmp" "$R5/a.txt"; echo late > "$R5/late.txt"; wait
check "a file the host replaces or creates shows fresh inside" [ "$(cat "$T/fresh.out")" = "$(printf 'renamed\nlate')" ]

echo "== refusals"
refused() {  # refused <description> <message part> <OVERLAY lines...>
  local d=$1 want=$2 out; shift 2
  profile "$T/pr" "$R1" rw "$@"
  out=$(bash "$RUNNER" "$T/pr" run -- true 2>&1)
  if grep -qF -- "$want" <<<"$out"; then ok "$d"; else no "$d" "${out:0:160}"; fi
}
mkdir -p "$T/elsewhere" "$R1/inner" "$T/lmix" "$T/llink/sub" "$T/ltype" "$T/ldir/a.txt"
echo f > "$T/lmix/.claude"; echo f > "$T/ltype/sub"; ln -s ../a.txt "$T/llink/sub/link"
refused "a destination outside ROOT is refused"         "is not ROOT or under it"   "$T/elsewhere|$LR"
refused "a missing layer is refused"                    "layer '$T/absent' is not a folder" "$R1|$T/absent"
refused "a layer inside its destination is refused"     "inside its destination"    "$R1|$R1/inner"
refused "nested destinations are refused"               "nested"                    "$R1|$LR" "$R1/sub|$LA"
refused "nested destinations are refused, inner first"  "nested"                    "$R1/sub|$LA" "$R1|$LR"
refused "a layer file over a repository folder is refused" "not a plain file"       "$R1|$T/ltype"
refused "a layer folder over a repository file is refused" "not a folder"       "$R1|$T/ldir"
refused "a path that is a file in one layer and a folder in another is refused" "but a"      "$R1|$T/lmix|$LR"
refused "a symlink into a folder the repository has is refused" "is a symlink"      "$R1|$T/llink"
refused "a destination with no layer is refused"        "names no layer"            "$R1"

echo "== show and test"
out=$(bash "$RUNNER" "$T/p1" show 2>&1)
check "show names each destination and its mount count" eval 'grep -qE "^overlay $R1: [0-9]+ read-only mounts" <<<"$out"'
check "show prints the layer binds" eval 'grep -qF -- "--ro-bind $LR/CLAUDE.md $R1/CLAUDE.md" <<<"$out"'
out=$(bash "$RUNNER" "$T/p1" test 2>&1)
check "test passes with the layer checks" eval 'grep -q " 0 failed" <<<"$out" && grep -q "^ok    instruction files match their layers" <<<"$out" && grep -q "^ok    instruction paths are read-only mounts" <<<"$out"'
grep -q " 0 failed" <<<"$out" || echo "$out" | grep FAIL
profile "$T/p6" "$R1" rw "$R1|$LA|$LR"; echo wrong > "$T/wrong"
printf 'EXTRA_RO=( "%s:%s" )\n' "$T/wrong" "$R1/.claude/settings.json" >> "$T/p6"
out=$(bash "$RUNNER" "$T/p6" test 2>&1)
check "positive control: test fails when a path does not show its layer" eval 'grep -q "^FAIL  instruction files match their layers" <<<"$out"'
profile "$T/p9" "$R1" rw "$R1|$LA|$LR"; printf 'EXTRA_RO=( "%s:%s" )\n' "$T/wrong" "$R1/CLAUDE.md" >> "$T/p9"
out=$(bash "$RUNNER" "$T/p9" test 2>&1)
check "positive control: test fails when a single bound file does not show its layer" eval 'grep -q "^FAIL  instruction files match their layers" <<<"$out"'
profile "$T/p7" "$R1" rw "$R1|$LA|$LR"; printf 'EXTRA_RW=( "%s:%s" )\n' "$T/elsewhere" "$R1/newdir" >> "$T/p7"
out=$(bash "$RUNNER" "$T/p7" test 2>&1)
check "positive control: test fails when a layer path is writable" eval 'grep -q "^FAIL  instruction paths are read-only mounts" <<<"$out"'
printf 'NAME=tplain\nROOT=%s\nROOT_MODE=rw\nNET=none\nAGENT_HOME=%s\n' "$R1" "$T/home-plain" > "$T/p8"
out=$(bash "$RUNNER" "$T/p8" test 2>&1)
check "a profile without OVERLAY has no layer checks" eval '! grep -q "instruction" <<<"$out" && grep -q " 0 failed" <<<"$out"'
echo "---"; echo "$pass passed, $fail failed (cases: $((pass + fail)))"; [ "$fail" = 0 ]
