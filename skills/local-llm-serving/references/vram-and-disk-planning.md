# VRAM fit and disk planning

Plan on paper, then measure. The paper figure tells you what to try; the measured figure on the card
decides. Keep every number here as a rough guide until you have measured it on your own build and card.

## Contents

- The budget
- Weights
- KV cache: the formula and a worked example
- Bytes per element by cache type
- Compute buffer and batch sizes
- Slots and context
- Flash attention and quantised KV
- Why not spill to system RAM
- Measuring the real footprint
- Disk planning

## The budget

```
usable VRAM  =  card total  -  memory already used by the display and other processes  -  headroom
needed       =  weights  +  KV cache at the chosen context  +  compute buffer
fits         =  needed  <=  usable VRAM
```

- Use `nvidia-smi --query-gpu=memory.total,memory.used --format=csv` for the card total and the idle use.
  On Windows-hosted WSL2 the display also uses VRAM, so the idle figure is not zero.
- Keep about 1 GiB of headroom. The compute buffer and the allocator both move a little between requests,
  and a model that fits exactly fails on the first long prompt.
- A 24 GB card is about 24 GiB of memory, shared. Plan in GiB and check the units `nvidia-smi` prints.

## Weights

The GGUF file size is the weights. Before download, estimate:

```
weights (GB)  ~=  parameters (billions)  x  bits per weight  /  8
```

Rough bits per weight: Q8_0 about 8.5, Q4_K_M about 4.8 to 4.9. Real files differ because some tensors
(embeddings, output head) are kept at higher precision, so the file size is the number to trust.

Example: a 9 billion parameter model at Q8_0 is about 9 x 8.5 / 8 = 9.6 GB of weights.

## KV cache: the formula and a worked example

The KV cache stores keys and values for every token of context, for every full-attention layer:

```
KV bytes  =  2  x  full_attention_layers  x  kv_heads  x  head_dim  x  context  x  bytes_per_element
```

- The leading 2 is keys plus values.
- Count only full-attention layers. Some newer architectures interleave linear-attention layers that
  keep no per-token cache. A model that is "64 layers" may have only 16 full-attention layers. Take the
  count from the model card or the GGUF metadata, not from the total layer count.
- `kv_heads` is the number of key/value heads (grouped-query attention). It is often much smaller than
  the number of query heads. Use the KV figure.
- `head_dim` is the per-head dimension. For many models it is 128.

Worked example (illustrative numbers, not a specific model): 32 full-attention layers, 8 KV heads,
head_dim 128, context 16,384, f16 cache (2 bytes per element):

```
per token  =  2 x 32 x 8 x 128 x 2 bytes  =  131,072 bytes  =  128 KiB
total      =  128 KiB x 16,384            =  2 GiB
```

The same model with a q8_0 cache is about 1.06 GiB at the same context.

## Bytes per element by cache type

| Cache type | Bytes per element | Notes |
|---|---|---|
| f16 (default) | 2.0 | Full precision for the cache. The safest choice when the card has room. |
| q8_0 | about 1.06 | 34 bytes per block of 32 values. Roughly half of f16. Small quality cost. |
| q4_0 | about 0.56 | 18 bytes per block of 32 values. Roughly a quarter of f16. Larger quality cost; test on your task. |

Quantised V cache requires flash attention (`-fa on`). Quantised K alone may not.

## Compute buffer and batch sizes

- The compute buffer is scratch memory for one forward pass. It grows with the physical batch size
  (`-ub`), not with the context. Some models need the whole prompt in one physical batch, so `-ub` must
  be at least the longest prompt; that is the case where the buffer grows large.
- A decision or classifier model that reads a long prompt in one pass may need a large `-ub`, and then
  needs the compute buffer budgeted explicitly.
- Do not guess the buffer. Measure it (below).

## Slots and context

- `-c` is the context for the whole model. With `-np N`:
  - without unified KV (`-kvu` off), each slot gets `-c / N` tokens, so a long request may not fit
    in its slot even when the total looks plenty;
  - with `-kvu`, the slots share one pool of `-c`, so a short request leaves the rest for others.
- More slots mean more concurrent requests and more scheduling state. One slot is the cheapest and
  the right choice for a single agent that makes one request at a time.
- Choose `-np` from the number of concurrent clients you really have, not from habit.

## Flash attention and quantised KV

- `-fa on` (or `-fa auto` on builds that default to it) enables flash attention. It lowers the attention
  memory and is required for a quantised V cache.
- Some model architectures or cards reject it with a message that names flash attention. Then run at f16
  KV and a smaller context, or use a build that supports the architecture.
- Quantised KV cache trades memory for a small quality cost. Measure the quality on the task the model
  is for. Do not trust a general claim that "q8 is free".

## Why not spill to system RAM

Partial GPU offload keeps some layers on the CPU. Each generated token then waits for the CPU layers,
so generation speed can fall by an order of magnitude or more. The model also still "loads", so the
failure is silent: the service looks healthy and every answer is slow. Full offload with `--fit off`
turns the same situation into a load error that names the memory shortfall.

Two cautions:
- Full offload does not cap host RAM. Some host buffers are still allocated. Check `free -h` under load.
- Prompt caches kept in host RAM (`-cram`) are separate from the GPU budget. `-cram 0` turns them off.

## Measuring the real footprint

1. With no model loaded (or with the other models unloaded), note `memory.used`.
2. Start the model. Note `memory.used` once it has loaded but before any request.
3. Send one request whose prompt is near the context you intend to run.
4. Note `memory.used` again. The difference from step 1 is the real footprint: weights, KV cache and
   compute buffer.

```sh
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits
```

Repeat at the two context lengths you care about. The difference between the two is the KV cost per
token, which you can check against the formula above.

## Disk planning

- Budget the GGUF files you will keep, plus about 20 percent free on the volume that holds them.
- Keep the models on the Linux filesystem of the machine that serves them. Slow or network-mounted paths
  make cold starts long enough to trip `healthCheckTimeout`.
- A model file on a Windows-hosted virtual disk grows the virtual disk. Deleting the file frees space
  inside the guest, not on the host drive, until the virtual disk is compacted (see `wsl2-gpu.md`).
- Before deleting a GGUF, prove no config or unit names it (see `SKILL.md`, procedure 2).
- Record each file's checksum next to its config entry, so a later re-download can be verified.
