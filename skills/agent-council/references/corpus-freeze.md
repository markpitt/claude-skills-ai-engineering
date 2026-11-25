# Corpus freeze

Corpus mode reviews a fixed set of inputs. The freeze makes that set fixed: what each member read is
what was locked, the same items are not counted twice, and nothing enters the set after the
independent view has started without being recorded. Do this before any member is dispatched.

All paths are relative to the repository root. `<slug>` names the review.

## Outputs

| Artefact | Purpose |
|---|---|
| `docs/council/<slug>/corpus/` | The kept inputs, copied, each named `NNN-<basename>` |
| `docs/council/<slug>/MANIFEST.sha256` | SHA-256 of every corpus file, one line each |
| `docs/council/<slug>/CORPUS.md` | What was collected, excluded, de-duplicated, locked, and amended |

If the source material is private, do not copy it into the repository. Freeze it into an empty
directory outside the repository, state that absolute path in `CORPUS.md`, and commit only the
manifest and `CORPUS.md`. The manifest still proves what was read.

## Steps

### 1. Collect candidates and state the denominator

```bash
src=<absolute path of the source directory>
find "$src" -type f -not -path '*/.git/*' | sort > /tmp/council-candidates.txt
wc -l /tmp/council-candidates.txt
```

Record the count in `CORPUS.md` as the denominator: every later "N of M" uses it. Read the count;
an empty file is a wrong path, not an empty corpus.

### 2. Hash the candidates

```bash
xargs -d '\n' sha256sum < /tmp/council-candidates.txt > /tmp/council-candidate-hashes.txt
wc -l /tmp/council-candidate-hashes.txt
```

Use `-d '\n'` so paths containing spaces survive.

### 3. Exclude by category, before reading content

Exclude these categories until the independent view is locked:

| Category | Examples | Why |
|---|---|---|
| Earlier reports and reviews | Any earlier council, audit or review of this object | A member who reads one returns its view |
| Prior verdicts | Any earlier verdict, decision record or conclusion on this object | Same reason; it also anchors the adjudicator |
| Drafts and superseded versions | Earlier drafts of the object, unless the object is the draft | The review is of one revision |
| The author's commentary | Notes explaining the object's intent | Members must judge what the record says, not what the author meant |

Decide categories from file names, folder names, headers and metadata, not from a reading of the
content that would colour the rest of the selection. Every excluded path goes into `CORPUS.md` with
its category and a one-line reason.

Excluded items are not deleted and are not copied into the corpus. After the lock, the adjudicator
may read them to compare its verdict with earlier conclusions. Members never receive them.

### 4. De-duplicate

Two copies of one opinion are one opinion. Count each piece of content once.

- **Identical bytes.** Find them with the hash list:
  ```bash
  sort /tmp/council-candidate-hashes.txt | uniq -w64 -D
  ```
  Keep one path per hash. Record the rest as duplicates of it.
- **Identical content in different formats.** A mail and its attachment, a document and its PDF,
  an export and its source. Extract the text with the sanctioned reader for that format, normalise
  whitespace, and hash the text. Equal text hashes form one content group. Keep the native source
  in preference to an export, and record the group.

Record every group in `CORPUS.md`: the kept path, and the paths it stands for.

Never read mail, office or archive formats raw. Use the sanctioned reader for the format. For PDFs,
run `pdftotext -layout <file> -` first. Before extracting any archive, list it with `unzip -l`,
then extract into a new, empty directory.

### 5. Copy the kept items

```bash
mkdir -p docs/council/<slug>/corpus
n=0
while IFS= read -r src_file; do
  n=$((n+1))
  id=$(printf '%03d' "$n")
  cp -- "$src_file" "docs/council/<slug>/corpus/${id}-$(basename -- "$src_file")"
  printf '| %s | %s |\n' "$id" "$src_file" >> docs/council/<slug>/CORPUS.md
done < /tmp/council-kept.txt
ls docs/council/<slug>/corpus | wc -l
```

`/tmp/council-kept.txt` lists the kept source paths, one per line, after steps 3 and 4. The
corpus item IDs (`001`, `002`, ...) are the names members use in their coverage statements. Read
the copy count and check it equals the kept count. A mismatch means a copy failed; do not proceed.

### 6. Write the manifest

```bash
(cd docs/council/<slug>/corpus && find . -type f | sort | xargs sha256sum > ../MANIFEST.sha256)
wc -l docs/council/<slug>/MANIFEST.sha256
```

Run the subshell form so the working directory does not carry over. The manifest lines are relative
to the corpus folder, so the check must run from there.

### 7. Lock and commit

1. Run the check and read its output:
   ```bash
   (cd docs/council/<slug>/corpus && sha256sum -c ../MANIFEST.sha256; echo "exit $?")
   ```
   The pass condition: every line reads `OK`, the exit status is 0, and the number of `OK` lines
   equals the copy count from step 5.
2. Record the lock in `CORPUS.md`:
   - the denominator from step 1
   - the number of excluded items, by category
   - the number of duplicates and content groups
   - the number of kept items
   - the lock time, and the SHA-256 of the manifest file itself:
     ```bash
     sha256sum docs/council/<slug>/MANIFEST.sha256
     ```
3. Commit the corpus and the manifest as their own commit, before any dispatch, so that the freeze
   is visible in history:
   ```bash
   git add docs/council/<slug>/CORPUS.md docs/council/<slug>/MANIFEST.sha256 docs/council/<slug>/corpus/001-<basename> docs/council/<slug>/corpus/002-<basename>
   git commit -m "docs(council): freeze <slug> corpus"
   ```
   List every corpus file explicitly, one per path, rather than a directory.

## Re-check before adjudication

Run the check from step 7 again before the adjudicator writes the verdict. Every line must still
read `OK`. A `FAILED` line means a corpus file changed during the review. Any reading of that item is
void: rerun the lenses that opened it, and say so in the verdict.

## Amendments

New evidence offered after the lock, typically by the author in a rebuttal round, is an amendment.
It is not silently added.

1. Copy the item to `docs/council/<slug>/corpus/A<NNN>-<basename>`.
2. Append its hash line to `MANIFEST.sha256`. Append, never rewrite, so that `git diff` shows exactly
   what was added:
   ```bash
   (cd docs/council/<slug>/corpus && sha256sum ./A001-<basename> >> ../MANIFEST.sha256)
   ```
3. Add an AMENDMENTS section to `CORPUS.md` with the date, the requester, the reason, the path, and
   the manifest hash as it stood before the append.
4. Report the amendment in the verdict, next to the findings it bears on.

Amendments are reviewed against the same lens as the original items, and only by the verification
step, not by a fresh council.
