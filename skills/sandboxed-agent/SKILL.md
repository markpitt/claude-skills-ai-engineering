---
name: sandboxed-agent
description: Create a sandboxed coding agent for one folder, using a bubblewrap sandbox profile inferred from the folder (secrets and state hidden, least privilege, network none by default), launchers on PATH, an env template for its credentials, and a curated, secret-free set of notes harvested from the host's Claude history so the agent can orient itself. Use when asked to sandbox an agent to a directory, give an agent access to only one project, set up a restricted agent for a service folder, seed a new agent's memory from existing sessions, or find out why sandboxed agents did not start after a reboot or after their folders moved. Do NOT use for general container isolation, CI sandboxes, or running untrusted binaries.
license: Apache-2.0
metadata:
  version: "1.3.0"
---

# Sandboxed agent

Give an agent one folder and nothing else of the machine that matters, then give it enough
knowledge to be useful on day one.

```
sandboxed-agent <folder> [description of how to configure it]
```

With no description, infer the configuration from the folder and ask about whatever the folder
cannot tell you.

## Where things live

Everything for an agent is under `~/sandboxes/<name>/` (override with `SANDBOX_BASE`): `profile`,
`env` (chmod 600) and `home/` (its Claude config directory, seen inside the sandbox as
`~/.<name>-agent`). The shared runner is `~/sandboxes/runner/sandbox.sh`. Launchers go in
`~/.local/bin`. Keep the versioned source profile in the machine's own repo; the copy here is
installed from it.

Run the skill's own scripts with `bash` (or `python3` for the `.py` ones), as the examples below do.
A copy taken from the public repository has no executable bits. The copies `new-agent.sh` and
`install-proxy.sh` install are made executable, so the installed launchers and runner are run directly.

## What the sandbox is

`bash scripts/sandbox.sh <profile> run|shell|show|test` wraps `bwrap`:

- No root, no Docker socket, a tmpfs home. Only the agent's own config directory is writable there.
- The folder is mounted read-only (`ROOT_MODE=ro`, changes go through an API) or read-write.
- The agent starts in `ROOT`, or in `WORKDIR` when set (a directory under `ROOT`, such as one checkout of several, so
  Claude.ai can tie the session to a GitHub repository). Claude keys transcripts and memory by the working directory,
  so when `WORKDIR` changes `scripts/carry-project.sh` (run by `run`, installed beside the runner) moves the agent's
  project folder to the new key. It never overwrites an existing folder, and a failed move stops the agent starting.
- Secrets and state are blanked: directories become empty, files become empty.
- `NET=none` (default), `NET=proxy` (a unix-socket bridge to a host-side allowlisting proxy at
  `PROXY_ADDR`; the sandbox has no network of its own), or `NET=host` (shared; bwrap cannot filter it).
- A seccomp filter covers what the namespaces do not: `AF_VSOCK` sockets fail (vsock is not
  network-namespaced before Linux 6.18, so without it `NET=none` still reaches a VM host such as
  ChromeOS under Crostini or Windows under WSL2), io_uring fails with `ENOSYS` (it can open sockets
  without `socket()`), and a foreign ABI (i386, x32) is killed. x86_64 and aarch64 only; on any
  other architecture the runner refuses to start.
- Credentials come from `~/.config/<name>-agent/env` (chmod 600) as environment variables, never
  from the profile or the command line.
- Host services the agent may use, with no network: `EXTRA_RO=("src:dst")` binds a path read-only (a directory that holds a
  unix socket works: `connect()` needs no write access, and a restarted service's new socket is still reachable through a
  directory bind, not through a file bind). `EXTRA_RW=("src:dst")` binds a path writable: a spool the host drains. The agent
  cannot remove or rename the mount point, so it cannot point the host's reader at another directory. What it can still
  create inside is anything: a symlink to any path (it resolves on the host, where the agent could not read the target), a
  FIFO (a reader that `open()`s it blocks forever), a subdirectory, and files of any size with no quota. So the host reader
  must check the type before it reads: open with `O_NOFOLLOW|O_NONBLOCK`, accept only `S_ISREG`, cap the size and the number
  of files, and refuse a symlinked spool directory. Create the source directory before the agent starts (a missing source
  stops bwrap), and keep the destination out of `~` (use `/run/...`): a mount below `~/.claude` or `~/.config` makes the
  self-test report a leak of the real home.

Least privilege first: read-only, network none, nothing passed in. Widen only when the user says so.

## When the agent must reach Anthropic (`NET=proxy`)

The agent is a Claude client, so `NET=none` cannot run it. Use `NET=proxy` and, once per machine,
`scripts/install-proxy.sh` (an allowlisting CONNECT proxy as a systemd user service). Start the allowlist
with `api.anthropic.com` and `platform.claude.com` only, and add a host only from an observed denial.
Do not "drop instead of deny": a refused connection is an error in the UI either way. Stop the client
making the connections instead; `new-agent.sh` runs `scripts/client-env.sh`, which switches off the
account's connectors and its synced plugins' MCP servers, telemetry and auto-update. Login is interactive (`<name>-sandbox shell`, `/login`)
unless a scoped token is passed in. An agent that must read one local endpoint gets one `GET http://host:port/path` line, ideally in its own
proxy instance (`PROXY_INSTANCE`, `PROXY_PORT`). Host table, reasons and the other traps are in
[references/proxy.md](references/proxy.md). Read it before diagnosing a UI error or a denied host.

## Procedure

1. **Inspect.** Run `bash scripts/inspect.sh <folder>`. It prints the kind of folder, candidate paths
   to blank (secret files, state, databases, backups), large files, and the questions the contents
   cannot answer. It writes nothing.
2. **Ask, do not guess.** For every `ASK:` line and every ambiguous path, use the question tool
   with a short list of concrete options (a series of questions is fine). Always settle:
   read-only or read-write; network none, proxy or host; which credentials to pass (names only).
   Treat anything unclassified as secret and blank it; the user can loosen that.
   If the user gave a description, apply it, and say which choices it changed.
3. **Write the profile** from `references/profile.example` and show it to the user before
   installing anything.
4. **Install.** `bash scripts/new-agent.sh <name> <profile> [launch command...]` puts
   `<name>-agent` (starts `claude remote-control --name <name>` inside the sandbox) and
   `<name>-sandbox` (`shell|test|show|run`) on the PATH, writes the env template with every value
   commented out, adds the launcher to the tmux-persist allowlist when that is set up, and runs
   `scripts/client-env.sh` and `scripts/protect-config.sh` on the agent's config directory (below).
   It also makes the agent's project memory folder, `projects/<key>/memory/` in its config directory, empty, so the
   agent writes its live store there from its first start. The key is the working directory's real path (`WORKDIR`,
   else `ROOT`) with every character but `[A-Za-z0-9]` as `-`, the way Claude and `carry-project.sh` key it. It is
   not made when the agent last ran in another folder (`carry-project.sh` moves that one on the next start) or when
   the folder is not on this host.
5. **Test.** `<name>-sandbox test` must pass before the agent is started. It proves the folder is
   readable, writable only if promised, every blank path is empty, no Docker socket, no real home,
   no root, and the network mode holds.
   A `ROOT` that is the home folder itself (an agent working across every repository in it) mounts
   the real home on purpose: the "no real home" test is skipped with a note, so blank the secrets
   and add `CHECKS` that prove them hidden. The read-only bind of that `ROOT` also lands on top of
   the agent's config mount, so bind `AGENT_HOME` again through `EXTRA_RW` and create the empty
   mount point `~/.<name>-agent` on the host first.
6. **Harvest** (below), then the user reviews the staged notes, then deliver.
7. **Record** the change wherever the user keeps an ops log, with the undo steps
   (delete the launchers, the profile and the agent config directory).

## Starting and restarting agents (tmux)

`scripts/start-agents.sh`, `scripts/stop-agents.sh` and `scripts/restart-agents.sh` (also installed beside the runner by `new-agent.sh`) manage
the agents of a machine in tmux. An agent is a folder `~/sandboxes/<name>/` with a `profile` and an installed
launcher `~/.local/bin/<name>-agent`. When `~/sandboxes` is a shared repo with a `hosts/map`, `start-agents.sh` looks in
`~/sandboxes/hosts/<host>/` instead, `<host>` being what the map lists against `uname -n`; an unlisted hostname is an error.

**`start-agents.sh` is the one way an agent starts.** The launcher `new-agent.sh` writes refuses to run unless `start-agents.sh`
handed it a one-time token (in its environment, matching a file in `$XDG_RUNTIME_DIR/start-agents/` that the launcher deletes). It is a
guard against other start routes and habit, not a security boundary. Do not add launchers to the tmux-persist allowlist
(`TMUX_SESSION_PROGRAMS`), do not type them by hand, and do not write other start scripts: run `start-agents.sh <name>`.
Headless one-off runs (`<name>-sandbox run -- claude -p ...`) are not agent starts and are unaffected.

- `start-agents.sh [names] [--group NAME] [--dry-run] [--status] [--session NAME]` starts every agent that is not running, one pane each in the
  `agents` window of the session (created when missing), or one window per agent with `--layout windows`. An agent whose folder holds a `.no-autostart` file is
  skipped; an explicit name overrides it. "Running" means a `<name>-agent` launcher process exists anywhere, so it never
  starts a second copy. `--status` prints each agent's group, when it starts and whether it runs.
- **Groups:** an optional file `groups` in the agents' folder, one line a group, `<group> <boot> <agent>...`. `<boot>` is a
  number (the group starts at boot, lowest first) or `no` (only on request: `--group NAME` or by name). Ungrouped agents start
  after the groups, unless they have `.no-autostart`. An agent in two groups, or a malformed line, is an error.
- **Pacing:** one at a time; `START_AGENTS_STAGGER_S` (default 5) seconds between starts. `START_AGENTS_GATE` names an executable
  run before every start (a memory check, for instance): while it fails the start waits (`START_AGENTS_GATE_POLL_S`, 15), and after
  `START_AGENTS_GATE_WAIT_S` (600) the rest are reported "deferred" with the gate's last line, exit 3.
- `stop-agents.sh <names> | --group NAME | --pane ID [--dry-run] [--session NAME]` stops agents: Ctrl-C, then SIGTERM to the launcher
  tree after 20 s, never SIGKILL. An agent that will not stop is reported and left alone. With nothing named it refuses.
- `restart-agents.sh [names] [--dry-run] [--session NAME]` stops each agent pane of the session with `stop-agents.sh --pane` and starts it
  again in the same pane with `start-agents.sh --pane`. Never the pane it runs in. Restart after a profile or hook change: hooks load at start.
- Boot: the tmux-persist restore brings back the layout only (no `*-agent` in `TMUX_SESSION_PROGRAMS`); a systemd drop-in
  `ExecStartPost=` on the restore unit then runs `start-agents.sh`, which starts the boot groups in order.
- Tests: `scripts/test-start-agents.sh` and `scripts/test-restart-agents.sh` run on an isolated tmux server with fake
  launchers (`TMUX_SOCKET`, `SANDBOXES`, `BIN`, `INT_WAIT`, `TERM_WAIT`, `START_AGENTS_SETTLE_S` are the test hooks).
- Layout: `--layout panes` (default, or `START_AGENTS_LAYOUT=panes`) puts each agent in a pane of one `agents` window; `--layout windows` gives each agent its own window named after it (`claude-x` for the launcher `claude-x-agent`), reusing an existing idle window of that name and leaving a busy one alone. `restart-agents.sh` works on any layout, because it finds the agent panes of the session. A session-per-agent layout is not supported.
- **Agents missing after a boot or a cutover:** work through
  [references/troubleshooting-start.md](references/troubleshooting-start.md) in order: the tmux restore unit, the
  folder `start-agents.sh` scanned, `.no-autostart`, profiles and launchers naming old paths, missing bind-mount
  sources, then agents that started and stopped.

## Keep the user in control of the agent's own config

The agent's config directory must be writable, so it could loosen its own limits by editing
settings (permissions, hooks), instructions, MCP servers, skills, plugins or tools.
`bash scripts/protect-config.sh <config-dir>` merges, without removing anything:

- ask rules on Edit (which covers Write and every other file-editing tool; Claude Code ignores `Write` rules) for the config directory's top-level files (`*.*`), `skills/`, `plugins/`, `tools/`, `agents/`, `commands/`, `hooks/`, `rules/`, `output-styles/`.
  Rules match like gitignore patterns, so a bare `*` would also match everything under `projects/` and ask on every memory write (ask rules beat allow rules); `*.*` leaves `projects/**/memory` free to write.
- an inline PreToolUse hook on Bash that asks when the command text names the config. It reads
  `.tool_input.command` with `jq` first; grepping all of stdin would match `transcript_path` and
  prompt on every command. Paths under `state/`, `backups/`, any name in `STATE_DIRS=(...)` in the profile (or `STATE_DIRS="a b"` in the
  environment of a direct `protect-config.sh` run) and `projects/*/memory/` are blanked first, so a log line that cites them does not
  prompt. A command that also has a `..` component, `cd`, `ln` or `symlink` is never blanked. Those
  directories are blind spots by design: a script that builds the path at run time is not seen. `jq` and
  `sed` must exist inside the sandbox; a missing `sed` makes the hook ask.

`scripts/client-env.sh` (run by `new-agent.sh`) also shuts the messaging door. An agent on Remote Control is
a message target for every session on the account, and a peer message is a prompt-injection path into a
session that may hold a deployed file. It sets `crossSessionInbound` to `refuse` (messages from other
sessions are dropped, and the sender is told the session "can't receive cross-session messages") and
denies the `SendMessage` and `ListAgents` tools. Remote Control typing by the user is not a message from
another session.

- **The default makes the agent one-way.** With `SendMessage` and `ListAgents` denied it can neither answer
  a health check nor report back, and a coordinating session gets "can't receive" for every instruction.
  An agent you coordinate by message must be installed with `ALLOW_MESSAGING=1` in its profile (or
  `SANDBOX_ALLOW_MESSAGING=1` for one run). Otherwise it is Remote Control typing only.
- **`ALLOW_MESSAGING=1` is reversible.** It removes the `refuse` and the two deny entries an earlier run added,
  so re-running the installer recovers an agent. A `refuse` or either deny entry the user wrote
  themselves looks the same and is removed too; a `hold` and the user's other rules stay.
- **Which value an allowing agent should use.** Leaving it alone gives the client default, which delivers
  from a prompting peer. For an agent that can edit something deployed, set `crossSessionInbound` to `hold`
  in its settings yourself (the user approves each message in the session's own dialog): it keeps the
  operator pattern while no peer message reaches the agent unattended.
- **Precedence.** A user who put `SendMessage` in `permissions.allow` should know a deny rule wins over an
  allow rule; the block does not override a value the user already set for `crossSessionInbound`.

`references/proxy.md` has the details and what was and was not tested.

The agent's `tools/bin` is put first on PATH by the sandbox, so routine tool use never names the
config directory and never trips the hook. Restart the agent session after the first run: hooks load
at start (ask rules apply at once). Tell the user and the agent that delivered rules, tools and notes
are a reviewed writable copy, not a mount; only the user's own messages approve config changes.

## Harvest knowledge from the host

Goal: a short instruction file and a few topic notes for the agent, built from what the host's
Claude history already knows about this folder or its service.

1. **Find sources** (read-only): per-project memory directories, session transcripts that mention
   the folder's path or the service's name (`grep -l -i`), and related skills. Do not read whole
   transcripts in the main session; they are large and can hold secrets.
2. **Run the harvest workflow.** Pass `references/harvest.workflow.js` to the Workflow tool with
   `args = {files, topic, keywords}`. Per file: extract (Haiku), redact (Haiku), then a Sonnet
   judge that checks every note against its source and keeps, fixes or drops it. Unsupported or
   host-only notes are dropped, not softened.
3. **Consolidate** into a staging directory: merge duplicates, drop incident narration and anything
   the agent cannot act on from inside the sandbox. Aim for 15 to 25 KB.
   Layout: an instruction file (short standing rules: who approves changes, no secrets in output, how
   changes are made and logged) and `memory/` (an index plus one file per topic).
4. **Scan** the staging directory for secret patterns (JWTs, long tokens, `password=`, private
   key headers, credentialed URLs). Show the result.
5. **User review gate.** The user reads the staged set. Nothing is delivered before that.
6. **Deliver** by copying into the agent's own config directory, not by mounting host files:
   the same instruction file in `~/.<name>-agent/`, and the notes into the memory folder `new-agent.sh` made,
   `~/.<name>-agent/projects/<key>/memory/`. Copy straight in: no seed copy is kept beside it, so a host that tracks the
   live store has one copy of each note. The agent owns those files afterwards and can extend them.
   Never mount the host's projects directory or transcripts into a sandbox.

## Limits to state to the user

- `NET=host` is not isolation. `NET=proxy` is only as strict as the proxy's allowlist.
- The seccomp filter blocks vsock and io_uring only; other host-reaching families that a kernel does not namespace would need adding there.
- An API token passed in can be as powerful as the account it belongs to; use a scoped one.
- A read-only Docker proxy still lets the agent run `inspect` and `logs`, which can show secrets.
- The inferred blank list is a heuristic; the user's review of it is part of the safety.
- The config hook matches text, so a deliberately disguised path can pass. It keeps routine changes
  visible; only a read-only mount makes them impossible.
