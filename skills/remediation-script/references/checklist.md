# Checklist

Use this before the hand-off, and again after the person reports "ran".

## Before the hand-off

- [ ] The refusal is quoted verbatim, and the guard is named: hook, sandbox, permission rule or protected path.
- [ ] I have not run the script, or any destructive command it contains, against the real tree.
- [ ] The script is named `YYYY-MM-DD-<verb>-<object>.sh` in the operations folder, or where the CLAUDE.md says.
- [ ] Shebang `#!/usr/bin/env bash`, then `set -Eeuo pipefail`.
- [ ] `-h` or `--help` prints the header; no argument is a dry run; `--apply` is the only way to change anything.
- [ ] Every destination is checked for existence before the move, and nothing is overwritten.
- [ ] Every delete checks a recorded sha256. No globs, no `rm -rf`, no directory deletes.
- [ ] Every move or copy compares hashes after the operation.
- [ ] The summary line is printed in both modes, and exit status is 1 whenever `failed` is above zero.
- [ ] No network calls, no `sudo`, no writes outside the repository, no secrets.
- [ ] `shellcheck` reports nothing, or the handover says it is not installed.
- [ ] The fixture test below passed, and its results are noted.
- [ ] The hand-off gives the exact commands in order, the expected reply, and says nothing has been applied.

## Fixture test

Test against a throwaway repository with inert names. Never run the script against the real tree to see what
happens. Use names that show quoting works, such as a file called `draft with spaces.md` or `keep; echo PWNED.md`.
Its name is data, so a correct script never runs it.

Where the estate has a sandbox wrapper for test code, run the fixture through it, for example
`mp-sandbox-test bash <script>`.

```bash
fixture="$(mktemp -d)"
git -C "$fixture" init -q
mkdir -p "$fixture/docs/drafts" "$fixture/scratch"
printf 'one\n' > "$fixture/docs/drafts/draft with spaces.md"
printf 'two\n' > "$fixture/scratch/keep; echo PWNED.csv"
cp /path/to/script.sh "$fixture/script.sh"
sha256sum -- "$fixture/scratch/keep; echo PWNED.csv"   # record this hash for the remove_file line
cd "$fixture"
```

In the copied `script.sh` only, change `main` to the fixture's names: `move_file "docs/drafts/draft with spaces.md"
"docs/archive/2026/draft with spaces.md"`, and `remove_file "scratch/keep; echo PWNED.csv"` with the hash just
printed. Then:

```bash
bash script.sh                 # 1. dry run: must say would move and would delete, changed=2, exit 0
ls docs/drafts                 # 2. the draft must still be there
bash script.sh --apply         # 3. apply: changed=2
bash script.sh                 # 4. re-run: must report changed=0 and skipped=2
echo "exit: $?"                # 5. exit 0 on a clean re-run
```

A green case that cannot go red is not coverage. Plant a conflict in the same fixture before a second apply:

```bash
printf 'one\n' > "docs/drafts/draft with spaces.md"          # source back in place
printf 'other\n' > "docs/archive/2026/draft with spaces.md"  # destination already exists: must not be overwritten
bash script.sh --apply; echo "exit: $?"   # must print FAIL destination exists for the move, and exit 1
cat "docs/archive/2026/draft with spaces.md"   # must still read: other
```

Also confirm that a wrong hash refuses the delete: put the zero placeholder back in the copied script, run a dry
run, and expect `FAIL sha256 differs` with exit 1.

Remove the fixture when finished, by its `mktemp` path only: `rm -rf -- "$fixture"`.

## After "ran"

- [ ] Re-run the dry run: `changed=0`.
- [ ] `sha256sum -- <destination>` matches the recorded hash for each destination.
- [ ] Each source is gone: `test ! -e <source>`.
- [ ] `git status --porcelain=v1` lists only the expected paths, plus paths already dirty before the work.
- [ ] The outcome note `<script-name-without-.sh>.outcome.md` is written next to the script and committed under the
      repository's git rules.
- [ ] The person has one line back: verified, or not verified and the reason.
