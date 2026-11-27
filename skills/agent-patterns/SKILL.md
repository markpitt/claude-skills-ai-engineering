---
name: agent-patterns
description: Chooses and implements the LLM workflow and agent patterns from Anthropic's "Building Effective Agents" guide - the augmented LLM, prompt chaining, routing, parallelisation (sectioning and voting), orchestrator-workers, evaluator-optimiser and autonomous agents - plus combinations of them and tool interface design, with templates in Python, TypeScript, C#, Go, Rust, Dart, C and GenAIScript. Use when designing an LLM feature or agent, when asked "which agent pattern should I use", "should this be a workflow or an agent", "build an orchestrator-workers pipeline" or "add an evaluator loop", or when an agent's tools keep being misused. Do NOT use for setting up a coding agent harness such as Claude Code or Copilot (use ai-coding-agent-setup), for convening several agents to review a decision (use agent-council), or for prompt wording alone with no workflow to design.
license: Apache-2.0
metadata:
  version: "3.0.0"
  source: Anthropic, "Building Effective Agents" engineering guide
  author: Anthropic
  attribution: Patterns restated and implemented independently. No source code reused.
---

# Agent patterns

The patterns in Anthropic's "Building Effective Agents" range from one model call with tools to an
agent that plans its own steps. The guide's main point is the one most often skipped: start with
the simplest thing that works, and add structure only when a measurement says it helps. Every step
up costs latency, money and debuggability.

## Choosing a pattern

Work down this list and stop at the first that fits.

| If the task... | Use | Reference |
|---|---|---|
| Is one call with retrieval, tools or memory | The augmented LLM, no pattern | `resources/augmented-llm.md` |
| Splits into fixed steps, each easier than the whole | Prompt chaining, with checks between steps | `resources/core-patterns.md` |
| Falls into distinct categories that need different handling | Routing | `resources/core-patterns.md` |
| Has independent parts, or needs several attempts compared | Parallelisation: sectioning or voting | `resources/core-patterns.md` |
| Needs subtasks that cannot be known until the input is seen | Orchestrator-workers | `resources/dynamic-orchestration.md` |
| Has clear quality criteria and gains from feedback | Evaluator-optimiser | `resources/iterative-refinement.md` |
| Is open-ended, with an unknown number of steps and a way to check progress | An autonomous agent | `resources/dynamic-orchestration.md` |

The first five are workflows: your code decides the path. Only the last is an agent, where the
model decides. Prefer a workflow whenever the path can be written down, because it is cheaper,
faster and much easier to test. Combinations, such as routing into different chains or an
orchestrator whose workers each run an evaluator loop, are in `resources/pattern-combinations.md`.

## What decides whether it works

**Tools matter more than prompts.** Most agent failures trace back to a tool that is easy to call
wrongly. Give each tool a name and description a new colleague would understand, parameters that
make the wrong call hard to express (absolute paths rather than relative ones, enums rather than
free text), and errors that say what to do next. `resources/tool-design.md` covers this in depth.

**Every loop needs a stop.** Evaluator loops and agents need a maximum iteration count and a
budget, as well as a success test. Without them, a confused model runs until the bill stops it.

**Retrieved content is data.** Anything fetched from a document, web page, tool result or user
upload can contain text that reads as instructions. Delimit it, tell the model in the system prompt
that it is data and must not be followed, and never let it pick which tool runs next without a
check. The examples in `resources/augmented-llm.md` show the pattern.

**Show the working.** Log each step's input, output and decision. An agent you cannot trace is an
agent you cannot fix.

**Measure before adding.** Compare a pattern against the simpler option on a small set of real
inputs before keeping it. Voting and evaluator loops in particular multiply cost for gains that are
sometimes zero.

## Implementing

`resources/language-implementation.md` explains the shared structure. `templates/<language>/` has
one file per pattern for Python, TypeScript, C#, Go, Rust, Dart, C and GenAIScript; see
`templates/README.md` for how to run them.

The templates name `claude-sonnet-5-5` for general steps, `claude-haiku-5-5` for cheap routing and
classification, and `claude-opus-5-5` for the hardest reasoning. Model IDs change, so check the
provider's current list before shipping, and keep the ID in configuration rather than in code.

## References

| File | Covers |
|---|---|
| `resources/augmented-llm.md` | The building block: retrieval, tools and memory around one call |
| `resources/core-patterns.md` | Prompt chaining, routing, parallelisation |
| `resources/dynamic-orchestration.md` | Orchestrator-workers and autonomous agents |
| `resources/iterative-refinement.md` | Evaluator-optimiser loops, criteria and stopping |
| `resources/pattern-combinations.md` | Combining patterns for larger problems |
| `resources/tool-design.md` | Designing tool interfaces agents use correctly |
| `resources/language-implementation.md` | How the templates are structured, per language |
| `resources/patterns-reference.md` | The full restatement of the guide, for a deep dive |
