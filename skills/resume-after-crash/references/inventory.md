# Inventorying state without changing it

Every command here is read-only. Run them from a shell that is not inside one of the repositories being
inspected, and pass the path with `-C`, so the root is always explicit. Print the root in the same block
as any figure you report: a wrong root returns true readings of the wrong thing.

## Contents

- Repositories: status, branch and upstream
- Stashes and worktrees
- Unpushed commits and the remote's view
- In-progress git operations
- Lock files and the processes that hold them
- Half-written files
- Background jobs and services
- Containers
- tmux panes
- Recording the inventory

## Repositories: status, branch and upstream

For each repository the work touched:

```sh
REPO=/absolute/path/to/repository
git -C "$REPO" rev-parse --show-toplevel            # the root you are reading
git -C "$REPO" branch --show-current                 # the branch; empty means detached HEAD
git -C "$REPO" status --short --branch               # changes, untracked files, ahead/behind on line 1
git -C "$REPO" log --oneline -n 5 --decorate         # what HEAD is and what it was recently
```

- `status --short --branch` with `??` lines is untracked work. Those files are not in git and a clean
  checkout will not bring them back.
- A detached HEAD with new commits is easy to lose. Note its SHA, and whether a branch points at it.
- Read the whole status. Do not stop at the first screen of a long list: the files you did not write
  matter as much as the ones you did.

## Stashes and worktrees

```sh
git -C "$REPO" stash list                             # shared by every worktree of this repository
git -C "$REPO" worktree list                          # every worktree, its branch, and whether it is locked or prunable
```

- A stash entry you did not create is someone else's work. Do not pop, apply or drop it. Record its
  message and SHA and report it.
- A worktree marked `prunable` has a directory that no longer exists. Do not prune it until its branch
  has been checked for unique commits.
- A worktree whose directory exists may have an owner. See the process check below before touching it.

To see which processes are working in a worktree directory, without reading their command lines, list the
processes whose working directory is in the worktree by reading their links, not their arguments:

```sh
WT=/absolute/path/to/worktree
for p in /proc/[0-9]*; do
  cwd="$(readlink "$p/cwd" 2>/dev/null)"
  case "$cwd" in "$WT"|"$WT"/*) echo "pid ${p#/proc/} comm $(cat "$p/comm" 2>/dev/null) cwd $cwd";; esac
done; echo "scan exit $?"
```

- That prints the process id, its short name, and its working directory. It does not print the command
  line, which can carry a brief.
- No output with exit 0 means no process in this shell's view has that directory as its working directory.
  It is not proof nothing owns the worktree: a process may be in a different mount namespace, or be a
  sandboxed session. Treat "nothing found" as a lead, and confirm with the owner before removal.

## Unpushed commits and the remote's view

```sh
git -C "$REPO" log --oneline '@{u}..'                # commits on this branch not on its upstream
echo "exit $?"                                        # 128 means no upstream is set
git -C "$REPO" remote -v                              # which remote is which (names only matter here)
git -C "$REPO" ls-remote origin "refs/heads/$(git -C "$REPO" branch --show-current)"   # remote's head for this branch
```

- `ls-remote` reads the remote without changing any local ref. Use it rather than `git fetch`, which
  moves remote-tracking refs and so changes the state you are trying to record.
- If a commit exists locally and the remote does not have its SHA, the work is not published. A crash
  does not publish anything, so this is the most common gap.
- Never push during the inventory. Pushing is a reconciliation step, taken only when the evidence says
  the commit is wanted and is a fast-forward (procedure 6 in `SKILL.md`).

## In-progress git operations

A crash in the middle of a rebase, merge, cherry-pick or revert leaves a marker in the git directory.
Find it before anything else:

```sh
GITDIR="$(git -C "$REPO" rev-parse --git-dir)"
ls -d "$GITDIR/MERGE_HEAD" "$GITDIR/CHERRY_PICK_HEAD" "$GITDIR/REVERT_HEAD" \
      "$GITDIR/rebase-merge" "$GITDIR/rebase-apply" "$GITDIR/BISECT_LOG" 2>/dev/null
echo "marker scan exit $?"
```

- `ls` lists only the markers that exist. No output with exit 2 means none of them exist, which is the
  normal state, not a failure.
- For a rebase, read `"$GITDIR/rebase-merge/head-name"` and `"$GITDIR/rebase-merge/msgnum"` to see how far
  it got. These are plain text files.
- Do not abort the operation to clean up. Finishing it, or recording its state, comes first. An abort
  discards the progress the crash interrupted.

To find commits that a crashed operation created and that no branch points to:

```sh
git -C "$REPO" fsck --unreachable --no-reflogs      # read-only; lists dangling commits, can be slow
```

Do not add `--lost-found`. That form writes files into the repository.

## Lock files and the processes that hold them

Git writes a lock file next to what it is changing. A stale one blocks the next command with "Another git
process seems to be running". Find them in the common git directory, which covers worktrees:

```sh
COMMON="$(git -C "$REPO" rev-parse --git-common-dir)"
find "$COMMON" -name '*.lock' -print 2>/dev/null; echo "find exit $?"
```

For each lock found, establish whether git is still running before anything else:

```sh
pgrep -l -x git; echo "git processes exit $?"        # exit 1: no git process at all
```

- Exit 1 with a lock present, and the lock's modification time older than the crash, is the stale case.
  Record the path and its age, then remove that one file (procedure 5 in `SKILL.md`).
- A `git` process running means a live operation. Wait for it, or ask its owner. Do not remove the lock.
- `pgrep -l -x git` prints the process id and the name only. Do not use `pgrep -a` or `ps -f` here: they print
  the full command line, which can contain a brief.

Other lock files in a project (a build tool's, a package manager's) follow the same rule: prove no process
holds them before removing them.

## Half-written files

A crash can leave a file present and partly written. Look at recently changed files in the repository,
excluding the git directory:

```sh
find "$REPO" -path "$REPO/.git" -prune -o -type f -newermt '-12 hours' -print 2>/dev/null; echo "find exit $?"
find "$REPO" -path "$REPO/.git" -prune -o -type f -size 0 -print 2>/dev/null; echo "zero-byte exit $?"
```

- Use a window that covers the crash and a margin. `-newermt '-12 hours'` is a starting point; widen it
  if the crash was earlier.
- For each recent file, check it is complete for its type. A JSON file must parse, a YAML or TOML file
  must parse, a Markdown file should end on a complete line and not mid-sentence, and a file the work
  generates should end where its generator ends. Parse with the project's own tools, for example
  `mise run <check>` if the project defines one, or a parser from the project's toolchain run with `uv`
  or `mise exec`.
- A half-written file is not repaired in place during the inventory. Note it, and decide in procedure 5
  whether it is rewritten, kept as evidence, or moved aside.

## Background jobs and services

```sh
systemctl --user --failed --no-pager                 # user units that failed
systemctl --user list-timers --no-pager              # timers and when they last and next ran
systemctl --user list-units --type=service --state=running --no-pager
```

- A failed unit after a crash is the first thing to explain. Its last log lines are in
  `journalctl --user -u <unit> -b --no-pager | tail -n 50`.
- A timer that did not run during the outage will run once after boot if it is `Persistent=true`. Check
  the unit file before assuming the job is lost or double-run.
- System units are read the same way with `systemctl --failed` and `journalctl -u <unit>` (no `--user`).

## Containers

```sh
command -v docker >/dev/null && docker ps -a --format '{{.Names}}\t{{.Status}}'; echo "docker exit $?"
```

- `docker ps -a` lists stopped containers too. A container that exited at the crash time with a non-zero
  status is a candidate for a partly applied job.
- Do not start, stop or remove a container during the inventory. A container may belong to another
  project, or to a service that restarts itself.
- If `docker` is not installed, the line exits 0 without printing. Check `command -v docker` separately
  if the container question matters.

## tmux panes

```sh
tmux list-sessions -F '#{session_name} #{session_windows} #{session_attached}' 2>&1; echo "tmux exit $?"
tmux list-panes -a -F '#{session_name}:#{window_index}.#{pane_index} #{pane_current_path} #{pane_current_command}' 2>&1; echo "panes exit $?"
```

- Exit 1 with "no server running" means no tmux server is up. That is a finding, not an error to fix.
- `pane_current_command` is the program's short name. Do not query `pane_start_command`: it returns the
  full command line that started the pane, which can carry a brief.
- A pane that is waiting at a prompt may belong to a live session. Do not send keys to it. Report it with
  its session and pane names.

## Recording the inventory

Write the inventory as a table in the report, one row per repository, with these columns: root, branch,
HEAD SHA, working changes (count and the untracked list), stashes (count and origin if known), unpushed
commits (count), in-progress operation (none or the marker), lock files (none or path and age), and any
half-written files. A row with an unknown cell says so.
