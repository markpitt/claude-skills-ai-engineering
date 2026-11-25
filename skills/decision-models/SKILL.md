---
name: decision-models
description: "Uses a System One decision model (OpenRouter, inception/mercury-decide:free) through the bundled `decide` tool: yes/no, choice and score questions about a text or JSON state, answered as probabilities. Use when a workflow needs a fast, cheap judgement such as CI failure triage, commit and changelog checks, routing an issue to the right repository or team, classifying review comments, calibrating those answers against real outcomes, adding an optional model decision to an app, or pointing decide at a local gateway in front of a llama-swap model and testing candidate models against a fixed question set. Do NOT use for generating text, writing review prose, serving the model itself (use local-llm-serving), or any check a parser, grep, build or test can answer exactly."
license: Apache-2.0
compatibility: "Requires .NET 10 or later (`dotnet run --file`) and network access to openrouter.ai, with OPENROUTER_API_KEY set unless a proxy injects the key. A local gateway route (DECIDE_URL) replaces that network requirement; the model harness needs Python 3."
metadata:
  version: "1.2.0"
  tags: "decision-model, openrouter, triage, ci, calibration, local-llm, gateway, model-harness, silent-fallback"
---

# Decision models

A System One model takes a **state** (text or JSON) and named **questions**
and returns **probabilities**, not prose. One request costs nothing on the
free model, answers in roughly 0.3 to 5 seconds, and can carry several
questions at once. Treat it as a fast, cheap System 1 judgement: good for
triage, routing and "should a human or a slower agent look at this?", never
the final word on anything that can be checked exactly.

## Critical

- Prefer a deterministic check whenever one exists. A package reference,
  a missing file, a format violation or a failing test is a grep or a
  build, not a question.
- A model answer is advisory. Never let it pass a gate, skip a test,
  silence a CI failure or merge anything. A probability is not evidence.
- Never put secrets, tokens, `.env` content or other people's private data
  in a state. States leave the machine (OpenRouter, then the model
  provider) and are also kept in the local decision log.
- Budget: the free model has a daily request quota. Set the key's own
  spending limit to $0 so a paid model fails rather than spending. Batch
  questions into one request, and never loop a recipe over hundreds of
  items without saying so first.
- When `decide` exits 3 (unsure), escalate to a person or a slower check;
  do not re-ask with tweaked wording until it agrees.
- A reply can come from a model you did not ask for: a gateway or a client
  retry can fall back silently. `decide` refuses a reply whose `model` field
  is not exactly the model requested, with exit 4 (see "Silent fallback"
  below).

## The tool

`scripts/decide` in this skill, a Bash shim over `scripts/decide.cs`. Run
it in place with `bash`, or `chmod +x` it and put the `scripts` folder on
`PATH` (a copy from the public repository has no executable bits). The first run builds
the app for a few seconds; later runs start in about half a second. Every
command has `--help`.

| Command | What it answers |
|---|---|
| `ask` | One ad hoc question (`--yes-no`, `--choice` with `--option KEY=DESC`, `--score` with `--anchor`s lowest first) or a `--questions FILE` |
| `ci-triage` | Why a CI job failed: code-defect, flaky-test, dependency-restore, quality-gate, infrastructure, actions-billing, timeout; and whether a plain re-run would pass |
| `commit-check` | For the staged diff or `--rev`: Conventional Commits type, subject accuracy, changelog-worthy, public API change, plus any project questions from `--questions FILE` |
| `route` | Which target (repository, team, queue) an issue or idea belongs to, from a `--targets FILE` of descriptions |
| `review` | Kind of review comment and whether it requires a code change |
| `label` / `calibrate` / `log` | Record real outcomes, then measure Brier score and accuracy per question |

Global options: `--dry-run` (print the request, send nothing), `--replay
FILE` (parse a saved response), `--json` (raw answers), `--no-log`,
`--model`, `--timeout`.

Exit codes: 0 yes or confident, 1 no, 2 usage, 3 unsure, 4 API or
network. Yes/no thresholds default to `--yes 0.8` and `--no 0.2`; choice
and score are unsure below `--min-confidence 0.6`.

Environment: `OPENROUTER_API_KEY`, `DECIDE_MODEL` (default model),
`DECIDE_LOG` (log file, default
`${XDG_STATE_HOME:-~/.local/state}/decide/decide.jsonl`), `DECIDE_TARGETS`
(default targets file for `route`), `DECIDE_URL` (endpoint override).

```sh
D="bash path/to/decision-models/scripts/decide"
$D ask --state '{"thermostat_c":17.5,"target_c":20}' --yes-no "Should the heating turn on?"
gh run view 123 --repo OWNER/REPO --log-failed | $D ci-triage -
$D ci-triage --run 123 --repo OWNER/REPO
git add -p && $D commit-check --message "fix(parser): handle empty input"
$D route --text @issue.md --targets templates/targets.example.json
$D review --text "nit: call this clipWidth"
```

## Project-specific checks

The recipes ship with generic questions only. Add a project's own rules as
files rather than editing the tool:

- `templates/targets.example.json`: a `route` targets file. Describe what
  belongs in each target, not just its name; the description is what the
  model weighs.
- `templates/commit-questions.example.json`: extra `commit-check`
  questions. Word each so that yes, or a high score, means a problem. A
  yes/no at or above 0.7 or a score at or above 0.5 raises a flag.

## Workflow

1. Decide whether the question needs judgement at all. If a parser,
   grep, build or test answers it, use that and stop.
2. Use a recipe when one fits. Otherwise write the question with `ask`;
   read references/question-design.md first, because wording moves the
   probabilities more than the state does.
3. Run once with `--dry-run` to see exactly what will be sent, then for
   real. Read the probabilities, not only the top label.
4. Act on the exit code: 0 proceed, 1 take the "no" branch, 3 hand to a
   person or a slower agent, 4 report the API failure and carry on
   without the model.
5. When the real outcome becomes known (the re-run passed, the issue was
   moved, the reviewer insisted), record it with
   `decide label ID QUESTION OUTCOME`. The id is printed on stderr after
   each call and shown by `decide log`.
6. Before gating anything on a question, run `decide calibrate`. A yes/no
   question needs a Brier score well under 0.25 (a coin flip) over a
   few dozen labels before it may block a step, and even then only as a
   prompt to look, never as a silent pass.

## Recipes in agent work

- **CI red on a PR.** Run `ci-triage --run ID --repo R` first.
  `actions-billing` means the run never started: report that the Actions
  credit or spending limit has run out instead of debugging code.
  `flaky-test` or `infrastructure` with a high re-run probability justifies
  one re-run; a second failure is real whatever the model says.
- **Before committing.** `commit-check` flags a mismatched type, a
  user-visible change with no CHANGELOG entry, a public API change with no
  docs change, and whatever the project's `--questions` file asks. A flag
  means re-read the diff; it is not proof of a problem.
- **Review comments.** `review` separates nits and questions from blocking
  asks. An early wording of `needs_change` scored a plain nit at 0.71; the
  current wording gets nits and real bugs right, but calibrate it before
  trusting it.
- **Issues and ideas.** `route` when the target is not obvious; exit 3
  usually means the work spans targets.

## Local route and silent fallback

`decide` can send its requests to a local gateway instead of the hosted route:
set `DECIDE_URL` to the route, and pass the id the gateway knows as `--model`
or `DECIDE_MODEL`. The route must accept the same request body and return the
same reply shape, so the gateway has to translate to and from the local model's
chat interface. Keys go in the launcher's environment or a mode-600 key file,
never on a command line or in a state. The default timeout is 30 seconds, which
a cold model load after a swap can exceed: measure one cold request and pass
`--timeout` above it. The server side (VRAM, the swap proxy, the systemd unit)
belongs to `local-llm-serving`.

**Silent fallback.** A gateway can route a failed request to another
deployment, a client retry can switch to a configured fallback model, and an
alias can be re-pointed in the gateway config. Each returns a clean answer from
a model you did not test. Rules:

- `decide` checks that the reply's `model` field equals the model you asked
  for, exactly, on every answer, and exits 4 on a mismatch without printing
  the answer. A gateway that reports its own name for the routed id (asked for
  `provider/name`, answered as `name`) needs `--served-as name` or
  `DECIDE_SERVED_MODEL=name` in the launcher: an explicit alias, never a guess.
  A reply with no `model` field is answered with a warning, not verified.
- A mismatch is a fault: do not count that answer for the candidate.
- A matching name shows what the route reports, not the weights. Re-test after
  any swap or gateway change.
- The decision log records the served `model` and the `requested_model` per
  entry. Check them against the intended model before reading a calibration
  into it.

`scripts/test_decide.py` covers the check offline through `--replay` fixtures.
`references/local-gateway.md` has the wiring, the timing and the full rules.

## Testing candidate models

`scripts/model_harness.py` (stdlib Python, tests in `scripts/test_model_harness.py`)
asks each candidate model every question in one fixed set, through the route
you name, and reports per model: verified answers, mismatches, unverifiable
replies, errors, unsure answers, accuracy and Brier score over verified answers
only. A model with any mismatch is disqualified for that run.

```sh
python3 scripts/model_harness.py --questions templates/question-set.example.json --model candidate-a --dry-run
python3 scripts/model_harness.py --questions my-set.json --model candidate-a --model candidate-b --endpoint "$DECIDE_URL" --timeout 180
```

Exit codes: 0 clean, 1 served-model mismatch, 4 transport or API error,
3 unverifiable reply, 2 usage. The template holds six synthetic questions, a
smoke test only. Fix the set before running it, balance yes and no, add
near-misses, and rank candidates by Brier over a few dozen questions rather
than by one run.

## In apps

The `SystemOne` region at the end of `decide.cs` (`SystemOneClient`, the
question and answer records, `DecisionResponse.Parse`) is BCL-only and
uses `JsonNode`, so it survives Native AOT. Copy it into an app rather
than referencing it. Rules for app use:

- Keep it out of libraries and frameworks: no network calls or model
  dependency in code other people build on.
- Opt-in and off by default, with the key from the user's own settings or
  environment, and a deterministic fallback when offline or unsure.
- Run it off the UI or render path, cancel it with the screen or request
  that started it, and show that an answer came from a model.

references/ideas.md lists app and workflow ideas worth trying.

## References

- references/question-design.md: how to word states, questions, options
  and anchors, and the API shape.
- references/ideas.md: uses across the dev process, agents and apps,
  including ensembles, routing agents and model-assisted test oracles.
- references/local-gateway.md: the route's request and reply shape, wiring
  `DECIDE_URL`, silent fallback in full, and the model harness's question-set
  rules and exit codes.
- templates/question-set.example.json: the harness's fixed question set format.
