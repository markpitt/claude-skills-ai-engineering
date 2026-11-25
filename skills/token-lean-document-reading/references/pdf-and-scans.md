# PDFs and scanned pages

Read this when the input is a PDF, or a scan, and `SKILL.md` step 2 has sent you here.

## 1. Check the page count and the text layer

```bash
python3 -I "$SKILL_DIR/scripts/read_document.py" pdf-info "$PDF"
```

The output has `Pages:` and `text layer: present` or `text layer: absent`. Use the page count to
pick ranges. Use the text layer result to pick the route:

- **Present:** read the text with `pdf-text` (below).
- **Absent:** the pages are images. Go to section 4, OCR, before reading content.

The text-layer check reads the whole file once, so it is cheap for short documents and slower for
very large ones. It does not render anything.

## 2. Read a page range into a temporary file

```bash
TMP=$(mktemp -d)
python3 -I "$SKILL_DIR/scripts/read_document.py" pdf-text "$PDF" 1 40 > "$TMP/p1-40.txt" && wc -c "$TMP/p1-40.txt"
```

- The output uses `pdftotext -layout`, which keeps table columns aligned. Use it for tables and
  for clauses with numbering.
- Each page starts with `=== page N ===`, so a grep hit gives its page directly.
- Ranges are 1-based and inclusive. A first page beyond the document exits with code 5 and an
  error message, not an empty file.

## 3. Grep, then read the matched ranges

```bash
grep -n -i 'termination' "$TMP/p1-40.txt"
python3 -I "$SKILL_DIR/scripts/read_document.py" text "$TMP/p1-40.txt" --lines 118:150
```

- Search for the term, the defined word or the figure you need, not for a whole section name. Try
  two spellings where the document could vary (for example `licence` and `license`).
- Read the matched lines with context. Widen only when the match is ambiguous.
- If the text has no hit in 1 to 40, the answer may be on a later page. Extend the range in steps
  of about 40 pages rather than reading the whole document at once.
- For a long document, build the `pdf-text` output once per section and grep those files, rather
  than re-extracting the pages for every question.

## 4. Scanned pages and OCR

If `pdf-info` reports no text layer, or `pdf-text` returns only page headers, the content is an
image. Run OCR only when the content matters, and only on the pages that matter.

Preferred: make a searchable copy, then use the same route as section 2.

```bash
ocrmypdf --skip-text "$PDF" "$TMP/searchable.pdf"
python3 -I "$SKILL_DIR/scripts/read_document.py" pdf-info "$TMP/searchable.pdf"
```

`--skip-text` leaves pages that already have text alone. If `ocrmypdf` is not installed, the
reader cannot supply OCR: report that OCR is needed, and do not guess at the content.

Page-by-page alternative with tesseract:

```bash
pdftoppm -r 300 -f 2 -l 2 -gray -png "$PDF" "$TMP/scan"
ls "$TMP"/scan-*.png
tesseract "$TMP/scan-02.png" stdout > "$TMP/scan-02.txt" && wc -c "$TMP/scan-02.txt"
```

`pdftoppm` zero-pads the page number to the length of the document's page count, so the file may
be `scan-2.png` or `scan-02.png`. Run the `ls` first and use the name it shows.

- 300 dpi is the usual setting for OCR. 100 dpi is for looking, not for reading small print.
- OCR output has errors in names, numbers and dates. Verify every figure you report against the
  image, with a 100 dpi `pdftoppm` view of that page (section 5).
- Never report a number from OCR without checking it visually.

## 5. Look at a page

Use an image only when layout, a signature, a stamp or handwriting is the question.

```bash
pdftoppm -r 100 -f 3 -l 3 -png "$PDF" "$TMP/page"
```

This writes `page-3.png` (the page number is zero-padded when the document is long). Open that
image with the image reader. Do not render every page to look for something; find the page with
grep first.

## 6. Failure modes to check for

| Symptom | Cause | What to do |
|---|---|---|
| Exit 5, "Incorrect password" | Encrypted PDF | Report it; do not guess at the content |
| Text is present but garbled | Font encoding problem | Check one page visually before trusting the text |
| Table columns run together | Layout mode not used | Re-run with `pdf-text`, which uses `-layout` |
| Hits appear on a page that is not the one you expected | Page labels differ from page indices | Cite the page index the reader printed, and say which |
| Output is shorter than the page count implies | Some pages are images | Check `pdf-info`, then OCR those pages |

## 7. Record what you read

Note the file name, the page range read, the page of each fact, and any pages skipped or
unreadable. A later reader should be able to see whether the whole document was covered.
