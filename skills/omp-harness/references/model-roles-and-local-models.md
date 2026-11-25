# Model roles, models.yml and local models

Contents

1. Roles
2. Role values and per-run flags
3. models.yml shape
4. Checking model ids
5. Auxiliary calls: judge, spotlight and offline
6. The silent-fallback test

## 1. Roles

The roles observed in the global and project config files (confirmed from files):

| Role | Used for |
|---|---|
| `default` | The main model for the session |
| `smol` | Light, fast work; the target of `--smol` |
| `slow` | Thorough or reasoning-heavy work; the target of `--slow` |
| `plan` | Planning; the target of `--plan` |
| `advisor` | Reviewing each turn when the advisor runtime is on (`--advisor`) |
| `task` | Subagent tasks |
| `commit` | Writing commit messages and changelog text |
| `tiny` | Small jobs such as session titles |
| `memory` | Memory work |
| `vision` | Images |
| `judge` | Judgement calls by the harness; the TTSR judge setting (`ttsr.judge`) is related, and the exact use is **verify with omp --help** |

The `--smol`, `--slow` and `--plan` flags and the `PI_SMOL_MODEL`, `PI_SLOW_MODEL` and
`PI_PLAN_MODEL` variables are confirmed from help text. The meaning of the other roles is from the
names in the config files and is **verify with omp --help** before a role is depended on.

Cycling between models with Ctrl+P is limited by `--models=PATTERN,PATTERN` (confirmed from help).

## 2. Role values and per-run flags

A role value is `provider/model-id`, for example `local/MODEL-ID`. Some hosted values carry a
suffix such as `:auto`; what the suffix selects is **verify with omp --help**.

Per-run overrides, confirmed from help:

```bash
omp --model local/MODEL-ID "task"
omp --smol local/MODEL-ID "task"
omp --thinking low "task"           # off, minimal, low, medium, high, xhigh, max, auto
```

`--model` accepts a fuzzy match or an exact `provider/id`. Prefer the exact form in scripts.

## 3. models.yml shape

Observed in the global `models.yml` (confirmed from files), with placeholder values:

```yaml
providers:
  local:
    baseUrl: http://127.0.0.1:PORT
    api: typesafe
    auth: none
    models:
      - id: MODEL-ID
        name: Display name
        kind: judge              # observed values include judge and chat
        reasoning: false
        input: [text]
        contextWindow: 16384
        maxToken: 16384
        cost:
          input: 0
          output: 0
          cacheRead: 0
          cacheWrite: 0
      - id: CHAT-MODEL-ID
        name: Chat model
        api: openai-completions  # a model can override the provider's api
        baseUrl: http://127.0.0.1:PORT/v1
        kind: chat
        input: [text]
        contextWindow: 16384
        maxToken: 16384
        compat:
          supportsReasoningEffort: false
          extraBody:
            chat_template_kwargs:
              enable_thinking: false
```

Notes:

- `auth: none` is what a local endpoint without a key uses. Do not put a key in this file. For a
  built-in provider, `omp --help` lists the environment variable that carries its key. The route
  for a key on a custom provider is **verify with omp --help**.
- A per-model `api` and `baseUrl` override the provider's, as the second entry shows.
- `cost` of zero is the honest value for a machine you run yourself.
- `contextWindow` and `maxToken` should match what the server really accepts. The config file
  does not prove that; check it against the server's own settings.

## 4. Checking model ids

```bash
omp models                   # list (default action)
omp models find PATTERN      # search by substring
omp models local             # one provider (action is the provider name)
omp models --json
omp models refresh           # re-read the catalogue
```

Confirmed from help. Check that a role's id appears in this list before saving it; an id that is
absent is a fault to find before the role is used.

## 5. Auxiliary calls: judge, spotlight and offline

Confirmed from help and from the config keys listed by `omp config list`:

| Flag | Config key | Effect |
|---|---|---|
| `--no-judge` | `models.noJudge` | Restricts judge calls to the active model's provider |
| `--no-spotlight` | (verify key) | Restricts Spotlight calls to the active model's provider |
| `--offline` | `models.offline` | Restricts auxiliary services to the active model's provider. Help text: "not a network firewall" |

These keys stop auxiliary calls being sent to another provider. They do not by themselves prove
that the main role never falls back. The main role's behaviour when its endpoint is down is
**verify with omp --help**, and the test below is the evidence.

## 6. The silent-fallback test

Run this in a profile so that no real session or setting is touched:

1. Create a throwaway profile. `--profile NAME` isolates auth, sessions, settings and caches
   (confirmed from help).
2. In that profile's settings, make the local provider's `baseUrl` a closed port. Where the
   profile keeps its `models.yml` is **verify with omp --help**.
3. Run one trivial prompt, with auxiliary calls pinned:
   ```bash
   omp --profile fallback-test --offline --no-judge -p "reply with the word ready"
   ```
4. Read the result. A failure is the expected outcome for a local-only setup. A reply means
   something answered; find out which provider from the session file (`sessions-and-rehoming.md`)
   before believing the setup is local.
5. Delete the profile after recording the result.

Record the omp version and the date with the result, because fallback behaviour can change between
versions.
