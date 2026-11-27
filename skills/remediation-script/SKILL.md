---
name: remediation-script
description: Writes a bash script for the human to run when a guard, sandbox or permission rule blocks the agent's own writes (moves, renames, deletes or bulk edits in a protected tree), then verify the end state once they report it has run. Use when a write is refused by a hook, sandbox, permission prompt or protected path and the change still needs making, or when a bulk file operation should be handed to a person as a reviewable script. Do NOT use for general Bash help or script review (use shell-guru), for a one-off command the agent is allowed to run, or for deciding whether a guard should be relaxed.
license: Apache-2.0
metadata:
  version: "1.0.1"
  tags: "remediation, guards, bash, dry-run, idempotent, human-in-the-loop, verification, operations"
---

# Remediation script

**Goal:** a change that a guard blocked still gets made, by the person the guard exists for, through a script they
can read, dry-run and undo. The agent writes the script and verifies the result. It does not route round the guard.

## Critical

- **Never run the script yourself when a guard blocked you.** Running it is the same write by another route. Write
  it, hand it over, and wait for the report.
- The script defaults to a dry run. The person passes `--apply` only after reading the dry-run output.
- Never test the script against the real tree. Test it against inert fixtures in a temporary directory
  (`references/checklist.md`).
- No secrets, tokens, credentials or personal data in the script, its output or its filename.
- A refusal of one tool is not answered by another tool reaching the same target. Report the refusal and stop.

## Situation to reference

| Situation | Load |
|---|---|
| Writing the script | `references/script-template.md` (the contract is in this file) |
| Before the hand-off, or after the person reports it has run | `references/checklist.md` |
| Asked how bash behaves, for example what `set -e` does | the shell-guru skill, not this one |

## The contract

Every remediation script meets all twelve points. A script that misses one is not handed over.

1. **Location.** `docs/05-operations/YYYY-MM-DD-<verb>-<object>.sh`, or the path the repository's CLAUDE.md names.
   The date is the day the script is written.
2. **Interpreter.** Starts with `#!/usr/bin/env bash` and `set -Eeuo pipefail`. The person runs it as
   `bash <script>`. Their login shell may be zsh, where `set -e` does not stop a failing command in the same way,
   so the explicit `bash` removes that difference.
3. **Dry run by default.** With no arguments it prints every action as `would ...` and changes nothing.
   `--apply` performs them. `-h` or `--help` prints the header comment.
4. **Every action printed.** Each line names the action and both paths, or the single path for a delete.
5. **Idempotent.** Each action checks its own precondition first. When the end state already holds it prints
   `skip` and counts it. A second `--apply` changes nothing and says so.
6. **Never overwrites.** A destination that exists is a failure, not a silent replacement. `mv -n` and `cp -n` sit
   behind an explicit existence check; they are not the only guard.
7. **Verify before delete.** A file is deleted only when its sha256 matches the value recorded in the script. No
   globs, no `rm -rf`, no deletion of a directory.
8. **Hashes for moves and copies.** Record the sha256 before the operation and compare after. A mismatch is a
   failure.
9. **Counts at the end.** One summary line:
   `summary: changed=N skipped=N failed=N mode=dry-run` or `mode=apply`.
10. **Exit status.** Exit 0 only when `failed=0`, in dry-run mode too. A dry run that finds a refused destination
    must not look clean.
11. **Local only.** No network, no sudo, no writes outside the repository, no package installs.
12. **Shellcheck clean.** `shellcheck <script>` reports nothing. If shellcheck is not installed, say so in the
    handover. Do not install it globally.

The script works from the repository root whatever the current directory is:
`ROOT="$(git rev-parse --show-toplevel)"` then `cd "$ROOT"`. Where the repository is not under git, use the root
the CLAUDE.md names.

## Procedure

1. **Confirm the block.** Quote the refusal message verbatim and name the guard: hook, sandbox, permission rule or
   protected path. If the guard is a permission prompt, the owner answers it, not you.

2. **Inventory the change.** List every source, destination and expected hash. Record the hashes now, before any
   move:
   ```bash
   sha256sum -- docs/notes/draft.md
   ```
   On macOS, use `shasum -a 256 -- <path>`. The script's `sha` helper already picks whichever exists.

3. **Write the script** from `references/script-template.md`. Name it by the contract, put one action per line
   in `main`, and record every expected hash in the script.

4. **Test it on a fixture.** Follow the fixture pattern in `references/checklist.md`. The test must show four
   things: a dry run changes nothing, `--apply` makes the change, a second run reports `changed=0`, and a planted
   conflict exits 1 without overwriting anything.

5. **Lint.** `shellcheck <script>`. Fix every finding, or justify a suppression in a comment next to it.

6. **Commit the script on its own**, following the repository's git rules, so the person runs a reviewed,
   committed file. Say which commit it is.

7. **Hand off.** Give the exact commands, in order, and what to reply with. Example:

   ```text
   From the repository root, run these in order:
     bash docs/05-operations/2026-11-19-move-drafts.sh
     bash docs/05-operations/2026-11-19-move-drafts.sh --apply
   Reply "ran" with the summary line from each run, and any FAIL line. Do not paste file contents.
   ```

8. **Wait.** Do not run `--apply`. Re-author the script only if the person reports a failure, and then diff the new
   script against the old one before handing it over again.

## After the person reports "ran"

Verify the end state yourself. The reported summary is evidence of what the script printed, not of the state of
the tree.

1. Re-run the dry run. It must print `changed=0`. Any other number means some of the work did not apply.
2. Check each destination's hash and that each source is gone:
   ```bash
   sha256sum -- <destination>
   test ! -e <source> && echo "source gone"
   ```
3. Check nothing else moved: `git status --porcelain=v1` must list only the paths the script touched, plus any
   paths already dirty before the work started.
4. Record the outcome in the same folder as the script, as `<script-name-without-.sh>.outcome.md`: the date, the
   summary lines the person reported, your verification commands, and their results. Commit it under the
   repository's git rules.
5. Tell the person the result in one line: verified, or not verified and why.
