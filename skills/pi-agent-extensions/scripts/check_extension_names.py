#!/usr/bin/env python3
"""Check the names a pi extension uses against the installed pi binary.

Standard library only (Python 3.12). For each TypeScript file given, collect:

  pi.<name>            ExtensionAPI methods and properties
  ctx.ui.<name>        UI methods
  pi.on("<event>")     event names

and check that each name occurs in the pi binary. A name that does not occur is reported as
NOT FOUND. Pi does not reject an unknown option or event name: it ignores it, which is why this
check exists.

Limits, stated so the output is not over-read: a name occurring in the binary is weak evidence
that the signature is right, because the name may appear in a string or a comment. A missing name
is strong evidence that the name is wrong for this version. Read the docs for the signature.

Exit codes: 0 every name found; 1 at least one name not found; 2 usage error or no binary.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

PI_CALL = re.compile(r"\bpi\.([A-Za-z_]\w*)")
UI_CALL = re.compile(r"\bctx\.ui\.([A-Za-z_]\w*)")
EVENT = re.compile(r"""\bpi\.on\(\s*["']([A-Za-z_]\w*)["']""")


def default_binary() -> Path | None:
    found = shutil.which("pi")
    return Path(found).resolve() if found else None


def code_lines(text: str) -> list[str]:
    """Drop whole-line comments. Inline comments are rare in extension files and are kept."""
    kept = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("//", "*", "/*")):
            continue
        kept.append(line)
    return kept


def collect(path: Path) -> dict[str, set[str]]:
    text = "\n".join(code_lines(path.read_text(encoding="utf-8")))
    return {
        "pi": set(PI_CALL.findall(text)) - {"on"},
        "ctx.ui": set(UI_CALL.findall(text)),
        "event": set(EVENT.findall(text)),
    }


def present(binary: bytes, name: str) -> bool:
    return name.encode("utf-8") in binary


def check(files: list[Path], binary_path: Path) -> int:
    binary = binary_path.read_bytes()
    missing = 0
    for path in files:
        names = collect(path)
        print(f"{path}")
        for group in ("pi", "ctx.ui", "event"):
            for name in sorted(names[group]):
                ok = present(binary, name)
                label = {"pi": f"pi.{name}", "ctx.ui": f"ctx.ui.{name}", "event": f'pi.on("{name}")'}[group]
                print(f"  {'found    ' if ok else 'NOT FOUND'}  {label}")
                if not ok:
                    missing += 1
        if not any(names.values()):
            print("  (no pi or ctx.ui names in this file)")
    print()
    print(f"binary: {binary_path}")
    print(f"{missing} name(s) not found in the binary")
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", type=Path, help="extension .ts files to check")
    parser.add_argument("--binary", type=Path, default=None, help="pi binary (default: pi on PATH)")
    args = parser.parse_args(argv)

    binary = args.binary.resolve() if args.binary else default_binary()
    if binary is None or not binary.is_file():
        print("error: no pi binary found; pass --binary PATH", file=sys.stderr)
        return 2
    for path in args.files:
        if not path.is_file():
            print(f"error: not a file: {path}", file=sys.stderr)
            return 2
    return check(args.files, binary)


if __name__ == "__main__":
    raise SystemExit(main())
