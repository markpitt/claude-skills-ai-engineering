#!/usr/bin/env python3
"""Static inventory of agent instruction files, with the checks that make a file silently not load.

Run it with the path-safe interpreter flag, so a file in the scanned tree cannot shadow a module:

    python3 -P audit_instruction_files.py [--json] [--strict] ROOT [ROOT ...]

It needs PyYAML. If PyYAML cannot be imported it exits 3 rather than report a clean result,
because an unparsed frontmatter block is exactly the failure this script exists to catch.

What it inventories (kinds in brackets)
    CLAUDE.md, CLAUDE.local.md                       [claude-md, claude-local-md]
    AGENTS.md, AGENTS.override.md, AGENTS.local.md    [agents-md, agents-override-md, agents-local-md]
    GEMINI.md, copilot-instructions.md, MEMORY.md     [gemini-md, copilot-instructions, memory-index]
    .claude/rules/**/*.md                             [claude-rule]
    .github/instructions/**/*.instructions.md         [copilot-instruction]
    <any>/skills/<name>/SKILL.md, incl. symlinked skill folders   [skill]

What it checks
    ERROR  broken symlink; skill without frontmatter; frontmatter not valid YAML; duplicate
           top-level key; skill name not equal to its folder; skill description missing, not a
           string, or over 1024 characters; the reserved words claude or anthropic in a skill name
    WARN   Claude-only keys in a skill (packaging rejects them); applyTo in a Claude rule (Claude
           Code ignores it, so the rule loads for every path); paths in a Copilot file; an empty
           instruction file; AGENTS.md and CLAUDE.md in one directory; AGENTS.override.md shadowing
           AGENTS.md in one directory
    Limit  symlinked directories are followed only where they hold a SKILL.md. Other symlinked
           directories are listed and not descended.

Exit codes: 0 no errors (and no warnings under --strict); 1 errors found, or warnings under
--strict; 2 bad arguments; 3 PyYAML missing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    print(
        "error: PyYAML is not importable, so frontmatter cannot be checked. This is a failed audit, "
        "not a clean one. Run with an interpreter that has PyYAML, for example: "
        "uv run --with pyyaml python3 -P audit_instruction_files.py ROOT",
        file=sys.stderr,
    )
    sys.exit(3)

INSTRUCTION_KINDS = {
    "CLAUDE.md": "claude-md",
    "CLAUDE.local.md": "claude-local-md",
    "AGENTS.md": "agents-md",
    "AGENTS.override.md": "agents-override-md",
    "AGENTS.local.md": "agents-local-md",
    "GEMINI.md": "gemini-md",
    "copilot-instructions.md": "copilot-instructions",
    "MEMORY.md": "memory-index",
}
PRUNE_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "target"}
SKILL_SPEC_KEYS = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
DESCRIPTION_LIMIT = 1024
RESERVED_SKILL_WORDS = ("claude", "anthropic")
TOP_LEVEL_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:", re.MULTILINE)


@dataclass
class Finding:
    severity: str  # ERROR or WARN
    path: str
    message: str


@dataclass
class Entry:
    kind: str
    path: Path
    via_symlink: str | None = None


@dataclass
class Report:
    roots: list[str]
    entries: list[Entry] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


def has_sequence(parts: tuple[str, ...], sequence: tuple[str, ...]) -> bool:
    width = len(sequence)
    return any(parts[i:i + width] == sequence for i in range(len(parts) - width + 1))


def classify(path: Path) -> str | None:
    name = path.name
    if name in INSTRUCTION_KINDS:
        return INSTRUCTION_KINDS[name]
    parts = path.parts
    if name == "SKILL.md" and path.parent.parent.name == "skills":
        return "skill"
    if name.endswith(".md") and has_sequence(parts, (".claude", "rules")):
        return "claude-rule"
    if name.endswith(".instructions.md") and has_sequence(parts, (".github", "instructions")):
        return "copilot-instruction"
    return None


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return ('none', '') when there is no block, ('unclosed', '') or ('ok', raw block)."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return "none", ""
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "ok", "\n".join(lines[1:index])
    return "unclosed", ""


def display(path: Path, roots: list[Path]) -> str:
    for root in roots:
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return str(path)


def collect(roots: list[Path], report: Report) -> list[tuple[Path, Path]]:
    """Return (candidate path, root) pairs and record broken symlinks as errors."""
    candidates: list[tuple[Path, Path]] = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            here = Path(dirpath)
            dirnames[:] = sorted(d for d in dirnames if d not in PRUNE_DIRS)
            for name in sorted(dirnames) + sorted(filenames):
                child = here / name
                if child.is_symlink():
                    if not child.exists():
                        report.findings.append(Finding(
                            "ERROR", display(child, roots),
                            f"broken symlink -> {os.readlink(child)}; the harness cannot load it",
                        ))
                        continue
                    if child.is_dir():
                        skill_file = child / "SKILL.md"
                        if skill_file.is_file() and classify(skill_file) == "skill":
                            candidates.append((skill_file, root))
                        continue
                    if classify(child):
                        candidates.append((child, root))
                    continue
                if name in dirnames:
                    continue
                if classify(child):
                    candidates.append((child, root))
    unique: dict[Path, tuple[Path, Path]] = {}
    for path, root in candidates:
        unique.setdefault(path, (path, root))
    return list(unique.values())


def check_skill(path: Path, meta: dict, report: Report, roots: list[Path]) -> None:
    where = display(path, roots)
    folder = path.parent.name
    name = meta.get("name")
    if not name:
        report.findings.append(Finding("ERROR", where, "no 'name' in frontmatter"))
    else:
        if str(name) != folder:
            report.findings.append(Finding(
                "ERROR", where, f"name {name!r} does not match directory {folder!r}; the skill will not load",
            ))
        for word in RESERVED_SKILL_WORDS:
            if word in str(name).lower():
                report.findings.append(Finding("ERROR", where, f"name contains the reserved word {word!r}"))
    description = meta.get("description")
    if not description:
        report.findings.append(Finding("ERROR", where, "no 'description' in frontmatter"))
    elif not isinstance(description, str):
        report.findings.append(Finding("ERROR", where, "description is not a string"))
    elif len(description) > DESCRIPTION_LIMIT:
        report.findings.append(Finding(
            "ERROR", where, f"description is {len(description)} characters, limit {DESCRIPTION_LIMIT}",
        ))
    extra = sorted(set(meta) - SKILL_SPEC_KEYS)
    if extra:
        report.findings.append(Finding(
            "WARN", where,
            f"key(s) outside the packaging allowlist: {', '.join(extra)}; Claude Code accepts them, "
            "claude.ai and the Skills API reject them",
        ))


def check_claude_rule(path: Path, meta: dict | None, report: Report, roots: list[Path]) -> None:
    if meta and "applyTo" in meta:
        report.findings.append(Finding(
            "WARN", display(path, roots),
            "applyTo is a Copilot key; Claude Code ignores it, so this rule loads for every path. "
            "Use paths: for Claude Code",
        ))


def check_copilot_instruction(path: Path, meta: dict | None, report: Report, roots: list[Path]) -> None:
    if meta and "paths" in meta:
        report.findings.append(Finding(
            "WARN", display(path, roots), "paths is a Claude Code key; Copilot ignores it. Use applyTo",
        ))


def read_entry(path: Path, kind: str, report: Report, roots: list[Path]) -> dict | None:
    where = display(path, roots)
    text = path.read_text(encoding="utf-8", errors="replace")
    if kind in INSTRUCTION_KINDS.values() and not text.strip():
        report.findings.append(Finding("WARN", where, "empty file; it loads as nothing"))
    if kind not in {"skill", "claude-rule", "copilot-instruction"}:
        return None
    status, raw = split_frontmatter(text)
    if status == "none":
        if kind == "skill":
            report.findings.append(Finding("ERROR", where, "no YAML frontmatter, so the skill will not load"))
        return None
    if status == "unclosed":
        report.findings.append(Finding("ERROR", where, "frontmatter block is not closed with ---"))
        return None
    duplicates = [key for key, count in Counter(TOP_LEVEL_KEY.findall(raw)).items() if count > 1]
    for key in duplicates:
        report.findings.append(Finding(
            "ERROR", where,
            f"duplicate key {key!r} in frontmatter; YAML keeps the last one without an error",
        ))
    try:
        meta = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        report.findings.append(Finding(
            "ERROR", where, f"frontmatter is not valid YAML: {str(exc).splitlines()[0]}",
        ))
        return None
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        report.findings.append(Finding("ERROR", where, f"frontmatter is {type(meta).__name__}, expected a mapping"))
        return None
    return meta


def audit(roots: list[Path]) -> Report:
    report = Report(roots=[str(r) for r in roots])
    candidates = collect(roots, report)
    by_directory: dict[Path, set[str]] = {}
    for path, root in sorted(candidates, key=lambda pair: str(pair[0])):
        kind = classify(path)
        if kind is None:
            continue
        via = None
        for ancestor in (path, path.parent):
            if ancestor.is_symlink():
                via = os.path.realpath(path)
                break
        report.entries.append(Entry(kind, path, via))
        if kind in INSTRUCTION_KINDS.values():
            by_directory.setdefault(path.parent, set()).add(path.name)
        meta = read_entry(path, kind, report, roots)
        if kind == "skill":
            if meta is not None:
                check_skill(path, meta, report, roots)
        elif kind == "claude-rule":
            check_claude_rule(path, meta, report, roots)
        elif kind == "copilot-instruction":
            check_copilot_instruction(path, meta, report, roots)
    for directory, names in sorted(by_directory.items(), key=lambda item: str(item[0])):
        where = display(directory, roots)
        if "AGENTS.md" in names and "CLAUDE.md" in names:
            report.findings.append(Finding(
                "WARN", where,
                "AGENTS.md and CLAUDE.md both sit in this directory. Claude Code reads CLAUDE.md (AGENTS.md "
                "only when no CLAUDE.md is on the path); pi takes AGENTS.md first. Check which one each "
                "tool is meant to see",
            ))
        if "AGENTS.override.md" in names and "AGENTS.md" in names:
            report.findings.append(Finding(
                "WARN", where,
                "AGENTS.override.md shadows AGENTS.md in this directory; AGENTS.md is not read here",
            ))
    return report


def print_text(report: Report) -> None:
    print(f"Instruction-load audit: {', '.join(report.roots)}")
    print(f"\nFiles ({len(report.entries)}):")
    print(f"  {'kind':<20} path")
    for entry in report.entries:
        target = f"  (symlink -> {entry.via_symlink})" if entry.via_symlink else ""
        print(f"  {entry.kind:<20} {display(entry.path, [Path(r) for r in report.roots])}{target}")
    print("\nFindings:" if report.findings else "\nFindings: none")
    for finding in report.findings:
        print(f"  {finding.severity} {finding.path}: {finding.message}")
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARN")
    print(f"\n{errors} error(s), {warnings} warning(s)")


def print_json(report: Report) -> None:
    roots = [Path(r) for r in report.roots]
    payload = {
        "roots": report.roots,
        "files": [
            {"kind": e.kind, "path": display(e.path, roots), "symlink_target": e.via_symlink}
            for e in report.entries
        ],
        "findings": [
            {"severity": f.severity, "path": f.path, "message": f.message} for f in report.findings
        ],
        "summary": {
            "files": len(report.entries),
            "errors": sum(1 for f in report.findings if f.severity == "ERROR"),
            "warnings": sum(1 for f in report.findings if f.severity == "WARN"),
        },
    }
    print(json.dumps(payload, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("roots", nargs="+", help="directories to scan; nothing outside them is read")
    parser.add_argument("--json", action="store_true", help="print machine-readable output")
    parser.add_argument("--strict", action="store_true", help="fail on warnings too")
    args = parser.parse_args(argv)
    roots = [Path(r).expanduser() for r in args.roots]
    for root in roots:
        if not root.is_dir():
            print(f"error: {root} is not a directory", file=sys.stderr)
            return 2
    report = audit(roots)
    if args.json:
        print_json(report)
    else:
        print_text(report)
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARN")
    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
