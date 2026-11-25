# Runtime probe: proving what a session loaded

Read this in step 4 of `SKILL.md`, after the expected set is written. The static audit says what
should load. The probe says what did, in a live session.

## 0. Why a canary, and why not a list

Asked for a list of the rules it has loaded, a model builds one from whatever it can see. That
includes files it read with a tool earlier, files it assumes exist, and files it remembers from
another session. A canary separates these. Each instruction file carries one unique marker string
that exists nowhere else. A session that can report a marker, quoted exactly and tied to its file,
has it in context. A session that cannot has not got it, whatever it believes.

The probe answers "what is in context". It does not answer "what did the model use". Say so in the
report.

## 1. Set up a disposable copy

Never insert markers into a live shared file, and never leave one behind.

1. Choose a scratch location with `mktemp -d`. For project files, create a git worktree of the
   target repository there (`git worktree add <scratch>/probe HEAD`), so the live working tree is
   untouched. Run the probe session from inside that worktree.
2. For user-level files (for example `~/.claude/CLAUDE.md`), check first whether the harness has a
   configuration-directory override. If it does, point the override at a scratch copy of the user
   files. If it does not, probe user-level files only in the owner's own session, with the owner's
   agreement, and restore them afterwards as in step 5.
3. Record a checksum of every file before you touch it:

```bash
find "$PROBE_ROOT" -type f \( -name 'CLAUDE.md' -o -name 'AGENTS.md' -o -name '*.md' \) \
  -not -path '*/.git/*' -exec sha256sum {} + > "$TMP/before.sha256"
```

Check the exit status of that command before you go on. A missing checksum file means nothing can
be restored.

## 2. Insert the markers

Use one marker per file, in plain text on its own line. Use the form `CANARY-<kind>-<6 hex>`,
for example `CANARY-claude-md-3fa91c`. Generate the hex from `openssl rand -hex 3` or equivalent.

Do not use HTML comments as the carrier. A harness may strip comments before it injects a file, and
then a missing marker tells you nothing about loading. A plain line is always injected with its
file.

Write the marker list to `$TMP/canaries.tsv` as `marker<TAB>file`. That file is the ground truth
for the comparison in step 4.

## 3. Run the probe in a fresh session

Start a new session in the probe worktree, and make no earlier reads of the instruction files in
it. Send this prompt unchanged. It contains no marker, so any marker in the answer came from context.

```text
Do not use any tool. Do not read, list, search or run anything. Do not change any file.

Answer only from what is already in your context before this message.

1. Report the working directory you were given at startup, if it is in your context. Do not check it.
2. List every string in your context of the form CANARY-, then a kind of lowercase letters and
   hyphens, then a hyphen, then six lowercase hex characters. For each one give:
   - the exact string, verbatim
   - the heading, path attribute or file name that the string sits under, as you can see it
3. If you can see no such string, say NONE.
4. For each instruction file you believe you have, say whether its text is in your context, or
   whether you are inferring that. Use the words IN CONTEXT or INFERRED. Do not list a file you
   cannot see text from.
5. Do not add a file to the list because it seems likely to exist.

Return the answer in that order, with no other commentary.
```

Run it once per harness and per session start. A second run after a `/compact` or a restart is a
separate probe, because compaction can drop content.

## 4. Compare and classify

Build the table from `$TMP/canaries.tsv` and the reply. Every marker gets one row.

| Classification | Test | Meaning |
|---|---|---|
| LOADED | Marker reported, verbatim, under its own file | The file is in context |
| NOT LOADED, EXPECTED | Marker absent, and the static audit or the harness rules explain why | Correct behaviour, for example a `paths:` rule before a matching file is touched, or a file past the size cap |
| NOT LOADED, FAULT | Marker absent, and the file should load | A real failure. Find the cause from the static findings: broken symlink, frontmatter error, wrong file name, fallback names not configured, or an earlier file in the same directory winning |
| SHADOWED | Marker absent, and a file of higher precedence in the same directory is loaded | The loader took another file. Name the file that won |
| UNEXPECTED | Marker reported for a file not in the expected set, such as a parent or an import | Record it. It may be correct, and the expected set was incomplete |
| UNVERIFIED | Marker reported under the wrong file, or the reply is ambiguous | Re-run the probe. Do not count it as loaded |

A reply that lists a file as IN CONTEXT without a marker is not LOADED. It is a claim, so mark it
UNVERIFIED and say so.

Check the reply for a false positive first. If a reported marker is not in `canaries.tsv`, the
probe prompt, the transcript or an earlier read of the file caused it. Mark it UNVERIFIED.

## 5. Restore and verify

```bash
find "$PROBE_ROOT" -type f \( -name 'CLAUDE.md' -o -name 'AGENTS.md' -o -name '*.md' \) \
  -not -path '*/.git/*' -exec sha256sum {} + > "$TMP/after.sha256"
diff "$TMP/before.sha256" "$TMP/after.sha256" && echo "restored: identical"
```

For a git worktree, remove it with `git worktree remove <scratch>/probe` once the report is written.
Do not use `git stash` to restore; a shared stash is not yours to pop.

A user-level file restored from a copy must be compared against its original checksum, not the
copy. If the checksums differ, say so in the report and stop until the owner has seen it.

## 6. Report template

```text
Harness: <name> <version>, checked against docs on <date>
Session: <how started>, working directory <path>, fresh session: yes or no
Expected set: <count> files, from the static audit (JSON file path)
Probe reply: <path to the saved reply, verbatim>

| Marker | File | Classification | Reason |
|---|---|---|---|
| CANARY-... | CLAUDE.md | LOADED | reported verbatim under CLAUDE.md |
| CANARY-... | .claude/rules/x.md | NOT LOADED, EXPECTED | paths: rule, no matching file touched |

Faults: <count>. Shadowed: <count>. Unexpected: <count>. Unverified: <count>.
Restored: identical checksums, yes or no.
Not established: <for example, what the model used, or the startup header, which the model cannot see>
```

Name the scope of each claim. "Loaded" means in context at the time of the probe, for that version
and that session start.
