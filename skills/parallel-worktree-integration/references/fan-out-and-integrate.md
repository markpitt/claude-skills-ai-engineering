# Fan out, integrate and prune: the full procedure

Read `SKILL.md` first for the rules. This file gives the commands in order. Shell snippets are for a POSIX
shell or bash. In zsh, store lists in arrays and do not rely on word splitting of an unquoted variable.
`<sandbox>` stands for whatever runs test code in isolation on your machine, for example a bubblewrap
wrapper that makes only the repository writable.

## 0. Set the variables and check the starting point

```bash
REPO=/absolute/path/to/repository          # the main checkout
WT_ROOT=/absolute/path/to/repository-wt    # outside the checkout (preferred), or an ignored folder inside it
BASE_BRANCH=main
git -C "$REPO" status --short              # must be empty, or holding only files you know are not part of this run
BASE_SHA=$(git -C "$REPO" rev-parse "$BASE_BRANCH")
echo "base $BASE_BRANCH = $BASE_SHA"
```

Stop if the status is not empty. Record `BASE_SHA`: every later step reads that commit, not a branch name that
can move while the work runs.

Check where worktrees will go. If `WT_ROOT` is inside the checkout, confirm it is ignored:

```bash
git -C "$REPO" check-ignore -v "$WT_ROOT/probe" || echo "NOT IGNORED: choose a folder outside the checkout"
```

## 1. Write the plan before any fan-out

Keep the plan outside the repository, or in an ignored path. It records, for each task:

| Field | Example |
|---|---|
| Task ID | `t1-parser` |
| Branch | `wt-t1-parser` |
| Worktree path | `$WT_ROOT/t1-parser` |
| Files the task may write | `src/parser.py`, `tests/test_parser.py` |
| Integration order | 1 |
| Expected test command | `<sandbox> python3 -m unittest discover -s tests` |

Two tasks that write the same file are sequential, not parallel. Put them in one task, or order them and expect a
conflict at integration time.

## 2. Fan out: one worktree per task, pinned to the base

```bash
git -C "$REPO" worktree add -b wt-t1-parser "$WT_ROOT/t1-parser" "$BASE_SHA"
git -C "$REPO" worktree add -b wt-t2-cli    "$WT_ROOT/t2-cli"    "$BASE_SHA"
```

- A branch can be checked out in one worktree only. `git worktree add -b` refuses a name already in use. If
  it refuses, the name is taken: choose another, do not `--force`.
- Give each subagent its worktree path and its file list. Tell it, in terms it can act on:
  - write only inside its worktree, and only the files on its list;
  - commit with explicit paths (`git add -- <file>`), never `git add -A` or `git add .`;
  - do not run `git stash`, `git checkout` or `git switch` to another branch, or `git -C` into another worktree;
  - run its tests through the repository's wrapper, and report the exact command and exit code;
  - report the branch name and the `HEAD` SHA of its final commit.

## 3. Check the tasks do not overlap before integrating

When the tasks finish, compare the files each branch changed against the base:

```bash
git -C "$REPO" diff --name-only "$BASE_SHA" wt-t1-parser | sort > "$WT_ROOT/t1.files"
git -C "$REPO" diff --name-only "$BASE_SHA" wt-t2-cli    | sort > "$WT_ROOT/t2.files"
comm -12 "$WT_ROOT/t1.files" "$WT_ROOT/t2.files"
```

Any output is a shared file. Expect a conflict there, and plan its order. An empty result means the picks
should apply cleanly. Keep the two `.files` lists outside the checkout.

## 4. Create an integration worktree from the pinned base

Integrate in a worktree of its own, so the main checkout is not touched until the result is checked:

```bash
git -C "$REPO" worktree add -b integrate-$(date +%Y%m%d) "$WT_ROOT/integrate" "$BASE_SHA"
cd "$WT_ROOT/integrate"
```

Run the cherry-picks from inside `$WT_ROOT/integrate`, so each command works on the integration branch.

## 5. Cherry-pick in plan order, one task at a time

For each task in the plan's order:

```bash
TASK_SHAS=$(git rev-list --reverse "$BASE_SHA..wt-t1-parser")
for sha in $TASK_SHAS; do git cherry-pick -x "$sha" || break; done
```

- `-x` appends the source SHA to the message, so the origin of each commit can be traced.
- The loop stops at the first conflict (`|| break`). Do not continue past a conflict with a later task.
- Run the task's test command after its picks, inside the sandbox, and record the exit code.
- After each task, confirm its patches are on the integration branch with `git cherry HEAD wt-<task>`. The
  pass condition is that there is no `+` line. A `+` line is a commit whose patch is not on HEAD. A `-` line is
  a commit picked under a new SHA. A commit can also be absent from the output because the pick kept its SHA
  (it lands on the same parent in the same second); absence is then a pass. Do not test ancestry with the
  task's SHA: a picked commit is usually a new SHA, so that test fails for a pick that worked.

An empty `TASK_SHAS` means the task has no commits past the base. Say so in the report; it is not a success
of integration.

## 6. Resolve a conflict, or give it back

When a pick stops:

1. Read the state: `git status --short`, then `git diff --name-only --diff-filter=U`.
2. For each conflicted file, read both sides and the base version (`git show "$BASE_SHA:<path>"`). Decide the
   result from the intent of each task, not from which side is longer.
3. Edit the file to the decided result. Remove every conflict marker. Run the tests.
4. Stage the named files only: `git add -- <file> <file>`.
5. Continue without opening an editor: `GIT_EDITOR=true git cherry-pick --continue`.

If the resolution needs a decision that is not in the plan, stop. Abort and return the task to its author:
`git cherry-pick --abort`. Abort restores the integration branch to its state before that pick.

Repeated conflicts on the same hunk can be remembered with `git rerere` (enable it in the integration worktree
only, and say so in the report). It is an aid, not a substitute for reading the resolution.

## 7. Verify the whole result against the base

```bash
git -C "$WT_ROOT/integrate" log --oneline "$BASE_SHA..HEAD"
git -C "$WT_ROOT/integrate" diff --stat "$BASE_SHA" HEAD
<sandbox> <the repository's full test command>; echo "exit=$?"
```

Run the full suite once on the integrated result. A green task test is not proof that the combined result is
green.

## 8. Hand the integration back, then prune

The integration branch is merged into the base by a person, under the repository's policy. Do not merge it, and
do not push `main`, from this procedure.

Once the integration branch is merged, prune the task worktrees. Use the report first:

```bash
python3 -I "$SKILL_DIR/scripts/worktree_report.py" -C "$REPO" -b "$BASE_BRANCH" --prefix wt-
```

- Remove only rows reported `would remove`, by path: `git -C "$REPO" worktree remove "$WT_ROOT/t1-parser"`.
- Delete the branch after the worktree: `git -C "$REPO" branch -d wt-t1-parser`. `-d` checks merge status against
  the branch's upstream if it has one, otherwise against the HEAD of the worktree the command runs in. Run it from
  the base checkout, and only after the integration branch is merged. Use `-D` only for an `applied` verdict, after reading `git cherry` for each branch.
- Never remove a worktree the report marks `dirty`, `locked`, `unmerged` or `inside`. Resolve the reason first.
- A `missing` row is a record with no directory: `git -C "$REPO" worktree prune`.

## 9. Report what is left

Give, in this order:

1. The base SHA, the integration branch and its head SHA, and the commits picked (SHA, task, pick result).
2. Each conflict: the file, how it was resolved, and the reason.
3. The full-suite command and its exit code, as printed.
4. The final report output: each remaining worktree with its verdict and flags, the stash count, and the
   branches left.
5. Anything not verified, such as a task whose tests were not run or a branch the report could not classify.
