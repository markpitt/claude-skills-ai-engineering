"""Tests for measure_context_budget.py. Fixtures are generated at run time in a temporary directory.

Run inside a sandbox (for example a bubblewrap wrapper) for test runs:
    python3 -P claude-skills-ai-engineering/skills/instruction-context-budget/scripts/test_measure_context_budget.py -v
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "measure_context_budget.py"
sys.path.insert(0, str(SCRIPT.parent))

import measure_context_budget as mcb  # noqa: E402


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def run_main(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mcb.main(argv)
    return code, out.getvalue(), err.getvalue()


class MeasureTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_bytes_are_utf8_bytes_not_characters(self) -> None:
        # "café" is 4 characters and 5 bytes in UTF-8. The byte count must be 5.
        write(self.root / "CLAUDE.md", "café")
        entries, _ = mcb.measure([str(self.root)], 4.0, 200, 25600)
        self.assertEqual(entries[0].bytes, 5)
        self.assertEqual(entries[0].lines, 1)

    def test_token_estimate_rounds_up_and_is_zero_for_empty(self) -> None:
        self.assertEqual(mcb.estimate_tokens(5, 4.0), 2)
        self.assertEqual(mcb.estimate_tokens(8, 4.0), 2)
        self.assertEqual(mcb.estimate_tokens(0, 4.0), 0)

    def test_missing_root_is_a_usage_error_not_an_empty_budget(self) -> None:
        # The wrong-root trap: a missing root must fail loudly rather than report zero files.
        code, out, err = run_main(["measure", str(self.root / "does-not-exist")])
        self.assertEqual(code, 2)
        self.assertIn("root does not exist", err)
        self.assertEqual(out, "")

    def test_missing_root_exit_code_through_a_real_process(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-I", "-P", str(SCRIPT), "measure", str(self.root / "nope")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 2)

    def test_companion_folder_is_excluded_and_counted_separately(self) -> None:
        write(self.root / "CLAUDE.md", "Always run the tests.\n")
        write(self.root / ".staging" / "CLAUDE.prose.md", "A long history of the rule. " * 50)
        entries, excluded = mcb.measure([str(self.root)], 4.0, 200, 25600)
        self.assertEqual([Path(e.path).name for e in entries], ["CLAUDE.md"])
        self.assertEqual(excluded, 1)

    def test_rule_with_paths_is_on_demand_and_unscoped_rule_is_always(self) -> None:
        write(self.root / ".claude" / "rules" / "scoped.md", "---\npaths:\n  - \"src/**\"\n---\nBody.\n")
        write(self.root / ".claude" / "rules" / "global.md", "---\ndescription: x\n---\nBody.\n")
        by_name = {Path(e.path).name: e for e in mcb.measure([str(self.root)], 4.0, 200, 25600)[0]}
        self.assertEqual(by_name["scoped.md"].budget, "on-demand")
        self.assertEqual(by_name["global.md"].budget, "always")

    def test_skill_counts_name_and_description_only_not_body(self) -> None:
        body = "Long procedure text that the listing never carries. " * 40
        description = "Measures a thing. Use when asked. Do NOT use for other things."
        write(
            self.root / "skills" / "demo" / "SKILL.md",
            f"---\nname: demo\ndescription: {description}\n---\n{body}\n",
        )
        entry = mcb.measure([str(self.root)], 4.0, 200, 25600)[0][0]
        self.assertEqual(entry.kind, "skill-description")
        self.assertEqual(entry.budget, "always")
        self.assertEqual(entry.effective_bytes, len(("demo\n" + description).encode("utf-8")))
        self.assertLess(entry.effective_bytes, len(body))

    def test_folded_description_is_joined(self) -> None:
        text = "---\nname: demo\ndescription: >\n  first part\n  second part\n---\nbody\n"
        fm = mcb.frontmatter(text)
        self.assertEqual(fm["description"], "first part second part")

    def test_memory_index_is_capped_at_its_line_limit(self) -> None:
        write(self.root / "memory" / "MEMORY.md", "".join(f"- line {i}\n" for i in range(300)))
        entry = mcb.measure([str(self.root)], 4.0, 200, 25600)[0][0]
        self.assertEqual(entry.kind, "memory-index")
        self.assertEqual(entry.lines, 300)
        self.assertEqual(entry.effective_lines, 200)
        self.assertLessEqual(entry.effective_bytes, 25600)

    def test_memory_topic_file_is_on_demand(self) -> None:
        write(self.root / "memory" / "topic.md", "detail\n")
        entry = mcb.measure([str(self.root)], 4.0, 200, 25600)[0][0]
        self.assertEqual((entry.kind, entry.budget), ("memory-topic", "on-demand"))

    def test_json_output_is_valid_and_summarises_always_set(self) -> None:
        write(self.root / "AGENTS.md", "Do the thing.\n")
        code, out, _ = run_main(["measure", "--json", str(self.root)])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["summary"]["always_files"], 1)
        self.assertIn("estimate", payload["summary"]["token_basis"])

    def test_empty_file_costs_nothing(self) -> None:
        write(self.root / "CLAUDE.md", "")
        entry = mcb.measure([str(self.root)], 4.0, 200, 25600)[0][0]
        self.assertEqual((entry.bytes, entry.est_tokens), (0, 0))


class VerifyMoveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.before = write(
            self.dir / "rule.md",
            "Always run the tests before committing.\n"
            "Rationale: a suite once deleted the home directory.\n"
            "Never push to main.\n",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_fully_moved_prose_passes(self) -> None:
        after = write(self.dir / "after.md", "Always run the tests before committing.\nNever push to main.\n")
        companion = write(
            self.dir / "companion.prose.md",
            "Rationale: a suite once deleted the home directory.\n",
        )
        code, out, _ = run_main(
            ["verify-move", "--before", str(self.before), "--after", str(after), "--companion", str(companion)]
        )
        self.assertEqual(code, 0)
        self.assertIn("unaccounted (lost or reworded, needs a human look): 0", out)

    def test_dropped_line_with_no_companion_copy_fails_and_is_named(self) -> None:
        # Positive control: the rationale line is deleted and not moved, so the check must fail.
        after = write(self.dir / "after.md", "Always run the tests before committing.\nNever push to main.\n")
        empty = write(self.dir / "companion.prose.md", "Unrelated note.\n")
        code, out, _ = run_main(
            ["verify-move", "--before", str(self.before), "--after", str(after), "--companion", str(empty)]
        )
        self.assertEqual(code, 1)
        self.assertIn("before line 2: Rationale: a suite once deleted the home directory.", out)

    def test_reworded_imperative_is_flagged_not_passed(self) -> None:
        # A near miss: one word changed in an imperative. Shortening is allowed only when a person checks
        # it, so the reworded line must count as unaccounted even though most of the file survived.
        after = write(
            self.dir / "after.md",
            "Always run the tests before you commit.\nRationale: a suite once deleted the home directory.\n"
            "Never push to main.\n",
        )
        empty = write(self.dir / "companion.prose.md", "Unrelated note.\n")
        code, out, _ = run_main(
            ["verify-move", "--before", str(self.before), "--after", str(after), "--companion", str(empty)]
        )
        self.assertEqual(code, 1)
        self.assertIn("before line 1:", out)

    def test_blank_line_changes_are_not_counted(self) -> None:
        after = write(
            self.dir / "after.md",
            "\n\nAlways run the tests before committing.   \n\nNever push to main.\n",
        )
        companion = write(self.dir / "c.md", "Rationale: a suite once deleted the home directory.\n")
        code, _, _ = run_main(
            ["verify-move", "--before", str(self.before), "--after", str(after), "--companion", str(companion)]
        )
        self.assertEqual(code, 0)

    def test_missing_companion_is_a_usage_error(self) -> None:
        after = write(self.dir / "after.md", "x\n")
        code, _, err = run_main(
            ["verify-move", "--before", str(self.before), "--after", str(after), "--companion", str(self.dir / "absent.md")]
        )
        self.assertEqual(code, 2)
        self.assertIn("file does not exist", err)


if __name__ == "__main__":
    unittest.main()
