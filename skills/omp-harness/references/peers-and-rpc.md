# RPC resumption, ACP, collab and coordinating omp instances

Contents

1. What the CLI offers
2. Resuming in RPC mode
3. ACP over stdio
4. Collab: sharing a live session
5. Background processes
6. Coordinating between instances
7. Verifying a peer's claim

## 1. What the CLI offers

Confirmed from `omp --help`:

| Facility | Command or flag | Purpose |
|---|---|---|
| Output modes | `--mode text`, `json`, `rpc`, `rpc-ui` | How a run reports its events |
| Headless extensions | `--no-ui` with `--mode rpc` or `rpc-ui` | Extensions run without a UI |
| ACP server | `omp acp` | Runs omp as an Agent Client Protocol server over stdio |
| Collab | `omp collab list`, `omp collab link`, `omp join LINK` | Share a live session with a link, view-only or control |
| Background processes | `omp ps` | List, inspect, log, stop and restart daemon-supervised processes |
| Ownership | `omp session lease` | Show which sessions a running omp owns, without taking them |

The CLI help does **not** list a command for one omp instance to send a message to another. Do not
assume one exists. Anything beyond the table above is **verify with omp --help** or the omp
documentation.

## 2. Resuming in RPC mode

```bash
omp --resume SESSION-ID-OR-PREFIX --mode rpc
```

Both flags are confirmed from help. Before starting it against a session that another process may
hold, check ownership:

```bash
omp session lease --json -- SESSION-ID
```

The `--` keeps an id that starts with `-` from being read as an option (help text). The
message format on stdin and stdout for RPC mode is not in the CLI help. Read the omp documentation
for the protocol, and write a client against that, not against a guessed shape. `rpc-ui` adds a
tool UI to the same protocol (confirmed from help); whether it changes the framing is **verify with
omp --help**.

Use `--no-ui` when the extensions should run headless. Use `--no-extensions` to disable discovery
and keep only explicit `-e` paths.

## 3. ACP over stdio

```bash
omp acp
```

Confirmed from help: runs omp as an Agent Client Protocol server over stdio. The client launches it as
a child process and speaks ACP on its standard streams. Which editors or clients speak ACP is not
in the help and is **verify with omp --help**.

## 4. Collab: sharing a live session

```bash
omp collab list             # active local hosts, without URLs
omp collab list --json
omp collab link INSTANCE-ID-OR-PID          # control link
omp collab link INSTANCE-ID-OR-PID --view   # view-only link
omp join "LINK"             # join a shared session from a link
```

Confirmed from help. `list` shows metadata without URLs. `link` retrieves a control link, and
`--view` asks for a view-only one. Share a control link only with someone who should be able to
act in the session, and prefer `--view` otherwise.

## 5. Background processes

```bash
omp ps                      # list processes for this project
omp ps --all                # include other projects and exited global services
omp ps info NAME
omp ps logs NAME --follow
omp ps stop NAME
omp ps restart NAME
```

Confirmed from help. `stop` takes a `--timeout` grace period before a hard kill; how `kill` differs
from `stop` is **verify with omp ps --help**. Use `--dir` to
target another project directory. Stopping a background process that belongs to another agent's
work is an action that needs that owner's decision. Read `omp ps info` and `omp ps logs` first.

## 6. Coordinating between instances

With no message channel in the CLI, coordinate through things that are checkable:

- **Ownership of sessions**: `omp session lease --json -- IDS` says which running omp holds a session.
  Do not resume a session it holds.
- **The repository**: branches, commits and pull requests are the shared record. Hand work over by
  committing to a named branch and saying which commit, not by describing the change.
- **Live sharing**: `omp collab` when two people or two instances must watch the same session.
- **Background work**: `omp ps` shows what a project's processes are doing, without touching the
  session that started them.

Do not interrupt, stop or restart another instance to get its attention. Send the question through
whatever channel the team uses, and wait for the answer.

## 7. Verifying a peer's claim

A peer that says a commit exists, a test passed or a file changed is giving a lead. Check it:

```bash
git -C REPO log --oneline -n 5
git -C REPO show COMMIT:path/to/file
git -C REPO status --short
```

Read the result from the repository, not from the peer's message. Record what the repository showed,
and the command used, in the reply. A claim that the repository does not show is reported as not
found, not as false, unless the check was complete.
