# GenAIScript Best Practices

Current-API guidance for authoring, securing, testing, and operating GenAIScript
workflows. Where this file and the other resources disagree on an API detail,
**this file wins**. It is the layer kept aligned with upstream releases.

## Table of Contents

- [Authoring and Runtime](#authoring-and-runtime)
- [Tools, MCP, and Security](#tools-mcp-and-security)
- [Testing, Structured Output, and RAG](#testing-structured-output-and-rag)
- [Sources](#sources)

---

## Authoring and Runtime

### Canonical script formats

- Prefer `.genai.mjs` and `.genai.mts` for importable module workflows.
- `.genai.js` is supported for compatibility, but prefer `.mjs`/`.mts` for explicit module imports.
- Use `.genai.md` for concise markdown-first prompts with frontmatter.
- Keep scripts discoverable in `genaisrc/` unless there is a clear project convention.

### Script metadata baseline

Use `script({...})` with explicit metadata and runtime options:

- `title`, `description`
- `model` (prefer aliases like `large`, `small`, `reasoning`)
- `parameters` for user/config input
- optional: `responseType`, `responseSchema`, `cache`, `tests`, `tools`, `system`

### Deterministic context grounding

Use `def` + `env.files` when context is known or selected by user/CLI.

- Preferred:
  - `def("FILE", env.files)`
  - `def("DOCS", env.files, { endsWith: ".md" })`
- Why:
  - More deterministic than waiting for LLM tool-calling decisions
  - Usually lower token/tool-call overhead for local file grounding

Use `def` controls to shape context:

- `maxTokens`, `line`, `lineStart/lineEnd`
- filters: `glob`, `endsWith`
- table/data slicing: `sliceHead`, `sliceTail`, `sliceSample`

### Inline prompts and composition

`runPrompt` / `prompt` are ideal for staged workflows (rewrite, classify, summarize, judge).

Critical pattern for inner prompts:

- Use `_.def`, `_.$`, etc. inside inner prompt lambdas.
- Do not call global `def`/`$` in inner prompts by accident.

### Model selection guidance

- Start with aliases (`large`, `small`, `vision`, `reasoning`, `reasoning_small`).
- Use `reasoningEffort` only when it adds value.
- Keep provider/model specifics configurable via aliases, env, or CLI.

```javascript
script({ model: "large" })     // maps to a capable general model
script({ model: "small" })     // maps to a cheap/fast model
script({ model: "reasoning" }) // maps to a reasoning model
```

Hardcoding a provider model (`"openai:gpt-4"`) pins the script to one vendor and
one generation. Aliases are resolved from configuration, so the same script
follows your environment.

### Caching guidance

- Request-level cache: `script({ cache: true })` or named cache.
- Prompt-caching hint: `cacheControl: "ephemeral"` on `def`/prompt blocks.
- Treat ephemeral behavior as provider-dependent.

---

## Tools, MCP, and Security

### Tool design with `defTool`

- Always define a clear schema for tool arguments.
- Keep tool descriptions concrete and task-oriented.
- Prefer deterministic return formats for downstream prompts.

Recommended hardening:

- `detectPromptInjection` on risky tool outputs
- output intent validation (`intent`) for high-stakes tools
- explicit max token controls when needed

### Fallback tool calling

- Some models do not support native tool calling.
- Use `fallbackTools` when required; expect performance variance.
- Prefer native tool-capable models for tool-heavy workflows.

### MCP server configuration

Use `mcpServers` / `mcpAgentServers` in script or loaded config files.

Security controls to enforce:

1. Pin server package versions (e.g. `@...@0.x.y`)
2. Validate tool signature via `toolsSha`
3. Enable prompt-injection detection in tool output pipeline
4. Apply secret detection/handling to tool results
5. Scope tool sets (`tools`) to least privilege where possible

```javascript
script({
    mcpServers: {
        memory: {
            command: "npx",
            args: ["-y", "@modelcontextprotocol/server-memory@0.6.2"],
            detectPromptInjection: "always",
            toolsSha: "",
        },
    },
})
```

Leave `toolsSha` empty on the first run: GenAIScript computes and logs the
expected signature. Review the tool list, then hardcode the hash to enforce
validation on later runs. This is the defence against a server silently changing
its tools after you approved them.

Operational notes:

- Server lifecycle is per prompt render/session.
- Inline prompt MCP definitions may restart servers frequently.
- Script config can be merged with CLI MCP config; script values take precedence.

### Content safety controls

- Default safety stack includes jailbreak/harmful/protected-material prompts.
- Force defaults with `systemSafety: "default"` when needed.
- Integrate Azure Content Safety for prompt-injection and harmful-content checks.
- Canary-word systems can detect prompt leaks in model outputs.

Prefer these framework controls over hand-rolled prompt hygiene. `resources/patterns.md`
→ Security Patterns covers the general trust-boundary reasoning; the options here
are what actually enforces it.

### Trust boundaries

- `.genai.*` scripts are executable code; do not run untrusted scripts.
- Do not blindly apply LLM-generated file edits; review changes.
- Workspace file APIs enforce safety boundaries by default; direct Node FS bypasses these protections.

---

## Testing, Structured Output, and RAG

### Script-level testing

Declare tests in `script({ tests: ... })`.

Useful fields:

- `files`: fixture files injected into `env.files`
- `rubrics`: model-graded quality expectations
- `facts`: factuality checks
- `asserts`: promptfoo assertions for concrete checks
- `testModels`: run same test suite across multiple models

Execution paths:

- VS Code Test Explorer
- CLI: `genaiscript test <scriptid>`
- Optional model override: `--models ...`

### Structured output reliability

Key options:

- `responseType`: `json`, `yaml`, `json_object`, `json_schema`
- `responseSchema`: validates output structure

Guidance:

- Use `json_schema` for strict machine contracts when provider supports it.
- Use `json` + schema when portability is needed with runtime repair/validation.
- Document schema constraints and failure behavior in production scripts.

```javascript
script({
    responseType: "json_schema",
    responseSchema: {
        type: "object",
        properties: { severity: { type: "string" } },
        required: ["severity"],
        additionalProperties: false,
    },
})
```

`responseSchema` constrains the **script's own output**. `defSchema()` constrains
a schema referenced inside the prompt or a tool's output. They are different
tools for different jobs; see `resources/api-reference.md` for `defSchema()`.

### Retrieval and vector search

Canonical flow:

1. `const index = await retrieval.index("name", options)`
2. `await index.insertOrUpdate(env.files)`
3. `const hits = await index.search("query")`

Stability rules:

- Keep index creation options stable over time.
- Keep embeddings model and chunking strategy stable across runs.
- Use explicit options for reproducibility in CI/automation.

Backends:

- Local vector database by default (`.genaiscript/vector`)
- Azure AI Search for managed/cloud indexing scenarios

### Web retrieval integration

- `retrieval.webSearch(...)` returns result snippets.
- Fetch full page content separately when needed.
- Treat web/tool outputs as untrusted input; apply injection defenses.

---

## Sources

Upstream Microsoft GenAIScript documentation. Paths are in the
[microsoft/genaiscript](https://github.com/microsoft/genaiscript) repository
under `docs/src/content/docs/`, verified 09/08/2026.

| Topic | Source |
|---|---|
| Model aliases | [`configuration/index.mdx`](https://github.com/microsoft/genaiscript/blob/main/docs/src/content/docs/configuration/index.mdx) |
| Reasoning models | [`reference/scripts/reasoning-models.mdx`](https://github.com/microsoft/genaiscript/blob/main/docs/src/content/docs/reference/scripts/reasoning-models.mdx) |
| Structured output | [`reference/scripts/structured-output.mdx`](https://github.com/microsoft/genaiscript/blob/main/docs/src/content/docs/reference/scripts/structured-output.mdx) |
| Schemas | [`reference/scripts/schemas.mdx`](https://github.com/microsoft/genaiscript/blob/main/docs/src/content/docs/reference/scripts/schemas.mdx) |
| MCP tools, `toolsSha`, injection detection | [`reference/scripts/mcp-tools.mdx`](https://github.com/microsoft/genaiscript/blob/main/docs/src/content/docs/reference/scripts/mcp-tools.mdx) |
| MCP tool validation | [`blog/mcp-tool-validation.mdx`](https://github.com/microsoft/genaiscript/blob/main/docs/src/content/docs/blog/mcp-tool-validation.mdx) |
| System prompts, `system.mcp` | [`reference/scripts/system.mdx`](https://github.com/microsoft/genaiscript/blob/main/docs/src/content/docs/reference/scripts/system.mdx) |
| Zod schema integration | [`guides/zod-schema.mdx`](https://github.com/microsoft/genaiscript/blob/main/docs/src/content/docs/guides/zod-schema.mdx) |

## See Also

- `resources/core-concepts.md`: framework fundamentals and script structure
- `resources/api-reference.md`: function signatures and options
- `resources/examples.md`: worked examples by use case
- `resources/patterns.md`: design patterns, performance, security reasoning
