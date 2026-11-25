#!/usr/bin/env python3
"""Harness-neutral transcript inventory and per-session aggregates. Standard library only.

Reads session transcripts from four coding-agent harnesses, plus Claude Code's prompt history:

    claude   ~/.claude/projects/**/*.jsonl (main sessions and <session>/subagents/*.jsonl)
    history  ~/.claude/history.jsonl (one row per prompt, across sessions)
    omp      OMP sessions (message, toolResult and bashExecution rows)
    codex    Codex CLI rollouts (session_meta, response_item, turn_context)
    pi       pi sessions (session, message and model_change rows)

It reports counts and provenance only. It never prints message text, so its output is safe to
paste into a note. Read the "complete" flag and the coverage block before drawing any conclusion.

Usage:
    python3 transcript_cli.py inventory ROOT [ROOT ...] [--harness NAME]
    python3 transcript_cli.py aggregate ROOT [ROOT ...] [--harness NAME] [--attribution user|all]
                                        [--format json|csv] [--out FILE] [--show-paths]

Deduplication, in order: byte-identical files are read once; a record with a uuid or id is counted
once across the whole corpus; a record without one is counted once per distinct raw line. Subagent
files are grouped under the session directory that contains their subagents/ folder.

Attribution: "user" marks text a person typed. "injected" marks harness-supplied user-role text
(Codex environment context, AGENTS.md, skill bodies, Claude local-command output). "subagent-brief"
marks the prompts a parent sent to a subagent. "tool-result", "assistant", "meta" and "none" are
the rest. --attribution user keeps only "user" events, so the aggregate then reports prompts only.

Exit status: 0 on success, 2 on bad arguments or a missing root, 3 when no transcript file is found.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

EXIT_OK, EXIT_USAGE, EXIT_NO_FILES = 0, 2, 3
HARNESSES = ("claude", "history", "omp", "codex", "pi")
CLASSIFY_WINDOW = 50
CODEX_INJECTED_TAGS = {"environment_context", "skill", "turn_aborted", "subagent_notification",
                       "recommended_plugins"}
CLAUDE_INJECTED_PREFIXES = ("<local-command-stdout", "<system-reminder", "<task-notification")
CLAUDE_SESSION_TYPES = {"attachment", "queue-operation", "last-prompt", "custom-title", "agent-name",
                        "session-owner", "atis-latch", "mode", "tools-used"}
CODEX_AGENTS_MD = "# AGENTS.md instructions"
CLAUDE_AGENT_LOG_TYPES = {"started", "launched", "result"}
MAX_ERRORS = 20


class UsageError(Exception):
    """A bad argument or a root that cannot be scanned."""


@dataclass
class Event:
    harness: str
    session: str
    role: str  # user, assistant, tool, developer, context, system
    attribution: str  # user, injected, subagent-brief, assistant, tool-result, meta, none
    timestamp: str | None = None
    model: str | None = None
    tools: tuple[str, ...] = ()
    uid: str | None = None
    subagent: bool = False
    raw_session: str | None = None


@dataclass
class Stats:
    roots: list[str] = field(default_factory=list)
    files_discovered: int = 0
    files_duplicate_content: int = 0
    files_unknown: int = 0
    files_by_harness: Counter = field(default_factory=Counter)
    subagent_files: int = 0
    subagent_session_mismatch_files: int = 0
    symlinks_skipped: int = 0
    records_seen: int = 0
    records_parsed: int = 0
    records_non_message: int = 0
    records_duplicate: int = 0
    records_filtered: int = 0
    parse_errors: int = 0
    read_errors: int = 0
    blank_lines: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    history_sessions_with_transcript: int = 0
    history_sessions_without_transcript: int = 0
    transcript_sessions: int = 0

    def error(self, kind: str, path: str, line: int | None = None) -> None:
        setattr(self, kind, getattr(self, kind) + 1)
        if len(self.errors) < MAX_ERRORS:
            self.errors.append({"kind": kind, "file": path, "line": line})


# ---------- helpers ----------------------------------------------------------------------------

def to_iso(value: Any) -> str | None:
    """Normalise epoch seconds, epoch milliseconds or an ISO string to UTC seconds precision."""
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 1e11 else value
            moment = datetime.fromtimestamp(seconds, timezone.utc)
        elif isinstance(value, str):
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
        else:
            return None
    except (OverflowError, OSError, ValueError):
        return None
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def text_of(content: Any) -> str:
    """Text from a string or a list of text-bearing blocks (text, input_text, output_text)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block["text"] for block in content
                         if isinstance(block, dict) and isinstance(block.get("text"), str))
    return ""


def blocks_of(content: Any) -> list[dict[str, Any]]:
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def message_of(row: dict[str, Any]) -> dict[str, Any]:
    message = row.get("message")
    return message if isinstance(message, dict) else {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def peek(path: Path, count: int = CLASSIFY_WINDOW) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("rb") as stream:
            for raw in stream:
                if not raw.strip():
                    continue
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                if len(rows) >= count:
                    break
    except OSError:
        return []
    return rows


def classify(rows: list[dict[str, Any]], path: Path) -> str:
    types = {row.get("type") for row in rows}
    if path.name == "history.jsonl" and any("display" in r and "type" not in r for r in rows):
        return "history"
    if types & {"session_meta", "response_item", "event_msg", "turn_context"}:
        return "codex"
    if any("parentUuid" in r for r in rows) or types & CLAUDE_SESSION_TYPES:
        return "claude"
    if any("parentId" in r for r in rows if r.get("type") in {"message", "model_change"}):
        return "pi"
    if types & {"message", "custom", "model_usage", "session", "title", "session_init",
                "compaction"}:
        return "omp"
    if any("display" in r and "type" not in r for r in rows):
        return "history"
    if "subagents" in path.parts[:-1] and types & CLAUDE_AGENT_LOG_TYPES:
        return "claude"  # subagent run logs: no message rows, counted as non-message records
    return "unknown"


def file_session_id(harness: str, rows: list[dict[str, Any]], fallback: str) -> str:
    if harness == "codex":
        for row in rows:
            if row.get("type") == "session_meta":
                payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
                return str(payload.get("id") or fallback)
    if harness in {"pi", "omp"}:
        for row in rows:
            if row.get("type") == "session" and row.get("id"):
                return str(row["id"])
    if harness == "claude":
        for row in rows:
            if row.get("sessionId"):
                return str(row["sessionId"])
    return fallback


def subagent_parent(path: Path) -> str | None:
    """The session directory above the nearest subagents/ folder, or None for a main session file.

    Workflow runs nest one level deeper (subagents/wf_<id>/agent.jsonl); the session is still the
    directory above subagents/.
    """
    parts = path.parts[:-1]
    if "subagents" not in parts:
        return None
    index = len(parts) - 1 - parts[::-1].index("subagents")
    return parts[index - 1] if index >= 1 else None


# ---------- per-harness extractors -------------------------------------------------------------

def claude_event(row: dict[str, Any], default: str) -> Event | None:
    kind = row.get("type")
    if kind not in {"user", "assistant"}:
        return None
    msg = message_of(row)
    content = msg.get("content")
    raw = row.get("sessionId")
    common = {"harness": "claude", "session": str(raw or default), "timestamp": to_iso(row.get("timestamp")),
              "uid": row.get("uuid"), "raw_session": raw}
    if kind == "assistant":
        tools = tuple(str(b.get("name") or "<unnamed>") for b in blocks_of(content) if b.get("type") == "tool_use")
        return Event(role="assistant", attribution="assistant", model=msg.get("model"), tools=tools, **common)
    if any(b.get("type") == "tool_result" for b in blocks_of(content)):
        return Event(role="tool", attribution="tool-result", **common)
    if row.get("isMeta") or row.get("isCompactSummary"):
        return Event(role="user", attribution="meta", **common)
    if row.get("isSidechain"):
        return Event(role="user", attribution="subagent-brief", subagent=True, **common)
    text = text_of(content).lstrip()
    if not text.strip():
        return Event(role="user", attribution="none", **common)
    attribution = "injected" if text.startswith(CLAUDE_INJECTED_PREFIXES) else "user"
    return Event(role="user", attribution=attribution, **common)


def history_event(row: dict[str, Any], default: str) -> Event | None:
    if "display" not in row or "type" in row:
        return None
    return Event(harness="history", session=str(row.get("sessionId") or default), role="user",
                 attribution="user", timestamp=to_iso(row.get("timestamp")), raw_session=row.get("sessionId"))


def codex_event(row: dict[str, Any], default: str) -> Event | None:
    kind = row.get("type")
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    common = {"harness": "codex", "session": default, "timestamp": to_iso(row.get("timestamp"))}
    if kind == "turn_context":
        return Event(role="context", attribution="context", model=payload.get("model"), **common)
    if kind != "response_item":
        return None
    ptype = payload.get("type")
    if ptype == "message":
        role = payload.get("role")
        if role == "assistant":
            return Event(role="assistant", attribution="assistant", **common)
        if role == "developer":
            return Event(role="developer", attribution="injected", **common)
        if role == "user":
            text = text_of(payload.get("content")).lstrip()
            injected = text.startswith(CODEX_AGENTS_MD)
            if text.startswith("<"):
                tag = text[1:].split(">", 1)[0].split()[0] if text[1:2].isalpha() else ""
                injected = injected or tag in CODEX_INJECTED_TAGS
            attribution = "injected" if injected else ("user" if text.strip() else "none")
            return Event(role="user", attribution=attribution, **common)
        return None
    if ptype in {"function_call", "custom_tool_call"}:
        return Event(role="assistant", attribution="assistant", tools=(str(payload.get("name") or "<unnamed>"),), **common)
    if ptype in {"function_call_output", "custom_tool_call_output"}:
        return Event(role="tool", attribution="tool-result", **common)
    if ptype == "web_search_call":
        return Event(role="assistant", attribution="assistant", tools=("web_search",), **common)
    return None


def pi_event(row: dict[str, Any], default: str) -> Event | None:
    kind = row.get("type")
    common = {"harness": "pi", "session": default, "uid": row.get("id")}
    if kind == "model_change":
        return Event(role="context", attribution="context", model=row.get("modelId"),
                     timestamp=to_iso(row.get("timestamp")), **common)
    if kind != "message":
        return None
    msg = message_of(row)
    role = msg.get("role")
    stamp = to_iso(row.get("timestamp")) or to_iso(msg.get("timestamp"))
    if role == "assistant":
        tools = tuple(str(b.get("name") or "<unnamed>") for b in blocks_of(msg.get("content")) if b.get("type") == "toolCall")
        return Event(role="assistant", attribution="assistant", tools=tools, model=msg.get("model"), timestamp=stamp, **common)
    if role in {"toolResult", "bashExecution"}:
        return Event(role="tool", attribution="tool-result", timestamp=stamp, **common)
    if role == "user":
        attribution = "user" if text_of(msg.get("content")).strip() else "none"
        return Event(role="user", attribution=attribution, timestamp=stamp, **common)
    return Event(role="system", attribution="injected", timestamp=stamp, **common)


def omp_event(row: dict[str, Any], default: str) -> Event | None:
    if row.get("type") != "message":
        return None
    msg = message_of(row)
    role = msg.get("role")
    stamp = to_iso(msg.get("timestamp")) or to_iso(row.get("timestamp"))
    common = {"harness": "omp", "session": default, "timestamp": stamp, "uid": row.get("id") or msg.get("id")}
    if role == "assistant":
        tools = tuple(str(b.get("name") or "<unnamed>") for b in blocks_of(msg.get("content")) if b.get("type") == "toolCall")
        return Event(role="assistant", attribution="assistant", tools=tools, model=msg.get("model"), **common)
    if role in {"toolResult", "bashExecution"}:
        return Event(role="tool", attribution="tool-result", **common)
    if role == "user":
        if msg.get("isMeta"):
            return Event(role="user", attribution="meta", **common)
        return Event(role="user", attribution="user" if text_of(msg.get("content")).strip() else "none", **common)
    return Event(role="system", attribution="injected", **common)


EXTRACTORS: dict[str, Callable[[dict[str, Any], str], Event | None]] = {
    "claude": claude_event, "history": history_event, "codex": codex_event,
    "pi": pi_event, "omp": omp_event,
}


# ---------- aggregation ------------------------------------------------------------------------

@dataclass
class Aggregate:
    harness: str
    session: str
    sources: set[str] = field(default_factory=set)
    subagent_sources: set[str] = field(default_factory=set)
    first: str | None = None
    last: str | None = None
    models: set[str] = field(default_factory=set)
    counts: Counter = field(default_factory=Counter)
    tools: Counter = field(default_factory=Counter)

    def add(self, event: Event, source: str) -> None:
        self.sources.add(source)
        if event.subagent:
            self.subagent_sources.add(source)
            self.counts["subagent_events"] += 1
        if event.timestamp:
            self.first = min(filter(None, [self.first, event.timestamp]))
            self.last = max(filter(None, [self.last, event.timestamp]))
        if event.model:
            self.models.add(str(event.model))
        bucket = {"user": "user_prompts", "injected": "injected_messages",
                  "subagent-brief": "subagent_briefs", "meta": "meta_messages"}.get(event.attribution)
        if bucket:
            self.counts[bucket] += 1
        if event.role == "assistant":
            self.counts["assistant_messages"] += 1
        if event.role == "tool":
            self.counts["tool_results"] += 1
        for name in event.tools:
            self.counts["tool_calls"] += 1
            self.tools[name] += 1

    def as_dict(self, show_paths: bool) -> dict[str, Any]:
        out: dict[str, Any] = {
            "harness": self.harness, "session": self.session,
            "source_files": len(self.sources), "subagent_files": len(self.subagent_sources),
            "first_seen": self.first, "last_seen": self.last, "models": sorted(self.models),
            "user_prompts": self.counts["user_prompts"], "injected_messages": self.counts["injected_messages"],
            "subagent_briefs": self.counts["subagent_briefs"], "meta_messages": self.counts["meta_messages"],
            "assistant_messages": self.counts["assistant_messages"], "tool_results": self.counts["tool_results"],
            "tool_calls": self.counts["tool_calls"], "subagent_events": self.counts["subagent_events"],
            "tool_calls_by_name": dict(self.tools.most_common(20)),
        }
        if show_paths:
            out["sources"] = sorted(self.sources)
        return out


# ---------- discovery and the main loop --------------------------------------------------------

def discover(roots: list[str], stats: Stats) -> Iterator[Path]:
    seen: set[Path] = set()
    for raw in roots:
        root = Path(raw).expanduser()
        if not root.is_absolute():
            raise UsageError(f"root must be an absolute path: {raw}")
        if not root.exists():
            raise UsageError(f"root does not exist: {raw}")
        if root.is_symlink():
            stats.symlinks_skipped += 1
            continue
        stats.roots.append(str(root.resolve()))
        if root.is_file():
            if root.suffix.lower() != ".jsonl":
                raise UsageError(f"root is not a .jsonl file or a directory: {raw}")
            candidates = iter([root])
        else:
            candidates = _walk(root, stats)
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield resolved


def _walk(root: Path, stats: Stats) -> Iterator[Path]:
    for directory, dirs, names in os.walk(root, followlinks=False):
        base = Path(directory)
        linked = [name for name in dirs if (base / name).is_symlink()]
        stats.symlinks_skipped += len(linked)
        dirs[:] = sorted(name for name in dirs if name not in linked)
        for name in sorted(names):
            candidate = base / name
            if candidate.suffix.lower() != ".jsonl":
                continue
            if candidate.is_symlink():
                stats.symlinks_skipped += 1
                continue
            yield candidate


def iter_rows(path: Path, stats: Stats) -> Iterator[tuple[int, dict[str, Any], bytes]]:
    with path.open("rb") as stream:
        for number, raw in enumerate(stream, 1):
            if not raw.strip():
                stats.blank_lines += 1
                continue
            stats.records_seen += 1
            try:
                row = json.loads(raw)
            except ValueError:
                stats.error("parse_errors", str(path), number)
                continue
            if not isinstance(row, dict):
                stats.records_non_message += 1
                continue
            stats.records_parsed += 1
            yield number, row, raw


def run_aggregate(args: argparse.Namespace, stats: Stats, want_sessions: bool) -> dict[str, Any] | None:
    files = list(discover(args.roots, stats))
    stats.files_discovered = len(files)
    if not files:
        raise LookupError("no non-symlink .jsonl files under the given roots")
    aggregates: dict[tuple[str, str], Aggregate] = {}
    seen_digests: set[str] = set()
    seen_uids: set[tuple[str, str]] = set()
    seen_lines: set[str] = set()
    history_sessions: set[str] = set()
    transcript_sessions: set[str] = set()
    for path in files:
        digest = sha256_file(path)
        if digest in seen_digests:
            stats.files_duplicate_content += 1
            continue
        seen_digests.add(digest)
        if path.stat().st_size == 0:
            stats.files_by_harness["empty"] += 1
            continue
        rows = peek(path)
        harness = classify(rows, path)
        stats.files_by_harness[harness] += 1
        if harness == "unknown":
            stats.files_unknown += 1
            continue
        if args.harness and harness != args.harness:
            continue
        parent = subagent_parent(path)
        if parent:
            stats.subagent_files += 1
        default = file_session_id(harness, rows, parent or path.stem)
        extract = EXTRACTORS[harness]
        mismatch_counted = False
        source = _relative(path, stats.roots)
        try:
            for number, row, raw in iter_rows(path, stats):
                event = extract(row, default)
                if event is None:
                    stats.records_non_message += 1
                    continue
                if parent:
                    if event.raw_session and event.raw_session != parent and not mismatch_counted:
                        stats.subagent_session_mismatch_files += 1
                        mismatch_counted = True
                    event = replace(event, session=parent, subagent=True)
                if event.uid:
                    key = (harness, str(event.uid))
                    if key in seen_uids:
                        stats.records_duplicate += 1
                        continue
                    seen_uids.add(key)
                else:
                    line_digest = hashlib.sha256(raw).hexdigest()
                    if line_digest in seen_lines:
                        stats.records_duplicate += 1
                        continue
                    seen_lines.add(line_digest)
                if args.attribution == "user" and event.attribution != "user":
                    stats.records_filtered += 1
                    continue
                if harness == "history":
                    history_sessions.add(event.session)
                else:
                    transcript_sessions.add(event.session)
                if want_sessions:
                    key = (harness, event.session)
                    aggregates.setdefault(key, Aggregate(harness, event.session)).add(event, source)
        except OSError:
            stats.error("read_errors", source)
        if parent and want_sessions and args.attribution == "all":
            # A subagent file with no message rows (a run log) still belongs to its session.
            owner = aggregates.setdefault((harness, parent), Aggregate(harness, parent))
            owner.sources.add(source)
            owner.subagent_sources.add(source)
    stats.history_sessions_with_transcript = len(history_sessions & transcript_sessions)
    stats.history_sessions_without_transcript = len(history_sessions - transcript_sessions)
    stats.transcript_sessions = len(transcript_sessions)
    if not want_sessions:
        return None
    rows_out = [agg.as_dict(args.show_paths) for agg in sorted(aggregates.values(), key=lambda a: (a.harness, a.session))]
    return {"sessions": rows_out, "session_count": len(rows_out)}


def _relative(path: Path, roots: list[str]) -> str:
    for root in roots:
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return path.name


def coverage(stats: Stats, session_count: int | None) -> dict[str, Any]:
    complete = (stats.parse_errors == 0 and stats.read_errors == 0 and stats.files_unknown == 0
                and stats.records_parsed > 0)
    out = {
        "roots": stats.roots, "files_discovered": stats.files_discovered,
        "files_by_harness": dict(stats.files_by_harness), "files_duplicate_content": stats.files_duplicate_content,
        "files_unknown": stats.files_unknown, "subagent_files": stats.subagent_files,
        "subagent_session_mismatch_files": stats.subagent_session_mismatch_files,
        "symlinks_skipped": stats.symlinks_skipped, "blank_lines": stats.blank_lines,
        "records_seen": stats.records_seen, "records_parsed": stats.records_parsed,
        "records_non_message": stats.records_non_message, "records_duplicate": stats.records_duplicate,
        "records_filtered_by_attribution": stats.records_filtered, "parse_errors": stats.parse_errors,
        "read_errors": stats.read_errors, "errors": stats.errors, "complete": complete,
        "transcript_sessions": stats.transcript_sessions,
        "history_sessions_with_transcript": stats.history_sessions_with_transcript,
        "history_sessions_without_transcript": stats.history_sessions_without_transcript,
    }
    if session_count is not None:
        out["session_count"] = session_count
    return out


def write_csv(sessions: list[dict[str, Any]], stream: io.TextIOBase) -> None:
    columns = ["harness", "session", "source_files", "subagent_files", "first_seen", "last_seen", "models",
               "user_prompts", "injected_messages", "subagent_briefs", "meta_messages", "assistant_messages",
               "tool_results", "tool_calls", "subagent_events", "tool_calls_by_name"]
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in sessions:
        flat = dict(row, models=";".join(row["models"]),
                    tool_calls_by_name=";".join(f"{k}={v}" for k, v in row["tool_calls_by_name"].items()))
        writer.writerow(flat)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inventory", "aggregate"):
        p = sub.add_parser(name)
        p.add_argument("roots", nargs="+", help="absolute directories or .jsonl files to scan")
        p.add_argument("--harness", choices=HARNESSES, help="keep only this harness")
        p.add_argument("--show-paths", action="store_true", help="include source file paths relative to each root")
        if name == "aggregate":
            p.add_argument("--attribution", choices=("user", "all"), default="all")
            p.add_argument("--format", choices=("json", "csv"), default="json")
            p.add_argument("--out", help="write to this file instead of standard output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stats = Stats()
    try:
        if args.command == "inventory":
            args.attribution = "all"
            run_aggregate(args, stats, want_sessions=False)
            report: dict[str, Any] = {"coverage": coverage(stats, None)}
            text = json.dumps(report, indent=2, sort_keys=True) + "\n"
            sys.stdout.write(text)
            return EXIT_OK
        result = run_aggregate(args, stats, want_sessions=True)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except LookupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_NO_FILES
    assert result is not None
    cov = coverage(stats, result["session_count"])
    if args.format == "csv":
        buffer = io.StringIO()
        write_csv(result["sessions"], buffer)
        output = buffer.getvalue()
    else:
        output = json.dumps({"attribution": args.attribution, "harness_filter": args.harness,
                             "coverage": cov, "sessions": result["sessions"]}, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).expanduser().write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
