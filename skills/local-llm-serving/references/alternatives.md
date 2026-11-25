# Alternatives: Ollama and LM Studio

llama-swap is the choice when you need exact control of the llama.cpp build, per-model flags, and
request-driven swapping between several models on one card. The alternatives trade some of that control
for less setup. Pick by what you need to pin, not by which one is newest.

## Contents

- Comparison
- Ollama
- LM Studio
- When to switch, and what carries over

## Comparison

| Need | llama-swap | Ollama | LM Studio |
|---|---|---|---|
| Pin the exact llama.cpp build per model | Yes, by path in `cmd` | Limited: the bundled runtime | Limited: its own runtime |
| Per-model flags (`-ngl`, `--fit`, `-ctk`, `-ub`) | Yes, all of them | Partly, through Modelfile parameters and server environment | Partly, through its load settings |
| Swap models on request | Yes, by `model` field | Yes, with a loaded-model limit | Yes, through its server and UI |
| Headless service on Linux | Yes, a user unit | Yes, a system or user service | Mainly a desktop app; its server can run, but it is not the usual headless choice |
| OpenAI-compatible API | Yes | Yes | Yes |
| llama.cpp-specific endpoints (for example a decision route) | Yes, when the build has them | Not generally | Not generally |
| Model library and downloads | Manual GGUF placement | Built-in library | Built-in browser |

## Ollama

- A background service that loads models on request, with its own model store.
- Context and cache are set per model in a Modelfile (`num_ctx`), and server-wide through environment
  variables such as flash attention and KV cache type. Check the names against the release you run.
- Concurrency and the number of models loaded at once are server settings. Expect less per-model control
  over batch sizes than llama-swap gives.
- Its OpenAI-compatible route is under `/v1`. A custom llama.cpp route is not generally exposed.
- Use it when the model library and simple setup matter more than pinning the build.

## LM Studio

- A desktop application with a local server. Its GUI manages downloads and loading.
- Good for interactive use and quick trials. Less suited to a headless service that must come back after
  a reboot without a logged-in desktop.
- Its server exposes an OpenAI-compatible API. Check the port and the authentication setting in the
  release you run before wiring a client to it.
- Use it for interactive work on a desktop. Move to llama-swap when the same model must run unattended.

## When to switch, and what carries over

- The client side is the same: an OpenAI-compatible base URL and a model id. A switch changes the
  address and the id, not the agent's code, if the client reads both from configuration.
- Keep the model alias in LiteLLM (see `litellm-routing.md`). Then changing the serving backend is a
  change to the gateway entry, and every agent keeps its alias.
- Re-measure the footprint after a switch. The same GGUF can use more or less memory under a different
  runtime, so the planning in `vram-and-disk-planning.md` must be redone for it.
- Do not run two servers on the same card at the same time without measuring both. The second load can
  fail, or both can slow to a crawl.
