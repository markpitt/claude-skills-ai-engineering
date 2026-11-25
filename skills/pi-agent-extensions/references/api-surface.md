# Extension API surface (pi 1.5.2)

Names below were read from pi's installed docs (`docs/extensions.md` and `docs/custom-provider.md` in the
pi package) and the binary. The docs are authoritative for signatures; the binary confirms that a name
exists in this version. Re-check after an upgrade with `scripts/check_extension_names.py`.

## Loading

- Default export: a factory `(pi: ExtensionAPI) => void`, sync or async. Async factories are awaited before
  startup continues, so providers registered there are available to startup model selection.
- Auto-discovered locations, one level deep: `~/.pi/agent/extensions/*.ts|js`, `~/.pi/agent/extensions/*/index.ts`,
  and a subdirectory with a `package.json` that has a `pi.extensions` field. Project-local `.pi/extensions/`
  loads only after the project is trusted (`~/.pi/agent/trust.json` records trusted folders).
- `pi -e <path>` loads a file for one run. `/reload` re-reads discovered locations in an active session.
- Settings can add paths (`extensions` in `settings.json`) or packages (`packages`).
- Imports: `@earendil-works/pi-coding-agent` (types and `CONFIG_DIR_NAME`, `isToolCallEventType`), `@earendil-works/pi-ai`
  (`StringEnum`, `createProvider` and related helpers), `@earendil-works/pi-ai/compat` (provider construction
  and built-in API implementations), `typebox` for tool schemas, and Node built-ins. npm dependencies work
  with a `package.json` beside the extension.
- `CONFIG_DIR_NAME` is the config folder name (`.pi` by default). Use it rather than a literal, because
  rebranded builds rename it.

## Events (`pi.on(name, handler)`)

Handler composition, from the docs:

| Pattern | Events | Effect |
|---|---|---|
| Notification | most events | Return value ignored |
| In-place mutation | `before_provider_headers`, `before_agent_start` (`systemPromptOptions`), `tool_call` (`input`) | Later handlers see the change |
| Chained transform | `input`, `context`, `context_with_system`, `message_end`, `tool_result`, `before_provider_request` | Each handler receives the previous handler's return |
| Gate | `input` (`handled`), `tool_call` (`block`), `user_bash`, session operations | First gate stops the normal path |
| Last override | `cache_warming_decision` | Last returned action wins |

Events used most, with their return shapes:

- `session_start` (`event.reason`: `startup`, `reload`, `new`, `resume`, `fork`). Notification.
- `input`: return `{ action: "continue" | "transform" | "handled", text? }`. Runs after extension commands,
  before skill and template expansion. `handled` skips the agent entirely.
- `before_agent_start`: return `{ message?, systemPrompt? }`. Returning `systemPrompt` replaces the whole
  prompt for the run. Prefer changing `systemPromptOptions.sections`, `promptGuidelines` or `selectedTools`:
  pi then sends only the changed sections. `systemPromptOptions.contextFiles` lists the context files
  pi has loaded, which is a measurement surface.
- `context`: return `{ messages }`. The prompt and tool declarations are not in `messages`; pi re-adds them.
- `context_with_system`: return `{ messages }` with the full transcript. Keep the system message at index 0,
  or pi reports an error. Check the result with `getCurrentSystemPrompt()` and `getCurrentTools()`.
- `before_provider_headers`: mutate `event.headers`. Set a key to a string to add it, or to `null` to delete.
- `before_provider_request`: return `undefined` to keep the payload, or a new payload to replace it.
- `after_provider_response`: `event.status` and normalised `event.headers`. Header availability depends on the
  provider.
- `provider_stream_event`: read-only, awaited in stream order. A slow handler delays the stream.
- `tool_call`: `event.input` is mutable and is not re-validated after mutation. Return
  `{ block: true, reason?, terminate? }` to refuse. Sibling calls in one assistant message are preflighted
  in order but may not see each other's results.
- `tool_result`: chained transform of the result.
- `model_select`, `thinking_level_select`: notification on selection.
- `agent_end` is not the final-idle signal. Use `agent_settled`, which fires after `agent_before_settle`
  and any continuation.

Typed tool narrowing: `isToolCallEventType("bash", event)` gives the input type for a built-in tool.

## Context objects

- `ctx.ui`: `notify(msg, level)`, `confirm(title, body)`, `select`, `input`, `editor`, `setStatus(key, text)`,
  `setWidget(key, lines)`, `setTitle`, `custom(...)`. Dialogs need `ctx.hasUI`; `ctx.mode` is `tui`, `rpc`,
  `json` or `print`. In print mode `ctx.hasUI` is false, so guard every dialog.
- `ctx.cwd`, `ctx.isProjectTrusted()`, `ctx.sessionManager` (entries, session file).
- `ctx.modelRegistry`: `getProvider(id)` returns the effective provider; `getProviderAuth(id)` resolves the
  current key, headers, base URL and provider environment. Avoid logging the result.
- `ctx.model`, `ctx.thinkingLevel`, `ctx.scopedModels` (read-only, from `--models` or `enabledModels`).
- `ctx.signal`, `ctx.isIdle()`, `ctx.abort()`, `ctx.hasPendingMessages()`, `ctx.getContextUsage()`,
  `ctx.compact()`, `ctx.getSystemPrompt()`.
- Command context adds `ctx.waitForIdle()`, `ctx.newSession()`, `ctx.fork()`, `ctx.navigateTree()`,
  `ctx.switchSession()` and `ctx.reload()`. Session replacement has footguns: read its lifecycle section before
  using them from a handler that continues after the call.

## ExtensionAPI methods

- `pi.registerTool(definition)`: `name`, `label`, `description`, `parameters` (TypeBox), `execute(toolCallId,
  params, signal, onUpdate, ctx)`, optional `promptSnippet`, `promptGuidelines`, `defaultActive`, rendering.
  Guidelines are appended flat, so each must name the tool: write "Use my_tool when...", not "Use this tool".
  Argument validation coerces numeric strings and single values; `Type.Refine()` is not run.
- `pi.registerCommand(name, { description, handler(args, ctx) })`. Duplicate names get numeric suffixes
  (`/review:1`).
- `pi.registerProvider(name | provider, config?)`, `pi.unregisterProvider(name)`. See `providers-and-auth.md`.
- `pi.registerVirtualModel(model)`, `pi.unregisterVirtualModel(provider, id)`: a selectable catalogue entry
  that routes to a physical model.
- `pi.registerMcpServer(name, config)`, `pi.unregisterMcpServer(name)`, `pi.getMcpServers()`.
- `pi.registerToolRenderer(resolver)`, `pi.registerMessageRenderer`, `pi.registerEntryRenderer`,
  `pi.registerMarkdownTransformer`, `pi.registerShortcut`, `pi.registerFlag`.
- `pi.sendMessage(message, { triggerTurn? })`, `pi.sendUserMessage(content, { expandPromptTemplates? })`.
- `pi.appendEntry(customType, data?)`: stores state in the session, so it survives a restart.
- `pi.setSessionName`, `pi.getSessionName`, `pi.setLabel`, `pi.getCommands`.
- `pi.exec(command, args, options?)`: runs a process. Treat its output as untrusted when it reaches a prompt.
- `pi.getActiveTools()`, `pi.getAllTools()`, `pi.setActiveTools(names)`, `pi.setModel(model)`,
  `pi.getThinkingLevel()`, `pi.setThinkingLevel(level)`, `pi.getSettings()`.
- `pi.events`: an event bus shared between extensions.

## Dialogs and widgets, in one line each

- `ctx.ui.confirm` gates a destructive action. Use it in a `tool_call` handler and return `block` on refusal.
- `ctx.ui.setStatus` writes to the footer and `ctx.ui.setWidget` above the editor. Both are for the operator's
  eyes; do not put a secret in either.
