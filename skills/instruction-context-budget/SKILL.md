---
name: instruction-context-budget
description: Measures what a coding-agent harness always loads (CLAUDE.md and AGENTS.md chains, unscoped rules, memory indexes and skill descriptions) in bytes and estimated tokens per file, then trims rationale and history out of those files into companion files while keeping the imperatives. Tags the repository first, verifies that no removed line was lost, and re-checks the result with agent-instruction-load-audit. Use when a session starts with too much instruction text loaded, a memory index is over its cap, skill descriptions crowd the context, or asked to slim CLAUDE.md, rules or memory. Do NOT use to prove which files a session actually loaded (use agent-instruction-load-audit), to write new instruction content (use ai-coding-agent-setup), or to change what a skill does (use skill-creator).
license: Apache-2.0
metadata:
  version: "1.0.0"
  tags: "agents, context-window, instructions, claude-md, agents-md, rules, memory, token-budget, measurement, pi, omp"
---

# Instruction context budget

**Goal:** make the instruction text a session pays for before its first message as small as its
imperatives allow, without losing the reasons a reviewer needs. Report the before and after in
bytes (exact) and estimated tokens, per file.

Only the always-loaded surfaces count: the instructions a session has before any work starts and
on every request after. A rule scoped by `paths:`, a topic memory and a skill body load on demand,
so they are listed but not budgeted. See `references/surfaces-by-harness.md`.

## Quick reference

| Situation | Load |
|---|---|
| Which surfaces count, and how each harness loads them | `references/surfaces-by-harness.md` |
| Tag, classify, move, verify and re-check one file at a time | `references/strip-procedure.md` |
| Measure a root, or verify a move | `scripts/measure_context_budget.py` (stdlib, Python 3.12) |

## Procedure

Set the skill folder and the root as quoted absolute paths.

```bash
SKILL_DIR=/absolute/path/to/instruction-context-budget
ROOT=/absolute/path/to/repository/or/config/folder
WORK=$(mktemp -d)
```

1. **Fix the harness and its version.** Record both and the date. Read the matching row in
   `references/surfaces-by-harness.md`. A row marked unverified is a measurement, not a finding.

2. **Measure the before state.** Keep the output outside the repository.

   ```bash
   python3 -I "$SKILL_DIR/scripts/measure_context_budget.py" measure "$ROOT"
   python3 -I "$SKILL_DIR/scripts/measure_context_budget.py" measure --json "$ROOT" > "$WORK/before.json"; echo "exit=$?"
   ```

   Exit 2 means a root does not exist. Stop and fix the root: a total from a wrong root is false.
   The table lists `always` files first. Those are the only ones that change the budget. Look at
   `excluded` as well: companion files are reported there so they cannot vanish silently.

3. **Rank the targets.** Start with the largest `always` file, then the skill descriptions. A
   description longer than its trigger needs is paid for in every session that loads the skill.

4. **Strip one file at a time** following `references/strip-procedure.md`. The steps, in order:
   confirm the tree is clean and yours, tag the repository, classify each block as imperative,
   rationale, history or pointer, write the companion under `.staging/` first, then cut the source.

5. **Verify the move.** Every removed line must reappear verbatim in a companion file.

   ```bash
   python3 -I "$SKILL_DIR/scripts/measure_context_budget.py" verify-move \
     --before "$WORK/original.md" --after "$WORK/edited.md" --companion "$DIR/.staging/<name>.prose.md"; echo "exit=$?"
   ```

   Exit 1 lists the lines with no companion copy. Restore them. Do not weaken the check to pass it.

6. **Re-check.** Measure the after state, compare the two JSON files, then run
   `agent-instruction-load-audit` on the same root. Its static audit confirms frontmatter, symlinks
   and precedence. Its runtime probe confirms that the imperatives still reach the session. A file
   that shrank and stopped loading is a regression.

7. **Report.** Use the template in `references/strip-procedure.md`, step 10.

## Rules

- **Imperatives stay in the always-loaded file.** Only rationale and history move. A rule that
  moves out of its file is no longer a rule the harness enforces.
- **Move, never delete.** A line removed from a source must exist in a companion file, or the
  verification fails. A deletion leaves no record, and the record is what a reviewer needs.
- **Companion files live in `.staging/` beside the source.** They are never named in `CLAUDE.md`
  or `AGENTS.md`, never imported with `@path`, and never placed under a rules folder.
- **Tag before the first edit, and stop on a dirty tree.** The tag name and commit go in the report.
- **Do not change meaning to save tokens.** A reworded imperative is a change until a person has
  checked it. Shortening wording is allowed; dropping a condition is not.
- **Preserve deliberate absences with their reason.** The absence stays as an imperative. Its
  reason moves.
- **Do not measure with the model.** Asking a session how large its instructions are is not a
  measurement. Use the script, and the harness's own context report where it has one.
- **Estimates are estimates.** Tokens are `ceil(bytes / 4)`. Say so wherever a token figure appears.

## Evidence behind the technique

Counts from the operator's session stores, taken for this skill, not transcript content:

- pi (`~/.pi/agent/sessions`): 49 session files, 36 compaction entries, 94 assistant messages with
  an error stop reason.
- omp (`~/.omp/agent/sessions`): 1232 session files, 1733 compaction entries, 4647 assistant messages
  with an error stop reason.

Compaction is the harness's own sign that the context window was full. Where it is frequent, the
always-loaded set is a candidate, though the count alone does not show that instructions caused it.

## Tests

Run them through the sandbox wrapper, from a directory inside the repository:

```bash
mp-sandbox-test python3 -P "$SKILL_DIR/scripts/test_measure_context_budget.py" -v
```

The tests generate their fixtures at run time. They include a missing-root case that must exit 2, a
dropped-line case that must exit 1, and a one-word rewording that must not pass.

## Limits

- Tokens are estimates. Two harnesses that tokenize differently can disagree with the same bytes.
- The script reads frontmatter with a small parser, not YAML. Unusual scalar forms (anchors, flow
  mappings) are not parsed, and the description is then counted as empty. Check the `skill-description`
  rows by eye when a skill uses them.
- A harness can change what it loads. Re-check the row in `references/surfaces-by-harness.md` for
  the version in use.
- The script measures files. It does not measure the system prompt a harness builds from them, or
  the tool definitions it sends.
