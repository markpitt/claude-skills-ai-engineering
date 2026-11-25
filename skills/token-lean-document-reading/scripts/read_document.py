#!/usr/bin/env python3
"""Read documents at the lowest token cost, and fail loudly when a read cannot be trusted.

Run with the interpreter isolated, so a file in the input's folder cannot shadow a module:

    python3 -I read_document.py <command> [arguments]

Commands
    inventory PATH [--recursive]          names, sizes and kinds, before anything is opened
    pdf-info FILE                         pages, and whether a text layer exists
    pdf-text FILE FIRST LAST              pages FIRST to LAST (1-based), with page headers
    eml FILE [--headers] [--max-chars N]  headers, body text, attachment names and sizes
    msg FILE [--max-chars N]              Outlook item, via extract_msg when installed
    docx FILE [--max-chars N]             Word text, via pandoc, else python-docx
    zip-list FILE                         member names and sizes, extracts nothing
    zip-extract FILE DEST                 extract into a new or empty DEST, after checks
    text FILE [--lines A:B] [--max-chars N]

Exit codes
    0  success
    2  bad input (missing path, bad range, bad arguments)
    3  a required tool is not installed (reported, never treated as an empty document)
    4  refused for safety (binary content in a text read, unsafe archive, busy destination)
    5  an external tool failed or timed out

Untrusted input: every external program runs as an argument list with shell=False and a timeout.
Attachment payloads, archive members and mail bodies are printed as data, never executed or
extracted except by zip-extract, which refuses the whole archive if any member is unsafe.
"""
from __future__ import annotations

import argparse
import email
import email.policy
import email.message
import html.parser
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import NoReturn

EXIT_OK, EXIT_INPUT, EXIT_MISSING_TOOL, EXIT_REFUSED, EXIT_TOOL_FAILED = 0, 2, 3, 4, 5
TOOL_TIMEOUT_SECONDS = 120
DEFAULT_MAX_CHARS = 20_000
MAX_EXTRACT_BYTES = 500 * 1024 * 1024
MAX_EXTRACT_MEMBERS = 10_000
KEY_HEADERS = ("Date", "From", "To", "Cc", "Subject")
SYMLINK_MODE = 0o120000
FILE_MODE_MASK = 0o170000


class Fail(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def fail(code: int, message: str) -> NoReturn:
    raise Fail(code, message)


def human_size(count: int) -> str:
    size = float(count)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} bytes" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"  # unreachable, keeps the type checker content


def require_file(path: Path) -> Path:
    if not path.exists():
        fail(EXIT_INPUT, f"{path} does not exist")
    if not path.is_file():
        fail(EXIT_INPUT, f"{path} is not a file")
    return path


def run_tool(argv: list[str]) -> str:
    """Run an external tool as an argument list. Missing, failing and slow are all loud."""
    executable = shutil.which(argv[0])
    if executable is None:
        fail(EXIT_MISSING_TOOL, f"{argv[0]} is not installed, so this file cannot be read here")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C.UTF-8"}
    try:
        proc = subprocess.run(
            [executable, *argv[1:]],
            capture_output=True,
            timeout=TOOL_TIMEOUT_SECONDS,
            check=False,
            shell=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        fail(EXIT_TOOL_FAILED, f"{argv[0]} timed out after {TOOL_TIMEOUT_SECONDS} seconds")
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()[:500]
        fail(EXIT_TOOL_FAILED, f"{argv[0]} exited {proc.returncode}: {detail}")
    return proc.stdout.decode("utf-8", errors="replace")


def emit(text: str, max_chars: int) -> None:
    """Print at most max_chars and say so when cutting, so a truncated read is never mistaken for a whole one."""
    if max_chars and len(text) > max_chars:
        print(text[:max_chars])
        print(f"... truncated at {max_chars} of {len(text)} characters; pass --max-chars for more")
    else:
        print(text)


def collapse(text: str) -> str:
    out: list[str] = []
    for line in (raw.rstrip() for raw in text.splitlines()):
        if not line and out and not out[-1]:
            continue
        out.append(line)
    return "\n".join(out).strip()


class _TextExtractor(html.parser.HTMLParser):
    BLOCK_TAGS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table"}
    SKIP_TAGS = {"script", "style", "head", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(markup)
    extractor.close()
    return collapse("".join(extractor.parts))


def part_text(part: email.message.Message) -> str:
    try:
        content = part.get_content()
    except (KeyError, LookupError, ValueError, TypeError):
        payload = part.get_payload(decode=True) or b""
        content = payload.decode("utf-8", errors="replace")
    if part.get_content_subtype() == "html":
        return html_to_text(content)
    return collapse(content)


# --- commands ------------------------------------------------------------------------

def cmd_inventory(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if not target.exists():
        fail(EXIT_INPUT, f"{target} does not exist")
    entries = sorted(target.rglob("*")) if args.recursive and target.is_dir() else (
        sorted(target.iterdir()) if target.is_dir() else [target]
    )
    files = [p for p in entries if p.is_file()]
    total = 0
    print(f"{'size':>12}  {'kind':<6}  path")
    for path in files:
        size = path.stat().st_size
        total += size
        kind = path.suffix.lower().lstrip(".") or "none"
        flag = "  <- large, read by range" if size > 1_000_000 else ""
        print(f"{human_size(size):>12}  {kind:<6}  {path}{flag}")
    print(f"\n{len(files)} file(s), {human_size(total)} in total")
    return EXIT_OK


def _pdf_page_count(path: Path) -> int | None:
    for line in run_tool(["pdfinfo", str(path)]).splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    return None


def cmd_pdf_info(args: argparse.Namespace) -> int:
    path = require_file(Path(args.file))
    pages = _pdf_page_count(path)
    text = run_tool(["pdftotext", "-layout", str(path), "-"])
    chars = len(text.strip())
    print(f"file: {path.name}")
    print(f"Pages: {pages if pages is not None else 'unknown'}")
    if chars:
        print(f"text layer: present ({chars} characters of text)")
    else:
        print("text layer: absent (scanned or image-only)")
        print("OCR needed if the content matters: see references/pdf-and-scans.md")
    return EXIT_OK


def cmd_pdf_text(args: argparse.Namespace) -> int:
    path = require_file(Path(args.file))
    first, last = args.first, args.last
    if first < 1 or last < first:
        fail(EXIT_INPUT, f"bad page range {first}-{last}: pages are 1-based and LAST must not be below FIRST")
    raw = run_tool(["pdftotext", "-layout", "-f", str(first), "-l", str(last), str(path), "-"])
    pieces = raw.split("\f")
    if pieces and not pieces[-1].strip():
        pieces = pieces[:-1]
    lines: list[str] = []
    for offset, piece in enumerate(pieces):
        lines.append(f"=== page {first + offset} ===")
        lines.append(piece.rstrip())
    emit("\n".join(lines), args.max_chars)
    return EXIT_OK


def cmd_eml(args: argparse.Namespace) -> int:
    path = require_file(Path(args.file))
    message = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    lines = [f"# {path.name}", ""]
    if args.headers:
        for name, value in message.items():
            lines.append(f"- {name}: {str(value).strip()}")
    else:
        for name in KEY_HEADERS:
            if message[name]:
                lines.append(f"- {name}: {str(message[name]).strip()}")
    attachments = []
    for part in message.walk():
        if part.is_multipart():
            continue
        name = part.get_filename()
        if name or part.get_content_disposition() == "attachment":
            payload = part.get_payload(decode=True) or b""
            attachments.append((name or "(unnamed)", part.get_content_type(), len(payload)))
    if attachments:
        lines.append("")
        lines.append(f"## Attachments ({len(attachments)}), not printed")
        for name, content_type, size in attachments:
            lines.append(f"- {name} ({content_type}, {human_size(size)})")
    body_part = message.get_body(preferencelist=("plain", "html"))
    body = part_text(body_part) if body_part is not None else ""
    lines.extend(["", "## Body", "", body or "(no body: headers and attachments only)"])
    emit("\n".join(lines), args.max_chars)
    return EXIT_OK


def cmd_msg(args: argparse.Namespace) -> int:
    path = require_file(Path(args.file))
    try:
        import extract_msg  # type: ignore[import-not-found]
    except ImportError:
        fail(EXIT_MISSING_TOOL, "the extract_msg package is not installed, so this .msg cannot be read here")
    message = extract_msg.Message(str(path))
    lines = [f"# {path.name}", ""]
    for label, value in (("Subject", message.subject), ("From", message.sender),
                         ("To", message.to), ("Cc", message.cc), ("Date", message.date)):
        if value:
            lines.append(f"- {label}: {value}")
    names = [str(a.longFilename or a.shortFilename) for a in message.attachments]
    if names:
        lines.append(f"- Attachments ({len(names)}), not printed: {', '.join(names)}")
    lines.extend(["", "## Body", "", collapse(message.body or "") or "(no body)"])
    emit("\n".join(lines), args.max_chars)
    return EXIT_OK


def cmd_docx(args: argparse.Namespace) -> int:
    path = require_file(Path(args.file))
    if shutil.which("pandoc"):
        text = run_tool(["pandoc", "-f", "docx", "-t", "plain", "--wrap=none", str(path)])
    else:
        try:
            import docx  # type: ignore[import-not-found]
        except ImportError:
            fail(EXIT_MISSING_TOOL, "neither pandoc nor python-docx is installed, so this .docx cannot be read here")
        document = docx.Document(str(path))
        paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
        text = "\n".join(paragraphs)
    emit(collapse(text), args.max_chars)
    return EXIT_OK


def _unsafe_member(info: zipfile.ZipInfo) -> str | None:
    name = info.filename
    if name.startswith("/") or "\\" in name or (len(name) > 1 and name[1] == ":"):
        return "absolute or backslash path"
    if any(part == ".." for part in name.split("/")):
        return "parent-directory component"
    if (info.external_attr >> 16) & FILE_MODE_MASK == SYMLINK_MODE:
        return "symbolic link"
    return None


def _open_archive(path: Path) -> zipfile.ZipFile:
    require_file(path)
    if not zipfile.is_zipfile(path):
        fail(EXIT_INPUT, f"{path.name} is not a zip archive")
    return zipfile.ZipFile(path)


def cmd_zip_list(args: argparse.Namespace) -> int:
    with _open_archive(Path(args.file)) as archive:
        print(f"{'size':>12}  {'packed':>12}  member")
        unsafe = 0
        for info in archive.infolist():
            reason = _unsafe_member(info)
            flag = f"  <- UNSAFE: {reason}" if reason else ""
            unsafe += bool(reason)
            print(f"{human_size(info.file_size):>12}  {human_size(info.compress_size):>12}  {info.filename}{flag}")
        print(f"\n{len(archive.infolist())} member(s), {unsafe} unsafe")
    return EXIT_OK


def cmd_zip_extract(args: argparse.Namespace) -> int:
    dest = Path(args.dest)
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        fail(EXIT_REFUSED, f"{dest} exists and is not an empty directory; choose a fresh one")
    with _open_archive(Path(args.file)) as archive:
        members = archive.infolist()
        if len(members) > MAX_EXTRACT_MEMBERS:
            fail(EXIT_REFUSED, f"{len(members)} members exceeds the limit of {MAX_EXTRACT_MEMBERS}")
        total = sum(info.file_size for info in members)
        if total > MAX_EXTRACT_BYTES:
            fail(EXIT_REFUSED, f"uncompressed size {human_size(total)} exceeds the limit")
        for info in members:
            reason = _unsafe_member(info)
            if reason:
                fail(EXIT_REFUSED, f"refusing the whole archive: member {info.filename!r} is a {reason}")
        dest.mkdir(parents=True, exist_ok=True)
        root = dest.resolve()
        for info in members:
            target = (root / info.filename).resolve()
            if root != target and root not in target.parents:
                fail(EXIT_REFUSED, f"member {info.filename!r} resolves outside the destination")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as sink:
                shutil.copyfileobj(source, sink)
        print(f"extracted {len(members)} member(s) into {dest}")
    return EXIT_OK


def cmd_text(args: argparse.Namespace) -> int:
    path = require_file(Path(args.file))
    data = path.read_bytes()
    if b"\x00" in data[:8192]:
        fail(EXIT_REFUSED, f"{path.name} looks binary; use the reader for its format, not text")
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if args.lines:
        try:
            start_text, end_text = args.lines.split(":", 1)
            start, end = int(start_text), int(end_text)
        except ValueError:
            fail(EXIT_INPUT, f"bad line range {args.lines!r}; use START:END, for example 40:90")
        if start < 1 or end < start:
            fail(EXIT_INPUT, f"bad line range {args.lines!r}: START must be 1 or more and END not below START")
        numbered = [f"{n}\t{lines[n - 1]}" for n in range(start, min(end, len(lines)) + 1)]
        print(f"# {path.name}: lines {start}-{min(end, len(lines))} of {len(lines)}")
        emit("\n".join(numbered), args.max_chars)
    else:
        print(f"# {path.name}: {len(lines)} lines, {len(text)} characters")
        emit(text, args.max_chars)
    return EXIT_OK


# --- argument handling ---------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, handler, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.set_defaults(func=handler)
        return p

    p = add("inventory", cmd_inventory, "list names, sizes and kinds")
    p.add_argument("path")
    p.add_argument("--recursive", action="store_true")

    p = add("pdf-info", cmd_pdf_info, "pages and text-layer check")
    p.add_argument("file")

    p = add("pdf-text", cmd_pdf_text, "text of a page range")
    p.add_argument("file")
    p.add_argument("first", type=int)
    p.add_argument("last", type=int)
    p.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)

    p = add("eml", cmd_eml, "mail headers, body and attachment list")
    p.add_argument("file")
    p.add_argument("--headers", action="store_true", help="print every header, not only the key ones")
    p.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)

    p = add("msg", cmd_msg, "Outlook .msg item")
    p.add_argument("file")
    p.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)

    p = add("docx", cmd_docx, "Word document as plain text")
    p.add_argument("file")
    p.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)

    p = add("zip-list", cmd_zip_list, "archive members, extracts nothing")
    p.add_argument("file")

    p = add("zip-extract", cmd_zip_extract, "extract a checked archive into a fresh directory")
    p.add_argument("file")
    p.add_argument("dest")

    p = add("text", cmd_text, "plain text, by line range")
    p.add_argument("file")
    p.add_argument("--lines", help="START:END, 1-based, inclusive")
    p.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Fail as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return exc.code
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT


if __name__ == "__main__":
    sys.exit(main())
