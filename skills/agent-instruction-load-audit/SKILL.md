---
name: agent-instruction-load-audit
description: Proves at runtime which instruction files a coding-agent harness actually loaded, in what precedence, and which failed silently, for Claude Code, Codex CLI, pi, GitHub Copilot CLI and similar. Covers a static inventory with frontmatter, symlink and shadowing checks, then a canary-marker probe run in a fresh session, and reports each file as loaded, not loaded, shadowed or unverified. Use when asked which CLAUDE.md, AGENTS.md, rules, memory or skills an agent really loaded, why an instruction is being ignored, whether a skill will load, or to verify instruction files after a change. Do NOT use to write or restructure AGENTS.md or CLAUDE.md content (use ai-coding-agent-setup), or to audit the content of a project's documentation.
license: Apache-2.0
metadata:
  version: "1.0.0"
  tags: "agents, instructions, claude-md, agents-md, skills, rules, audit, harness, canary, verification"
---

# Agent Instruction Load Audit

**Goal:** establish, from evidence, the set of instruction files a live session has in context,
and say which expected files are missing and why. A file that exists is not a file that loaded.

An agent's own list of what it has loaded is not evidence. It is built from whatever the model can
see, and from files it assumes exist. Two sources are evidence: the harness's own record (for
example `/context all` in Claude Code), and a canary that the session can report verbatim. This
skill uses both, and it reads the loader's rules rather than the model's account.

## Quick reference

| Situation | Load |
|---|---|
| Which files each harness reads, precedence, import and override rules, and how to see them | `references/harness-load-rules.md` |
| Canary markers, the paste-in probe prompt, the classification table and the report template | `references/runtime-probe.md` |

## Procedure

Set the skill folder and the probe root, as quoted absolute paths.

```bash
SKILL_DIR=/absolute/path/to/agent-instruction-load-audit
PROBE_ROOT=/absolute/path/to/the/project/or/worktree/being/audited
TMP=$(mktemp -d)
```

### 1. Fix the target before anything else

Record the harness, its version, the working directory a session will start in, and the date.

```bash
claude --version   # or: codex --version, pi --version
```

For pi, `pi --help` on the installed binary is the authority on its CLI, not the website. Find the
row for the target in `references/harness-load-rules.md`. If the harness is not listed, build its
row from its loader source first, and mark it unverified until step 4 confirms it.

### 2. Build the expected set (static inventory)

```bash
python3 -P "$SKILL_DIR/scripts/audit_instruction_files.py" "$PROBE_ROOT" > "$TMP/audit.txt"; echo "exit=$?"
python3 -P "$SKILL_DIR/scripts/audit_instruction_files.py" --json "$PROBE_ROOT" > "$TMP/expected.json"; echo "exit=$?"
```

- The script needs PyYAML. Exit code 3 means it is not importable from this interpreter. Run it with
  an interpreter that has PyYAML. Do not treat an exit of 3 as a clean audit.
- Exit 1 means errors were found. Read `$TMP/audit.txt` in full: each ERROR line is a file that will
  not load as intended.
- Exit 0 with WARN lines is clean for loading, but read the warnings. An `applyTo` key in a Claude
  rule, for example, means the rule loads for every path.
- Broken symlinks are also reported by the script. For a quick independent check:
  `find "$PROBE_ROOT" -xtype l`. Empty output means none.
- Symlinked directories are followed only where they hold a `SKILL.md`. Check other linked folders
  by hand.

Then write the expected set for the target session, using the rules in
`references/harness-load-rules.md`. Include the user-level files (`~/.claude/CLAUDE.md`, the user
rules folder, `~/.codex/AGENTS.md`), which the static audit of a project does not scan. Note for
each file whether it should load at launch, load on a path match, or not load at all. Do not
include a file on the strength of its existence alone.

### 3. Fix or record the faults before the probe

A skill with a frontmatter ERROR will not load, so probing it will show "not loaded". That is the
right answer, and the cause is already known. Record it as a fault with its cause. Fix it only if
the owner of the repository asks for a fix. The probe then tests the state that really exists.

### 4. Run the runtime probe

Follow `references/runtime-probe.md` in full:

1. Set up a disposable copy, and checksum every file before touching it.
2. Insert one plain-text canary per file, and write `canaries.tsv` as the ground truth.
3. Start a fresh session in the probe worktree, and send the paste-in prompt from the reference,
   unchanged. Do not read any instruction file in that session first.
4. Save the reply verbatim.

For Claude Code, also run `/context all` in the same session, and keep its output as the harness's
own record. It is more reliable than the model's reply.

### 5. Compare, classify and restore

Classify every marker as LOADED, NOT LOADED (EXPECTED or FAULT), SHADOWED, UNEXPECTED or UNVERIFIED,
using the table in the reference. Then restore the files and compare the checksums. Do not finish
the report until the restore has been checked with `diff` and the result shown.

### 6. Report

Use the template at the end of `references/runtime-probe.md`. Put the expected count, the observed
count, each fault with its cause, and what was not established. Name the harness version and the
date of the docs check on the first line. Keep the saved reply and `audit.txt` with the report.

## Rules

- Never ask a session to recite the files it has loaded as the evidence. Ask for markers.
- Never write canary markers into a live shared file, and never leave one in place. Work in a
  disposable copy, and restore from checksums.
- Never put a marker string in the probe prompt. A marker in the prompt is a marker the model can
  see, so the probe would prove nothing.
- Never use `git stash` to restore a probe. Remove a scratch worktree with `git worktree remove`.
- Treat a model's reply as evidence of what was in its context at that moment, not of what it used.
  Say that in the report.
- Do not repair a fault you find. Report it with its cause, unless the owner asks for the fix.
- A probe is per harness, per version and per session start. A result does not carry to another.
- Do not run the probe on a machine or account whose owner has not agreed to the user-level files
  being read in that session.

## Common failures

| Symptom | Likely cause | Check |
|---|---|---|
| A skill never triggers | Frontmatter error, or the name does not equal the folder | `audit.txt` ERROR lines |
| A rule loads for every file | `applyTo` in a Claude rule, which Claude Code ignores | `audit.txt` WARN line |
| `AGENTS.md` loads in one tool but not another | Both files in one directory; each tool takes a different one | `audit.txt` WARN line, and the probe |
| Codex ignores `CLAUDE.md` | Fallback names are not configured for Codex | Codex config, and the probe |
| A Claude rule is not loaded | It has `paths:` and no matching file has been touched | Expected, not a fault |
| The model says a file is loaded, but no marker is reported | The claim is unverified | Classify UNVERIFIED |

## Tests

Run them with an interpreter that has PyYAML (check with `python3 -c 'import yaml'`). Run them through
the repository's sandbox wrapper for test runs, if it has one.

```bash
python3 -P claude-skills-ai-engineering/skills/agent-instruction-load-audit/scripts/test_audit_instruction_files.py -v
```

The tests generate their fixtures at run time. One test removes PyYAML from the interpreter and
expects exit 3, so a missing parser cannot pass as a clean audit.

## Limits

- The probe shows what was in context at one moment. It does not show what the model used, or
  whether the model followed an instruction.
- The startup header that some harnesses print is UI. The model cannot see it, so it cannot report
  from it.
- Hooks that log loads may not see every kind of load. Read the hook's documentation for the
  harness version, and do not treat silence as absence.
- The script inventories a fixed list of filenames. A harness that reads other names needs its
  names added to the expected set by hand.
