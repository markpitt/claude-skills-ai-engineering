# Recurring provider and extension bugs

Each row gives a symptom, the cause, a check that confirms it, and the fix. Most provider faults in pi are
silent: an unknown option is ignored, a stale list is kept, a key is cached. Start from the check, not the
symptom's first guess.

Evidence for what recurs: in the operator's pi session files (49 files, counted for this skill), 94 assistant
messages carry an error stop reason, and 74 of the 101 stored error messages contain the string `429`. Rate
limiting and quota responses are therefore the most frequent recorded provider failure. Two transport failure
entries were also recorded. The counts do not show the cause of each error, and the message text is not
reproduced here.

| # | Symptom | Cause | Check | Fix |
|---|---|---|---|---|
| 1 | A live model list never changes | An option name is misspelt, or the legacy and complete forms are mixed (`refreshModels` on `createProvider` is not the name; the option is `fetchModels`) | `scripts/check_extension_names.py` on the file; `grep -a -o '.\{0,80\}<name>.\{0,80\}' <pi binary>` for an object key the script does not read | Use the documented name for the form in use |
| 2 | Refresh never runs, offline or in print mode | `refreshModels` is skipped when `context.allowNetwork` is false or the signal is aborted | Read the `context` flags in the handler; run once with network | Expected offline. Serve the saved snapshot, or say so in the report |
| 3 | `/v1/models` succeeds, chat says no model is loaded | The server lists models it can load but is not serving them | Compare `/v1/models` with the server's loaded set | Filter to loaded models in `fetchModels` (see the example) |
| 4 | 404 on chat and on model refresh | `baseUrl` lacks `/v1`; pi appends `/chat/completions` and `/models` | `curl` the composed URL with the key | Put `/v1` in `baseUrl` |
| 5 | Built-in provider catalogue vanished | Legacy `models` supplied while the intent was a redirect | `/model` shows only the extension's models | Register only `baseUrl` or `headers` for a redirect |
| 6 | A model's settings are not the ones written | An entry with the same `id` replaces the built-in model; a `modelOverrides` key with an unknown ID is ignored | `pi --list-models`; compare the model's fields | Use `modelOverrides` for metadata; check the ID spelling |
| 7 | A rotated key still fails | An `auth.json` `!command` key is cached for the life of the process | Restart pi and retry | Restart, or move to a `models.json` `!command`, which runs per request |
| 8 | A new key in config is ignored | A stored `/login` credential in `auth.json` outranks `models.json` `apiKey` | `auth.json` has an entry for the provider | Remove or update the stored credential |
| 9 | Key works in one shell only | The variable is set in a shell, not in the process that starts pi | `env` inside the same shell as `pi` | Export it before starting pi, or set it in a stored credential's `env` object |
| 10 | Provider missing from `/model` | Its credential does not resolve | `/model` lists only providers with usable auth | Fix the credential resolution |
| 11 | Wrong reasoning output, or a reasoning field rejected | Compatibility detected from an unknown host; `thinkingFormat` wrong for the server | Read the request body with a payload-logging handler in a private file | Set `thinkingFormat` and the related fields for the server, verified against its behaviour |
| 12 | Tool results rejected by a proxy | The proxy needs a name on tool results, or a `tools` field with tool history | The error text and the proxy's version | Set `requiresToolResultName` or `requiresToolsWithToolHistory` |
| 13 | `developer` role rejected | The server accepts only `system` | Error on first request | `supportsDeveloperRole: false` |
| 14 | Prompt cache misses every run | A `before_agent_start` handler returns `systemPrompt`, replacing the whole prompt | Turn on the `showCacheMissNotices` setting (documented in `settings.md`) and read the notices | Change `systemPromptOptions.sections` or `promptGuidelines` instead |
| 15 | Context overflow not recovered | The provider's overflow message is not recognised, so pi does not compact and retry | The error text | Normalise only that provider's overflow message to `context_length_exceeded`, guarded. Do not map rate limits to overflow |
| 16 | A handler's return value does nothing | The event is notification-only (the docs name `thinking_level_select`; the handler-composition table lists the notification pattern) | The event's section in `api-surface.md` | Move the change into a gate or transform event that accepts a return value |
| 17 | Session breaks after a context handler | A `context_with_system` handler dropped the system message at index 0 | Pi reports an error on the next request | Keep index 0 and check with `getCurrentSystemPrompt()` |
| 18 | A blocked command still runs, or an edited command runs unchecked | `tool_call` input is changed after the check, or the handler does not block on the failure path | Test the handler with a benign and an inert payload | Validate after mutation; fail closed when the safety decision cannot be made |
| 19 | Secrets in a log file | A payload or header logger writes the request | Read the log file's contents before sharing | Log names and sizes only; keep the file private and out of repositories |
| 20 | Claude rules missing from a session | A rule has `paths:` and no matching file was touched | Expected behaviour; check the rule's `paths` | Not a fault. Touch a matching file, or remove `paths` if it must always load |
| 21 | Claude memory index truncated | The index is larger than the loaded part | Measure it with `instruction-context-budget` | Shorten the index and move detail to topic files |
| 22 | Extension not discovered | Placed one level too deep, or in an untrusted project's `.pi/extensions` | `pi` startup output; `trust.json` | Move it to a discovered location, or trust the project |

## Two checks that catch most of these

1. **Name check.** Run `scripts/check_extension_names.py` on every extension file. It catches a wrong method or
   event name, not a wrong object key. Keys in `createProvider` and `registerProvider` config objects are
   checked by reading the docs, or by searching the binary with context, as the table shows.
2. **Model list check.** Run `pi --list-models` and compare the output with the server's own list, read by
   hand. A list that matches the server is evidence. A list that matches the code is not.

## Things this file does not establish

- Whether any of the numbered causes applies to a given server. Each row is a cause to test, not a finding.
- The exact text of the operator's stored errors. The counts above are from the files, and the messages are
  not copied into this skill.
