# llama-swap configuration

llama-swap is a proxy in front of llama.cpp's `llama-server`. It listens on one port, reads the
`model` field of each request, starts the matching `llama-server` on its own upstream port if it is not
running, waits for it to become healthy, and forwards the request. It unloads idle models after their
`ttl`. Check the schema for your release before relying on a key that is not in this reference: the
keys below are the ones in use on the author's setup at the time of writing.

## Contents

- Top-level keys
- Macros
- Model entries
- Flags that matter for a single consumer GPU
- Several context lengths from one GGUF
- Routing: sets (matrix) and groups
- Hooks: preloading at startup
- Worked minimal config

## Top-level keys

```yaml
healthCheckTimeout: 300     # seconds a model may take to become healthy: must cover a cold load
logLevel: info
logToStdout: proxy          # proxy log to stdout, which journald captures under a user unit
startPort: 10001            # each model's llama-server gets its own port from here upwards
unloadTimeout: 10           # seconds allowed for an unload before it is forced
includeAliasesInList: true  # /v1/models also lists the aliases
```

- `healthCheckTimeout` is the single most common cause of "the first request fails after a swap".
  Set it above your slowest cold load, with margin. A large GGUF read from a slow disk can take minutes.
- `startPort` must not collide with another service. Leave a gap from the proxy's own port.

## Macros

```yaml
macros:
  "llama-server": "${env.HOME}/.local/share/llama-swap/llama-bNNNN/llama-server"
  "models": "${env.HOME}/models"
  "decision-args": >
    --host 127.0.0.1 --port ${PORT} --no-webui --alias ${MODEL_ID}
    -ngl all --fit off -cram 0 -t 4
```

- `${env.NAME}` reads an environment variable at load time.
- `${PORT}` and `${MODEL_ID}` are filled in by llama-swap for each model. `${PORT}` is the model's own
  upstream port, not the proxy port.
- Macros are for the flags shared by several models. Keep one `llama-server` path per build you pin, so
  rolling back a build is a one-line change.

## Model entries

```yaml
models:
  "qwen-small-q8":                        # the id a client sends in the "model" field
    name: "Small model (Q8_0)"           # shown in the model list
    description: "Source, quant, licence, purpose"
    ttl: 3600                            # idle seconds before unload; 0 keeps it loaded until swapped
    aliases: ["small"]                   # optional extra ids for the same model
    cmd: |
      ${llama-server}
      --host 127.0.0.1 --port ${PORT} --no-webui --alias ${MODEL_ID}
      -m "${models}/Small-9B-Q8_0.gguf"
      -ngl all --fit off -cram 0 -t 4
      -c 16384 -np 4 -kvu -b 4096 -ub 4096 -fa on
```

- `cmd` is the whole `llama-server` command line. Multi-line YAML block scalars keep it readable. Keep
  one flag group per line so a diff shows what changed.
- `--alias ${MODEL_ID}` makes the `model` field in responses equal the id. Without it, the response
  reports the GGUF path, which breaks clients that match on the id.
- `ttl` trades VRAM for load time. A short ttl frees the card for other models or other work. A
  long ttl avoids the cold start between bursts of requests.
- `cmd` may use a different `llama-server` build per model. Use this for a patched build that one
  model needs (for example, a build carrying a local patch) without changing the others.

## Flags that matter for a single consumer GPU

| Flag | Why it is set |
|---|---|
| `-ngl all` | Offload every layer to the GPU. Partial offload is the usual cause of a slow model that loads fine. |
| `--fit off` | Do not let the fitter place layers in host RAM. An oversized model then fails at load. Check your build accepts it (`llama-server --help`). |
| `-cram 0` | Turn off the host-RAM prompt cache. Useful when requests never reuse a prefix. Costs time when they do. |
| `-t 4` | CPU threads for the non-GPU work. The GPU does the decoding. Match your CPU's physical cores. |
| `-c N` | Total context for the model. With `-np` and no unified KV, each slot gets `N / np`. |
| `-np N` | Parallel slots, so `N` requests can be in flight. Each slot costs scheduling state. |
| `-kvu` | Unified KV cache: slots share one pool of `-c`. A short request no longer pays for an empty slot. |
| `-b N`, `-ub N` | Logical and physical batch. A prompt that must go in one physical batch needs `-ub` at least as large. The compute buffer grows with `-ub`. |
| `-fa on` | Flash attention. Needed for a quantised V cache. Some models or cards reject it. |
| `-ctk q8_0 -ctv q8_0` | Quantised KV cache. Roughly halves the KV memory. Quality cost is usually small at q8_0 and larger at q4_0. |
| `--jinja` | Use the GGUF's chat template. Needed for chat-style requests on most instruct models. |
| `--chat-template-kwargs '{...}'` | Per-model template switches, such as turning off a thinking block. |
| `--no-webui` | No built-in web interface on the upstream port. |
| `--embeddings --pooling last` | Embedding models. The pooling type must match the model's design. |
| `--temp`, `--top-p`, `--top-k`, `--min-p` | Sampling defaults per model. Clients may still override them per request. |

Exact flag names and accepted values change between llama.cpp builds. Confirm each one against
`"$LLAMA_SERVER" --help` for the build you pin, before the config depends on it.

## Several context lengths from one GGUF

The same weights can be exposed at two context lengths, with two ids:

```yaml
models:
  "model-64k":
    ttl: 900
    cmd: |
      ${llama-server} --host 127.0.0.1 --port ${PORT} --alias ${MODEL_ID}
      -m "${models}/Model-Q4_K_M.gguf" -ngl all --fit off -t 4
      -c 65536 -np 1 -fa on
  "model-128k-q8kv":
    ttl: 900
    cmd: |
      ${llama-server} --host 127.0.0.1 --port ${PORT} --alias ${MODEL_ID}
      -m "${models}/Model-Q4_K_M.gguf" -ngl all --fit off -t 4
      -c 131072 -np 1 -fa on -ctk q8_0 -ctv q8_0
```

Two entries are two processes. They do not share VRAM or a warm cache, so a client that alternates
between them pays a cold load on every switch. Put the two in no routing set, so asking for one
unloads the other, and state in the entry's `description` which context and cache type each is for.
Use a second id only when a client genuinely needs the other setting.

## Routing: sets (matrix) and groups

Two ways llama-swap decides which models may run at once. Use one per config.

### Sets (matrix routing)

Newer releases let you write which models may be loaded together:

```yaml
routing:
  router:
    use: matrix
    settings:
      matrix:
        vars:
          e: embedding-model
        evict_costs:
          e: 10
        sets:
          small: "e & (decision-a | decision-b)"
          large: "e & big-model"
```

- A model named in no set can only run alone. Asking for it unloads everything else, and the next
  request for anything else unloads it.
- `evict_costs` weights what gives way when a set must change. Read the schema for your release for the
  exact rule before tuning it; the value here is the author's choice, not a universal default.
- The sets above mean an embedder can stay resident beside any one of several small models, so a
  search that embeds and then asks a decision model does not reload the embedder each time.

### Groups (older form)

Older configs use `groups` with members and `swap`/`exclusive`/`persistent` flags. The intent is the
same: a group defines which members may be resident together. Check the schema for the release you run,
because the semantics of `swap` and `exclusive` have changed between releases.

## Hooks: preloading at startup

```yaml
hooks:
  on_startup:
    preload:
      - embedding-model
```

Preloading loads the named model when the proxy starts. Use it only for a model whose cold load would
break a latency-sensitive client. A preloaded model still obeys its `ttl` and the routing sets. Each
preload costs VRAM the whole time it is resident, so budget for it before adding it.

## Worked minimal config

A single model, with one set of conservative flags. Replace the paths and names.

```yaml
healthCheckTimeout: 300
logToStdout: proxy
startPort: 10001

macros:
  "llama-server": "${env.HOME}/.local/share/llama-swap/llama-bNNNN/llama-server"
  "models": "${env.HOME}/models"

models:
  "example-8b-q8":
    name: "Example 8B (Q8_0)"
    description: "Illustrative entry: replace the GGUF and the flags after measuring"
    ttl: 1800
    cmd: |
      ${llama-server} --host 127.0.0.1 --port ${PORT} --no-webui --alias ${MODEL_ID}
      -m "${models}/Example-8B-Q8_0.gguf"
      -ngl all --fit off -cram 0 -t 4
      -c 8192 -np 2 -kvu -b 2048 -ub 2048 -fa on --jinja
```
