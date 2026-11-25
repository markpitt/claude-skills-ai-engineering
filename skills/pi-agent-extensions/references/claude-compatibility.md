# Claude compatibility in pi

pi reads `AGENTS.md` and `CLAUDE.md` context files, and `~/.pi/agent/skills` and `.pi/skills` natively. It does
not read `~/.claude/CLAUDE.md`, `.claude/rules/` or Claude project memory by default (see the load table in
`agent-instruction-load-audit`, and the surface table in `instruction-context-budget`). An extension supplies
the rest. The pattern below is what the operator's own `claude-compat` extension does; `pi`'s examples folder
has a smaller `claude-rules.ts` that does the rules part alone.

## What each Claude surface needs

| Claude surface | Where it lives | How pi gets it |
|---|---|---|
| Global instructions | `~/.claude/CLAUDE.md` | Read in `before_agent_start` and appended to the system prompt, marked as the user's own standing instructions |
| Project instructions | `CLAUDE.md` up the tree | pi reads these natively, but only the first match per directory (`AGENTS.md` beats `CLAUDE.md`), so a directory with both loads one |
| Rules | `~/.claude/rules/**/*.md`, `<repo>/.claude/rules/**/*.md` | Listed by path in the system prompt, or inlined when a rule must load before any file is opened |
| Skills | `<repo>/.claude/skills/` and `~/.claude/skills` | `resources_discover` returns the folder as a skill path (`skillPaths`); `~/.claude/skills` also works through `settings.json` `skills` |
| Slash commands | `<repo>/.claude/commands/` | `resources_discover` returns it as a prompt path (`promptPaths`) |
| Project memory | `~/.claude/projects/<slug>/memory/MEMORY.md` plus topic files | The index is injected; topic files are listed by path for the agent to read |

## Finding the project folders

Walk from the working directory toward the root, stopping at the first folder with a `.git` entry, or at the
home directory when there is no repository. Collect each `.claude/` folder found on the way, so a nested repo
gets its parent's rules too. Deduplicate the folders before returning them: from the home directory the walk
reaches `~/.claude/skills`, which `settings.json` may already supply, and pi warns on name collisions and
keeps the first.

The memory slug is the absolute working path with every character outside `[a-zA-Z0-9-]` replaced by a dash.
The operator's `~/.claude/projects` folder names confirm it: `/home/<user>/.claude` becomes a folder whose
name has a double dash where the dot was. Check a new machine's folder names before trusting the slug.

## Rules that must load eagerly

A `paths:`-scoped rule loads only when a matching file is touched. Some rules say in their own text that they
must apply before any file is opened, and a path pointer cannot honour that. The operator's extension inlines
such a rule into the system prompt when a marker phrase in its text matches. The marker is a convention the
rule's author must keep: if the rule is reworded, the marker can go missing and the rule silently drops to a
path pointer. Test with a fresh session after changing either.

## Costs to keep in view

- **The whole prompt is replaced.** The operator's extension returns `systemPrompt` from `before_agent_start`,
  which replaces the prompt for the run and forces a prompt-cache miss when the text changes. The docs
  recommend changing `systemPromptOptions.sections` or `promptGuidelines` instead, so that pi sends only the
  changed sections. Treat the current design as a lead to test, not a settled fault: measure the cache
  behaviour before changing it.
- **Everything is read on every run.** The `before_agent_start` handler re-reads rules and memory on each run. The
  files are small, but a large memory index adds to every request. Measure with `instruction-context-budget`.
- **Shared text can be loaded twice.** A repository `CLAUDE.md` that is a symlink to `~/.claude/CLAUDE.md`
  would be read natively by pi and again by the extension. This is an expected consequence of the design, not
  observed here. Check for duplicates before adding a new source.

## What not to do

- Do not copy a Claude rule into pi's own files. Two copies drift.
- Do not inline a rule that the author did not flag as eager. Inlined text costs every turn.
- Do not log the injected prompt. It contains the operator's standing instructions and memory.
- Do not rely on `AGENTS.md` alone for the Claude surfaces. It is not a substitute for the rules folder.
