# Which instruction files each harness loads

Read this in step 1 or 2 of `SKILL.md`, to build the expected set before any probe. Every row was
checked against the vendor's documentation or source on 17/11/2026. These harnesses change: a
Claude Code change in September 2026 altered what it reads when `CLAUDE.md` is absent. Re-check the
row for the version you run before you rely on it, and record the version in the report.

## 1. Claude Code

| Item | Behaviour |
|---|---|
| Files read | `~/.claude/CLAUDE.md`; `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md` from the working directory up to the root; `.claude/rules/*.md`; the start of the auto-memory `MEMORY.md` |
| `AGENTS.md` | Read natively only when no `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` is in the working directory or above it (from 2.1.277). The setting "Project instructions" in `/config` changes this. Its default is `claude-md-or-agents-md`; the others are `claude-md-and-agents-md`, `claude-md` and `managed-only` |
| Imports | `@path/to/file` inside a `CLAUDE.md`, relative to that file, up to four hops deep; not inside code spans or fenced blocks. `@AGENTS.md` shares one file with another tool |
| Rules without `paths:` | Load at launch, with the same priority as `.claude/CLAUDE.md` |
| Rules with `paths:` | Load only when Claude works on a matching file. Before any matching file is touched, not being loaded is correct, not a fault |
| Precedence | Everything found is concatenated: user rules before project rules, root first, so the nearer file comes last. Nothing overrides anything else |
| `AGENTS.override.md` | Not read |
| Auto-memory | First 200 lines or 25 KB of `MEMORY.md` at session start; topic files on demand |
| How to see it | `/context all` (the Memory files section), `/memory`, and the `InstructionsLoaded` hook |
| Hook caveat | `InstructionsLoaded` fires for files pulled in by import, not for a native `AGENTS.md` read. An interactive session shows a line of the form `no CLAUDE.md found; AGENTS.md loaded: <path>` instead. So a hook log can prove that imports were observed, not that no native read happened |
| Docs | https://code.claude.com/docs/en/memory (sections on AGENTS.md and imports); changelog entry 2.1.277 |

Read `/context all` output yourself; do not ask the model to recite it. It is the harness's own record.

## 2. Codex CLI

| Item | Behaviour |
|---|---|
| Files read | `AGENTS.override.md`, or else `AGENTS.md`, in the Codex home (first non-empty only); then at most one file per directory from the project root down to the working directory |
| Other names | Read only if listed in `project_doc_fallback_filenames`. The docs say: "Filenames not on this list are ignored". `CLAUDE.md` is not read unless listed |
| Precedence | Concatenated root first, so nearer files come later and win in practice |
| Size cap | `project_doc_max_bytes`, 32 KiB by default. Content past the cap is cut, silently from the user's point of view |
| How to see it | The TUI log via `codex -c log_dir=<dir>`; the session JSONL; a canary probe (see `runtime-probe.md`). Asking "summarise the current instructions" is not evidence |
| Docs | https://learn.chatgpt.com/docs/agent-configuration/agents-md (redirects from developers.openai.com/codex/guides/agents-md) |

Check the Codex config file for `project_doc_fallback_filenames` and `project_doc_max_bytes` before
the expected set is written; both change what is read.

## 3. pi (earendil-works/pi)

| Item | Behaviour |
|---|---|
| Files read | One context file per directory: the first that exists of `AGENTS.override.md`, `AGENTS.md`, `CLAUDE.md`, for the agent directory and then each directory from the working directory up to the root |
| Precedence | Within a directory, the first match wins and the others are not read. `AGENTS.md` beats `CLAUDE.md` in the same directory. This is in the loader source (`resource-loader.ts`), not in the docs page, which does not state it |
| Override | `AGENTS.override.md` replaces the others in its own directory only |
| Claude material | `~/.claude/CLAUDE.md`, `.claude/rules/` and Claude project memory are not read by default. A local extension can add them |
| Skills | `~/.pi/agent/skills/`, `~/.agents/skills/`, `.pi/skills/`, `.agents/skills/`. `~/.claude/skills` only when added under `skills` in `settings.json` |
| How injected | Each injected context file appears in the system prompt as a `<project_instructions path="...">` block. The model can see those paths, though not the startup header |
| How to see it | The startup header shows loaded resources, but it is UI, not model context. A model asked about the header cannot see it. Use the canary probe, and check the `path` attributes if the model can see the system prompt |
| Docs | https://github.com/earendil-works/pi (`packages/coding-agent/docs/configuration.md`, `packages/coding-agent/src/core/resource-loader.ts`). Read the installed version's docs and `pi --help`, which is authoritative for the CLI |

## 4. GitHub Copilot CLI

| Item | Behaviour |
|---|---|
| Files read | `.github/copilot-instructions.md`; `.github/instructions/**/*.instructions.md` with `applyTo`; `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`; personal `~/.copilot/copilot-instructions.md` and `~/.copilot/instructions/**` |
| Precedence | Personal, then repository, then organisation, all provided. The nearest `AGENTS.md` wins for its subtree |
| Frontmatter | `applyTo` scopes Copilot instructions. Claude Code ignores it, and `paths` is the Claude key |
| How to see it | Nothing CLI-specific is documented. The References list belongs to Copilot Chat. Use the canary probe |
| Docs | https://docs.github.com/en/copilot/reference/custom-instructions-support |

## 5. Other harnesses

For a harness not listed, find its loader before writing the expected set. Look for: the filenames
it searches, whether it stops at the first match per directory, how it walks the tree, any size cap,
and whether it has an import syntax. Record the answer in the same table shape, with the source
location, and mark it unverified until a canary has confirmed it.

## 6. Frontmatter keys that scope a file, and which harness honours them

| Key | Honoured by | Silently ignored by |
|---|---|---|
| `paths` (rules) | Claude Code (per its memory docs) | Copilot: its docs use `applyTo`, not `paths` |
| `applyTo` (instructions) | Copilot (per its docs) | Claude Code: not in its rule syntax, so it is ignored |

The skill keys `name` (equal to the folder) and `description` (up to 1024 characters) come from the
Agent Skills specification and the packaging rules of the skills repository, not from each harness's loader. The
audit script enforces them so that a skill which would fail packaging, or that a loader would
reject, is caught before the runtime probe. Confirm per harness with a canary before you assume
that a harness rejects a bad skill rather than skipping it.

A key the harness ignores is not an error to the harness. The audit script flags the mismatch so
the author can see it.
