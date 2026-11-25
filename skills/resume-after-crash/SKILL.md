---
name: resume-after-crash
description: Recover an agent's work after a host crash, WSL restart, Windows update reboot or lost terminal. Establishes what happened (boot history, disk full, out-of-memory kills), inventories state without changing it (git status, stashes, worktrees, unpushed commits, in-progress git operations, lock files, half-written files, background jobs, containers, tmux panes), reads the plan and the last handover, reconciles each in-flight step as done, partial or not started from evidence, then resumes from the last verified step and reports what was lost and what was redone. Use when an agent or long task was interrupted by a reboot, crash or terminal loss, when asked to pick up work after the machine restarted, or when a git index lock or half-finished change blocks a resume. Do NOT use to set up tmux sessions that survive reboots (use tmux-persist), for ordinary merge conflict resolution, or for starting fresh work with no prior state.
license: Apache-2.0
metadata:
  version: "1.0.0"
  tags: "recovery, crash, reboot, wsl2, git, handover, resume, reconciliation"
---

# Resume after a crash

Recover where an agent's work got to. The aim is to know what is actually on disk and in git, not what
the last message said, then to continue from the last step you can prove finished.

Procedures 1 to 4 only read. Nothing changes until procedure 5, and then only the verified steps.
Paths and session names here are placeholders. A private host overlay may be loaded alongside this skill
with the real repository list, handover location and plan location. Use it when present.

## Critical

- **Read first, change later.** Procedures 1 to 4 must not write to any repository, lock file, stash,
  worktree, service or container.
- **Never kill, restart, clear or interrupt another agent's session or pane.** A pane that looks dead
  may be a session waiting for input. Report it. Do not send keys to it.
- **A lock file is not garbage until proven so.** Delete a git lock only after `pgrep -x git` shows no
  git process and the lock is older than any live operation could be. Record the path and its age first.
- **A worktree is not garbage until proven so.** Do not remove one until nothing has its directory as
  a working directory and its branch has no unique uncommitted work. Removing one with uncommitted
  changes destroys them.
- **Prefer a WIP commit to a stash in a shared tree.** The stash list is shared by every worktree of a
  repository. Use `git stash push` only with a unique message, and never bare `git stash` or `pop`.
- **Re-run only idempotent steps.** Before repeating any step with an external effect (a send, a post,
  a publish, a deploy, a payment, a migration, a pull request), query the target first and decide from
  what is there.
- **Print names, not argument vectors.** A process listing with arguments can expose a brief or a key.
  Use `pgrep -l -x <name>` or `ps -o pid,etime,stat,comm`, which show names only.
- **A handover is a lead, not evidence.** Verify each claim it makes against the repository or the
  output it cites before relying on it.

## Situation to reference

| Situation | Read |
|---|---|
| Working out what stopped the work: reboot, WSL restart, Windows update, disk full, out of memory | `references/boot-and-cause.md` |
| Inventorying repositories, git operations in progress, lock files, half-written files, jobs, containers, tmux | `references/inventory.md` |
| Reading the plan and handover, reconciling each step, resuming, and writing the report | `references/reconcile-and-report.md` |

## Procedures

### 1. Establish what happened (read only)

```sh
uptime -s                                              # when this kernel (or WSL VM) booted
cat /proc/uptime                                       # seconds up
journalctl --list-boots --no-pager | tail -n 5         # boots the journal knows about
ls -d /var/log/journal 2>/dev/null; echo "persistent journal dir exit $?"
journalctl -b -1 -p warning --no-pager | tail -n 80    # end of the previous boot, warnings and worse
```

- No `/var/log/journal` means the journal is volatile: the previous boot's log is gone after a reboot.
  Say so in the report; it limits what can be proven about the cause.
- A previous boot whose log stops abruptly, with no shutdown sequence, points to a crash or power loss.
  A clean stop ends with the shutdown targets being reached.
- On WSL2 and Windows-side causes, see `references/boot-and-cause.md`.

### 2. Check the disk and memory (read only)

```sh
df -h / ; echo "df exit $?"
df -i / ; echo "df -i exit $?"
journalctl -k -b -1 --no-pager | grep -i -E 'out of memory|oom-kill|killed process'; echo "grep exit $?"
```

- Exit 1 from grep means no kill was logged. It does not prove there was none, if the journal is volatile.
- Full disks cause crashes that look like everything else. On WSL2, the Windows drive holding the
  virtual disk can be full even when the guest's `df` is fine. See `references/boot-and-cause.md`.

### 3. Inventory the state (read only)

Work through every repository the interrupted work touched. Get the list from the plan, the handover, or
the overlay, not from memory. Use `references/inventory.md` for the exact commands. The minimum per repo:

```sh
git -C "$REPO" rev-parse --show-toplevel                 # print the root you are reading
git -C "$REPO" status --short --branch
git -C "$REPO" stash list
git -C "$REPO" worktree list
git -C "$REPO" log --oneline '@{u}..' ; echo "unpushed exit $?"   # exit 128: no upstream set
```

Then check for in-progress git operations, lock files, and processes holding them:

```sh
GITDIR="$(git -C "$REPO" rev-parse --git-dir)"
ls -d "$GITDIR/MERGE_HEAD" "$GITDIR/CHERRY_PICK_HEAD" "$GITDIR/REVERT_HEAD" \
      "$GITDIR/rebase-merge" "$GITDIR/rebase-apply" "$GITDIR/BISECT_LOG" 2>/dev/null; echo "markers exit $?"
pgrep -l -x git; echo "git processes exit $?"          # exit 1: none running
```

Exit 2 from the `ls` line means none of the markers exists, which is the normal state. Full detail is in
`references/inventory.md`.

### 4. Read the plan and the handover, then reconcile (read only)

1. Read the work's todo list and the newest handover note. The todo list is the source of what was in
   flight. The handover is the last thing the interrupted agent wrote down.
2. For each step marked in flight, partial or unstarted, decide `done`, `partial` or `not started` from
   the repository and the output it should have left. Use `references/reconcile-and-report.md`.
3. Do not mark anything done on the strength of a message, a handover line, or memory of having run it.

### 5. Clean up what is provably safe

Only after procedures 1 to 4, and only for items the evidence shows are not owned by a live process:

- A git lock older than the crash with no git process running: record its path and age, then remove
  that one file. Do not remove the other locks in the same directory without the same proof.
- A half-written file that fails to parse, or is zero bytes, and whose content the next step rewrites
  anyway: move it aside with a dated name, never delete it, so it can be compared later.
- Uncommitted changes that belong to the interrupted work: commit them to the working branch as a WIP
  commit, with explicit paths, then continue. Do not `git add .`, `git add -A`, or `git commit -a`.
- A worktree with no live owner and no unique work: leave it in place and report it. Removal is a
  separate decision.

Never clean up another session's files, branches or containers without its owner's answer.

### 6. Resume from the last verified step

1. Re-verify the last step you marked done. A crash can leave a file present and wrong. Re-run its check,
   not just its existence test.
2. Continue with the first step marked partial or not started. For a partial step, finish it from
   where its evidence says it stopped; for an unstarted one, start it.
3. Re-run idempotent steps rather than guessing whether they took. A build, a test run, `git status`,
   or a formatter can be repeated safely. A send, a post or a deploy cannot: query its target first
   (for example `gh pr list --head <branch>` before opening a pull request, or the remote's branch list
   before pushing).
4. Update the todo list as each step finishes. Record completion only after checking the result.

### 7. Report what was lost and what was redone

Write the report as the last step, to the person who asked, and to the handover location if the work
has one. Use the template in `references/reconcile-and-report.md`. It must name:

- what was lost (unsaved editor buffers, in-memory state, drafts never written, uncommitted changes you
  could not recover) and how you established that;
- what was redone and why it was safe to redo it;
- what is still unverified, with the reason;
- what needs the owner's decision (worktree removal, a stale lock whose owner you could not establish,
  a stash entry of unknown origin).

## Guardrails

- A dirty tree that is not wholly yours is a stop, not a clean-up. Report it and ask.
- Do not abort an interrupted rebase, merge or cherry-pick to make the tree clean. Finishing it or
  recording its state comes first. An abort discards the progress the crash interrupted.
- Do not force-push, reset, or check out over uncommitted work to get to a known point.
- Do not run `git fsck --lost-found`: it writes into the repository. Use the read-only form
  `git fsck --unreachable --no-reflogs` to find dangling commits from an interrupted operation.
