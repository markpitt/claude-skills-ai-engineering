# Agents that do not start after a boot or a cutover

The symptom is always the same: after a reboot, or after the agents' folders were moved, some or all
agents are missing from tmux, or their panes sit at a shell prompt, or a pane shows a `bwrap` error and
exits. The causes are few. Check them in this order, because each one hides the next: nothing after the
tmux restore runs if the restore itself failed.

Read-only checks first. Starting or restarting an agent is the user's call where agents are shared or
long-running; say what you found and which command would fix it.

## Contents

- [1. Did the tmux restore run at all?](#1-did-the-tmux-restore-run-at-all)
- [2. Did `start-agents.sh` look in the right folder?](#2-did-start-agentssh-look-in-the-right-folder)
- [3. Was the agent skipped on purpose?](#3-was-the-agent-skipped-on-purpose)
- [4. Does the profile point at the old path?](#4-does-the-profile-point-at-the-old-path)
- [5. Is a bind-mount source missing?](#5-is-a-bind-mount-source-missing)
- [6. Did it start, then stop?](#6-did-it-start-then-stop)
- [After a fix](#after-a-fix)

## 1. Did the tmux restore run at all?

```bash
systemctl --user status tmux-session.service
journalctl --user -u tmux-session -b --no-pager | tail -40
```

- **The unit failed.** `start-agents.sh` is normally an `ExecStartPost=` of the restore unit, and systemd
  does not run `ExecStartPost=` when the start fails. So one restore failure means no agent starts, and
  nothing in the agents' own logs says why.
- **`width invalid` or a layout error.** Newer tmux (3.8 and later) writes window layouts in a format
  older restore scripts cannot read back, so the restore stops at the first window. Update tmux-persist to
  a version that handles the new format, then re-run the restore or `start-agents.sh`.
- **`no space for new pane`.** Too many agents for one `agents` window at the terminal's size. Use
  `--layout windows` (or `START_AGENTS_LAYOUT=windows`) so each agent has its own window.
- **The unit is fine but no `ExecStartPost=` line ran.** Check the drop-in is installed:
  `systemctl --user cat tmux-session.service` should show the `start-agents.sh` line.

## 2. Did `start-agents.sh` look in the right folder?

```bash
start-agents.sh --dry-run
```

The dry run lists each agent it would start or skip, and why. An empty list means it found no agent
folder, which is a path fault, not a healthy state.

- **Shared repo with a `hosts/map`.** The agents live in `~/sandboxes/hosts/<host>/`, and `<host>` comes
  from the map entry for `uname -n`. An unlisted hostname is an error. After a rename or a new machine,
  add the map line.
- **An older copy of the script.** Versions before the host map only scanned `~/sandboxes/*/`. After a
  cutover to the per-host layout, an old installed copy beside the runner finds nothing. Compare the
  installed copy with the skill's `scripts/start-agents.sh` and reinstall with `new-agent.sh` or a copy.
- **A stale environment.** The drop-in may set `SANDBOXES` or `TMUX_SESSION_NO_AUTOSTART_DIR` to the old
  folder. Read both from `systemctl --user cat tmux-session.service`.

## 3. Was the agent skipped on purpose?

- A `.no-autostart` file in the agent's folder skips it at boot. An explicit
  `start-agents.sh <name>` overrides it.
- Its group starts on request: a `<group> no ...` line in the `groups` file. `start-agents.sh --status`
  shows each agent's group and when it starts; `start-agents.sh --group <group>` starts it.
- The memory gate deferred it: the drop-in's `START_AGENTS_GATE` failed for `START_AGENTS_GATE_WAIT_S`.
  The journal of the restore unit has `deferred <name>: <reason>`. Start it later with `start-agents.sh <name>`.
- The launcher refused: `<name>-agent: refused. Start it with start-agents.sh`. Something other than
  `start-agents.sh` ran it, such as an old tmux-persist allowlist that still lists `<name>-agent`, or a
  hand-written fallback. Remove that route; `start-agents.sh` is the one way an agent starts.
- "Running" means a `<name>-agent` launcher process exists anywhere, so `start-agents.sh` will not start
  a second copy of an agent running outside tmux. Look for it with `pgrep -af '<name>-agent'`
  before assuming it is missing.

## 4. Does the profile point at the old path?

After the agents' folders move (for example from `~/sandboxes/<name>` to
`~/sandboxes/hosts/<host>/<name>`), three things can still name the old place:

- the **profile** (`ROOT`, `AGENT_HOME`, `EXTRA_RO`, `EXTRA_RW` lines);
- the **launcher** `~/.local/bin/<name>-agent`, which names its profile by path;
- the agent's **config** (`CLAUDE_CONFIG_DIR` and any absolute paths in its settings or hooks).

```bash
grep -n -- "$HOME/sandboxes/" ~/.local/bin/*-agent ~/sandboxes/hosts/*/*/profile
```

Any line naming the old layout is the fault. Fix the profile and launcher together, then restart only
that agent. A symlink from the old path to the new one hides the fault and is easy to forget; prefer
fixing the paths.

## 5. Is a bind-mount source missing?

`sandbox.sh` names a missing bind source and stops, instead of the bare `bwrap` error:

```
sandbox: bind source '<path>' does not exist; create it first
```

- **After a path move in a shared tree** (for example a skills folder moved into group folders), an
  `EXTRA_RO` entry still names the old location. Update the profile to the new path.
- **A spool or socket a host service creates** (an `EXTRA_RW` spool, a gateway socket) is missing
  because that service did not start, or starts after the agents. Check the service first, then order
  it before the tmux restore (`After=` and `Wants=` on the restore unit).
- An older `sandbox.sh` without the check shows only `bwrap: Can't find source path`. The fix is the
  same.

## 6. Did it start, then stop?

- **Signed out.** The agent's credentials expired or were never written into its config directory. The
  pane shows a login prompt or exits. Log in interactively (`<name>-sandbox shell`, then the agent's own
  login), never by copying the host's credentials in.
- **Proxy mode with no proxy.** With `NET=proxy` the agent needs the allowlist proxy's socket. If the
  proxy unit is down, the agent starts but every request fails. See `proxy.md`.
- **The agent binary moved.** The sandbox binds only the agent's install directory. A runtime upgrade that
  changed the path leaves `command not found` inside. Re-run the launcher install.

## After a fix

- Start only what is missing: `start-agents.sh` (all gaps) or `start-agents.sh <name>`.
- Restart an agent only after a profile or hook change, with `restart-agents.sh <name>`; hooks load at
  start. Never restart the pane you are running in.
- Re-run `start-agents.sh --dry-run` and confirm the list is empty of starts, and that each skip has the
  reason you expect.
- Record the cause and fix wherever the user keeps an ops log.
