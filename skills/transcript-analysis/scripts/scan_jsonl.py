"""Register a read-only, parent-scoped transcript search tool in OMP eval."""

import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

_FIELDS = {"user_text", "assistant_text", "tool_calls", "tool_results", "all_text"}


def _text(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for block in value:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    yield text


def _chunks(row: dict[str, Any], field: str) -> Iterator[str]:
    """Select transcript fields without searching images or unrelated metadata."""
    if row.get("isMeta") or row.get("isCompactSummary"):
        return
    if isinstance(row.get("display"), str):
        if field in {"user_text", "all_text"}:
            yield row["display"]
        return
    message = row.get("message")
    if not isinstance(message, dict):
        return
    role = message.get("role", row.get("type"))
    category = {"user": "user_text", "assistant": "assistant_text",
                "toolResult": "tool_results", "tool": "tool_results"}.get(role)
    content = message.get("content")
    if isinstance(content, str):
        if category and field in {category, "all_text"}:
            yield content
        return
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind in {"toolCall", "tool_use"}:
            if field in {"tool_calls", "all_text"}:
                arguments = block.get("arguments", block.get("input", {}))
                yield str(block.get("name", "")) + "\n" + json.dumps(arguments, ensure_ascii=False)
        elif kind == "tool_result":
            if field in {"tool_results", "all_text"}:
                yield from _text(block.get("content"))
        elif kind == "text" and category and field in {category, "all_text"}:
            yield from _text([block])


def register_scan_jsonl(
    allowed_roots: list[str], register: Callable[..., Any]
) -> Callable[..., dict[str, Any]]:
    """Freeze parent-authorised roots and register scan_jsonl with eval's tool helper."""
    if not allowed_roots:
        raise ValueError("Provide at least one parent-authorised corpus root")
    roots = tuple(Path(root).expanduser().resolve(strict=True) for root in allowed_roots)
    for root in roots:
        if not root.is_dir() and not (root.is_file() and root.suffix.lower() == ".jsonl"):
            raise ValueError(f"Not a JSONL file or corpus directory: {root}")

    def scan_jsonl(
        paths: list[str], terms: list[str], field: str = "user_text", max_examples: int = 20
    ) -> dict[str, Any]:
        """Stream JSONL transcripts under parent-authorised roots. Search case-insensitive
        literal terms in user_text, assistant_text, tool_calls, tool_results or all_text.
        Return record counts and bounded path/line provenance, never message contents.
        Examples are capped, not scanning. Empty terms count every selected record.
        complete=false means malformed/unreadable input or no selected text; do not
        make absence claims. This is a read-only search, not a command executor.
        """
        if not paths or len(paths) > 32:
            raise ValueError("Provide 1 to 32 corpus paths")
        if field not in _FIELDS:
            raise ValueError(f"Unknown field: {field}; choose {sorted(_FIELDS)}")
        if not 0 <= max_examples <= 50:
            raise ValueError("max_examples must be between 0 and 50")
        if len(terms) > 32 or any(not isinstance(term, str) or not term.strip()
                                  or len(term) > 200 for term in terms):
            raise ValueError("Use at most 32 non-blank literal terms, each at most 200 characters")
        needles = {term.casefold(): term for term in terms}
        if len(needles) != len(terms):
            raise ValueError("Terms must be distinct ignoring case")
        selected = []
        for raw in paths:
            path = Path(raw).expanduser()
            if not path.is_absolute():
                raise ValueError("Corpus paths must be absolute")
            if path.is_symlink():
                raise ValueError(f"Symlink inputs are not scanned: {path}")
            path = path.resolve(strict=True)
            if not any(path.is_relative_to(root) for root in roots):
                raise PermissionError(f"Outside parent-authorised corpus roots: {path}")
            if not path.is_dir() and not (path.is_file() and path.suffix.lower() == ".jsonl"):
                raise ValueError(f"Not a JSONL file or corpus directory: {path}")
            selected.append(path)

        result: dict[str, Any] = {
            "paths": [str(path) for path in selected], "field": field, "terms": terms,
            "files_discovered": 0, "files_scanned": 0, "symlinks_skipped": 0,
            "records_seen": 0, "records_parsed": 0, "records_with_selected_text": 0,
            "records_without_selected_text": 0, "blank_lines": 0,
            "matched_records": 0, "matching_files": 0,
            "matched_records_by_term": dict.fromkeys(terms, 0),
            "parse_errors": 0, "read_errors": 0, "errors": [], "examples": [],
        }
        seen: set[Path] = set()

        def error(kind: str, path: Path, line: int | None = None) -> None:
            result[kind] += 1
            if len(result["errors"]) < 20:
                result["errors"].append({"kind": kind, "path": str(path), "line": line})

        def candidates() -> Iterator[Path]:
            for path in selected:
                if path.is_file():
                    yield path
                    continue
                def walk_error(exc: OSError) -> None:
                    error("read_errors", Path(exc.filename or path))
                for directory, dirs, names in os.walk(path, followlinks=False, onerror=walk_error):
                    base = Path(directory)
                    linked = [name for name in dirs if (base / name).is_symlink()]
                    result["symlinks_skipped"] += len(linked)
                    dirs[:] = sorted(name for name in dirs if name not in linked)
                    for name in sorted(names):
                        candidate = base / name
                        if candidate.suffix.lower() != ".jsonl":
                            continue
                        if candidate.is_symlink():
                            result["symlinks_skipped"] += 1
                        else:
                            yield candidate

        for candidate in candidates():
            path = candidate.resolve()
            if path in seen:
                continue
            if not any(path.is_relative_to(root) for root in roots):
                raise PermissionError(f"Discovered file escaped authorised roots: {path}")
            seen.add(path)
            result["files_discovered"] += 1
            file_matched = False
            try:
                # Binary iteration isolates invalid UTF-8 to its own physical record.
                with path.open("rb") as stream:
                    for number, raw in enumerate(stream, 1):
                        if not raw.strip():
                            result["blank_lines"] += 1
                            continue
                        result["records_seen"] += 1
                        try:
                            row = json.loads(raw.decode("utf-8"))
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            error("parse_errors", path, number)
                            continue
                        result["records_parsed"] += 1
                        found: set[str] = set()
                        has_text = False
                        if isinstance(row, dict):
                            for chunk in _chunks(row, field):
                                if not chunk:
                                    continue
                                has_text = True
                                folded = chunk.casefold()
                                found.update(term for needle, term in needles.items() if needle in folded)
                        if not has_text:
                            result["records_without_selected_text"] += 1
                            continue
                        result["records_with_selected_text"] += 1
                        if terms and not found:
                            continue
                        result["matched_records"] += 1
                        file_matched = True
                        for term in found:
                            result["matched_records_by_term"][term] += 1
                        if len(result["examples"]) < max_examples:
                            result["examples"].append({
                                "path": str(path), "line": number, "terms": sorted(found),
                            })
                result["files_scanned"] += 1
            except OSError:
                error("read_errors", path)
            if file_matched:
                result["matching_files"] += 1
        if not result["files_discovered"]:
            raise ValueError("No non-symlink JSONL files found in the selected corpus")
        result["examples_omitted"] = result["matched_records"] - len(result["examples"])
        result["errors_omitted"] = result["parse_errors"] + result["read_errors"] - len(result["errors"])
        result["complete"] = (result["parse_errors"] == 0 and result["read_errors"] == 0
                              and result["records_with_selected_text"] > 0)
        return result

    register(scan_jsonl)
    return scan_jsonl
