# Evidence ledger

Each fact in the skill, with where it was confirmed. Checked against omp v18.20.2 on 19/11/2026,
using the agent directory's files, the project config header of a sample project, and the output of
`omp --help`, `omp config --help`, and the `--help` of `config`, `models`, `session`, `collab`, `ps`,
`skill`, `ttsr`, `join` and `acp`. No session was started and no model was called.

Status key: **files** = read from a file; **help** = printed by an omp `--help`; **verify** = not
confirmed, check with `omp --help` before relying on it.

## Layers and config

| Fact | Status | Source |
|---|---|---|
| Global config at `$(omp config path)/config.yml` | files, help | `omp config path`; directory listing |
| Project config at `<cwd>/.omp/config.yml` | files, help | `omp config list --scope` help; sample project's `.omp/config.yml` |
| Precedence global < project < CLI overlay < runtime | files | Header comment in the sample project's `.omp/config.yml` |
| `omp config get` returns the merged value | files | `omp config get modelRoleStorage` run in the sample project printed `project` |
| `omp config list --scope=global\|project` | help | `omp config --help` |
| `modelRoleStorage: project` sends role changes to the project file; other settings do not | files | Same header comment |
| `omp config set` writes to which layer | verify | Help takes no scope flag |
| `--config FILE` overlay, repeatable | help | `omp --help` |
| `--profile NAME` isolates auth, sessions, settings and caches | help | `omp --help` |

## Models

| Fact | Status | Source |
|---|---|---|
| Role names: default, smol, slow, plan, advisor, task, commit, tiny, memory, vision, judge | files | Global and project `config.yml` |
| `--smol`, `--slow`, `--plan` flags and `PI_*_MODEL` variables | help | `omp --help` |
| `provider/model-id` role value form | files | Global `config.yml` |
| `:auto` suffix meaning | verify | Seen in values only |
| `models.yml` provider shape: baseUrl, api, auth, models with kind, contextWindow, maxToken, cost, compat | files | Global `models.yml` (values not reproduced) |
| Per-model `api` and `baseUrl` override | files | Global `models.yml` |
| `omp models`, `find`, `refresh`, `<provider>`, `--kind`, `--json` | help | `omp models --help` |
| `--model`, `--thinking` levels | help | `omp --help` |
| `--no-judge` restricts judge calls to the active provider | help | `omp --help` |
| `--offline` restricts auxiliary services; not a firewall | help | `omp --help` |
| `--no-spotlight` restricts Spotlight calls | help | `omp --help` |
| Config keys `models.offline`, `models.noJudge` | files | `omp config list` output |
| Main role falls back to a hosted provider when the endpoint is down | verify | Not in help or config. Test in a throwaway profile (SKILL.md procedure 2) |

## Language servers, rules, hooks, approvals

| Fact | Status | Source |
|---|---|---|
| `lsp.json` path and `servers` map with command, args, fileTypes, rootMarkers, languageId | files | `~/.omp/agent/lsp.json` (values not reproduced) |
| `command` is case-sensitive on Linux (`OmniSharp` binary, lower-case id) | files | `lsp.json` shape; case rule is the Linux lookup behaviour, verify with `command -v` |
| Per-project `lsp.json` is read | verify | Not seen |
| `--no-lsp`, `task.enableLsp`, `lsp.diagnosticsOnEdit` | help, files | `omp --help`; config key names |
| TTSR rule frontmatter: name, description, condition, scope | files | `~/.omp/agent/rules/*.md` (one observed file) |
| `omp ttsr test/list/scan` and flags | help | `omp ttsr --help` |
| `--no-rules` | help | `omp --help` |
| Project rule folders | verify | Not seen |
| `.omp/hooks/pre/*.ts` present in a sample project | files | Directory listing |
| `--hook FILE`, `-e FILE`, `--no-extensions` | help | `omp --help` |
| Hook auto-loading from `.omp/hooks/` | verify | Not confirmed |
| `bash.patterns` with `match` and `approval`, first match wins, values prompt and deny | files | Header and entries in a sample project's `.omp/config.yml` |
| Bash patterns do not cover `eval` | files | Same header |
| `--approval-mode always-ask\|always-ask-cached\|write\|yolo` | help | `omp --help` |

## Skills

| Fact | Status | Source |
|---|---|---|
| `~/.omp/agent/skills/<name>/SKILL.md` | files | Directory listing |
| `skills.*` keys: enabled, enablePi/Agents/Claude/Codex, customDirectories, ignoredSkills, includeSkills, manualSkills | files | `omp config list` output |
| `--no-skills`, `--skills=GLOBS` | help | `omp --help` |
| `omp skill` actions, `-g`, `-y`, `--dry-run`, `--allow-secrets` | help | `omp skill --help` |
| Project skill folder names for the pi-named location | verify | Not confirmed |
| New skills need a new session | verify | Not in help; expected behaviour, not seen |
| `/restart` exists as an in-session command | verify | Not in CLI help |

## Sessions

| Fact | Status | Source |
|---|---|---|
| Session root `~/.omp/agent/sessions/`, JSONL files | files, help | Directory listing; `--restore` example |
| Folder names encode the working directory, leading `-`, slashes as hyphens | files | Directory names observed; exact rule verify |
| `--session-dir` | help | `omp --help` |
| `--resume` with id prefix, path or picker; `--continue` | help | `omp --help` |
| `--cwd` overrides the start directory | help | `omp --help` |
| `--restore` resumes unfinished turn and subagents | help | `omp --help` |
| `omp session pack`, `unpack --cwd`, `moved --to`, `lease` | help | `omp session --help` |
| Resuming a stale-marked copy forks it | help | `omp session --help` |
| `omp --export`, `omp anonymize` | help | `omp --help`, command list |
| `agent.db`, `history.db`, `models.db` in agent directory | files | Directory listing (contents not read) |

## Peers and RPC

| Fact | Status | Source |
|---|---|---|
| `--mode rpc`, `rpc-ui`, `--no-ui` | help | `omp --help` |
| RPC message framing | verify | Not in help |
| `omp acp` | help | `omp --help`, `omp acp --help` |
| `omp collab list/link`, `--view`, `omp join LINK` | help | `omp collab --help`, `omp join --help` |
| `omp ps` actions and flags | help | `omp ps --help` |
| `omp session lease --json --` | help | `omp session --help` |
| An instance-to-instance message command | not found | Absent from the command list in `omp --help`; treat as verify if any doc claims one |

## Not checked

- Provider accounts, billing and quotas (`omp usage` exists; not read).
- Contents of any credential file, database or session. Deliberately not read.
- Behaviour of a running session on config change. Verify on the machine before relying on it.
