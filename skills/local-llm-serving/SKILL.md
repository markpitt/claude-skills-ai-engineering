---
name: local-llm-serving
description: Serve local GGUF models on a single consumer GPU (for example 24 GB) through llama-swap, optionally fronted by LiteLLM, with Ollama and LM Studio as alternatives. Covers the llama-swap config.yaml (models, llama-server flags, ttl, routing sets, proxy port), GGUF placement and disk planning, VRAM-fit arithmetic for weights and KV cache, a systemd --user unit with linger, health checks, diagnosing load failures and cold-start timeouts, LiteLLM aliases, and WSL2 GPU passthrough. Use when setting up, sizing, debugging or routing a local model server, when a local model will not load, runs out of memory or is slow after a swap, or when an agent must reach a local model through LiteLLM. Do NOT use to ask a System One decision model a question or to triage with the decide tool (use decision-models), for choosing a hosted API model, or for GPU driver or CUDA development.
license: Apache-2.0
metadata:
  version: "1.0.0"
  tags: "llama-swap, llama.cpp, gguf, vram, kv-cache, litellm, systemd, wsl2, local-llm"
---

# Local LLM serving

Serve GGUF models from one consumer GPU behind llama-swap, with an optional LiteLLM gateway in front.
The working rule: decide what fits on paper, measure it on the card, then route to it.

Every path, port, unit name and model name here is a placeholder. A private host overlay may be loaded
alongside this skill for a particular machine. If it is, its paths, ports, unit names and model
names replace the placeholders below. Read it before running the generic steps.

## Critical

- **Size before you load.** A model too big for the card should fail at load time. With the wrong
  flags it instead runs with layers in system RAM at a small fraction of the speed. Plan with
  `references/vram-and-disk-planning.md` first, and pin full GPU offload (`-ngl all`) with the fit
  guard off (`--fit off` on builds that have it) so an oversized model fails loudly.
- **A restart interrupts every client.** Restarting llama-swap or forcing an unload drops in-flight
  requests and reloads the model for everyone. Another agent may be mid-request. Run procedure 6
  first, and do not restart a proxy another session depends on without its owner's agreement.
- **Never put an API key in a config file, unit file, log or chat.** Read it from a mode-600 key file
  or an environment variable. Redact any key in pasted output.
- **`/v1/models` proves the proxy is up, not that a model is loaded.** A model loads on first request.
  Prove a model works with a one-token completion (procedure 5).
- **Use one port per concern.** llama-swap listens on one port and gives each model its own
  upstream port from `startPort`. A collision shows as "address already in use" in the model log.
- **Keep paths relative to `$HOME` or `%h`** in anything shared. Do not copy absolute private paths or
  machine names into shared documents.

## Situation to reference

| Situation | Read |
|---|---|
| Writing or editing the llama-swap `config.yaml`: macros, models, routing sets, groups | `references/llama-swap-config.md` |
| Deciding whether a model and context fit in VRAM, or where GGUF files go and how much disk they need | `references/vram-and-disk-planning.md` |
| Installing the proxy as a `systemd --user` unit, linger, and the health-check sequence | `references/service-and-health.md` |
| A model fails to load, runs out of memory, times out, or is slow after a swap | `references/load-failures.md` |
| Putting LiteLLM in front: aliases, `api_base`, cold-start timeouts | `references/litellm-routing.md` |
| Running under WSL2: GPU visible or not, driver rules, disk and memory limits | `references/wsl2-gpu.md` |
| Choosing between llama-swap, Ollama and LM Studio | `references/alternatives.md` |

## Procedures

Commands assume `LLAMA_URL` is the proxy address, for example `export LLAMA_URL=http://127.0.0.1:8080`.
Set it to the proxy you actually run.

### 1. Plan the model on paper

1. Record the GGUF file size. That is the weights figure (rough rule in the VRAM reference).
2. Work out the KV cache for the context you want, using the layer, KV-head and head-dimension counts
   from the model card or the GGUF metadata. Count full-attention layers only.
3. Add the compute buffer (grows with `-ub`; measure it, procedure 4) and about 1 GiB of headroom.
4. Compare the total with the card's free memory, not its nameplate size.
5. If it does not fit, change one thing at a time: smaller quant, shorter context, quantised KV cache
   (needs flash attention), fewer slots, smaller `-ub`, or a smaller model. Do not plan on system RAM.

### 2. Place the GGUF file and check the disk

```sh
df -h "$MODELS_DIR"                                  # free space on the volume holding the models
ls -lh "$MODELS_DIR"/*.gguf                          # sizes; check each one is complete
sha256sum "$MODELS_DIR/<file>.gguf"                  # compare with the publisher's checksum
```

Keep the models on the Linux filesystem, not on a Windows-mounted path (see `references/wsl2-gpu.md`).
Keep about 20 percent of the backing volume free. Before deleting an old GGUF, prove nothing references it:

```sh
grep -rn "<file>.gguf" ~/.config/systemd/user "$LLAMA_CONFIG_DIR" 2>/dev/null; echo "grep exit $?"
```

Exit 0 means a reference exists. Exit 1 means none was found. Exit 2 means a path error, not a clean result.

### 3. Add or edit a model entry

1. Edit the config following `references/llama-swap-config.md`. Give the model a stable id, a `ttl`, and
   explicit flags for offload, context, parallel slots and batch sizes.
2. Check the YAML parses. Use the repository's Python tooling rather than a global install:

```sh
uv run --with pyyaml python3 -c 'import sys, yaml; yaml.safe_load(open(sys.argv[1])); print("yaml ok")' "$LLAMA_CONFIG"
```

   A parse error prints a traceback and a non-zero exit. Fix it before restarting anything.

### 4. Restart the proxy and watch the first load

```sh
systemctl --user restart llama-swap.service          # interrupts clients: see procedure 6 first
systemctl --user status llama-swap.service --no-pager
journalctl --user -u llama-swap -n 80 --no-pager     # the last 80 lines, including the load log
```

Read the log for `offloaded N/N layers` and for the VRAM figures llama-server prints. Then measure
memory with nothing else loaded (`nvidia-smi` in procedure 5) before and after the first full-length
request. The difference is the real footprint: weights, KV cache and compute buffer together.

### 5. Verify in this order

```sh
systemctl --user is-active llama-swap.service        # prints "active"; exit 0 when it is
curl -fsS --max-time 10 "$LLAMA_URL/v1/models"; echo "models exit $?"
nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv
curl -fsS --max-time 300 "$LLAMA_URL/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model":"<model-id>","messages":[{"role":"user","content":"Reply with OK."}],"max_tokens":4,"stream":false}'
echo "completion exit $?"
```

- The first completion after a swap includes the cold load. Use `--max-time 300` or more, and time it
  with `-w '%{time_total}\n'` to learn the cold-start cost.
- A second completion should be quick. If it is slow too, the model is on the CPU (see `load-failures.md`).
- On WSL, `nvidia-smi` may need its full path: `/usr/lib/wsl/lib/nvidia-smi`.

### 6. Check who is using the proxy before disrupting it

```sh
ss -tnp state established '( sport = :8080 or dport = :8080 )'   # who holds connections (name and pid only)
nvidia-smi --query-compute-apps=pid,used_memory --format=csv      # what holds GPU memory
```

Use the proxy port in place of 8080 if yours differs. If a connection belongs to an agent you do not
own, do not restart the proxy and do not unload its model. Report it to the operator or to the owning session.
Never stop or restart another agent's session to free the GPU.

### 7. Route agents through LiteLLM

Follow `references/litellm-routing.md`. The short version: one alias per role, the llama-swap model id
behind it, the key read from the environment, and a read timeout longer than a cold load.

### 8. Diagnose a failure

Start with the proxy log and the model log, then match the message in `references/load-failures.md`:

```sh
journalctl --user -u llama-swap --since "-30 min" --no-pager > "$TMPDIR/llama-swap.log"; echo "journal exit $?"
grep -n -i -E 'out of memory|cuda|failed|error|invalid|unknown|address already in use' "$TMPDIR/llama-swap.log"; echo "grep exit $?"
```

Keep the output to a file and read the grep exit code too. Exit 1 from grep means no match, which is
not the same as a clean log. Exit 2 means the search itself failed.

## Guardrails

- Do not run a model by hand on the same port as the proxy. It hides which process owns the GPU.
- Do not raise `-c`, `-np` or `-ub` in the config and restart in one step. Change one and measure.
- Do not treat a model's advertised context as usable context on this card. Measure the largest context
  that loads and answers a full-length request.
- A model answer is not a test result. Use a completion to prove the service works, and use a real
  test suite to prove the software that calls it works.
