# Sessions: where they live, moving a folder, handing off

Contents

1. Where sessions are stored
2. Finding a session
3. Why a moved folder hides its sessions
4. Re-homing options
5. Pack, unpack and the moved marker
6. Crash recovery and export
7. What not to touch

## 1. Where sessions are stored

Sessions are JSON Lines files. The default root is `~/.omp/agent/sessions/` (confirmed from files
and from the `--restore` example in help). Beneath it, each folder is named after a working
directory. The names observed on the machine checked start with `-` and carry the path with the
slashes turned into hyphens, for example a folder for `/src/app` appears as `-src-app`
(confirmed from files; the exact encoding rule is **verify with omp --help** before scripting
against it).

A session file is `<id>.jsonl` inside that folder. Each line is one event.

Override the root for one run with `--session-dir DIR` (confirmed from help). Use this for an
isolated test, and keep the directory outside the repository.

The agent directory also holds `agent.db`, `history.db` and `models.db` (confirmed from files).
Do not open or edit those databases to repair a session. Use the commands below.

## 2. Finding a session

```bash
omp --resume                 # opens a picker of sessions
omp --resume ID-PREFIX       # by an id prefix
omp --resume /path/to/file.jsonl   # by path
omp --continue               # most recent session in this folder
```

Confirmed from help. `--resume` accepts an id prefix, a path, or nothing for the picker.

To list the session files on disk, use `ls` on the folder that matches the working directory, using
the encoding from section 1. Do not rely on a glob that could match another project's folder.

## 3. Why a moved folder hides its sessions

Session folders are named after the working directory (section 1). After a project moves from one
path to another, the folder for the new path does not hold the old sessions, so `omp --continue`
and the picker there will not show them. The old sessions are still in the old folder. Nothing is
lost; they sit under the old name. Confirm this on the machine with `omp --resume` in the new folder
before acting on it.

## 4. Re-homing options

Choose the least invasive option that meets the need:

1. **Resume by path, and point it at the new folder.** The fastest, with no file moves:
   ```bash
   omp --resume /path/to/old-folder-session.jsonl --cwd /new/path/to/project
   ```
   `--cwd` overrides the directory the session starts in (confirmed from help).

2. **Move the session file into the folder for the new path.** Only if you want the picker to
   find it. Compute the encoded folder name for the new path using the rule in section 1, create
   that folder under the sessions root, and move the `.jsonl` file into it. Do this with the
   session not running. Verify with `omp --resume` in the new folder.

3. **Pack and unpack** when the session has to move to another machine, which also carries its
   artefacts (see section 5).

Do not edit the `cwd` values inside the JSON lines by hand. The file is an event log, and a hand
edit is hard to undo.

## 5. Pack, unpack and the moved marker

Confirmed from help:

```bash
omp session pack SRC.jsonl OUT.tar                    # session with artefacts and image blobs
omp session unpack OUT.tar --cwd /new/path/to/project # prints the session file path
omp session moved SRC.jsonl --to TARGET               # marks the local copy stale
```

- `pack` includes the session's artefacts and image blobs, so the unpacked session can show them.
- `unpack --cwd` sets the folder the session continues in on this machine. Give the path that
  exists on the receiving machine.
- `moved` marks the local copy stale. Resuming a stale copy later forks it (help text). Use it after
  a hand-off, so that two machines do not keep writing the same session silently.

## 6. Crash recovery and export

- `omp --restore ID-OR-PATH` resumes a session as `--resume` does, and then goes on with what the
  last process left unfinished, including subagents it was running (confirmed from help). Use it
  after a crash, not as a routine resume.
- `omp --export SESSION.jsonl` writes an HTML export and exits (confirmed from help).
- `omp anonymize` writes a shareable copy with content redacted, metadata kept, and paths and
  literals replaced by consistent tokens (confirmed from the command list). Use it before sharing a
  transcript outside the machine. Read the output before sharing it; redaction is not a guarantee.

## 7. What not to touch

- A session file that another running omp owns. Check first with
  `omp session lease --json -- SESSION-ID`, which reports ownership without taking it (confirmed from
  help).
- The databases in the agent directory.
- Another agent's session, which is not yours to stop, restart or move without its owner's decision.
