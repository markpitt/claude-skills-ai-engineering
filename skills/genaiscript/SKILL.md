---
name: genaiscript
description: Writes, debugs and hardens scripts for Microsoft's GenAIScript, the JavaScript and TypeScript framework for prompts-as-code and LLM automation. Covers script structure, file context with def and env.files, structured output with responseSchema, tools and agents, MCP servers and toolsSha pinning, parsing PDF, CSV and DOCX, script tests and evals, retrieval, and model aliases. Use when creating, fixing or optimising a .genai.mjs or .genai.mts script, or when asked how to do something in GenAIScript, to "add tests to this script" or to "make this script safe against prompt injection". Do NOT use for generic prompt engineering with no GenAIScript code, or for other LLM frameworks unless the user is migrating to or from GenAIScript.
license: Apache-2.0
metadata:
  version: "4.0.0"
---

# GenAIScript

GenAIScript builds prompts in JavaScript or TypeScript: a script declares its model and options,
pulls in files and data, writes the prompt with a template tag, and can parse the answer into files,
edits or structured data. Answers about it should use its own primitives, with runnable snippets,
rather than general prompting advice.

`resources/best-practices.md` tracks the current API. Where it disagrees with another resource,
it wins.

## Rules that hold for every script

1. Ground on local files with `def(...)` and `env.files`. Do not make the model fetch them with a
   tool when `def()` would do.
2. A tool is something the model may call, not something it will. Never rely on a call happening.
3. Output that code will read needs `responseType` or `responseSchema`, in strict mode. A prompt
   asking for JSON is not structured output.
4. Leave the safety defences on: `systemSafety`, `detectPromptInjection` and secret scanning.
5. Give every script that matters `script({ tests: ... })`, and use `testModels` to compare models.
6. Pin MCP server versions, and pin their tool signatures with `toolsSha`.
7. Use the model aliases (`large`, `small`, `reasoning`, `vision`) instead of a provider's model
   name, so the script runs on whatever the user has configured.

## The shape of a script

```javascript
script({
    title: "Review changed files",
    model: "large",
    tests: { files: "src/sample.ts", keywords: "issue" },
})

def("CODE", env.files, { endsWith: ".ts", lineNumbers: true })
$`Review CODE for bugs. Give the file, line and a one-line fix for each.`
```

Data goes in with `defData()` after a parser such as `parsers.CSV()`, the expected output with
`defSchema()`, and output files with `defFileOutput()`. `runPrompt` runs a sub-prompt inside a
script, which is how multi-step workflows are built. From the command line:

```bash
genaiscript run review src/*.ts
genaiscript run review --vars KEY=value --model small
```

Scripts live in `genaisrc/` as `.genai.mjs` or `.genai.mts` files. `.genai.js` still works, but the
module forms make imports explicit, and `.genai.md` suits a short prompt with frontmatter. The VS
Code extension adds IntelliSense, debugging and an output preview.

## Untrusted content

A script that reads web pages, search results, uploaded documents, API responses or MCP tool output
is open to indirect prompt injection: instructions hidden in the content that the model then follows.

Use the framework's controls first. `detectPromptInjection: "always"` scans tool output and drops an
answer if it finds an attack. `systemSafety: "default"` keeps the standard safety prompts on.
`toolsSha` stops an MCP server changing its tools after you approved them. `intent` checks that a
high-stakes tool's output matches what was asked.

On top of those, extract from untrusted content in its own call, with a strict schema
(`additionalProperties: false`), before anything acts on it. Tell the model the content is data and
not instructions. Check any argument the model passes to an external API against an allowlist. Use
the workspace file APIs, not Node's `fs`, because only the workspace APIs enforce the boundaries.
`resources/patterns.md` has worked examples.

## Where to look

| For | Read |
|---|---|
| How scripts, context and file processing work | `resources/core-concepts.md` |
| A function's signature and options: `$`, `def`, `defSchema`, `defTool`, `defAgent`, parsers, environment | `resources/api-reference.md` |
| A starting point: code review, documentation, data extraction, multi-step workflows | `resources/examples.md` |
| Token budgets, caching, parallel calls, error handling, design patterns, security patterns | `resources/patterns.md` |
| MCP and `toolsSha`, structured output, safety controls, tests and `testModels`, `retrieval.index`, model aliases and `reasoningEffort` | `resources/best-practices.md` |

## Mistakes to catch

Treat each of these as a defect, in the user's script or in your own answer:

- reading local files through a tool where `def()` would do;
- an MCP server on `latest`, or with no `toolsSha`, in anything that matters;
- claiming structured output without `responseType` or `responseSchema`;
- web, MCP or tool output used with no thought for injection;
- calling a script production-ready when it has no tests;
- a hard-coded provider model where an alias would do;
- trusting scripts, or file edits the model generated, from a source you do not control.
