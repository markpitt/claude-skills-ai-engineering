# What is always loaded, by harness

The budget is the set of instruction text a session pays for before the first user message, and on
every request after it. Four surfaces make it up. Each harness loads them differently, so measure
each surface on its own.

| Surface | Always loaded? | Measured as |
|---|---|---|
| Context files (`CLAUDE.md`, `AGENTS.md` and their chain) | Yes, at launch | `context-file`, budget `always` |
| Rules without a path scope | Yes, at launch | `rule`, budget `always` |
| Rules with a path scope (`paths:`) | Only when a matching file is touched | `rule-scoped`, budget `on-demand` |
| Memory index (`MEMORY.md`) | The first part only, at launch | `memory-index`, capped at 200 lines or 25 KB |
| Memory topic files | Only when read | `memory-topic`, budget `on-demand` |
| Skill name and description | Yes, in the skill listing | `skill-description`, name and description only |
| Skill body (`SKILL.md` after the frontmatter) | Only when the skill is invoked | not counted |

The skill body is not in the budget, which is why a long procedure in a `SKILL.md` costs nothing per
session. A long `description` costs every session, so it is the first thing to shorten in a skill
that is loaded everywhere.

## Load rules per harness

The rows below are summarised from the harness load rules in the `agent-instruction-load-audit` skill,
which were checked against vendor sources on 17/11/2026. That neighbour is the authority for file
names and precedence. Re-check the row for the version you run before relying on it, and record
the version in your report.

### Claude Code

- Always: `~/.claude/CLAUDE.md`; `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md` from the
  working directory up to the root; `.claude/rules/*.md` without `paths:`.
- Scoped: rules with `paths:` load when a matching file is touched.
- Memory: the first 200 lines or 25 KB of `MEMORY.md` at session start; topic files on demand.
- `applyTo:` in a Claude rule is ignored. A rule that uses it loads for every path.
- To see the real load: `/context all` in the session. Read that output, do not ask the model.

### Codex CLI

- Always: `AGENTS.override.md`, or else `AGENTS.md`, in the Codex home, then at most one file per
  directory from the project root down to the working directory.
- A size cap applies (`project_doc_max_bytes`, 32 KiB by default). Content past it is cut silently.
- `CLAUDE.md` is not read unless listed in `project_doc_fallback_filenames`.

### pi

- Always: the first existing file of `AGENTS.override.md`, `AGENTS.md`, `CLAUDE.md` in each directory
  from the working directory up to the root, and in the agent directory.
- `~/.claude/CLAUDE.md`, `.claude/rules/` and Claude project memory are not read by default. A local
  extension can add them, and that extension's text is then part of the budget.
- `systemPromptOptions.contextFiles` in a `before_agent_start` handler lists the context files pi
  has chosen. That is a measurement surface, not a guess.

### GitHub Copilot CLI

- Always: `.github/copilot-instructions.md`, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, and personal
  `~/.copilot/copilot-instructions.md`. Path-scoped instruction files use `applyTo`.

### Other harnesses

Find the loader before measuring. Record the filenames it searches, whether it stops at the first
match per directory, any size cap, and whether it has an import syntax. Label the row unverified until
a canary has confirmed it (see `agent-instruction-load-audit`).

## What the estimate means

Tokens are estimated as `ceil(bytes / 4)`. This is a rough rule for English prose and for Markdown
with code. It is not a tokenizer, and it understates dense tables and code. Compare two measurements
made the same way, and report the byte counts, which are exact, alongside any token figure.
