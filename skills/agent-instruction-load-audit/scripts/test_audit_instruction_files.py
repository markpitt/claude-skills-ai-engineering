#!/usr/bin/env python3
"""Tests for audit_instruction_files.py. Run them wrapped:

    python3 -P claude-skills-ai-engineering/skills/agent-instruction-load-audit/scripts/test_audit_instruction_files.py -v

Run it through the repository's sandbox wrapper for test runs, if it has one.

Every fixture is generated at test time inside a temporary directory. Each error case has a
matching clean case in the same test run, so a check that never fires cannot pass as green.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "audit_instruction_files.py"

EXIT_CLEAN, EXIT_FINDINGS, EXIT_NO_YAML = 0, 1, 3

GOOD_SKILL = """---
name: {name}
description: Does one thing. Use when the user asks for that thing. Do NOT use for other things.
---

# {name}
"""


class AuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_audit(self, *args: str, root: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-P", str(SCRIPT), *args, str(root or self.root)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    def test_clean_tree_passes_and_scan_really_ran(self) -> None:
        self.write("CLAUDE.md", "# Project rules\n\nUse British English.\n")
        self.write(".claude/rules/style.md", "# Style\n\nNo em dashes.\n")
        self.write(".claude/skills/alpha/SKILL.md", GOOD_SKILL.format(name="alpha"))
        result = self.run_audit()
        self.assertEqual(result.returncode, EXIT_CLEAN, result.stdout + result.stderr)
        # Positive control: the scan found the files, so a zero-error result is not an empty scan.
        self.assertIn("CLAUDE.md", result.stdout)
        self.assertIn("style.md", result.stdout)
        self.assertIn("alpha/SKILL.md", result.stdout)
        self.assertIn("0 error(s)", result.stdout)

    def test_skill_name_must_match_directory(self) -> None:
        self.write(".claude/skills/beta/SKILL.md", GOOD_SKILL.format(name="gamma"))
        result = self.run_audit()
        self.assertEqual(result.returncode, EXIT_FINDINGS)
        self.assertIn("ERROR", result.stdout)
        self.assertIn("does not match directory", result.stdout)

    def test_overlong_description_is_an_error(self) -> None:
        long_description = "x" * 1100
        self.write(".claude/skills/delta/SKILL.md", f"---\nname: delta\ndescription: {long_description}\n---\n")
        result = self.run_audit()
        self.assertEqual(result.returncode, EXIT_FINDINGS)
        self.assertIn("1024", result.stdout)

    def test_duplicate_frontmatter_key_is_an_error(self) -> None:
        text = "---\nname: epsilon\ndescription: First. Use when x. Do NOT use for y.\ndescription: Second.\n---\n"
        self.write(".claude/skills/epsilon/SKILL.md", text)
        result = self.run_audit()
        self.assertEqual(result.returncode, EXIT_FINDINGS)
        self.assertIn("duplicate", result.stdout)
        self.assertIn("description", result.stdout)

    def test_yaml_syntax_error_is_an_error(self) -> None:
        self.write(".claude/skills/zeta/SKILL.md", "---\nname: zeta\ndescription: [unclosed\n---\n")
        result = self.run_audit()
        self.assertEqual(result.returncode, EXIT_FINDINGS)
        self.assertIn("not valid YAML", result.stdout)

    def test_missing_frontmatter_on_a_skill_is_an_error(self) -> None:
        self.write(".claude/skills/eta/SKILL.md", "# No frontmatter here\n")
        result = self.run_audit()
        self.assertEqual(result.returncode, EXIT_FINDINGS)
        self.assertIn("no YAML frontmatter", result.stdout)

    def test_broken_symlink_is_an_error(self) -> None:
        skills = self.root / ".claude" / "skills"
        skills.mkdir(parents=True)
        os.symlink(str(Path(self._tmp.name) / "does-not-exist"), skills / "theta")
        result = self.run_audit()
        self.assertEqual(result.returncode, EXIT_FINDINGS)
        self.assertIn("broken symlink", result.stdout)

    def test_working_symlink_is_reported_not_an_error(self) -> None:
        target = Path(self._tmp.name) / "shared-skill"
        target.mkdir()
        (target / "SKILL.md").write_text(GOOD_SKILL.format(name="iota"), encoding="utf-8")
        skills = self.root / ".claude" / "skills"
        skills.mkdir(parents=True)
        os.symlink(str(target), skills / "iota")
        result = self.run_audit()
        self.assertEqual(result.returncode, EXIT_CLEAN, result.stdout + result.stderr)
        self.assertIn("symlink", result.stdout)

    def test_applies_to_in_a_claude_rule_is_a_warning(self) -> None:
        self.write(".claude/rules/scoped.md", "---\napplyTo: \"**/*.ts\"\n---\n\nRule text.\n")
        lenient = self.run_audit()
        self.assertEqual(lenient.returncode, EXIT_CLEAN, lenient.stdout)
        self.assertIn("applyTo", lenient.stdout)
        self.assertIn("WARN", lenient.stdout)
        strict = self.run_audit("--strict")
        self.assertEqual(strict.returncode, EXIT_FINDINGS, "--strict must turn warnings into a failing exit")

    def test_agents_and_claude_in_one_directory_is_flagged(self) -> None:
        self.write("CLAUDE.md", "# Manual\n")
        self.write("AGENTS.md", "# Signpost\n")
        result = self.run_audit()
        self.assertEqual(result.returncode, EXIT_CLEAN, result.stdout)
        self.assertIn("both", result.stdout)
        self.assertIn("AGENTS.md", result.stdout)

    def test_override_shadows_agents_in_same_directory(self) -> None:
        self.write("AGENTS.md", "# Base\n")
        self.write("AGENTS.override.md", "# Override\n")
        result = self.run_audit()
        self.assertEqual(result.returncode, EXIT_CLEAN, result.stdout)
        self.assertIn("shadow", result.stdout)

    def test_json_output_lists_kinds_and_findings(self) -> None:
        self.write("CLAUDE.md", "# Manual\n")
        self.write(".claude/skills/kappa/SKILL.md", GOOD_SKILL.format(name="kappa"))
        result = self.run_audit("--json")
        self.assertEqual(result.returncode, EXIT_CLEAN, result.stderr)
        data = json.loads(result.stdout)
        kinds = {entry["kind"] for entry in data["files"]}
        self.assertIn("claude-md", kinds)
        self.assertIn("skill", kinds)
        self.assertEqual(data["summary"]["errors"], 0)

    def test_missing_yaml_fails_loudly_not_clean(self) -> None:
        self.write(".claude/skills/lambda/SKILL.md", GOOD_SKILL.format(name="lambda"))
        probe = (
            "import runpy, sys\n"
            "sys.modules['yaml'] = None\n"
            "sys.argv = [sys.argv[1], sys.argv[2]]\n"
            "runpy.run_path(sys.argv[0], run_name='__main__')\n"
        )
        result = subprocess.run(
            [sys.executable, "-P", "-c", probe, str(SCRIPT), str(self.root)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(result.returncode, EXIT_NO_YAML, result.stdout + result.stderr)
        self.assertIn("PyYAML", result.stderr)


if __name__ == "__main__":
    unittest.main()
