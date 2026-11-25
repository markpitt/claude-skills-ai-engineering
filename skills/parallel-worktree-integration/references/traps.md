# Traps in parallel worktrees

Each trap below has a symptom, the mechanism, a check, and the rule that avoids it. The first two are the ones
that cause data loss in practice; the stash rule is absolute.

## 1. The stash stack is shared by every worktree

**Symptom.** A `git stash pop` in one worktree restores work from another, or drops it. A stash appears in a
worktree that never made one.

**Mechanism.** `refs/stash` and its reflog live in the repository's common directory, not in each worktree. Every
linked worktree of a repository reads and writes the same stack. Git's per-worktree state covers `HEAD`, the index
and some refs such as `refs/bisect`, but not the stash.

**Check.** Print the stack from any worktree; the count is the same everywhere:

```bash
git -C "$REPO" stash list | wc -l
git -C "$WT_ROOT/t1-parser" stash list | wc -l
```

`worktree_report.py` prints the stash count and labels it as shared.

**Rule.** Never run a bare `git stash` in a parallel run. Do not use `git stash` to set work aside while another
worktree is active. Options that do not touch the shared stack:

- commit the work-in-progress on the task's own branch, and amend or squash it later with a person's approval;
- work in a new worktree rather than switching the one you have;
- if a stash is unavoidable, name it and refer to it by its commit, not by position. Check the entry count
  before and after `git stash push -m "wt-t1 pause: <reason>"`: no change in the count means no entry was made,
  and `stash@{0}` would then name an older entry. When an entry was made, record `git rev-parse stash@{0}`,
  restore with `git stash apply <sha>`, and drop by index only after `git stash list` shows that SHA at that index.

Every stash entry in a run is one a person may need to recover. List them in the report.

## 2. Worktrees inside an un-ignored folder show up as untracked in the main checkout

**Symptom.** `git status` in the main checkout shows `?? .worktrees/` or `?? <folder>/`, and a blanket
`git add -A` takes the linked worktree in as a nested repository.

**Mechanism.** A linked worktree is a directory with its own `.git` entry (a file, not a folder). Git treats a
directory that holds its own `.git` as a nested repository, and reports it as untracked unless an ignore rule covers it. The main checkout
has no way to know the folder is a worktree.

**Check.** Before fan-out and after it:

```bash
git -C "$REPO" check-ignore -v .worktrees/probe || echo "NOT IGNORED"
git -C "$REPO" status --short
```

`worktree_report.py` flags such a worktree as `exposed`.

**Rule.** Put worktrees outside the checkout (for example `<repo>-wt/` next to it). If a folder inside the checkout
is needed, add its name to `.gitignore` and commit that, before the first `worktree add`. A local-only rule in
`.git/info/exclude` clears the status for one machine but is not visible to other clones, so do not rely on it
for a shared repository.

## 3. A branch can be checked out in one worktree only

**Symptom.** `fatal: '<branch>' is already checked out at '<path>'`.

**Mechanism.** Git refuses to check out the same branch in two worktrees, because two working trees on one branch
would race on the same ref.

**Rule.** Each task gets its own branch. Do not use `--force` to share one. If a task is returned to its author,
the author's worktree keeps the branch and nothing else takes it.

## 4. A worktree in use must not be removed

**Symptom.** Files vanish from a worktree that an agent is still editing, or a commit it was about to make is lost.

**Mechanism.** `git worktree remove` deletes the directory. It refuses a dirty or locked worktree, but a worktree
whose agent is still running is neither dirty nor locked until it writes.

**Rule.** Remove a worktree only after its agent has reported its final SHA and stopped. Lock a worktree that must
survive a pause (`git worktree lock --reason "<why>" <path>`), so a clean-up pass refuses it. Never use
`git worktree remove --force` on a worktree the report did not classify as `safe`.

## 5. Cherry-picking the same patch twice

**Symptom.** A commit appears twice on the integration branch, or a pick reports an empty commit.

**Mechanism.** A cherry-pick creates a new commit with the same patch and a new SHA. Picking a task's commits again
after a partial run duplicates them.

**Check.** `git cherry <base> <branch>`: a `-` line is a patch already present on the base, a `+` line is not.

**Rule.** Before a pick run, read `git cherry`. Pick only the `+` lines. If `git cherry-pick` reports an empty
commit, it means the patch is already there: `git cherry-pick --skip` is correct only after that check.

## 6. Commands run in the wrong worktree

**Symptom.** A commit lands on the base checkout, or a test runs against another task's files.

**Mechanism.** A relative path or a stale current directory resolves to a different worktree. `git -C` in a
shared command line is the usual cause.

**Rule.** Use absolute paths in every command, and print the root the command runs in:
`git -C "$WT" rev-parse --show-toplevel`. The root is the evidence; a green test in the wrong root is not.

## 7. A failed pick leaves the index dirty

**Symptom.** After a conflict, `git status` shows files staged that were never chosen.

**Mechanism.** A conflicted cherry-pick leaves the index holding the partial merge. A blanket `git add` during
resolution stages everything, including unrelated files.

**Rule.** Stage only the named files that were resolved. Check `git status` before `--continue`.
