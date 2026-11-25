# Language servers, TTSR rules, hooks and approval patterns

Contents

1. lsp.json
2. Binary names and case
3. LSP switches
4. TTSR rules
5. Hooks
6. Bash approval patterns and approval modes

## 1. lsp.json

The global file is `~/.omp/agent/lsp.json` (confirmed from files). Its top level has a `servers`
map. Each key is the server's id, and each value describes how to start it. Fields observed in
the file (confirmed from files):

| Field | Meaning |
|---|---|
| `command` | The executable to start |
| `args` | Arguments, such as `["--stdio"]` |
| `fileTypes` | Extensions the server handles, for example `[".ts", ".html"]` |
| `rootMarkers` | Files or globs that mark a project root, for example `*.sln` or `.git` |
| `languageId` | The language identifier sent to the server, where the server needs one |

Minimal shape with placeholder values:

```json
{
  "servers": {
    "example": {
      "command": "example-language-server",
      "args": ["--stdio"],
      "fileTypes": [".ext"],
      "rootMarkers": [".git"]
    }
  }
}
```

Whether a per-project `lsp.json` is read from `.omp/` is **verify with omp --help**.

## 2. Binary names and case

The `command` value is looked up as written. On Linux the lookup is case-sensitive. A server
known as `OmniSharp` on the command line is therefore `OmniSharp` in `command`, even if its id in
the map is in lower case. Check the exact name before writing it:

```bash
command -v OmniSharp || echo "not on PATH"
```

Prefer a bare name that resolves on `PATH` over an absolute path. An absolute path into an editor's
extension directory breaks when the extension updates, and it ties the shared file to one
machine. Where a server only exists under a tool manager's directory, put that directory on `PATH`
for the shell that starts omp, not in the file.

## 3. LSP switches

Confirmed from help and from config key names:

- `--no-lsp` disables LSP tools, formatting and diagnostics for one run. Use it to separate a
  broken server from a broken session.
- `task.enableLsp` and `lsp.diagnosticsOnEdit` are config keys seen in the global config. Read their
  current values with `omp config get KEY` rather than from a copy.

## 4. TTSR rules

Time-Traveling Stream Rules watch the model's output or a tool call and inject text when a pattern
matches. Rules are markdown files with frontmatter. The observed fields (confirmed from files):

```markdown
---
name: example-rule
description: "Short statement of what the rule guards"
condition: "PATTERN"
scope: "tool:edit(*.ts)"
---

Text the rule injects when it fires. Keep it to one or two sentences.
```

- `condition` is a regular expression. Test that it matches the intended text and not ordinary text.
- `scope` limits when the rule applies. A tool scope such as `tool:edit(*.ts)` is the observed form.
- Personal rules live in `~/.omp/agent/rules/`. Project rule folders are **verify with omp --help**.

Test a rule before relying on it, in isolation and with a snippet:

```bash
omp ttsr test --rule ~/.omp/agent/rules/example-rule.md --source tool --tool edit \
  --path src/file.ts "snippet text to test"
omp ttsr list
omp ttsr scan DIRECTORY        # what rules would match across a tree (read-only)
```

Confirmed from help. A rule that never fires in the test cannot be relied on in a session. A rule
that fires on every snippet is also wrong, so test a negative case too. `--no-rules` disables rule
discovery for a run (confirmed from help).

## 5. Hooks

A project hook file lives under `.omp/hooks/pre/` in the repository (confirmed from files). The
files observed there are TypeScript modules that guard shell commands and paths. Two ways to load
them are confirmed from help:

- `--hook FILE` loads a hook or extension file for one run, and can be repeated.
- `-e FILE` or `--extension FILE` loads an extension file, and can be repeated.

Whether a project's `.omp/hooks/` folder loads automatically is **verify with omp --help**. Do not
assume a hook is active because it exists. Test it with a harmless input that it must refuse, and
one that it must allow. A guard that refuses everything looks the same as one that works.

Disable all extension discovery for a run with `--no-extensions`, which keeps explicit `-e` paths
(confirmed from help).

## 6. Bash approval patterns and approval modes

The project config can hold a `bash.patterns` list. Each entry has a `match` and an `approval`.
The first matching entry wins (stated in the project config header). Observed values (confirmed
from files):

```yaml
bash:
  patterns:
    - match: "git push * --force-with-lease*"
      approval: prompt
    - match: "git push * --force*"
      approval: deny
```

- `approval: prompt` asks the user before the command runs. `approval: deny` refuses it. The
  observed values are these two.
- The project header states that `bash.patterns` is a literal-text backstop. A precise regex
  version sits in a hook file. Keep both in step.
- Bash patterns do not reach the `eval` tool. The project header says `eval` can shell out, so it
  needs its own prompt rule where the risk matters (the header's commented example uses `prompt`).
- Put the more specific `match` before the broader one, because the first match wins.

Approval mode is set globally or per run. Confirmed from help:

```bash
omp --approval-mode always-ask "task"     # always-ask, always-ask-cached, write, yolo
```

`yolo` approves every tool call without a prompt. Keep it out of a shared project file, and
treat a personal global `yolo` as a deliberate choice, not a default.
