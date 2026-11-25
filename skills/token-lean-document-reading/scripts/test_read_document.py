#!/usr/bin/env python3
"""Tests for read_document.py. Run them wrapped:

    python3 -I claude-skills-ai-engineering/skills/token-lean-document-reading/scripts/test_read_document.py -v

Run it through the repository's sandbox wrapper for test runs, if it has one.

Fixtures are generated inside a temporary directory at test time. No test reads a real
document. Every test drives the CLI as a subprocess, so the argument parsing, the exit
codes and the output are what is checked, not an internal function.
"""
from __future__ import annotations

import base64
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from email.message import EmailMessage
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "read_document.py"

EXIT_OK, EXIT_INPUT, EXIT_MISSING_TOOL, EXIT_REFUSED, EXIT_TOOL_FAILED = 0, 2, 3, 4, 5

HAVE_PDFTOTEXT = shutil.which("pdftotext") is not None
HAVE_PANDOC = shutil.which("pandoc") is not None


def make_pdf(page_texts: list) -> bytes:
    """Build a small PDF by hand. A None page has no text layer (a scan stand-in)."""
    count = len(page_texts)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(count))
    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(page_texts):
        content = b"" if text is None else b"BT /F1 24 Tf 72 720 Td (" + text.encode() + b") Tj ET"
        bodies.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode()
        )
        bodies.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(bodies, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(bodies) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(bodies) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


def make_docx(path: Path, paragraphs: list) -> None:
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{body}</w:body></w:document>",
        )


class ReadDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_cli(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        run_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")} if env is None else env
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), *args],
            capture_output=True,
            text=True,
            env=run_env,
            timeout=120,
            check=False,
        )

    # --- inventory -------------------------------------------------------------------

    def test_inventory_lists_names_and_sizes(self) -> None:
        (self.root / "notes.txt").write_bytes(b"x" * 2000)
        (self.root / "letter.eml").write_bytes(b"To: a@example.test\n\nhi\n")
        result = self.run_cli("inventory", str(self.root))
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertIn("notes.txt", result.stdout)
        self.assertIn("letter.eml", result.stdout)
        self.assertIn("2.0 KB", result.stdout)
        self.assertIn("2 file(s)", result.stdout)

    def test_inventory_missing_path_fails_loudly(self) -> None:
        result = self.run_cli("inventory", str(self.root / "absent"))
        self.assertEqual(result.returncode, EXIT_INPUT)
        self.assertIn("does not exist", result.stderr)

    # --- mail ------------------------------------------------------------------------

    def _write_eml_with_attachment(self, payload: bytes) -> Path:
        message = EmailMessage()
        message["From"] = "sender@example.test"
        message["To"] = "reader@example.test"
        message["Subject"] = "Quarterly figures"
        message["X-Trace-Id"] = "trace-4417"
        message.set_content("BODY-MARKER-7731 please see the attached file.")
        message.add_attachment(payload, maintype="application", subtype="octet-stream", filename="report.bin")
        path = self.root / "thread.eml"
        path.write_bytes(message.as_bytes())
        return path

    def test_eml_never_prints_base64_payload(self) -> None:
        payload = bytes((i * 7) % 256 for i in range(300_000))
        path = self._write_eml_with_attachment(payload)
        result = self.run_cli("eml", str(path))
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        out = result.stdout
        # Positive control: the body was found, so an empty result cannot pass this test.
        self.assertIn("BODY-MARKER-7731", out)
        self.assertIn("Quarterly figures", out)
        self.assertIn("report.bin", out)
        self.assertIn("Attachments (1)", out)
        # The payload itself must never appear, in any encoding a mail file would use.
        encoded = base64.b64encode(payload).decode()
        self.assertNotIn(encoded[:60], out)
        self.assertLess(len(out), 4000)

    def test_eml_headers_flag_adds_transport_headers(self) -> None:
        path = self._write_eml_with_attachment(b"abc")
        plain = self.run_cli("eml", str(path))
        full = self.run_cli("eml", str(path), "--headers")
        self.assertEqual(plain.returncode, EXIT_OK, plain.stderr)
        self.assertEqual(full.returncode, EXIT_OK, full.stderr)
        self.assertNotIn("trace-4417", plain.stdout)
        self.assertIn("trace-4417", full.stdout)

    def test_eml_html_only_body_is_converted_and_script_dropped(self) -> None:
        message = EmailMessage()
        message["Subject"] = "Html only"
        message.set_content("<html><body><p>Hello <b>there</b></p><script>alert(1)</script></body></html>", subtype="html")
        path = self.root / "html.eml"
        path.write_bytes(message.as_bytes())
        result = self.run_cli("eml", str(path))
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertIn("Hello there", result.stdout)
        self.assertNotIn("<p>", result.stdout)
        self.assertNotIn("alert(1)", result.stdout)

    # --- pdf -------------------------------------------------------------------------

    @unittest.skipUnless(HAVE_PDFTOTEXT, "pdftotext not installed")
    def test_pdf_text_returns_only_requested_pages(self) -> None:
        path = self.root / "three.pdf"
        path.write_bytes(make_pdf(["PAGEONEWORD", "PAGETWOWORD", "PAGETHREEWORD"]))
        result = self.run_cli("pdf-text", str(path), "2", "2")
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertIn("PAGETWOWORD", result.stdout)
        self.assertIn("=== page 2 ===", result.stdout)
        self.assertNotIn("PAGEONEWORD", result.stdout)
        self.assertNotIn("PAGETHREEWORD", result.stdout)

    @unittest.skipUnless(HAVE_PDFTOTEXT, "pdftotext not installed")
    def test_pdf_out_of_range_fails_loudly(self) -> None:
        path = self.root / "three.pdf"
        path.write_bytes(make_pdf(["ONE", "TWO", "THREE"]))
        result = self.run_cli("pdf-text", str(path), "9", "9")
        self.assertEqual(result.returncode, EXIT_TOOL_FAILED, "an empty page range must not look like an empty page")
        self.assertIn("pdftotext", result.stderr)

    @unittest.skipUnless(HAVE_PDFTOTEXT, "pdftotext not installed")
    def test_pdf_info_reports_pages_and_text_layer(self) -> None:
        path = self.root / "text.pdf"
        path.write_bytes(make_pdf(["SOMEWORDS", "MORE WORDS"]))
        result = self.run_cli("pdf-info", str(path))
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertIn("Pages: 2", result.stdout)
        self.assertIn("text layer: present", result.stdout)

    @unittest.skipUnless(HAVE_PDFTOTEXT, "pdftotext not installed")
    def test_pdf_info_flags_missing_text_layer(self) -> None:
        path = self.root / "scan.pdf"
        path.write_bytes(make_pdf([None, None]))
        result = self.run_cli("pdf-info", str(path))
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertIn("text layer: absent", result.stdout)
        self.assertIn("OCR", result.stdout)

    def test_missing_tool_is_reported_not_treated_as_empty(self) -> None:
        path = self.root / "any.pdf"
        path.write_bytes(make_pdf(["X"]))
        empty_path = self.root / "empty-bin"
        empty_path.mkdir()
        result = self.run_cli("pdf-info", str(path), env={"PATH": str(empty_path)})
        self.assertEqual(result.returncode, EXIT_MISSING_TOOL)
        self.assertIn("not installed", result.stderr)

    # --- office ----------------------------------------------------------------------

    @unittest.skipUnless(HAVE_PANDOC, "pandoc not installed")
    def test_docx_text_via_pandoc(self) -> None:
        path = self.root / "memo.docx"
        make_docx(path, ["Quarterly memo", "Revenue rose modestly"])
        result = self.run_cli("docx", str(path))
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertIn("Quarterly memo", result.stdout)
        self.assertIn("Revenue rose modestly", result.stdout)

    # --- archives --------------------------------------------------------------------

    def _make_zip(self, name: str, members: dict) -> Path:
        path = self.root / name
        with zipfile.ZipFile(path, "w") as archive:
            for member, data in members.items():
                archive.writestr(member, data)
        return path

    def test_zip_list_names_members_and_extracts_nothing(self) -> None:
        path = self._make_zip("bundle.zip", {"a/one.txt": "first", "two.txt": "second"})
        dest = self.root / "should-not-exist"
        result = self.run_cli("zip-list", str(path))
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertIn("a/one.txt", result.stdout)
        self.assertIn("two.txt", result.stdout)
        self.assertFalse(dest.exists())

    def test_zip_extract_writes_into_fresh_directory(self) -> None:
        path = self._make_zip("bundle.zip", {"a/one.txt": "first", "two.txt": "second"})
        dest = self.root / "fresh"
        result = self.run_cli("zip-extract", str(path), str(dest))
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertEqual((dest / "a" / "one.txt").read_text(), "first")
        self.assertEqual((dest / "two.txt").read_text(), "second")

    def test_zip_extract_refuses_path_traversal_and_writes_nothing(self) -> None:
        path = self._make_zip("hostile.zip", {"ok.txt": "fine", "../escape.txt": "outside"})
        dest = self.root / "dest"
        result = self.run_cli("zip-extract", str(path), str(dest))
        self.assertEqual(result.returncode, EXIT_REFUSED, result.stderr)
        self.assertFalse((self.root / "escape.txt").exists())
        self.assertFalse((dest / "ok.txt").exists(), "a refused archive must not be partly written")

    def test_zip_extract_refuses_non_empty_destination(self) -> None:
        path = self._make_zip("bundle.zip", {"a.txt": "a"})
        dest = self.root / "busy"
        dest.mkdir()
        (dest / "existing.txt").write_text("keep me")
        result = self.run_cli("zip-extract", str(path), str(dest))
        self.assertEqual(result.returncode, EXIT_REFUSED, result.stderr)
        self.assertEqual((dest / "existing.txt").read_text(), "keep me")

    # --- text ------------------------------------------------------------------------

    def test_text_line_range_is_numbered(self) -> None:
        path = self.root / "lines.txt"
        path.write_text("".join(f"line {n}\n" for n in range(1, 11)))
        result = self.run_cli("text", str(path), "--lines", "3:4")
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertIn("3\tline 3", result.stdout)
        self.assertIn("4\tline 4", result.stdout)
        self.assertNotIn("line 5", result.stdout)
        self.assertNotIn("line 2", result.stdout)

    def test_text_refuses_binary_content(self) -> None:
        path = self.root / "blob.dat"
        path.write_bytes(b"\x00\x01\x02binary" * 100)
        result = self.run_cli("text", str(path))
        self.assertEqual(result.returncode, EXIT_REFUSED, result.stderr)
        self.assertIn("binary", result.stderr)

    def test_bad_line_range_is_an_input_error(self) -> None:
        path = self.root / "lines.txt"
        path.write_text("one\ntwo\n")
        result = self.run_cli("text", str(path), "--lines", "5:2")
        self.assertEqual(result.returncode, EXIT_INPUT, result.stderr)
        # Exit 2 alone also comes from argparse or a missing script; the message pins the cause.
        self.assertIn("line range", result.stderr)

    def test_truncation_says_so(self) -> None:
        path = self.root / "long.txt"
        path.write_text("word " * 5000)
        result = self.run_cli("text", str(path), "--max-chars", "100")
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertIn("truncated", result.stdout)
        self.assertIn("--max-chars", result.stdout)


if __name__ == "__main__":
    unittest.main()
