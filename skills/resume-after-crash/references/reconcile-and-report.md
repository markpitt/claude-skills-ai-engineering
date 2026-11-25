# Reconciling in-flight steps, resuming, and reporting

## Contents

- Reading the plan and the handover
- Evidence for each status
- Reconciling a step
- Which steps may be repeated
- Checking an external effect before repeating it
- Resuming
- The report template
- Worked example

## Reading the plan and the handover

Two documents describe what was happening. Read both before deciding anything:

1. **The plan or todo list** the work named. For each item, its last recorded status: done, in flight,
   waiting or blocked. For waiting items, the record should say who is awaited and since when.
2. **The newest handover note**: the last thing the interrupted agent wrote. Find it by modification time
   in the handover location, then read it in full.

```sh
ls -t "$HANDOVER_DIR" 2>/dev/null | head -n 5; echo "ls exit $?"   # the newest few, by time
```

- A plan item marked done with no evidence in the repository is a claim to check, not a fact.
- A handover that says "tests pass" is a claim about a run. Check that the run's output exists, that it
  is from after the last change to the files it covered, and that its exit status was zero.
- If the plan and the handover disagree, the repository decides. Report the disagreement.

## Evidence for each status

Use the strongest evidence the step allows. A status needs at least one line of evidence, with its time.

| Status | What counts as evidence |
|---|---|
| done | The artefact exists and matches the step's acceptance check, re-run now. A commit on the branch, with the SHA. A file with the expected content. A check that exited 0 and ran after the last change to what it checks. A remote ref that shows the SHA (`git ls-remote`). |
| partial | Some of the artefacts exist, or a file stops mid-way, or a commit exists locally with no remote copy, or an operation marker is present. |
| not started | No artefact. No commit. No file. The plan item's record shows no start. |
| unknown | The evidence is missing: the journal is volatile, a file cannot be read, interop is off. Treat as partial and re-verify before going on. |

Evidence that does not count:
- a sentence in the handover or the plan without a check behind it;
- a file's presence alone, when the step's acceptance is about its content;
- a test run whose output is not kept, or whose log is older than the most recent edit to what it tested;
- the agent's memory of having done something. Memory is not in the repository.

To compare a test log with the files it tested, compare modification times:

```sh
find "$REPO" -path "$REPO/.git" -prune -o -type f -newer "$TEST_LOG" -print 2>/dev/null; echo "find exit $?"
```

Any output means a file changed after the test log was written. That test run does not cover the
current tree and must be run again.

## Reconciling a step

For each step that was in flight, in the order of the plan:

1. Write its status and its evidence, with the time and the command or path that showed it.
2. If done: re-run its acceptance check now, not later. A check that passed before a crash may fail after
   it, because the crash may have left a file wrong.
3. If partial: decide the remaining work from the evidence. Finish the part the evidence shows is missing,
   and nothing more. Do not redo the parts that are already correct, unless they fail their check.
4. If not started: start it from the beginning of its own procedure.
5. If unknown: verify as if partial. Record that the status was not established.

Do not reconcile a step by re-doing it blindly. Check first, then act on what the check found.

## Which steps may be repeated

Repeat a step freely when it:
- only reads (status, listing, a parse, a search);
- writes only to its own output, which the next run overwrites (a build, a formatter run in check mode,
  a test run that writes a fresh log);
- is a fast-forward or no-op at the target (a `git push` of a commit already on the remote is a no-op, but
  check with `ls-remote` first, because the remote may hold something else).

Do not repeat a step blindly when it:
- sends, posts or publishes (a message, a comment, a release, an email);
- deploys, migrates, or changes a shared service;
- spends money or creates a paid resource;
- appends to a file, which duplicates the entry on a second run;
- creates an external record with no natural key (a ticket, a pull request, a calendar event).

For these, query the target first and act on what it says.

## Checking an external effect before repeating it

Check the target, then decide:

```sh
gh pr list --head "$BRANCH" --state all --json number,state,url     # is there already a pull request?
git -C "$REPO" ls-remote origin "refs/heads/$BRANCH"                # did the push land?
```

- A pull request that already exists for the branch is the outcome of the step. Do not open a second one.
- A commit on the remote with the expected SHA means the push landed. A different SHA on the remote means
  someone else has pushed: stop and report, do not force.
- For a message or a comment, search the thread or the sent items for the text before sending again. If
  it is there, the send landed.
- If the target cannot be queried, the step is unknown. Ask the owner before repeating an external effect.

## Resuming

1. Re-verify the last step marked done.
2. Start at the first step that is partial, unknown or not started.
3. After each step, record its new status and evidence in the plan or todo list, in the same place as the
   others, so the next reader sees it.
4. If a step cannot be completed from the evidence, mark it blocked with the reason and the person who can
   unblock it. Do not carry on past a blocked step that later steps depend on.
5. When something is found that the plan did not expect (a dirty tree you did not write, a stash of
   unknown origin, a process holding a lock), stop that thread, record it, and ask. Do not resolve it by
   assumption.

## The report template

Write the report to the person who asked, and to the work's handover location if it has one. Use this
structure. Keep each section short; name the evidence, not the feeling.

```text
Resume report: <work name>, <date>

Cause: established | probable | not established. Evidence: <journal line or event, with time>.
Host state: boot time <time>; disk <guest %, host %, or "not checked: <reason>">.

Inventory (root, branch, HEAD, changes, stashes, unpushed, operations, locks, half-written):
  <one row per repository>

Steps:
  <step>: done | partial | not started | unknown. Evidence: <command and result, time>.

Lost:
  <what was lost, how that was established; "nothing established as lost" if none>

Redone:
  <step>: <why it was safe to redo>

Unverified:
  <step or file>: <why it is not verified yet>

Needs a decision:
  <item>: <options and the recommendation, one sentence each>
```

Lost work usually means one of: unsaved editor buffers, in-memory state of a running process, a draft that
was never written to disk, uncommitted changes the crash destroyed. Say which of these you could confirm
from the evidence, and which you are inferring.

## Worked example

Suppose the handover says a migration was written and its tests run. The inventory shows a branch one commit
ahead of its upstream, a `.lock` file older than the crash, and no git process running.

1. The commit's SHA is on the branch and not on the remote: the work is committed but not published.
2. The lock is older than the crash and `pgrep -l -x git` exits 1. Record its path and age, then remove
   that one file.
3. The handover says tests pass. The test log is older than two files in the migration directory, so the
   run does not cover the current tree. The step is partial: rerun the tests.
4. The tests pass on the rerun. The step is done. The push is not done: check `ls-remote` shows no
   such SHA, then push the branch as a fast-forward and check `ls-remote` again.
5. The report records the lock removal with its path and age, the rerun, and the push with its SHA.
