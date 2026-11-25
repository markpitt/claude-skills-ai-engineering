# Question design

## API shape (checked 2026-10-11)

`POST https://openrouter.ai/api/v1/systemone`, not listed in `/models`.

```json
{
  "model": "inception/mercury-decide:free",
  "state": "any string",
  "questions": {
    "heat_on": { "type": "noul", "instructions": "Should the heating turn on now?" },
    "commit_type": {
      "type": "choice",
      "instructions": "Which Conventional Commits type fits?",
      "criteria": { "feat": "adds a capability", "fix": "corrects wrong behaviour" }
    },
    "risk": {
      "type": "score",
      "instructions": "How risky is this change?",
      "criteria": ["trivial", "contained", "touches a hot path", "changes public API"]
    }
  }
}
```

`state` may be a string or any JSON value. `instructions` is required (the
schema also accepts a record or array there; the tool always sends a
string). Question types:

| Type | `criteria` | Answer |
|---|---|---|
| `noul` (yes/no) | none | `{"type":"noul","noul":0.996}`: probability of yes |
| `choice` | object, option key to description | `choice`, `probabilities` per key, `confidence` |
| `score` | array of anchors, lowest first | `score` in [0, 1], `probabilities` and `legend` per anchor index, `confidence` |

The response also carries `model` (the dated snapshot that answered),
`usage` (`cost` is 0 on the free model) and an `id`. Errors come back as
`{"error":{"message":...,"code":400}}`; validation messages name the
offending path, which is how this shape was found.

## Wording

- **One question, one decision.** "Is this a flaky test or an infra
  problem?" is a choice, not a yes/no.
- **Say what yes means.** "Is the reviewer requiring a code change before
  merge, rather than offering an optional suggestion?" beats "Does this
  need a change?". The vaguer form scored a plain nit at 0.71.
- **Describe options, do not just name them.** The description is what the
  model weighs. "flaky-test: fails intermittently from timing or ordering
  with no code cause in the log" separates far better than "flaky".
- **Options must be exhaustive and exclusive.** Add an `other` or
  `unclear` option rather than forcing a wrong pick.
- **Anchors are a scale.** Order them from least to most, keep the steps
  even, and describe observable states ("a clear escape") rather than
  adjectives ("very bad").
- **Structure the state.** A JSON object with named fields (`commit_subject`,
  `files`, `diff_excerpt`) answers better than a wall of text, and the
  field names act as hints.
- **Trim the state.** Send the evidence, not the whole log: earlier error
  lines plus the tail is what `ci-triage` sends. Keep it under roughly
  10k characters.
- **Put several questions in one request.** They share the state and cost
  one request against the daily quota.

## Reading answers

- High confidence is not correctness. The model is sure of many wrong
  things; only `decide calibrate` over labelled outcomes says how far to
  trust a question.
- Look at the runner-up. `fix 0.55, refactor 0.44` is a genuine tie and
  should be treated as unsure even above a threshold.
- A score is not a percentage of anything. Compare scores from the same
  question and anchors only.
- The answering snapshot can change under the `:free` alias. The log keeps
  `model`, so recalibrate when it changes.
