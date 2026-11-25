# Providers, credentials and model lists

Sources: pi's installed docs (`docs/custom-provider.md`, `docs/models.md`, `docs/models-configuration.md`,
`docs/providers.md`, `docs/extensions.md`, `docs/llama-cpp.md`) and the `createProvider` implementation
in the installed binary, checked for pi 1.5.2. Re-check the names against the installed version with
`scripts/check_extension_names.py` before writing new code.

## Three ways to add or change a provider

| Need | Use | Where |
|---|---|---|
| Point an existing provider at a gateway that keeps the upstream protocol | `pi.registerProvider("<builtin>", { baseUrl, headers })` | An extension, or `models.json` |
| Add a server that speaks a supported protocol, with a fixed model list | `models.json` (`providers` with `baseUrl`, `api`, `models`) | `~/.pi/agent/models.json` |
| A live catalogue, custom login, or a non-standard stream | `createProvider` from `@earendil-works/pi-ai/compat`, passed to `pi.registerProvider` | An extension |

Prefer `models.json` when no code is needed. Use an extension when the model list comes from a
running server, when authentication is custom, or when code is shared with other extension features.

## Registration forms

**Complete provider (new code).** `createProvider({ id, name, baseUrl, api, auth, models, fetchModels })`
returns a provider. Pass it to `pi.registerProvider(provider)`. Installed-binary facts:

- `fetchModels(context)` is the option name for live discovery. Internally it becomes the provider's
  `refreshModels`. The option is read at creation time, so a misspelt option is ignored without an error.
- Refresh runs only when `context.allowNetwork` is true and the signal is not aborted. A list that never
  refreshes offline is the expected behaviour, not a fault in the code.
- A refresh with a persisted snapshot publishes through `context.publish({ persist, update })`. The
  snapshot is what a later offline start reads. A live server can skip persistence.
- Models of an unknown type are dropped. A model with no `type` is a chat model.

**Legacy form.** `pi.registerProvider("<name>", { name, baseUrl, apiKey, api, headers, authHeader, models, refreshModels, oauth, streamSimple })`.
Its `refreshModels` returns model definitions, not a `Provider`. The docs call this form legacy: it still works,
and existing extensions use it.

**Factory timing.** Calls made while the extension factory runs are queued and applied when the runner starts.
Calls made later (for example from a command handler) take effect at once, without `/reload`.
`pi.unregisterProvider(name)` removes a provider and restores any built-in it had overridden.

## Redirect a built-in, and the replacement trap

```ts
pi.registerProvider("anthropic", {
	baseUrl: "https://gateway.example.com/anthropic",
	headers: { "X-Gateway-Key": "$GATEWAY_API_KEY" },
});
```

Registering only `baseUrl` or `headers` keeps the built-in catalogue, its authentication and its
compatibility settings. Supplying `models` replaces the provider's models across chat, image and
classifier operations. Copying the built-in list into an extension for a small change turns a
redirect into a catalogue replacement that drifts.

The same rule applies in `models.json`: a `models` entry whose `id` matches an existing model replaces
it. `modelOverrides` changes metadata for an existing model without replacing the list, and an override
whose ID does not exist is ignored without an error.

## Credentials: where a key comes from, and in what order

From `docs/models.md`, the first source that resolves wins:

1. A runtime `--api-key` flag.
2. A stored credential in `~/.pi/agent/auth.json`.
3. An `apiKey` in `models.json`.
4. The provider's environment variable, or ambient cloud credentials.

Provider extensions can define their own resolution, as the `resolve` callback in the example does.

`auth.json` holds `{ "<provider>": { "type": "api_key", "key": "...", "env": { ... } } }`. The `key` may be
a literal or a `!command`:

- `!command` in `auth.json` runs once when the key is first needed and caches its stdout for the life of
  the process. A rotated key needs a restart. Empty output, a timeout or a non-zero exit leaves the key
  unresolved until a restart.
- `!command` in `models.json` runs at request time and is not cached.
- `$NAME` and `${NAME}` read environment variables. `$$` is a literal `$`, and `$!` a literal leading `!`.
- The `env` object in a stored credential overrides the process environment for that provider only.

Rules for handling secrets in an extension: never write tokens, headers or whole provider responses to a
log. `docs/extensions.md` says extensions run with the same operating-system permissions as pi, and the
payload hooks see the prompt and the tool definitions. A file that logs `before_provider_request` payloads holds the
conversation: keep it private and out of repositories.

## Listing models, and when the list is refreshed

- `/model` opens the picker. It shows models whose provider has usable authentication.
- For OpenRouter, the docs list the refresh points: startup in interactive mode, opening `/model`, after
  `/login`, and `pi update --models`. The last list is saved and used offline and in print and RPC modes.
  Other live providers follow their own `fetchModels` or `refreshModels` and the same `allowNetwork` rule.
- After switching a key outside `/login`, the previous key's list stays until the next refresh.
- A provider whose model is in `models.json` but whose credential does not resolve does not appear in
  `/model`. The docs call this out in troubleshooting, and it is the first thing to check.

## OpenAI-compatible local servers

Use `api: "openai-completions"` for servers such as llama.cpp, Ollama, LM Studio, vLLM and SGLang, unless
the server implements another protocol pi supports. Points to get right:

- **The base URL ends in `/v1`.** pi appends `/chat/completions` and `/models`. Without `/v1`, both fail.
- **A key is required by the client.** Ollama ignores it, so the docs use a dummy key. Send a placeholder
  rather than leaving the field empty.
- **Compatibility is set per server.** The `compat` object (see the table in `docs/models-configuration.md`)
  describes verified differences. Set the fields you have verified, and do not enable one because a server
  claims compatibility. Fields that matter most for local servers:
  - `maxTokensField`: `"max_tokens"` for llama-server, as `references/example-local-provider.ts` sets. The
    default is detected from the URL.
  - `supportsDeveloperRole: false` for servers that reject the `developer` role.
  - `thinkingFormat`: the reasoning parameter a server reads. Left unset, pi detects it from the URL, and
    an unrecognised host gets the wrong format.
  - `requiresToolResultName`, `requiresAssistantAfterToolResult`, `requiresNonNullAssistantContent`,
    `requiresToolsWithToolHistory`: proxies in front of other providers differ here. The last one is for
    older LiteLLM versions, per the docs.
  - `supportsUsageInStreaming`: defaults to true. Turn it off for a server that rejects `stream_options`.
- **A server's `/v1/models` may list models it is not serving.** The example filters on a `loaded` flag
  for that reason. A chat call to an unloaded entry fails at request time.
- **llama.cpp router mode.** Start `llama serve` without `--model`. Use `--no-models-autoload` to keep loading
  explicit, through the `/llama` command. Only models the router has loaded appear in `/model`.

## Claude-family endpoints

- A proxy in front of Anthropic is `api: "anthropic-messages"`, with `baseUrl` set to the proxy. Redirect the
  built-in `anthropic` provider with `baseUrl` alone where that is enough.
- `authHeader: true` adds `Authorization: Bearer` with the resolved key. Use it only where the gateway
  takes that header, and test one request to confirm.
- `compat.supportsMessageThreads` is true only for api.anthropic.com by default. A gateway that forwards
  the thread field needs it set to true explicitly.

## Checklist before reporting a provider as working

1. `pi --list-models` (or `/model`) shows the expected IDs. Read the output yourself.
2. One ordinary prompt returns text, and one prompt with a tool call returns a tool result.
3. A deliberately wrong key produces an authentication error, not a silent empty answer.
4. The name check (`scripts/check_extension_names.py`) passes for the file.
5. Run the provider's own tests where the project has them, through `mp-sandbox-test` if they run code
   from the repository.
