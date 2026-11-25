# Script template

Copy this file's script into `docs/05-operations/YYYY-MM-DD-<verb>-<object>.sh`, then replace the placeholders in
`main`. Every line below is needed. Remove none of them: each one carries a part of the contract in `SKILL.md`.

Placeholders: `<verb>`, `<object>`, the example paths, and the 64-zero hash. The zero hash is deliberately wrong.
Replace it with the output of `sha256sum -- <path>` taken before the change, or the script refuses to delete.

```bash
#!/usr/bin/env bash
# <Verb> <object>: <one line on why the guard blocked the agent>.
# Written YYYY-MM-DD by the agent. Dry run by default.
#   bash docs/05-operations/YYYY-MM-DD-<verb>-<object>.sh           shows every action, changes nothing
#   bash docs/05-operations/YYYY-MM-DD-<verb>-<object>.sh --apply   performs them
set -Eeuo pipefail

usage() {
  sed -n '2,5p' "$0"
}

APPLY=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    -h | --help) usage; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

trap 'printf "aborted at line %s, exit %s: no summary printed\n" "$LINENO" "$?" >&2' ERR

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

changed=0
skipped=0
failed=0

say() { printf '%s\n' "$*"; }

# sha prints the sha256 of one file, on Linux or macOS.
sha() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -- "$1" | awk '{print $1}'
  else
    shasum -a 256 -- "$1" | awk '{print $1}'
  fi
}

# move_file SRC DST: never overwrites; the hash must match after the move.
move_file() {
  local src="$1" dst="$2" before after
  if [[ -e "$dst" ]]; then
    if [[ ! -e "$src" ]]; then
      say "skip (already moved): $dst"
      skipped=$((skipped + 1))
    else
      say "FAIL destination exists, not overwritten: $dst"
      failed=$((failed + 1))
    fi
    return 0
  fi
  if [[ ! -f "$src" ]]; then
    say "FAIL source missing or not a regular file: $src"
    failed=$((failed + 1))
    return 0
  fi
  before="$(sha "$src")"
  if [[ "$APPLY" -eq 0 ]]; then
    say "would move: $src -> $dst (sha256 $before)"
    changed=$((changed + 1))
    return 0
  fi
  mkdir -p -- "$(dirname -- "$dst")"
  mv -n -- "$src" "$dst"
  after="$(sha "$dst")"
  if [[ "$before" == "$after" && ! -e "$src" ]]; then
    say "moved: $src -> $dst"
    changed=$((changed + 1))
  else
    say "FAIL hash or source check failed after move: $dst"
    failed=$((failed + 1))
  fi
  return 0
}

# remove_file PATH SHA256: deletes only the exact file whose hash was recorded.
remove_file() {
  local path="$1" expected="$2" actual
  if [[ ! -e "$path" ]]; then
    say "skip (already gone): $path"
    skipped=$((skipped + 1))
    return 0
  fi
  if [[ ! -f "$path" ]]; then
    say "FAIL not a regular file, not deleted: $path"
    failed=$((failed + 1))
    return 0
  fi
  actual="$(sha "$path")"
  if [[ "$actual" != "$expected" ]]; then
    say "FAIL sha256 differs from the recorded value, not deleted: $path"
    failed=$((failed + 1))
    return 0
  fi
  if [[ "$APPLY" -eq 0 ]]; then
    say "would delete: $path"
    changed=$((changed + 1))
    return 0
  fi
  rm -- "$path"
  say "deleted: $path"
  changed=$((changed + 1))
  return 0
}

main() {
  # One line per action. Paths are relative to the repository root.
  move_file "docs/drafts/example-old.md" "docs/archive/2026/example-old.md"
  remove_file "scratch/example-export.csv" "0000000000000000000000000000000000000000000000000000000000000000"
}

main

mode=dry-run
if [[ "$APPLY" -eq 1 ]]; then
  mode=apply
fi
printf 'summary: changed=%s skipped=%s failed=%s mode=%s\n' "$changed" "$skipped" "$failed" "$mode"
if [[ "$failed" -gt 0 ]]; then
  exit 1
fi
```

## What each part does

| Part | Contract point |
|---|---|
| Shebang and `set -Eeuo pipefail` | 2: deterministic under `bash <script>` |
| `APPLY` flag and `--help` | 3: dry run by default |
| `say` on every branch | 4: every action printed |
| `skip (already ...)` branches | 5: idempotent |
| `[[ -e "$dst" ]]` before `mv -n` | 6: refuses to overwrite |
| `remove_file` hash comparison | 7: verify before delete |
| `before` and `after` hashes in `move_file` | 8: hashes for moves |
| `summary:` line and `changed` counters | 9: counts |
| `exit 1` when `failed` is above zero | 10: exit status, dry run included |
| `ERR` trap | a failing command stops the script loudly, with its line |

## Adapting it

- Add one `move_file` or `remove_file` line per action. Do not add a loop over a glob: the list is explicit so the
  person can read exactly what will happen.
- Record the hash of each source before writing the script, and put it in the call.
- A copy needs the same shape as `move_file` with `cp -n` in place of `mv -n`, and a hash check on the copy.
- Keep the script free of network calls, package installs and `sudo`.
