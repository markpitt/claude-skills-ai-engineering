---
name: parallel-worktree-integration
description: Runs several subagents in parallel git worktrees, one branch per task pinned to a base commit, then integrates their commits by cherry-pick in plan order with conflict handling, verifies the result, prunes the wt-* worktrees and reports what is left. Covers the shared stash stack (never a bare git stash), worktrees inside an un-ignored folder that show as untracked in the main checkout, and a read-only report of every worktree's state. Use when fanning work out to parallel agents in git worktrees, cherry-picking task branches into an integration branch, cleaning up leftover wt-* worktrees, or asking what worktrees and stashes remain. Do NOT use for splitting one dirty tree into commits (use atomic-commit-organiser), for an audit-fix-review cycle (use audit-remediation-loop), or for resolving a single merge conflict with no worktrees involved.
license: Apache-2.0
metadata:
  version: "1.0.1"
  tags: "git, worktree, parallel, subagents, cherry-pick, integration, stash, prune, multi-agent, workflow"
---

# Parallel worktree integration

**Goal:** let several agents work at once without sharing a working tree, then bring their commits back
onto one integration branch in a stated order, with every conflict decided and the result tested. End with
an honest list of what is left behind.

Parallel agents in one checkout overwrite each other's edits and share one index. Separate worktrees
remove the shared files, but not the shared repository: refs, the stash stack and the object store are
common to all of them. The procedure below is built around that.

## Quick reference

| Task | Load |
|---|---|
| The full sequence, with commands, from variables to the final report | `references/fan-out-and-integrate.md` |
| The traps: shared stash, untracked worktrees, one-branch-one-worktree, removal in use, duplicate picks | `references/traps.md` |
| Which ideas came from the worktree helper scripts, and what was changed | `references/helper-ideas.md` |
| Read-only state report with verdicts and the commands a person could run | `scripts/worktree_report.py` |

## Procedure

Set the variables as quoted absolute paths, then follow `references/fan-out-and-integrate.md` in order.

```bash
SKILL_DIR=/absolute/path/to/parallel-worktree-integration
REPO=/absolute/path/to/repository
WT_ROOT=/absolute/path/to/repository-wt
```

1. **Start clean.** `git status` in the main checkout is empty. Record the base commit SHA. Every later
   step reads that SHA, not a branch that can move.
2. **Plan.** One task per branch, each with a file list it may write. Two tasks that write one file are
   sequential, not parallel. Keep the plan outside the repository or in an ignored path.
3. **Check the worktree location** is outside the checkout, or inside an ignored folder. Confirm with
   `git check-ignore -v`.
4. **Fan out.** `git worktree add -b wt-<task> <path> <base-sha>` for each task. Give each agent its path,
   its file list and the rules in step 5.
5. **Brief each agent with the rules:** write only inside its worktree and its files; commit with explicit
   paths; no `git stash`; no `git checkout` or `git switch` away from its branch; no `git -C` into another
   worktree; wrapped tests with the exit code reported; the branch and final `HEAD` SHA reported.
6. **Check overlap** before integrating: the files each branch changed, against the base, intersected
   pairwise. Any shared file sets the order and expects a conflict.
7. **Integrate in an integration worktree** from the pinned base, not in the main checkout:
   `git worktree add -b integrate-<date> <path> <base-sha>`.
8. **Cherry-pick in plan order**, `git cherry-pick -x` per commit, stopping at the first conflict. After
   each task, run its tests wrapped and record the exit code.
9. **Resolve or give back.** Read both sides and the base version. Stage named files only. Continue with
   `GIT_EDITOR=true git cherry-pick --continue`. If the resolution needs a decision the plan does not
   contain, `git cherry-pick --abort` and return the task to its author.
10. **Verify the whole result** with the repository's full test command, wrapped, once.
11. **Hand back the integration branch** for a person to merge under the repository's policy. Do not merge
    or push `main` from this procedure.
12. **Prune** after that merge: run the report, remove only rows it marks `would remove`, delete branches
    after their worktrees, and never remove a `dirty`, `locked`, `unmerged` or `inside` worktree.
13. **Report** the base, the integration SHA, each pick and its result, each conflict and its resolution,
    the test exit codes, and the final report output (worktrees, verdicts, stash count, branches left).

## The report script

```bash
python3 -I "$SKILL_DIR/scripts/worktree_report.py" -C "$REPO" -b main [--prefix wt-]; echo "exit=$?"
```

It is read-only. It reports for each linked worktree a verdict (`merged`, `applied`, `unmerged`, `detached`,
`missing`, `base`) and flags (`dirty`, `locked`, `inside`, `exposed`), and it prints the stash count, which
is shared. Its verdict `applied` means every commit's patch is already on the base under another SHA, as
after a cherry-pick. Exit 0 means nothing needs action, 1 means something does, 2 is a usage or repository
error. It runs no removal.

## Rules

- **Never run a bare `git stash`.** The stash stack is shared by every worktree of the repository. A pop in
  one worktree can restore or drop another's work. Commit work-in-progress on its branch instead, or name and
  refer to any stash by its SHA.
- **Keep worktrees out of un-ignored folders.** Inside an un-ignored folder they show as untracked in the
  main checkout, and a blanket `git add -A` takes them in as nested repositories.
- **One branch, one worktree.** Never force a branch into a second worktree.
- **Pin the base by SHA** for the whole run, and read it from the SHA, not the branch name.
- **Integrate in a worktree of its own**, so a failed pick leaves the main checkout untouched.
- **Pick in plan order, and stop at the first conflict.** Do not skip ahead to a later task.
- **Use `git cherry` before a re-pick,** and pick only the `+` lines. An empty pick is a patch already present.
- **Remove a worktree only after its agent has stopped and reported its SHA.** A worktree a running agent is
  writing to looks clean until it writes.
- **Keep every command on absolute paths** and print `git rev-parse --show-toplevel` where a result depends
  on the root.
- **Never merge or push `main`** from this procedure, and never use `--force` on a worktree or branch.
- **Verify before reporting.** A test passing in a task worktree is not proof that the integrated result passes.

## Tests

The report script has tests that build real repositories in a temporary directory, covering each verdict, each
flag, the shared stash, the prefix filter and the usage error.

```bash
cd "$REPO"   # any directory inside the repository being tested from
<sandbox> python3 -P "$SKILL_DIR/scripts/test_worktree_report.py" -v; echo "exit=$?"
```

`<sandbox>` stands for whatever runs test code in isolation on your machine, for example a bubblewrap (`bwrap`) wrapper that makes only the repository writable. Leave it out to run the tests directly. Run them from a directory inside the repository. The
repositories they build live under the wrapper's private `/tmp`.

## Limits

- The report judges content by patch equivalence (`git cherry`). It does not judge intent. A patch that is
  equivalent on the base may still need a reading before its branch is deleted.
- It does not resolve conflicts, run tests or merge. Those stay with the procedure and the person who
  decides.
- Worktree behaviour is taken from git's documented model. The tests check the cases above with the git
  installed when they ran; a different git version is not covered.
- Nothing here changes the repository's branch protection or its merge policy.
