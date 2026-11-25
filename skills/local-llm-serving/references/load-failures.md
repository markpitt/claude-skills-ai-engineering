# Diagnosing load failures

Match the symptom to the row, then run the check. Read the log first: the proxy log and the model's own
log (llama-swap prints the upstream output into the same journal) carry the decisive line.

## Contents

- Collecting the evidence
- Symptom table
- Out of memory during load
- Wrong or damaged file
- Flash attention or quantised cache refused
- Port already in use
- Endpoint returns 404
- Cold load longer than the health-check timeout
- First request times out after a swap
- Model is slow after load (CPU offload)
- Models keep unloading and reloading

## Collecting the evidence

```sh
journalctl --user -u llama-swap --since "-30 min" --no-pager > "$TMPDIR/llama-swap.log"; echo "journal exit $?"
grep -n -i -E 'out of memory|cudaMalloc|failed|error|invalid|unknown|unsupported|address already|offloaded' \
  "$TMPDIR/llama-swap.log"; echo "grep exit $?"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
```

- Read the whole matched section around the first error, not just the matched line. The earliest error
  is usually the cause; later lines are consequences.
- `grep` exit 1 means no match. It does not prove the log is clean. Check that `journal exit` is 0 and
  that the log is not empty.
- `--compute-apps` shows the processes holding GPU memory. A stale model from before a restart can hold
  memory that a new load then cannot get.

## Symptom table

| Symptom in the log or client | Likely cause | First check |
|---|---|---|
| `out of memory`, `cudaMalloc failed`, load aborts after weights | Weights plus KV plus compute buffer exceed free VRAM | Free VRAM before load; the planning reference; lower `-c`, `-ub`, `-np`, or quantise KV |
| `invalid magic`, `unknown tensor type`, `unknown model architecture`, `failed to load model` on a file | Damaged download, wrong quant, or a GGUF newer than the build | `sha256sum` against the publisher; `llama-server --version`; the model card's build requirement |
| `V cache quantization requires flash_attn`, or a message naming flash attention | Quantised V cache without flash attention, or an architecture that refuses it | Add `-fa on`; otherwise drop `-ctv` quantisation or use f16 |
| `address already in use` | Another process holds the upstream or proxy port | `ss -ltnp` on the port (name and pid only) |
| `404` on an endpoint the client uses, model loads | Build too old for that endpoint | `llama-server --version`; the endpoint's minimum build |
| Client sees a timeout, log shows a load still in progress | Cold load longer than the health-check timeout, or the client's own read timeout | `healthCheckTimeout`; the client timeout; the cold-start time |
| First request fails, second succeeds | Client gave up during the cold load | Raise the client timeout; warm the model at startup if the workload allows |
| Answers slow after load, GPU utilisation low | Some layers on the CPU | `offloaded N/N layers` line; `-ngl all`; `--fit off` |
| Load and unload repeat in the log | Two ids share a set they cannot share, or a short `ttl` with bursty clients | Routing sets; the `ttl` values; which clients use which ids |
| Service active, model list empty or missing an id | Config not reloaded, or the entry failed to parse | The unit's status; YAML parse (`SKILL.md`, procedure 3) |

## Out of memory during load

1. Check nothing else holds the card. `nvidia-smi --query-compute-apps=...`. A model from a previous run,
   or the display on Windows, can take the headroom.
2. Compare the failing config with the planning arithmetic. Which term is larger than expected? Usually
   the KV cache at the configured `-c`, or the compute buffer at a large `-ub`.
3. Change one thing: lower `-c` first, then `-ub`, then quantise the KV cache (needs `-fa on`), then the
   quant of the weights. Restart and measure after each change.
4. Do not fix it by allowing layers in system RAM. That turns a load error into a slow model.

## Wrong or damaged file

- A truncated download loads partway and then fails, often with an unexpected end of file or an invalid
  tensor. Compare `sha256sum` with the checksum the publisher gives. A matching size is not enough.
- A quant the build does not support fails with an unknown tensor type. Use a quant from the same family
  the build supports, or update the build.
- A GGUF from a newer release than the build fails with an unknown architecture. Check the model card for
  the minimum build.

## Flash attention or quantised cache refused

- Set `-fa on` for any model with `-ctv` quantisation.
- If the architecture rejects flash attention, run it with f16 KV (`-ctk f16 -ctv f16` or no cache-type
  flags) and a smaller context, and record that the model runs without it.

## Port already in use

- The proxy listens on one port. Each model's `llama-server` takes its own port from `startPort` upwards.
- `ss -ltnp 'sport = :<port>'` shows what holds the port, by name and pid. Do not print the full command
  line of a process another agent started: it may carry a brief (see the global rule on not reading a
  dispatched agent's command line).
- Fix the collision by moving `startPort` or the proxy port, not by killing the other process. If the
  other process is another agent's service, it is that agent's to stop.

## Endpoint returns 404

- The endpoint exists in newer builds only. The proxy forwards the request; the upstream says 404.
- Check the build: `"$LLAMA_SERVER" --version`. Check the minimum build named by the model's card or by the
  client's documentation. Update the pinned build path in the macro, not in each model.
- A client that calls a decision or other custom endpoint may also need a pass-through route in LiteLLM
  (see `litellm-routing.md`). A 404 can come from the gateway rather than from llama-server.

## Cold load longer than the health-check timeout

- The proxy waits up to `healthCheckTimeout` for the model to answer its health check. If the load takes
  longer, the proxy reports the model as failed.
- Measure the cold load: time the first request against a warm one (`-w '%{time_total}'`). Read the
  load timings in the model log.
- Raise `healthCheckTimeout` above the measured cold load, with margin. Keep the model on a fast local
  filesystem so the load is mostly the read from that disk.

## First request times out after a swap

- The request waits while the model loads. A client with a short read timeout gives up mid-load, and the
  model then finishes loading with nobody listening.
- Raise the client's timeout above the cold load. For LiteLLM, see `litellm-routing.md`.
- If the workload allows, preload the model at startup (`hooks.on_startup.preload`), or keep its `ttl`
  longer so it is not evicted between bursts.

## Model is slow after load (CPU offload)

- Look for `offloaded N/M layers` in the model log. `N` should equal `M`.
- If `-ngl` is not `all`, or the fitter moved layers to the CPU, set `-ngl all` and `--fit off`. Then
  the load fails loudly if it does not fit, which is the point.
- A small model that is still slow may be running on the CPU because the GPU build is not in use. Check
  the build is the CUDA one (`llama-server --version`, and the build's own notes).

## Models keep unloading and reloading

- Two ids in one set they cannot share, or in no set but used alternately, make each request evict the
  other. Check the routing sets (`llama-swap-config.md`).
- A short `ttl` with clients that pause longer than it causes a reload on every burst. Lengthen the
  `ttl`, or accept the cold start and say so in the client's timeout.
