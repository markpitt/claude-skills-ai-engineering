# Routing agents through LiteLLM

LiteLLM is an OpenAI-compatible gateway. Agents ask it for a model by an alias, and it forwards the call
to an upstream, here the llama-swap proxy. The gateway gives one place to rename models, hold keys,
set timeouts, and log calls. It does not load models: llama-swap does.

LiteLLM often runs on a different machine from the GPU. Then the agent-side config names the gateway,
and the gateway's own config names the llama-swap address. Keep the two configs distinct, and say which
host each belongs to.

## Contents

- Shape of a model entry
- Aliases
- The api_base and the key
- Timeouts for cold starts
- Retries
- Routes that are not OpenAI-shaped
- Checking the route end to end

## Shape of a model entry

```yaml
model_list:
  - model_name: local-small              # the alias agents ask for
    litellm_params:
      model: openai/small-9b-q8          # "openai/" prefix: the upstream speaks the OpenAI API
                                         # the id after the slash is the llama-swap model id
      api_base: os.environ/LOCAL_LLM_API_BASE   # for example http://<llama-host>:8080/v1
      api_key: os.environ/LOCAL_LLM_KEY         # a placeholder value if the proxy checks no key
      timeout: 600                       # seconds to wait for a response, cold load included
      stream_timeout: 600                # seconds to wait for each streamed chunk
      num_retries: 0                     # see Retries below

litellm_settings:
  request_timeout: 600                   # check your LiteLLM version honours this key here
```

- `os.environ/NAME` reads the value from the gateway's environment at start. Put the real key in the
  environment or a secrets file the gateway reads, never inline.
- Check the key names against the LiteLLM release in use. The `timeout` on `litellm_params` and the
  gateway-wide `request_timeout` have moved between releases; confirm which one your version applies.

## Aliases

- One alias per role, not per model. Agents then ask for `local-small` or `local-decision`, and a model
  swap is a one-line change in the gateway.
- Keep the alias names stable once agents use them. Renaming breaks every caller.
- Two aliases can point at the same llama-swap id if two roles need different timeouts or defaults.

## The api_base and the key

- `api_base` ends in `/v1` for an OpenAI-shaped upstream. A missing `/v1` gives 404s that look like a
  missing model.
- llama-swap does not check a key unless one is configured for it. The gateway still wants a value, so
  use a placeholder that is not a real credential, or the key the proxy is configured to check.
- Read the key from a mode-600 file into the environment at start. Never paste it into a config, a
  unit file, a log or a chat. If it has leaked, rotate it.

## Timeouts for cold starts

A request that arrives while a model loads waits for the load. The client's read timeout must be longer
than the cold load, or the client gives up while the model is still loading.

Set, in order from the inside out:
1. `healthCheckTimeout` in llama-swap: longer than the cold load.
2. `timeout` (and `stream_timeout`) on the gateway's `litellm_params`: longer than the cold load plus the
   longest generation you expect.
3. Any timeout in the calling agent or tool: longer again.

Measure the cold load first (`time_total` on the first request after a swap, against a warm one), then
add margin. Do not guess a timeout of 30 seconds for a model whose cold load is two minutes.

## Retries

- A retry on a timeout re-sends a request that may still be running upstream. The model then does the
  work twice and the second answer is discarded.
- Start with `num_retries: 0`. Add one retry only for a transient network error you have seen, and only
  for calls that are safe to repeat.
- Retries stack with timeouts: two retries at a 600 second timeout can hold a caller for 30 minutes.

## Routes that are not OpenAI-shaped

`model_list` covers the OpenAI-style routes. A llama.cpp-specific endpoint (for example a custom
decision route) is not a model alias. Either:
- call it directly against the llama-swap address, if the caller can reach it; or
- configure a pass-through route in the gateway for that path, and check the pass-through documentation
  for your LiteLLM release.

Do not assume an alias works for a custom path. A 404 from a custom path may come from the gateway
rather than the upstream, so check which hop answered.

## Checking the route end to end

Work from the upstream outward, one hop at a time, so a failure has one owner.

```sh
# 1. the upstream answers and lists the id (on the llama-swap host)
curl -fsS --max-time 10 "$LLAMA_URL/v1/models"; echo "upstream exit $?"

# 2. the gateway answers and lists the alias (the header comes from a mode-600 file, not the command line)
curl -fsS --max-time 10 -H "@$LITELLM_AUTH_HEADER_FILE" "$LITELLM_URL/v1/models" >/dev/null; echo "gateway exit $?"

# 3. one completion through the alias, with a long read timeout
curl -fsS --max-time 300 -H "@$LITELLM_AUTH_HEADER_FILE" "$LITELLM_URL/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model":"local-small","messages":[{"role":"user","content":"Reply with OK."}],"max_tokens":4}'
echo "completion exit $?"
```

- `$LITELLM_AUTH_HEADER_FILE` names a file holding one line, `Authorization: Bearer <key>`, mode 600.
  `curl -H @file` reads the header from the file, so the key never appears in the command line or a
  process listing. Do not echo the file's contents.
- The gateway log shows the alias, the upstream id and the timing of each call. Use it when step 3 fails
  and steps 1 and 2 pass.
