<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/banner-dark.svg">
    <img src="docs/assets/banner-light.svg" alt="AI engineering" width="100%">
  </picture>
</h1>

Building with and around models: agent patterns, coding agent setup and sandboxing, fine-tuning data and project kickoff.

`sandboxed-agent` is Linux only (bubblewrap, x86_64 and aarch64). It can run its agents in tmux, and [tmux-persist](https://github.com/markpitt/claude-skills-dev-environment) in claude-skills-dev-environment knows its no-autostart convention, but each works without the other. `decision-models` needs .NET 10 and an OpenRouter key.

This is one of seven skill groups. [claude-skills](https://github.com/markpitt/claude-skills) lists them all and
holds the shared tooling: validation, packaging, the evaluation harness and the TUI.

## Skills

<!-- BEGIN GENERATED SKILL INDEX -->
| Skill | Bundled files | What it does |
|---|---|---|
| [agent-council](skills/agent-council/SKILL.md) | 4 files | Convenes a council of independent expert agents, each blind to the others and fixed to one lens, to review a… |
| [agent-instruction-load-audit](skills/agent-instruction-load-audit/SKILL.md) | 2 files | Proves at runtime which instruction files a coding-agent harness actually loaded, in what precedence, and… |
| [agent-patterns](skills/agent-patterns/SKILL.md) | 8 files | Modular orchestration of agent patterns from Anthropic's engineering guide. |
| [ai-coding-agent-setup](skills/ai-coding-agent-setup/SKILL.md) | 4 files | Configures AI agents (GitHub Copilot, Claude Code, Cursor, Codex) to understand a codebase and self-improve… |
| [browser-assisted-portal](skills/browser-assisted-portal/SKILL.md) | 1 file | Help a person through a government or service portal in a browser-automation session (for example Claude in… |
| [decision-models](skills/decision-models/SKILL.md) | 3 files | Uses a System One decision model (OpenRouter, inception/mercury-decide:free) through the bundled `decide`… |
| [fine-tuning-data-generator](skills/fine-tuning-data-generator/SKILL.md) | 6 files | Generates synthetic fine-tuning datasets in ChatML format (JSONL) for use with Unsloth, Axolotl, and similar… |
| [genaiscript](skills/genaiscript/SKILL.md) | 5 files | Expert guidance for Microsoft's GenAIScript framework - a JavaScript/TypeScript-based system for building… |
| [instruction-context-budget](skills/instruction-context-budget/SKILL.md) | 2 files | Measures what a coding-agent harness always loads (CLAUDE.md and AGENTS.md chains, unscoped rules, memory… |
| [local-llm-serving](skills/local-llm-serving/SKILL.md) | 7 files | Serve local GGUF models on a single consumer GPU (for example 24 GB) through llama-swap, optionally fronted… |
| [omp-harness](skills/omp-harness/SKILL.md) | 7 files | Configures and operates the omp coding agent harness, covering global and project config layers, model roles… |
| [parallel-worktree-integration](skills/parallel-worktree-integration/SKILL.md) | 3 files | Runs several subagents in parallel git worktrees, one branch per task pinned to a base commit, then… |
| [pi-agent-extensions](skills/pi-agent-extensions/SKILL.md) | 5 files | Writes, debugs and checks extensions for the pi coding agent, covering its ExtensionAPI events and tools… |
| [project-kickoff](skills/project-kickoff/SKILL.md) | none | Turns a rough idea for a new product, venture or project into a short goal statement and a set of parallel… |
| [remediation-script](skills/remediation-script/SKILL.md) | 2 files | Write a bash script for the human to run when a guard, sandbox or permission rule blocks the agent's own… |
| [resume-after-crash](skills/resume-after-crash/SKILL.md) | 3 files | Recover an agent's work after a host crash, WSL restart, Windows update reboot or lost terminal. |
| [sandboxed-agent](skills/sandboxed-agent/SKILL.md) | 4 files | Create a sandboxed coding agent for one folder, using a bubblewrap sandbox profile inferred from the folder… |
| [thought-patterns](skills/thought-patterns/SKILL.md) | 7 files | Orchestrates cognitive thinking patterns for complex problem-solving. |
| [token-lean-document-reading](skills/token-lean-document-reading/SKILL.md) | 2 files | Reads PDFs, email files (.eml and .msg), Word documents, zip archives, large text files and scanned images… |
| [transcript-analysis](skills/transcript-analysis/SKILL.md) | none | Inventory and aggregate coding-agent session transcripts across Claude Code, OMP, Codex CLI and pi, with… |

20 skills.
<!-- END GENERATED SKILL INDEX -->

## Install

Copy a skill directory into either skills location, then start a new session:

```bash
cp -r skills/<skill-name> ~/.claude/skills/    # personal, all projects
cp -r skills/<skill-name> .claude/skills/      # this project only
```

For Claude Desktop, build the skill's zip with `mise run skill:package:all` in claude-skills and
upload it under Settings, Capabilities, Skills.

## Licence

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Each skill directory carries its
own copy of the licence, so a skill copied out on its own stays covered.
