---
name: pi-agent-extensions
description: Writes, debugs and checks extensions for the pi coding agent, covering its ExtensionAPI events and tools, registerProvider and createProvider with auth.json and models.json credentials, live model-list refresh, Claude compatibility (rules, skills, memory, CLAUDE.md), OpenAI-compatible local servers such as llama.cpp, and the provider bugs that recur. Names are checked against the installed binary. Use when writing or changing a file under ~/.pi/agent/extensions or .pi/extensions, adding a pi provider, a model list that does not update, a key that is ignored, or Claude rules missing from pi. Do NOT use for omp configuration or extensions (use omp-harness), for writing AGENTS.md or CLAUDE.md content (use ai-coding-agent-setup), or for choosing a hosted model without pi involved.
license: Apache-2.0
metadata:
  version: "1.0.1"
  tags: "pi, coding-agent, extensions, providers, auth, models, openai-compatible, llama-cpp, claude-compat, typescript"
---

# pi agent extensions

**Goal:** make a pi extension do what its author intended, and show that it does. Pi does not reject an
unknown option or event name. It ignores it. So every name is checked against the installed version, and
every provider is checked with a real list and a real request.

Pi is the `@earendil-works/pi-coding-agent` CLI. This skill covers its TypeScript extension API as shipped
in pi 1.5.2. Read the installed docs for the version in use, not a remembered API.

## Quick reference

| Task | Load |
|---|---|
| Events, tool and command registration, contexts, ExtensionAPI methods | `references/api-surface.md` |
| `registerProvider`, `createProvider`, `auth.json`, `models.json`, refresh, local servers | `references/providers-and-auth.md` |
| Reading Claude rules, skills, memory and CLAUDE.md from pi | `references/claude-compatibility.md` |
| A symptom, its cause and its check | `references/recurring-bugs.md` |
| A working template for an OpenAI-compatible local server | `references/example-local-provider.ts` (not compiled here) |
| Check the names in an extension against the binary | `scripts/check_extension_names.py` |

## Where pi's docs and binary are

The installed package holds the docs under its `docs/` folder and examples under `examples/extensions/`. Find
it from the binary, not from memory:

```bash
PI=$(readlink -f "$(command -v pi)")          # the installed binary
PI_HOME=$(dirname "$PI")                       # its package folder holds docs/ and examples/
ls "$PI_HOME/docs" | head                      # extensions.md, custom-provider.md, models-configuration.md, ...
pi --version
```

If `pi --version` and the package folder disagree, the package folder is from another install. Use the
folder that the binary sits in. Record the version in every report.

## Procedure

Set the skill folder as a quoted absolute path first.

```bash
SKILL_DIR=/absolute/path/to/pi-agent-extensions
```

1. **Fix the target.** Note the pi version, whether the extension is global (`~/.pi/agent/extensions/`),
   project-local (`.pi/extensions/`, which needs a trusted project), or run with `pi -e <path>` for a test.
   A project-local file in an untrusted project does not load, and that looks like a broken extension.

2. **Read the relevant reference, then the docs section it names.** The references point at the installed
   doc sections. A signature is taken from the docs; the binary only confirms that a name exists.

3. **Write the smallest extension.** One concern per file. Prefer a complete provider (`createProvider`) for a
   live catalogue, and `models.json` for a fixed one. Put no secret in the file: keys come from `auth.json`,
   an environment variable of the starting process, or a `!command`.

4. **Check the names.**

   ```bash
   python3 -I "$SKILL_DIR/scripts/check_extension_names.py" <file.ts> [more.ts]; echo "exit=$?"
   ```

   Exit 1 lists a method, UI call or event name that does not occur in the binary. Exit 2 is a usage error
   or no binary on PATH; pass `--binary` for a specific build. Object keys (options such as `fetchModels`) are
   not read by the script: confirm each one against the docs, and against the binary with a context search
   as shown in `references/recurring-bugs.md`, row 1.

5. **Test the path that matters.**
   - Provider: `pi --list-models` shows the expected IDs. One prompt returns text. One prompt that needs a
     tool returns a tool result. A wrong key gives an authentication error.
   - Event handler: a benign input and an inert input, as the safety rules below require, with the
     expected block or pass-through.
   - Claude compatibility: a fresh session shows the rule text or the path pointer, and the rule's effect is
     visible in the answer. The session's own context report is the evidence, not the model's recitation.

6. **Run any project test suite inside a sandbox**, such as a bubblewrap wrapper that makes only the
   repository writable, from a directory inside the repository. A suite started through a task runner may
   escape a wrapper applied to the outer command, so check what the task runs, or run the underlying
   command wrapped.

7. **Report** the pi version, the names checked and their exit code, the tests run, and which claims were
   not checked (for example a provider that was not reachable from this machine).

## Rules

- **Check the name, not the memory.** A name that compiles in your head can be absent from the installed
  version. Pi does not warn.
- **Keep secrets out of files and logs.** A `before_provider_request` logger writes the conversation and the
  tool definitions. Log sizes and names only, keep any log private, and never commit it.
- **Do not replace the whole system prompt when a section change will do.** Returning `systemPrompt` forces a
  cache miss whenever the text changes. Use `systemPromptOptions` where it is enough.
- **Fail closed in a gate.** A `tool_call` handler that cannot decide must block, and say why. Do not let an
  error in a safety check pass the call.
- **Do not map rate limits to context overflow.** Rate limits and quota responses use pi's normal retry.
  Only a recognised context-overflow message may be normalised, and only for its own provider.
- **Use `CONFIG_DIR_NAME`, not a literal `.pi`,** when building project-local paths.
- **A refresh that cannot reach the network is not a failure to hide.** Serve the saved snapshot, and say the
  list is stale.
- **Keep local extensions local.** Do not publish an extension that contains a host address, a machine name
  or a path under a home directory. Read the value from an environment variable with a generic default.

## Limits

- The docs and the binary are the only sources checked for pi 1.5.2. Behaviour in other versions, and in
  forks, is not established by this skill.
- `references/example-local-provider.ts` has not been compiled or run against a server. Its names were checked
  against the docs and the binary, not its types.
- The name check reads only `pi.<name>`, `ctx.ui.<name>` and `pi.on("<event>")`. It does not check option keys,
  argument shapes or return types.
- Whether a given server behaves as its compatibility flags say is a fact to test on that server, not one this
  skill can supply.
