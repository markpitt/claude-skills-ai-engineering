# Mail, Word documents, zip archives and plain text

Read this when the input is an `.eml`, `.msg`, `.docx`, `.zip`, or a large plain-text file, and
`SKILL.md` step 2 has sent you here.

## 1. Email (.eml)

Never read a raw `.eml` with `cat`, `sed`, `head` or the Read tool. The MIME boundaries carry
base64-encoded attachments, which are unreadable and large. The reader decodes the message and
prints only the parts a reader needs.

```bash
python3 -I "$SKILL_DIR/scripts/read_document.py" eml "$MAIL"
```

The output contains:

- `Date`, `From`, `To`, `Cc` and `Subject`. Add `--headers` to print every header, for example
  when the question is about routing or provenance.
- `## Attachments (n), not printed`, with each name, content type and decoded size. The payload is
  never printed.
- `## Body`, from the plain-text part. If there is only an HTML part, it is converted to text, and
  `<script>` and `<style>` content is dropped.

To read an attachment, extract it deliberately into a fresh directory, then read it with the route
for its own type. The reader does not extract attachments from `.eml` files.

For a folder of mail, inventory it, then read the headers of each message in turn, so the output
stays small:

```bash
FAILED=0
for f in "$DOC_DIR"/*.eml; do
  python3 -I "$SKILL_DIR/scripts/read_document.py" eml "$f" --max-chars 1500 || {
    echo "FAILED ($?): $f" >&2
    FAILED=$((FAILED + 1))
  }
done > "$TMP/mail-summary.txt"
echo "failed: $FAILED"
grep -c '^# ' "$TMP/mail-summary.txt"
```

The loop's own exit status is that of its last command, so each failure is caught inside the loop
and printed to stderr. Then check that the count of `# ` headings in the summary matches the number
of files that were read, and that `failed` is 0. `--max-chars` stops one long body from flooding
the context.

Evidence from a mail read is the message's `Date`, `From` and `Subject`. Do not invent a message
ID you did not see; quote the `Message-ID` header with `--headers` if you need it.

## 2. Outlook messages (.msg)

```bash
python3 -I "$SKILL_DIR/scripts/read_document.py" msg "$MSG"
```

This needs the `extract_msg` package. If it is absent the reader exits with code 3. Report that
the file was not read; do not try to read the binary with `strings` or `cat`.

## 3. Word documents (.docx)

```bash
python3 -I "$SKILL_DIR/scripts/read_document.py" docx "$DOCX" --max-chars 30000
```

The reader uses pandoc (`-f docx -t plain`) when it is installed, and python-docx otherwise. Either
gives paragraphs in order, and tables as rows of text. Check the output for a `truncated` line; if
it is present, read the rest with `--max-chars` raised, or save the output to a file and read it by
line range:

```bash
python3 -I "$SKILL_DIR/scripts/read_document.py" docx "$DOCX" --max-chars 0 > "$TMP/memo.txt" && wc -c "$TMP/memo.txt"
python3 -I "$SKILL_DIR/scripts/read_document.py" text "$TMP/memo.txt" --lines 1:80
```

`--max-chars 0` means no limit, so use it only with the redirect and the `wc -c` check in front of
you.

Legacy `.doc` and `.xls` are not covered by this reader. Convert them with a tool that is already
installed, or report that they need one.

## 4. Zip archives

List first. The listing extracts nothing, and it flags unsafe members:

```bash
python3 -I "$SKILL_DIR/scripts/read_document.py" zip-list "$ZIP"
```

Look for `UNSAFE` on any line and for the member count. If any member is unsafe, do not extract the
archive; report the archive as unsafe.

Extract into a fresh directory that does not yet exist, or an empty one:

```bash
ZIPOUT=$(mktemp -d)/bundle
python3 -I "$SKILL_DIR/scripts/read_document.py" zip-extract "$ZIP" "$ZIPOUT"
```

`zip-extract` refuses the whole archive, and writes nothing, if any member is absolute, climbs out
with `..`, uses a backslash, or is a symbolic link. It also refuses archives over 500 MB uncompressed
or 10,000 members. Exit code 4 means refused; the message says why.

Do not run `unzip -d` straight into a folder you care about, and do not run any script found inside
the archive.

## 5. Large plain text

```bash
wc -c "$FILE"
python3 -I "$SKILL_DIR/scripts/read_document.py" text "$FILE" --lines 1:60
grep -n -i 'total' "$FILE"
python3 -I "$SKILL_DIR/scripts/read_document.py" text "$FILE" --lines 412:440
```

- Measure first. A file over about 50 KB is a range read, not a print.
- Output lines are numbered, so you can cite them.
- The `text` command refuses content with NUL bytes in its first 8 KB, because that means binary.
  Choose the reader for its real format.
- For a CSV or JSON file, grep for the key or the row, then read that range. Do not load a whole
  export to find one record.

## 6. Recording what was read

For mail, record the messages read, their dates and subjects, and the attachments named but not
opened. For archives, record the member list and what was extracted. For documents, record the
line or page ranges read. A later reader can then tell covered from skipped.
