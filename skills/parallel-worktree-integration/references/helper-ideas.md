# Ideas taken from worktree helper scripts, and what was changed

Two shell helpers for linked worktrees (a status reporter and a pruner) informed the design of this skill. Only the
ideas are reused. No code, names or paths from those scripts appear here, and the scripts are not a dependency.

## Ideas kept

- **A verdict per worktree, judged against one named base branch.** The verdict vocabulary is merged, unmerged,
  detached and missing, with a status report that changes nothing.
- **Dry run by default.** The pruner prints what it would remove and removes nothing until told to. This skill's
  report prints suggested commands and runs none of them.
- **Protected cases.** A worktree with uncommitted changes, an unmerged branch, a detached head, a missing
  directory, a locked worktree, the base branch itself, and the worktree the command is standing in are never
  removed.
- **Selectors resolve before action.** A name that matches two worktrees is an error, not a guess. Every selector
  is resolved before the first removal, so a typo stops the run before anything changes.
- **Recovery information is printed before deletion.** The tip SHA of each branch is printed, so a deleted branch
  can be recreated with `git branch <name> <sha>` until git garbage-collects the commits.
- **Branch deletion follows the verdict.** A merged branch is deleted with `-d`, which refuses unmerged work. A
  branch judged only by content is deleted with `-D`, and only after its patches are read.
- **Keep the branch, remove the worktree, as an option.** Removing the directory and keeping the branch is a
  separate, reversible choice.

## Ideas changed

- **Superseded detection.** The helper called a branch superseded when every commit subject and every touched
  file existed on the base. That is a heuristic, and its own documentation warns to read the diff. This skill uses
  `git cherry`, which compares patch IDs: a `-` line means an equivalent patch is already on the base. It is still
  not proof of equal content, so the procedure keeps a person's reading of the diff before `-D`.
- **Missing worktrees.** Handled as a verdict in the report, with `git worktree prune` as the fix, not as a
  removal target.
- **Exposed folders.** The helper did not check whether a worktree sat inside an un-ignored folder of the main
  checkout. This skill does, because that is the cause of untracked nested repositories.
- **Stash count.** Added, because the stash stack is shared across worktrees and is the easiest loss to miss.
- **Naming.** The skill uses `wt-` branch names by convention, and the `--prefix` filter scopes a report to them.
  A repository that uses another prefix passes its own.

## Not carried over

- Any path, host, repository or project name from the helper scripts.
- Their dependency on a shared library of shell functions. This skill's script is standard library Python with
  tests that build their own repositories.
