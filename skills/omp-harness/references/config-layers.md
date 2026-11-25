# Config layers, precedence and what to commit

Contents

1. The files
2. Precedence
3. Reading and writing settings
4. Commit or gitignore: the tradeoff
5. Per-run overlays

## 1. The files

| File | Layer | Evidence |
|---|---|---|
| `~/.omp/agent/config.yml` | Global, for every project | confirmed from files |
| `<repo>/.omp/config.yml` | Project, read from the working directory | confirmed from files and from `omp config list --scope` help text (`<cwd>/.omp`) |
| `~/.omp/agent/models.yml` | Providers and their models | confirmed from files |
| `~/.omp/agent/lsp.json` | Language servers | confirmed from files |
| `~/.omp/agent/rules/*.md` | TTSR rules | confirmed from files |
| `~/.omp/agent/skills/<name>/SKILL.md` | Personal skills | confirmed from files |
| `<repo>/.omp/hooks/pre/*.ts` | Project hook files | confirmed from files; automatic loading is **verify with omp --help** |

The agent directory is printed by `omp config path`. Do not hard-code `~/.omp/agent` in
anything shared; use `$(omp config path)` in local scripts.

## 2. Precedence

The project config header states the order: **global, then project, then CLI overlay, then
runtime**. Later layers win. Runtime means changes made in the running session through `/settings`.

Two checks confirm the layering on a machine:

```bash
omp config get KEY                    # the merged value
omp config list --scope=project       # only the keys the project layer sets, as written
```

`--scope` on `list` takes `global` or `project` (help text). Use the two together to see which
layer a value came from.

## 3. Reading and writing settings

Confirmed subcommands:

```bash
omp config list [--scope=global|project] [--json]
omp config get KEY
omp config set KEY VALUE...
omp config reset KEY
omp config path
omp config init-xdg                   # help lists it; read `omp config init-xdg --help` before use
```

Writing with `set` is convenient but its target layer is **verify with omp --help**. For a value
that belongs to a project, edit the project's `.omp/config.yml` directly and check with
`omp config get`.

Values in `config list` can include credentials on some setups. Use `--scope=project` for
shared notes, and redact before pasting output anywhere.

## 4. Commit or gitignore: the tradeoff

A project's `.omp/` holds two kinds of thing:

- **Shared**: hooks, bash approval patterns, the agreed role for each job, the rules everyone
  should follow. These belong in git, so a clone behaves the same way.
- **Personal**: a local endpoint, a role set to a model one person has access to, a profile
  preference. These do not belong in a shared file.

Pick one of these, per repository:

| Choice | Effect | Use when |
|---|---|---|
| Commit `.omp/config.yml` with only shared settings | Clones match; personal settings stay in the global file | Most repositories |
| Commit `.omp/` and set `modelRoleStorage: project` | Role choices made in the UI land in the shared file, so commit them deliberately | The team agrees the roles |
| Gitignore `.omp/` | Nothing in the folder is shared; hooks are not shared either | The whole project file is personal to one machine or one person |

Whichever you choose, check the ignore state with `git check-ignore -v .omp/config.yml`. An empty
output means the file is not ignored. Do not assume either way.

`modelRoleStorage: project` is stated in the project config header: role changes made in the model
selector save to the project file, and other `/settings` changes still go to the global file.

## 5. Per-run overlays

`--config FILE` loads an extra config-style file for one run. It can be given more than once
(confirmed from help). It sits above the project layer and below runtime changes, so it is the
right place for a temporary local-only run, instead of editing a shared file:

```bash
omp --config /tmp/local-only.yml --offline -p "reply with the word ready"
```

Keep such overlay files outside the repository, and delete them after the run.
