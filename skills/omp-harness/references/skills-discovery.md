# Skills discovery and settings

Contents

1. Where skills are read from
2. Settings that control discovery
3. Run-time filters
4. Why a new skill does not appear
5. The skill registry
6. Writing a skill for omp

## 1. Where skills are read from

Personal skills sit at `~/.omp/agent/skills/<name>/SKILL.md` (confirmed from files; one observed
skill folder has a `SKILL.md` and supporting folders beside it).

Other locations are controlled by settings. The keys below are confirmed from `omp config list`:

| Key | Meaning |
|---|---|
| `skills.enabled` | Master switch |
| `skills.enablePiUser`, `skills.enablePiProject` | The `pi`-named user and project locations |
| `skills.enableAgentsUser`, `skills.enableAgentsProject` | The cross-tool `.agents/skills` convention, for user and project |
| `skills.enableClaudeUser`, `skills.enableClaudeProject` | Claude-style locations |
| `skills.enableCodexUser` | Codex-style user location |
| `skills.customDirectories` | Extra folders to read |

Defaults can differ by version and by layer. Read the value that applies with
`omp config get skills.KEY`, not from memory. Which folders the `pi`-named locations read, and
their project folder names, are **verify with omp --help**.

## 2. Settings that control discovery

Confirmed config keys:

- `skills.customDirectories`: a list of extra folders.
- `skills.ignoredSkills`: skill names to drop.
- `skills.includeSkills`: names to keep when the list is non-empty. Check whether an empty list
  means "all" with `omp config get skills.includeSkills` and a test, not by assumption.
- `skills.manualSkills`: skills that are loaded only when asked for by name. The exact behaviour is
  **verify with omp --help**.

## 3. Run-time filters

Confirmed from help:

```bash
omp --no-skills "task"                 # no skills at all for this run
omp --skills='git-*,docker' "task"     # only skills whose names match these globs
```

These are the quickest way to find out whether a skill's content is what changes behaviour: run the
same prompt with and without the filter.

## 4. Why a new skill does not appear

Work through these in order, and stop at the first cause:

1. The file exists at the expected path and its folder name matches the `name` field.
2. The frontmatter parses as YAML and has a `name` and a `description`. Whether a parse error is
   reported in the session is **verify with omp --help**; check the file with a YAML parser first.
3. The location's `skills.enable*` key is `true` for this layer. Read it with `omp config get`.
4. `skills.ignoredSkills` does not name it, and `skills.includeSkills` does not exclude it.
5. The session was started after the file was added. Discovery at session start is the expected
   behaviour; whether an in-session reload exists (such as `/restart`) is **verify with
   omp --help**, because the CLI help does not list it.
6. Do not restart another agent's session to make it appear. Start a new session for the work.

## 5. The skill registry

The CLI manages skills from a registry (confirmed from help: `omp skill`, registry at
`skills.registryUrl`):

```bash
omp skill search TERM
omp skill info NAME
omp skill list
omp skill install NAME              # without -g, the project layer (verify with omp --help)
omp skill install -g NAME           # the user-global skills.json
omp skill uninstall NAME
omp skill update NAME
```

Installing a skill that ships scripts asks first unless `-y` is given. Read the scripts before
installing with `-y`.

Publishing (`omp skill publish`) has a `--dry-run` that packs and validates without publishing, and
an `--allow-secrets` flag that publishes even when credential-shaped strings are found. Always run
the dry run first, and do not use `--allow-secrets` to get past a finding without reading it.

## 6. Writing a skill for omp

- Keep `SKILL.md` to the instructions, with detail in supporting files that it names.
- Write the description so that a model can tell when to use it, and say what it must not be used
  for. The same discipline as the other skills in this repository applies.
- Test discovery with a fresh session and the `--skills` filter before relying on the skill.
