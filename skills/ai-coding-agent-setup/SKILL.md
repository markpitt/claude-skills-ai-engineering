---
name: ai-coding-agent-setup
description: Sets a repository up so AI coding agents (GitHub Copilot, Claude Code, Cursor, Codex) understand it and keep improving as the project changes. Covers writing AGENTS.md and the tool-specific instruction files, packaging repeatable project workflows as agent skills, configuring MCP servers for code navigation, and the feedback loops that stop instructions going stale. Use when setting up a new project for AI-assisted development, onboarding agents to an existing repo, writing or fixing AGENTS.md, configuring .vscode/mcp.json, or when asked "why does the agent keep making the same mistake" or "the agent ignores our conventions". Do NOT use for writing or testing a single skill in depth (use skill-creator), for sandboxing an agent (use sandboxed-agent), or for choosing an LLM workflow pattern in application code (use agent-patterns).
license: Apache-2.0
metadata:
  version: "2.0.0"
  tags: [agents, ai, codebase, mcp, agents-md, self-improvement]
---

# AI coding agent setup

An agent works well in a repository when three things are in place: a short file that says what
the project is and how to build and test it, packaged workflows for the jobs that repeat, and tools
that let it look things up instead of guessing. This skill covers each, and how to keep them true
as the code moves on.

| Layer | What it holds | Reference |
|---|---|---|
| AGENTS.md | Project identity: overview, build and test commands, conventions, layout | `resources/agents-md-guide.md` |
| Agent skills | Repeatable workflows, loaded only when needed | `resources/agent-skills-architecture.md` |
| MCP servers | Live tools: code search, GitHub, databases | `resources/mcp-codebase-tools.md` |
| Feedback loops | Keeping all of the above current | `resources/self-improvement-patterns.md` |

## Where to start

| The user says | Start with |
|---|---|
| "Set up AI for this project" | `agents-md-guide.md`, then decide whether skills or MCP are needed at all |
| "The agent ignores our conventions" | `agents-md-guide.md`, conventions section |
| "It keeps making the same mistake" | `self-improvement-patterns.md`, feedback loops |
| "It can't find its way round the code" | `mcp-codebase-tools.md` |
| "Can we package this workflow for the agent?" | `agent-skills-architecture.md` |

Produce the files themselves (AGENTS.md, SKILL.md, `mcp.json`), not advice about them.

## A new project

1. Write `AGENTS.md` at the repository root from the template in `agents-md-guide.md`: what the
   project is, the exact build and test commands, the conventions a newcomer would get wrong, and a
   map of the folders. Keep it short. Every line costs context in every session.
2. Point the tool-specific files at it rather than copying it. In `CLAUDE.md`, a line reading
   `Read @AGENTS.md` is enough. `copilot-instructions.md` can say the same.
3. Add MCP only for what the built-in tools cannot do. VS Code's own tools already give errors,
   symbol navigation and semantic search. The GitHub MCP remote server (`type: http`, OAuth) adds
   cross-repository access without a token in the file.
4. Package a workflow as a skill only once it has been done by hand more than once and the steps are
   stable.
5. Commit all of it. These files are part of the project, and reviewing changes to them matters as
   much as reviewing code.

## An existing repository

Read the README for content an agent needs and a human reader does not: build flags, test scripts,
folder purposes. Move that into AGENTS.md. In a monorepo, put global rules in the root AGENTS.md and
package-specific ones in an AGENTS.md beside each package; the closest file wins.

## Keeping it true

Treat a repeated agent mistake as a documentation bug. When it happens, find the missing or wrong
instruction, fix it in AGENTS.md or the relevant skill, and ask the agent to do the same task again
to check the fix took. After a long debugging session, ask the agent what one line in AGENTS.md
would have prevented it, and review that line before committing it.

Instructions also go stale the other way: a rule for code that no longer exists still costs
context and can mislead. Prune them on a regular review, using the prompts in
`self-improvement-patterns.md`.

## Choices worth getting right

- **Identity in AGENTS.md, procedure in skills.** AGENTS.md is read every session, so keep
  step-by-step workflows out of it.
- **Skills stay small.** Keep SKILL.md under 500 lines, put heavy reference material in
  `resources/`, and link every reference directly from SKILL.md rather than chaining one reference to
  another.
- **Name MCP tools in full** in AGENTS.md, as `ServerName:tool_name` (for example
  `GitHub:search_code`), so the agent knows which server to call.
- **Share skills across tools.** Keep them in `.agents/skills/`, which Copilot and other Agent Skills
  tools read, and link `.claude/skills/` to it for Claude Code. Use one tool's path only for a skill
  that only that tool will use.
- **Delegate the big jobs.** Research, audits and large refactors go to subagents, which keep the
  main session's context clear.

## References

- [AGENTS.md](https://agents.md)
- [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
- [Agent Skills best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
- [Model Context Protocol](https://modelcontextprotocol.io)
- [GitHub MCP Server](https://github.com/github/github-mcp-server)
- [VS Code MCP servers](https://code.visualstudio.com/docs/copilot/customization/mcp-servers)
