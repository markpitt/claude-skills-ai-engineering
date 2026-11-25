# Local route, silent fallback and the model harness

This reference covers three things the main skill points to: sending `decide` to a local model
through a gateway, the silent-fallback trap that a gateway or a client can set, and how to test
candidate models against a fixed question set. Checked against `scripts/decide.cs` and
`scripts/model_harness.py` at skill version 1.1.0.

For the model server itself (VRAM sizing, the model-swap proxy, cold-load timeouts and the
systemd unit), read the `local-llm-serving` skill. This reference does not repeat it.

## 1. When a local route is the right choice

- The states must stay on the machine. A hosted route sends every state to the provider; a local
  route keeps the state on the network you control, and the decision log is the only copy kept
  locally anyway.
- The price is a GPU that is busy, a cold load after a model swap, and a model that is probably
  smaller than the hosted one. Measure the answers, not the marketing, with the harness below.
- A local route has no daily quota, so the free-model budget rule does not apply. Batch questions
  all the same: a loop over hundreds of items is still a loop.

## 2. The shape the route must present

`decide` sends one POST per request, with this body (see `DecisionRequest.ToJson` in `decide.cs`):

```json
{
  "model": "<the id the gateway knows>",
  "state": "<any JSON>",
  "questions": {
    "<name>": { "type": "noul", "instructions": "<yes or no question>" }
  }
}
```

It reads back `model`, `id` and an `answers` object. Each yes/no answer is
`{ "type": "noul", "noul": <probability of yes> }`. Choice and score answers have their own shapes.

A gateway that only offers an OpenAI-style chat completions endpoint is not enough on its own. Something
must translate the System One request into a chat request for the local model, and translate the
reply back into this shape. Most breakage is in that translation, so test it with the harness
before trusting it.

## 3. Wiring `decide` to a route

| Setting | What it does | Notes |
|---|---|---|
| `DECIDE_URL` | Replaces the hosted endpoint | The full route URL, including its path |
| `--model` or `DECIDE_MODEL` | The id sent in the request | Must be the id the gateway knows; list the gateway's models, do not guess |
| `OPENROUTER_API_KEY` | Sent as a Bearer token | The name is fixed in `decide`; a local gateway can use the same variable or sit behind a proxy that injects a key |
| `--timeout` | Per-request timeout, default 30 seconds | Raise it above the measured cold-load time after a swap |

Key handling:

- Put the key in the launcher's environment or a key file with mode 600 that the launcher reads.
  Never type it on a command line, in a state, or in a committed file.
- Refer to a key file by its path only. Do not print it, cat it or paste it into a transcript.

Timing:

- Measure one cold request before setting a timeout: run `decide ask --dry-run` for the body, then time
  one real request after the model has been unloaded. Set `--timeout` above that figure with margin.
- A warm request should take about a second. If every request is slow, the problem is the server,
  not the timeout.

## 4. Silent fallback

A gateway or a client can answer a request with a different model and still return a clean reply.
The answer looks identical, so nothing downstream notices. Three ways this happens:

1. **Gateway fallback routing.** A gateway can send a request to another deployment when the first
   errors or is overloaded.
2. **Client retry with fallback models.** Agent harnesses can retry a failed request against a list
   of configured fallback models. The omp agent harness, for example, has a `modelFallback`
   setting that lets retry recovery switch to configured fallback models. A retry that succeeds on
   the second model returns a normal answer.
3. **Re-pointed alias.** A gateway name such as a logical alias can be moved to a different model in
   the gateway's configuration. The name is unchanged; the model is not.

Rules that follow:

- Compare the reply's `model` field with the model you asked for, on every answer. Both the
  harness and `decide` (from skill version 1.2.0) do this, by exact match. `decide` exits 4 on a
  mismatch and does not print the answer; the decision log keeps both names. Where the gateway
  reports its own deployment name for the routed id, set `DECIDE_SERVED_MODEL` (or pass
  `--served-as`) to that name in the launcher. A reply without a `model` field gets a warning on
  stderr and is not verified.
- Treat a mismatch as a fault, not a result. Do not count the answer for the candidate you asked
  for, and do not average it in.
- A matching name proves only that the route reports that name. It does not prove the weights.
  Re-run the harness after any swap, gateway change or model upgrade, and keep labels per model.
- The decision log records the served `model` and the `requested_model` for each entry (`decide log`). Afterwards, check it
  against the model the run was meant to use before reading a calibration into it.

## 5. The model harness

`scripts/model_harness.py` (stdlib only) asks each candidate model every question in one fixed set,
through the route you name, and reports a row per model.

```sh
H=path/to/decision-models/scripts/model_harness.py
python3 "$H" --questions templates/question-set.example.json --model candidate-a --dry-run
python3 "$H" --questions my-set.json --model candidate-a --model candidate-b \
  --endpoint "$DECIDE_URL" --key-env OPENROUTER_API_KEY --timeout 180
python3 "$H" --questions my-set.json --model candidate-a --json > report.json
```

What it reports per model: questions, verified answers, mismatches (served by another model),
unverifiable replies (no `model` field), errors, unsure answers (probability between the yes and no
thresholds, 0.2 and 0.8), correct answers, accuracy over verified answers, and Brier score over
verified answers. A model with any mismatch is disqualified for that run and its scores are not a
result.

Exit codes: 0 every answer verified and no fault; 1 at least one served-model mismatch; 4 at least
one transport or API error; 3 at least one unverifiable answer; 2 usage or input error. The worst
fault wins, in that order.

Question set rules:

- A JSON list of objects with `id`, `state`, `question` and `expect` (true or false). The template
  has six synthetic questions across three domains. Write your own set for the decision you need.
- Balance yes and no answers. Include near-misses, the cases a person would disagree about, and at
  least one case each way that a naive rule gets wrong.
- Fix the set before you run it. Do not tune wording to one model; if a question is bad, change it
  for every model and run again.
- Use synthetic states in a public repository. A real state can carry personal data, and the
  harness output names the question id, which should carry nothing identifying either.
- Six questions is a smoke test, not a comparison. Trust a difference between models only over a
  few dozen questions, and read the Brier score, which penalises confident wrong answers, not just
  the accuracy.

Choosing: rank candidates by Brier on the same fixed set, check accuracy beside it with its
denominator (verified answers only), and discard any candidate with a mismatch for that run. Note
the latency from `--json` if the workflow runs in a loop.

The harness does not replace `decide calibrate` or the labels in `decide label`. Use it to choose a
model; use the labels on real outcomes to decide whether a question may gate anything at all.

## 6. Cross-links

- `local-llm-serving`: the server, VRAM budget, the model-swap proxy and its health-check timeout,
  the systemd unit and the gateway alias that a route points at.
- `references/question-design.md`: how to word states, questions and anchors. Wording moves the
  probabilities more than the model does, so word the question set first.
