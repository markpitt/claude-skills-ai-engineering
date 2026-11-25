---
name: omp-harness
description: Configures and operates the omp coding agent harness, covering global and project config layers, model roles and local-model routing, lsp.json language servers, TTSR rules, bash approval patterns, skills discovery, session storage and re-homing, RPC resumption and coordination between omp instances. Use when editing ~/.omp/agent/config.yml or a project .omp/config.yml, stopping a role from falling back to a hosted provider, fixing a language server that is not found, explaining why a new skill is missing, moving or resuming an omp session, or asking what the omp CLI can do. Do NOT use for writing AGENTS.md or setting up other coding agents such as Claude Code, Copilot or Codex (use ai-coding-agent-setup), or for general model selection with no omp configuration involved.
license: Apache-2.0
metadata:
  version: "1.0.0"
  tags: "omp, oh-my-pi, coding-agent, configuration, local-models, lsp, skills, sessions, rpc"
---

# oh-my-pi (omp) harness

Operate the `omp` coding agent: its configuration layers, model roles, language servers, rules,
hooks, skills and sessions. Facts here are checked against omp v18.20.2 (`omp --version`). Each
fact is marked in `references/evidence-ledger.md` as one of:

- **confirmed from files**: read from a file on the machine;
- **confirmed from help**: printed by `omp --help` or a subcommand's `--help`;
- **verify with omp --help**: not confirmed by either. Check it before relying on it.

Do not invent a flag, key or path that is not in one of those three places.

## Critical rules

1. **Config files can hold credentials.** Never print `auth*`, `*key*` or `secret*` files, and do
   not run `omp token` or `omp auth` (they print or export credentials). Redact anything before
   it goes into a transcript, an issue or a commit.
2. **Keep a hosted provider from answering silently.** Where a local model must answer, pin
   auxiliary calls with `--offline` or `models.offline`, and `--no-judge` or `models.noJudge`, then
   test the setup as in procedure 2. `--offline` is not a network firewall (help text).
3. **Never stop, restart or interrupt another agent's omp session.** New skills and settings are
   picked up by new sessions; whether a running session reloads them is **verify with omp --help**.
   Check which session owns what with `omp session lease` before touching anything.
4. **Find a session by its working directory.** Session storage is keyed by the folder path, so a
   moved folder hides its sessions. Use procedure 6, not a manual rename of the store.
5. **Check a peer's claim against git.** A message from another omp instance that names a commit,
   file or test result is a lead. Confirm it with `git -C <repo> show <sha>:<path>` or `git log`.

## Situation to reference

| Situation | Load |
|---|---|
| Which file wins, what to commit, UI changes landing in the project file | `references/config-layers.md` |
| Model roles, `models.yml`, a local model, stopping a silent hosted fallback | `references/model-roles-and-local-models.md` |
| `lsp.json`, a server binary not found, TTSR rules, hooks, bash approval patterns | `references/lsp-rules-and-hooks.md` |
| A new skill is not visible, skill settings, skill registry | `references/skills-discovery.md` |
| Where sessions live, moving a folder, pack and unpack, crash recovery | `references/sessions-and-rehoming.md` |
| Resuming in RPC mode, ACP, collab, background processes, peer coordination | `references/peers-and-rpc.md` |
| Which facts are confirmed and from where | `references/evidence-ledger.md` |

## Procedure 1: audit an omp setup read-only

1. Confirm the version and the agent directory:
   ```bash
   omp --version
   omp config path
   ```
2. List the files that exist, names only. Do not `cat` anything whose name matches `*key*`, `auth*`
   or `secret*`:
   ```bash
   ls -la "$(omp config path)"
   ls "$(omp config path)/rules" "$(omp config path)/skills" 2>/dev/null
   ```
3. Read merged settings by key, which shows the value after layering:
   ```bash
   omp config list --scope=global
   omp config list --scope=project   # run from inside the repository
   omp config get modelRoles
   ```
   Redact any value that looks like a credential before it is shown or pasted.
4. Read the project layer directly if it exists: `.omp/config.yml`, `.omp/hooks/`.
5. List the models the providers offer, to check each role's `provider/model-id` string:
   ```bash
   omp models
   omp models find <pattern>
   ```

## Procedure 2: route a role to a local model without a silent hosted fallback

1. Define the local provider in `models.yml`, using the shape in
   `references/model-roles-and-local-models.md`. Check its `id` with `omp models`.
2. Point the role at it by editing the `modelRoles` block in the file that owns the setting. Writing
   it with `omp config set modelRoles` is possible (`omp config list` shows it as a record); which
   layer that writes to is **verify with omp --help**.
3. Pin auxiliary calls to the active provider for runs that must stay local:
   ```bash
   omp --offline --no-judge -p "reply with the word ready"
   ```
   Or set `models.offline` and `models.noJudge` to `true` for the layer that should always hold.
4. Test the fallback in a throwaway profile whose local provider points at a closed port, so no
   other session is touched. `--profile NAME` isolates auth, sessions, settings and caches (help
   text). Where a profile keeps its `models.yml` is **verify with omp --help**.
   ```bash
   omp --profile fallback-test --offline -p "reply with the word ready"
   ```
   The run must fail or name the local provider. If it answers from a hosted provider, treat the
   setup as broken. Whether the main role falls back on its own is **verify with omp --help**; the
   test is the evidence, not the documentation.
5. Remove the throwaway profile once the result is recorded.

## Procedure 3: put UI model choices in the project file

1. Add this line to the repository's `.omp/config.yml`, as the header of the project config
   describes:
   ```yaml
   modelRoleStorage: project
   ```
   `omp config set` takes no scope flag in its help, so it is not the route for a project key;
   where it writes is **verify with omp --help**. Confirm from inside the repository with
   `omp config get modelRoleStorage`, which should print `project`.
2. Only `modelRoles` is written to the project file. Other `/settings` changes still go to the
   global file (stated in the project config's own header).
3. Decide whether the file is shared. A shared file is committed; a personal one is not. The
   tradeoff is in `references/config-layers.md` section 4.

## Procedure 4: fix a language server that is not found

1. Check the exact binary name, which is case-sensitive on Linux:
   ```bash
   command -v OmniSharp || echo "not on PATH"
   ```
2. Set `command` in `~/.omp/agent/lsp.json` to that exact name, with `args` if needed. Prefer a
   PATH name over an absolute path, because an absolute path into an editor's extension folder
   breaks when the extension updates.
3. Check `fileTypes` and `rootMarkers` for the project, then start a fresh session in the project.
4. If the server still does not start, run without it to separate the two faults: `--no-lsp`.

## Procedure 5: diagnose a skill that does not appear

1. Confirm the file is where discovery looks, with the frontmatter parsing as YAML: `name`,
   `description`, and the directory name matching `name`.
2. Check the skill settings for the layer in use: `omp config list --scope=global` and
   `--scope=project`, looking at `skills.*` keys. Check `skills.ignoredSkills` and
   `skills.includeSkills` first.
3. Confirm the session was started after the file was added. Whether an in-session `/restart`
   exists is **verify with omp --help** (it is not in the CLI help).
4. Do not restart another agent's session to make the skill appear. Start a new session for the
   work instead.

## Procedure 6: find, move or resume a session

1. List what is resumable from the folder you are in with `omp --resume` (no argument opens a
   picker) or `omp --continue` for the most recent session.
2. After a folder has moved, resume the session by its file path, which the help accepts:
   ```bash
   omp --resume /path/to/session.jsonl --cwd /new/path/to/project
   ```
3. To hand a session to another machine, pack it and unpack it there with the new folder:
   ```bash
   omp session pack /path/to/session.jsonl /tmp/session.tar
   omp session unpack /tmp/session.tar --cwd /new/path/to/project
   ```
4. Flag the source copy as moved so that resuming it later forks rather than diverges silently:
   `omp session moved /path/to/session.jsonl --to OTHER-MACHINE`.
5. For a crash, use `omp --restore <id or path>`, which also resumes subagents that were running.

## Procedure 7: resume a session in RPC mode

```bash
omp --resume SESSION-ID-OR-PREFIX --mode rpc
```

`--mode rpc` and `--resume` are confirmed from help. The message framing on stdin and stdout is
**verify with omp --help** and the omp documentation; do not write a client against a guessed
format. Add `--no-ui` to run extensions headless. Before resuming a session that another process may
own, run `omp session lease --json -- SESSION-ID` to see which session a running omp holds.

## Validation checklist

- Every key, flag and path in a change is in the evidence ledger, or is marked verify.
- No credential appears in the diff, the transcript or a commit. Files matching `*key*`, `auth*`
  or `secret*` were not printed.
- A local-only run was tested with a deliberately wrong endpoint in a throwaway profile.
- The change was made in the file that owns the layer, and `omp config get KEY` shows the merged
  value you expected.
- No other session was stopped, restarted or re-homed without its owner's decision.

## Scope

This skill covers the omp CLI, its files in `~/.omp/agent/` and a project's `.omp/` folder. It does
not cover omp's provider accounts, billing, or building extensions and plugins.
