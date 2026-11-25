#!/usr/bin/env python3
"""Measure a harness's always-loaded instruction set, and prove that moved prose was not lost.

Standard library only (Python 3.12). Two subcommands:

  measure      bytes, lines and an estimated token count for each instruction file under the roots
  verify-move  prove that every line removed from a source file reappears in a companion file

Token counts are ESTIMATES: ceil(bytes / bytes-per-token), default 4. They are not a tokenizer and
must be reported as estimates. Byte counts are exact.

Budget classes:
  always     loaded at session start or on every request (context files, unscoped rules,
             memory index up to its cap, skill name and description)
  on-demand  loaded only when a matching file is touched or a topic is read (scoped rules,
             memory topic files, skill bodies). Listed, not added to the budget.
  excluded   companion folders (.staging) and tool folders. Reported so that nothing vanishes
             silently, but never counted.

Exit codes: 0 ok; 1 verify-move found lines with no companion copy; 2 usage error, or a root
that does not exist (a wrong root must fail loudly, not report an empty budget).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

CONTEXT_NAMES = {"CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "AGENTS.override.md"}
PRUNED_DIRS = {".git", "node_modules", ".worktrees", ".venv", "__pycache__"}
COMPANION_DIR = ".staging"
DEFAULT_MEMORY_LINE_CAP = 200
DEFAULT_MEMORY_BYTE_CAP = 25 * 1024
DEFAULT_BYTES_PER_TOKEN = 4.0


@dataclass(frozen=True)
class Entry:
    path: str
    kind: str
    budget: str
    bytes: int
    lines: int
    est_tokens: int
    effective_bytes: int
    effective_lines: int


def estimate_tokens(size: int, bytes_per_token: float) -> int:
    """Estimate tokens for a byte count. Labelled as an estimate wherever it is printed."""
    return math.ceil(size / bytes_per_token) if size else 0


def frontmatter(text: str) -> dict[str, str]:
    """Parse a leading YAML-like frontmatter block without PyYAML.

    Handles `key: value`, and folded (`>`) or literal (`|`) scalars whose value is the indented
    lines that follow. This is enough for the name and description keys of a skill, and for the
    presence of a `paths:` or `applyTo:` key. It is not a YAML parser.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    key: str | None = None
    buf: list[str] = []
    for raw in lines[1:]:
        if raw.strip() == "---":
            break
        if raw[:1] not in (" ", "\t") and ":" in raw:
            if key is not None:
                fields[key] = " ".join(buf).strip()
            name, _, value = raw.partition(":")
            key = name.strip()
            value = value.strip()
            buf = [] if value in (">", "|", "") else [value]
        elif key is not None:
            buf.append(raw.strip())
    if key is not None:
        fields[key] = " ".join(buf).strip()
    return fields


def classify(path: Path) -> tuple[str, str]:
    """Return (kind, budget) for one file, from its name and position. Raises nothing."""
    name = path.name
    parts = set(path.parts)
    if name in CONTEXT_NAMES:
        return "context-file", "always"
    if name == "SKILL.md":
        return "skill-description", "always"
    if name == "MEMORY.md":
        return "memory-index", "always"
    if "memory" in path.parent.parts and name.endswith(".md"):
        return "memory-topic", "on-demand"
    if "rules" in parts and name.endswith(".md"):
        fm = frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        return ("rule-scoped", "on-demand") if "paths" in fm else ("rule", "always")
    return "", ""


def measure_file(
    path: Path,
    kind: str,
    budget: str,
    bytes_per_token: float,
    memory_line_cap: int,
    memory_byte_cap: int,
) -> Entry:
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    effective = data
    effective_lines = lines
    if kind == "memory-index":
        head = data.splitlines(keepends=True)[:memory_line_cap]
        effective = b"".join(head)[:memory_byte_cap]
        effective_lines = min(lines, memory_line_cap)
    if kind == "skill-description":
        fm = frontmatter(text)
        counted = (fm.get("name", "") + "\n" + fm.get("description", "")).encode("utf-8")
        effective = counted
        effective_lines = counted.count(b"\n") + 1
    return Entry(
        path=str(path),
        kind=kind,
        budget=budget,
        bytes=len(data),
        lines=lines,
        est_tokens=estimate_tokens(len(effective), bytes_per_token),
        effective_bytes=len(effective),
        effective_lines=effective_lines,
    )


def walk(root: Path) -> tuple[list[Path], int]:
    """Return candidate instruction files under root, and the count of companion files skipped."""
    found: list[Path] = []
    excluded = 0
    if root.is_file():
        return [root], 0
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        if COMPANION_DIR in dirnames:
            excluded += sum(1 for _, _, fs in os.walk(here / COMPANION_DIR) for f in fs)
        dirnames[:] = sorted(d for d in dirnames if d not in PRUNED_DIRS and d != COMPANION_DIR)
        for name in sorted(filenames):
            if name.endswith(".md") or name in CONTEXT_NAMES:
                found.append(here / name)
    return found, excluded


def measure(roots: list[str], bytes_per_token: float, memory_line_cap: int, memory_byte_cap: int):
    entries: list[Entry] = []
    excluded_total = 0
    for raw in roots:
        root = Path(raw)
        if not root.exists():
            raise FileNotFoundError(raw)
        files, excluded = walk(root)
        excluded_total += excluded
        for path in files:
            kind, budget = classify(path)
            if not kind:
                continue
            entries.append(
                measure_file(path, kind, budget, bytes_per_token, memory_line_cap, memory_byte_cap)
            )
    return entries, excluded_total


def summarise(entries: list[Entry], excluded: int) -> dict[str, object]:
    always = [e for e in entries if e.budget == "always"]
    return {
        "files": len(entries),
        "always_files": len(always),
        "always_bytes": sum(e.effective_bytes for e in always),
        "always_est_tokens": sum(e.est_tokens for e in always),
        "on_demand_files": sum(1 for e in entries if e.budget == "on-demand"),
        "excluded_companion_files": excluded,
        "token_basis": "estimate: ceil(bytes / bytes_per_token)",
    }


def cmd_measure(args: argparse.Namespace) -> int:
    try:
        entries, excluded = measure(
            args.roots, args.bytes_per_token, args.memory_line_cap, args.memory_byte_cap
        )
    except FileNotFoundError as exc:
        print(f"error: root does not exist: {exc}", file=sys.stderr)
        print("error: nothing was measured; check the root before trusting any total", file=sys.stderr)
        return 2
    summary = summarise(entries, excluded)
    if args.json:
        payload = {"summary": summary, "entries": [asdict(e) for e in entries]}
        print(json.dumps(payload, indent=2))
        return 0
    header = f"{'budget':<10} {'kind':<17} {'bytes':>8} {'eff.B':>8} {'lines':>6} {'~tokens':>8}  path"
    print(header)
    for e in sorted(entries, key=lambda e: (e.budget, e.kind, e.path)):
        print(
            f"{e.budget:<10} {e.kind:<17} {e.bytes:>8} {e.effective_bytes:>8} "
            f"{e.lines:>6} {e.est_tokens:>8}  {e.path}"
        )
    print()
    print(
        f"always-loaded: {summary['always_files']} file(s), {summary['always_bytes']} bytes, "
        f"about {summary['always_est_tokens']} tokens (estimate)"
    )
    print(f"on-demand: {summary['on_demand_files']} file(s), not counted")
    print(f"excluded: {excluded} companion file(s) under {COMPANION_DIR}/, not counted")
    return 0


def load_lines(path: Path) -> list[str]:
    """Non-blank lines, trailing whitespace removed. Blank lines carry no instruction."""
    text = path.read_text(encoding="utf-8")
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def cmd_verify_move(args: argparse.Namespace) -> int:
    try:
        before = load_lines(Path(args.before))
        after = load_lines(Path(args.after))
        companions = [load_lines(Path(c)) for c in args.companion]
    except FileNotFoundError as exc:
        print(f"error: file does not exist: {exc.filename}", file=sys.stderr)
        return 2
    if not companions:
        print("error: give at least one --companion file", file=sys.stderr)
        return 2
    after_set = set(after)
    companion_set = {line for lines in companions for line in lines}
    removed = [(n, line) for n, line in enumerate(before, 1) if line not in after_set]
    moved = [(n, line) for n, line in removed if line in companion_set]
    lost = [(n, line) for n, line in removed if line not in companion_set]
    added = [line for line in after if line not in set(before)]
    print(f"before: {len(before)} non-blank line(s); after: {len(after)}; added: {len(added)}")
    print(f"removed from source: {len(removed)}; found verbatim in a companion: {len(moved)}")
    print(f"unaccounted (lost or reworded, needs a human look): {len(lost)}")
    for n, line in lost:
        print(f"  before line {n}: {line}")
    return 1 if lost else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    m = sub.add_parser("measure", help="measure the always-loaded set under the given roots")
    m.add_argument("roots", nargs="+", help="directories or files to scan (for example a repo, ~/.claude)")
    m.add_argument("--json", action="store_true", help="print JSON instead of a table")
    m.add_argument("--bytes-per-token", type=float, default=DEFAULT_BYTES_PER_TOKEN)
    m.add_argument("--memory-line-cap", type=int, default=DEFAULT_MEMORY_LINE_CAP)
    m.add_argument("--memory-byte-cap", type=int, default=DEFAULT_MEMORY_BYTE_CAP)
    m.set_defaults(func=cmd_measure)

    v = sub.add_parser("verify-move", help="check that no removed line is missing from the companions")
    v.add_argument("--before", required=True, help="the source file as it was before the edit")
    v.add_argument("--after", required=True, help="the source file after the edit")
    v.add_argument("--companion", action="append", default=[], help="a companion file; repeatable")
    v.set_defaults(func=cmd_verify_move)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
