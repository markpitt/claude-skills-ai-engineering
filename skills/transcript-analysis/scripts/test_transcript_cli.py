#!/usr/bin/env python3
"""Tests for transcript_cli.py. Run them wrapped:

    python3 -I claude-skills-ai-engineering/skills/transcript-analysis/scripts/test_transcript_cli.py -v

Run it through the repository's sandbox wrapper for test runs, if it has one.

Every fixture is synthetic and written at test time inside a temporary directory. No test reads a
real transcript. Each test drives the CLI as a subprocess, so argument parsing, exit codes and the
JSON it prints are what is checked. Every "clean" assertion sits beside a positive control in the
same corpus, so a check that never fires cannot pass as green.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "transcript_cli.py"

EXIT_OK, EXIT_USAGE, EXIT_NO_FILES = 0, 2, 3
CANARY = "SYNTHETIC_CANARY_7d41"  # must never appear in any output


def write_rows(path: Path, rows: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [row if isinstance(row, str) else json.dumps(row) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def claude_user(uid: str, session: str, text: str, **extra: object) -> dict:
    return {"type": "user", "uuid": uid, "parentUuid": None, "sessionId": session, "timestamp": "2026-01-02T03:04:05.000Z",
            "message": {"role": "user", "content": text}, **extra}


def claude_assistant(uid: str, session: str, tools: list[str], model: str = "synthetic-model") -> dict:
    content = [{"type": "text", "text": "reply"}] + [{"type": "tool_use", "name": n, "input": {}} for n in tools]
    return {"type": "assistant", "uuid": uid, "parentUuid": None, "sessionId": session, "timestamp": "2026-01-02T03:05:00.000Z",
            "message": {"role": "assistant", "model": model, "content": content}}


def claude_tool_result(uid: str, session: str) -> dict:
    return {"type": "user", "uuid": uid, "parentUuid": None, "sessionId": session, "timestamp": "2026-01-02T03:06:00.000Z",
            "message": {"role": "user", "content": [{"type": "tool_result", "content": "out"}]}}


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True)


def aggregate(root: Path, *extra: str) -> tuple[int, dict]:
    result = run_cli("aggregate", str(root), "--format", "json", *extra)
    payload = json.loads(result.stdout) if result.returncode == 0 else {}
    return result.returncode, payload


def session_row(payload: dict, harness: str, session: str) -> dict:
    matches = [s for s in payload["sessions"] if s["harness"] == harness and s["session"] == session]
    assert len(matches) == 1, f"expected one {harness}/{session} row, got {len(matches)}"
    return matches[0]


def build_claude_corpus(root: Path) -> Path:
    projects = root / "projects" / "-synthetic-project"
    main = projects / "sess-main.jsonl"
    write_rows(main, [
        claude_user("u1", "sess-main", f"prompt one {CANARY}"),
        claude_assistant("a1", "sess-main", ["Read", "Edit"]),
        claude_tool_result("t1", "sess-main"),
        {"type": "user", "uuid": "m1", "parentUuid": None, "sessionId": "sess-main", "isMeta": True,
         "message": {"role": "user", "content": "meta text"}},
        claude_user("u2", "sess-main", "prompt two"),
        "",  # blank line, counted as blank and not as a record
        "{not json",  # parse error, must stay visible
    ])
    # Subagent file under the parent session directory. Its brief is a sidechain user record.
    sub = projects / "sess-main" / "subagents" / "agent-one.jsonl"
    side_brief = claude_user("sb1", "sess-main", "brief from parent", isSidechain=True)
    side_reply = claude_assistant("sa1", "sess-main", ["Grep"])
    side_reply["isSidechain"] = True
    write_rows(sub, [side_brief, side_reply])
    # A second main session with a different id.
    write_rows(projects / "sess-other.jsonl", [claude_user("u9", "sess-other", "other prompt")])
    return projects


class ClaudeSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="tc-claude-")
        self.root = Path(self._tmp.name)
        build_claude_corpus(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_user_prompts_and_subagents_group_under_parent(self) -> None:
        code, payload = aggregate(self.root)
        self.assertEqual(code, EXIT_OK)
        main = session_row(payload, "claude", "sess-main")
        self.assertEqual(main["user_prompts"], 2, "two typed prompts in the main file")
        self.assertEqual(main["tool_calls"], 3, "Read, Edit from the parent and Grep from the subagent")
        self.assertEqual(main["subagent_files"], 1, "the subagent file belongs to sess-main")
        self.assertEqual(main["subagent_briefs"], 1, "the parent's brief is not a user prompt")
        self.assertEqual(main["meta_messages"], 1)
        self.assertEqual(main["tool_results"], 1)
        self.assertEqual(session_row(payload, "claude", "sess-other")["user_prompts"], 1)

    def test_attribution_user_keeps_only_typed_prompts(self) -> None:
        code, payload = aggregate(self.root, "--attribution", "user")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["attribution"], "user")
        main = session_row(payload, "claude", "sess-main")
        self.assertEqual(main["user_prompts"], 2)
        self.assertEqual(main["tool_calls"], 0, "tool calls are not user-attributed and are filtered out")
        self.assertGreater(payload["coverage"]["records_filtered_by_attribution"], 0,
                           "positive control: the filter removed something")

    def test_output_never_contains_message_text(self) -> None:
        result = run_cli("aggregate", str(self.root), "--format", "json")
        self.assertEqual(result.returncode, EXIT_OK)
        self.assertNotIn(CANARY, result.stdout)
        self.assertNotIn("prompt one", result.stdout)

    def test_parse_error_is_visible_and_clears_complete(self) -> None:
        _, payload = aggregate(self.root)
        cov = payload["coverage"]
        self.assertEqual(cov["parse_errors"], 1)
        self.assertFalse(cov["complete"])
        self.assertEqual(cov["errors"][0]["kind"], "parse_errors")
        self.assertEqual(cov["errors"][0]["line"], 7)
        self.assertEqual(cov["blank_lines"], 1)


class DedupeAndSafetyTests(unittest.TestCase):
    def test_uuid_duplicates_across_files_counted_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tc-dup-") as tmp:
            root = Path(tmp)
            shared = claude_user("same-uuid", "sess-a", "copied prompt")
            write_rows(root / "a" / "one.jsonl", [shared, claude_user("only-a", "sess-a", "x")])
            write_rows(root / "b" / "two.jsonl", [shared])
            _, payload = aggregate(root)
            self.assertEqual(payload["coverage"]["records_duplicate"], 1)
            self.assertEqual(session_row(payload, "claude", "sess-a")["user_prompts"], 2)

    def test_byte_identical_file_read_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tc-bytes-") as tmp:
            root = Path(tmp)
            rows = [claude_user("only-once", "sess-b", "same bytes")]
            write_rows(root / "p1" / "x.jsonl", rows)
            write_rows(root / "p2" / "y.jsonl", rows)
            _, payload = aggregate(root)
            self.assertEqual(payload["coverage"]["files_duplicate_content"], 1)
            self.assertEqual(session_row(payload, "claude", "sess-b")["user_prompts"], 1)

    def test_symlinks_are_not_followed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tc-link-") as tmp:
            root = Path(tmp) / "corpus"
            outside = Path(tmp) / "outside.jsonl"
            write_rows(outside, [claude_user("out-1", "sess-out", "outside prompt")])
            write_rows(root / "real.jsonl", [claude_user("in-1", "sess-in", "inside prompt")])
            (root / "linked.jsonl").symlink_to(outside)
            (root / "linked-dir").symlink_to(Path(tmp), target_is_directory=True)
            _, payload = aggregate(root)
            self.assertEqual(payload["coverage"]["symlinks_skipped"], 2)
            self.assertEqual(payload["coverage"]["files_discovered"], 1)
            self.assertEqual(session_row(payload, "claude", "sess-in")["user_prompts"], 1)
            self.assertEqual([s["session"] for s in payload["sessions"]], ["sess-in"],
                             "positive control: the inside file was read, the linked one was not")


class OtherHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="tc-others-")
        self.root = Path(self._tmp.name)
        codex = self.root / "codex" / "sessions" / "2026" / "rollout-x.jsonl"
        write_rows(codex, [
            {"timestamp": "2026-02-01T10:00:00Z", "type": "session_meta", "payload": {"id": "codex-1"}},
            {"timestamp": "2026-02-01T10:00:01Z", "type": "turn_context", "payload": {"model": "synthetic-codex"}},
            {"timestamp": "2026-02-01T10:00:02Z", "type": "response_item",
             "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "# AGENTS.md instructions for x"}]}},
            {"timestamp": "2026-02-01T10:00:03Z", "type": "response_item",
             "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>x</environment_context>"}]}},
            {"timestamp": "2026-02-01T10:00:04Z", "type": "response_item",
             "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": f"typed {CANARY}"}]}},
            {"timestamp": "2026-02-01T10:00:05Z", "type": "response_item",
             "payload": {"type": "function_call", "name": "shell", "arguments": "{}"}},
            {"timestamp": "2026-02-01T10:00:06Z", "type": "response_item",
             "payload": {"type": "function_call_output", "output": "ok"}},
        ])
        pi = self.root / "pi" / "agent" / "sessions" / "pi-session.jsonl"
        write_rows(pi, [
            {"type": "session", "version": 3, "id": "pi-1", "timestamp": "2026-03-01T09:00:00Z", "cwd": "/synthetic"},
            {"type": "model_change", "id": "mc1", "parentId": None, "timestamp": "2026-03-01T09:00:01Z",
             "provider": "synthetic", "modelId": "synthetic-pi"},
            {"type": "message", "id": "pm1", "parentId": "mc1", "timestamp": "2026-03-01T09:00:02Z",
             "message": {"role": "user", "content": [{"type": "text", "text": "pi prompt"}], "timestamp": 1772355602000}},
            {"type": "message", "id": "pm2", "parentId": "pm1", "timestamp": "2026-03-01T09:00:03Z",
             "message": {"role": "assistant", "content": [{"type": "toolCall", "name": "read", "arguments": {}}]}},
            {"type": "message", "id": "pm3", "parentId": "pm2", "timestamp": "2026-03-01T09:00:04Z",
             "message": {"role": "toolResult", "content": [{"type": "text", "text": "r"}]}},
        ])
        omp = self.root / "omp" / "sessions" / "omp-session.jsonl"
        write_rows(omp, [
            {"type": "session", "id": "omp-1", "title": "synthetic"},
            {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "omp prompt"}],
                                            "timestamp": 1772355602000}},
            {"type": "message", "message": {"role": "assistant", "model": "synthetic-omp",
                                            "content": [{"type": "toolCall", "name": "edit", "arguments": {}}],
                                            "timestamp": 1772355603000}},
            {"type": "message", "message": {"role": "toolResult", "content": [{"type": "text", "text": "done"}]}},
        ])
        history = self.root / "history.jsonl"
        write_rows(history, [
            {"display": "history one", "timestamp": 1772355602000, "project": "/synthetic", "sessionId": "codex-1"},
            {"display": "history two", "timestamp": 1772355700000, "project": "/synthetic", "sessionId": "gone-9"},
        ])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_each_harness_is_classified_and_counted(self) -> None:
        code, payload = aggregate(self.root)
        self.assertEqual(code, EXIT_OK)
        cov = payload["coverage"]
        self.assertEqual(cov["files_by_harness"], {"codex": 1, "pi": 1, "omp": 1, "history": 1})
        self.assertEqual(cov["files_unknown"], 0)
        codex = session_row(payload, "codex", "codex-1")
        self.assertEqual(codex["user_prompts"], 1, "AGENTS.md and environment_context are injected, not typed")
        self.assertEqual(codex["injected_messages"], 2)
        self.assertEqual(codex["tool_calls"], 1)
        self.assertEqual(codex["tool_results"], 1)
        self.assertEqual(codex["models"], ["synthetic-codex"])
        self.assertEqual(codex["first_seen"], "2026-02-01T10:00:01Z", "first counted event is the turn context; session_meta is not an event")
        pi = session_row(payload, "pi", "pi-1")
        self.assertEqual(pi["user_prompts"], 1)
        self.assertEqual(pi["tool_calls_by_name"], {"read": 1})
        self.assertEqual(pi["models"], ["synthetic-pi"])
        omp = session_row(payload, "omp", "omp-1")
        self.assertEqual(omp["user_prompts"], 1)
        self.assertEqual(omp["models"], ["synthetic-omp"])
        self.assertEqual(omp["first_seen"], "2026-03-01T09:00:02Z", "epoch milliseconds normalised to UTC")

    def test_history_is_reported_apart_and_joins_by_session(self) -> None:
        _, payload = aggregate(self.root)
        cov = payload["coverage"]
        self.assertEqual(session_row(payload, "history", "codex-1")["user_prompts"], 1)
        self.assertEqual(session_row(payload, "history", "gone-9")["user_prompts"], 1)
        self.assertEqual(cov["history_sessions_with_transcript"], 1)
        self.assertEqual(cov["history_sessions_without_transcript"], 1)

    def test_harness_flag_restricts_the_corpus(self) -> None:
        _, payload = aggregate(self.root, "--harness", "pi")
        self.assertEqual([s["harness"] for s in payload["sessions"]], ["pi"])

    def test_csv_output_has_header_and_rows(self) -> None:
        result = run_cli("aggregate", str(self.root), "--format", "csv")
        self.assertEqual(result.returncode, EXIT_OK)
        lines = result.stdout.strip().splitlines()
        self.assertTrue(lines[0].startswith("harness,session,"))
        self.assertEqual(len(lines), 1 + 5, "header plus five rows: codex, pi, omp, and two history sessions")
        self.assertNotIn(CANARY, result.stdout)

    def test_unknown_file_is_reported_not_dropped(self) -> None:
        write_rows(self.root / "strange" / "odd.jsonl", [{"unrelated": "shape"}])
        _, payload = aggregate(self.root)
        self.assertEqual(payload["coverage"]["files_unknown"], 1)
        self.assertFalse(payload["coverage"]["complete"])


class EdgeClassificationTests(unittest.TestCase):
    def test_empty_file_is_counted_not_unknown(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tc-empty-file-") as tmp:
            root = Path(tmp)
            (root / "zero.jsonl").write_bytes(b"")
            write_rows(root / "real.jsonl", [claude_user("e1", "sess-e", "one prompt")])
            _, payload = aggregate(root)
            cov = payload["coverage"]
            self.assertEqual(cov["files_by_harness"]["empty"], 1)
            self.assertEqual(cov["files_unknown"], 0, "an empty file is not an unrecognised shape")
            self.assertTrue(cov["complete"], "positive control: complete holds with one real file")

    def test_subagent_run_log_is_claude_with_no_messages(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tc-runlog-") as tmp:
            root = Path(tmp)
            write_rows(root / "p" / "sess-r" / "subagents" / "run-log.jsonl", [
                {"type": "started", "task": "synthetic"}, {"type": "launched"}, {"type": "result", "ok": True}])
            write_rows(root / "p" / "sess-r" / "subagents" / "wf_synthetic" / "run-log.jsonl", [
                {"type": "started", "task": "synthetic"}, {"type": "result", "ok": True}])
            write_rows(root / "p" / "sess-r.jsonl", [claude_user("r1", "sess-r", "a prompt")])
            _, payload = aggregate(root)
            cov = payload["coverage"]
            self.assertEqual(cov["files_by_harness"], {"claude": 3}, "both run logs are recognised, not unknown")
            self.assertEqual(cov["records_non_message"], 5)
            self.assertEqual(cov["subagent_files"], 2, "the workflow log is grouped under the same session")
            self.assertEqual(session_row(payload, "claude", "sess-r")["subagent_files"], 2)
            self.assertEqual(session_row(payload, "claude", "sess-r")["user_prompts"], 1,
                             "positive control: the run log adds no prompts")
            self.assertTrue(cov["complete"])


class UsageTests(unittest.TestCase):
    def test_missing_root_exits_usage(self) -> None:
        result = run_cli("aggregate", "/nonexistent/synthetic-root")
        self.assertEqual(result.returncode, EXIT_USAGE)
        self.assertIn("does not exist", result.stderr)

    def test_relative_root_exits_usage(self) -> None:
        result = run_cli("inventory", "relative/path")
        self.assertEqual(result.returncode, EXIT_USAGE)

    def test_empty_root_exits_no_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tc-empty-") as tmp:
            result = run_cli("aggregate", tmp)
            self.assertEqual(result.returncode, EXIT_NO_FILES)
            self.assertIn("no non-symlink", result.stderr)

    def test_inventory_reports_counts_without_sessions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tc-inv-") as tmp:
            root = Path(tmp)
            build_claude_corpus(root)
            result = run_cli("inventory", str(root))
            self.assertEqual(result.returncode, EXIT_OK)
            cov = json.loads(result.stdout)["coverage"]
            self.assertEqual(cov["files_by_harness"], {"claude": 3})
            self.assertEqual(cov["subagent_files"], 1)
            self.assertNotIn("sessions", json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
