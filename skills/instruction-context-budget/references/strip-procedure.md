# Strip procedure: moving rationale out of always-loaded files

This procedure takes one always-loaded file (a context file, a rule without `paths:`, or a memory
index) and moves its rationale and history into a companion file. The imperatives stay where the
harness loads them. The companion is kept beside the source, in `.staging/`, where no loader reads it.

Work one file at a time. Finish one file, verify it, and only then start the next.

## 1. Confirm the target is clean and yours

```bash
git -C <repo> status --short
git -C <repo> rev-parse --show-toplevel
```

Stop if the tree has changes you did not make. A dirty tree that is not wholly yours is a stop,
whatever else is true. In a tree another session writes, read `git status` before every edit.

## 2. Tag the repository before the work

Tag the commit you are about to change, so the starting point can be found and restored without a
rewrite:

```bash
git -C <repo> tag -a context-budget-before-<YYYYMMDD> -m "Before instruction context budget pass"
git -C <repo> rev-parse context-budget-before-<YYYYMMDD>^{commit}
```

Report the tag name and the commit it names. A tag is a reference, not a commit: do not push it
unless the repository's policy says tags are pushed. Do not move or delete an existing tag.

## 3. Measure the before state

```bash
python3 -I <skill>/scripts/measure_context_budget.py measure --json <root> > "$TMPDIR/before.json"; echo "exit=$?"
```

Exit 2 means a root does not exist. Fix the root. A total from a wrong root is a false total.
Keep the JSON outside the repository, so it is not committed by accident.

## 4. Classify every block of the file

Read the whole file. It is small by definition, so whole-file context is required here. Put each
block (a heading and its bullets, or a paragraph) into one of four classes:

| Class | Meaning | Action |
|---|---|---|
| Imperative | Says what to do or not do, in terms an agent can act on | Keep verbatim |
| Rationale | Says why the imperative exists | Move to the companion |
| History | Says how the rule came to be, who asked, the dates and the incident | Move to the companion |
| Pointer | Points at another file that carries the detail | Keep, one line |

Some blocks mix classes. Split them: the imperative clause stays, the reason clause moves.

A ruling with a date that changed the rule keeps a short date tag on the imperative, for example
`(ruling 16/10/2026)`, so a reader can tell that it is settled. The story of the ruling moves.

A deliberate absence keeps its reason. "Do not run the suite unwrapped" is an imperative. Why the
suite cannot be run unwrapped is rationale, and it moves, but the absence stays in the file.

## 5. Write the companion first, then edit the source

The companion is written before the source is cut, so no text exists only in a deleted state.

Companion path: `<dir>/.staging/<name>.prose.md`, where `<name>` is the source's filename without
extension, and `<dir>` is the source's directory. Structure:

```markdown
# <name>: rationale and history moved from <source filename>

Moved on <DD/MM/YYYY> from `<source filename>`, commit <sha or "uncommitted">.
Each section quotes the imperative it supports, so the reason can be found from the rule.

## <imperative, quoted verbatim>

<rationale and history, verbatim where possible>
```

Quote each moved line exactly as it stood in the source. The verification step matches lines
verbatim, so a paraphrase in the companion is reported as lost, which is the correct result: it
needs a human look.

## 6. Edit the source

Remove the moved lines and keep the imperatives. Shortening an imperative is allowed, but a reworded
line is a change of meaning until a person has checked it, and the verification step flags it.

Write the edited source to its own file, not over the original, then compare:

```bash
python3 -I <skill>/scripts/measure_context_budget.py verify-move \
  --before <original-copy> --after <edited-file> --companion <dir>/.staging/<name>.prose.md; echo "exit=$?"
```

- Exit 0: every removed line is in the companion, and nothing was reworded silently.
- Exit 1: a removed line is in neither the source nor the companion. Restore it to the companion
  or the source, and run the check again. Do not accept exit 1 by editing the check.
- Keep `<original-copy>` outside the repository (for example in `$TMPDIR`), or take it from the tag
  with `git show context-budget-before-<YYYYMMDD>:<path>`.

## 7. Check the companion is not loaded

The companion must not be in any harness's load path. Check three things:

1. It sits in `.staging/`, which the measurement script excludes and the harnesses do not scan.
2. No `CLAUDE.md` or `AGENTS.md` imports it with `@path`. Search for it:
   `grep -rn "staging" <repo> --include=CLAUDE.md --include=AGENTS.md`. Empty output means no import.
3. It is not under `.claude/rules/` or a `rules/` folder that a harness reads.

## 8. Measure the after state and re-check the load

```bash
python3 -I <skill>/scripts/measure_context_budget.py measure --json <root> > "$TMPDIR/after.json"; echo "exit=$?"
```

Compare `always_bytes` and `always_est_tokens` in the two JSON files. Then re-check which files
loaded with `agent-instruction-load-audit`: its static audit for frontmatter, symlinks and
precedence, and its runtime probe for what the session actually had in context. A smaller file that
no longer loads is a regression, not a saving.

## 9. Commit under the repository's policy

Commit per the repository's rules: one logical change, explicit paths, Conventional Commits. A
companion file and the edited source are normally one commit. In a shared index, commit with
explicit paths only. Do not commit the JSON measurements.

## 10. Report

Give the tag, the before and after byte and token counts per file, the companion paths, the exit
codes of both `verify-move` runs as they were printed, and anything not verified (for example a
harness whose load was not probed after the change).
