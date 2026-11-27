"""Tests for worktree_report.py. Every repository is built at run time in a temporary directory.

Run inside a sandbox (for example a bubblewrap wrapper) for test runs, from a directory inside the repository:
    python3 -P claude-skills-ai-engineering/skills/parallel-worktree-integration/scripts/test_worktree_report.py -v
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "worktree_report.py"
sys.path.insert(0, str(SCRIPT.parent))

import worktree_report as wr  # noqa: E402

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), env=ENV, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout


def commit_file(repo: Path, name: str, text: str, message: str) -> str:
    (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", "--", name)
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


def run_report(repo: Path, here: Path | None = None, base: str = "main", prefix: str = "") -> tuple[int, str]:
    out = io.StringIO()
    previous = Path.cwd()
    try:
        if here is not None:
            os.chdir(here)
        with contextlib.redirect_stdout(out):
            code = wr.run(repo.resolve(), base, prefix, Path.cwd().resolve())
    finally:
        os.chdir(previous)
    return code, out.getvalue()


def row(output: str, name: str) -> str:
    for line in output.splitlines():
        if line.startswith(f"{name} ") or line.startswith(f"{name}\t"):
            return line
    raise AssertionError(f"no row for {name} in:\n{output}")


class WorktreeReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        commit_file(self.repo, "README.md", "base\n", "chore: base")
        self.wt_dir = self.root / "wt"
        self.wt_dir.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def add(self, name: str, branch: str | None = None, detach: bool = False) -> Path:
        path = self.wt_dir / name
        if detach:
            git(self.repo, "worktree", "add", "--detach", str(path), "main")
        else:
            git(self.repo, "worktree", "add", "-b", branch or name, str(path), "main")
        return path

    def test_branch_with_no_new_commits_is_merged_and_safe(self) -> None:
        self.add("wt-merged")
        code, out = run_report(self.repo)
        self.assertEqual(code, 0)
        self.assertIn("merged", row(out, "wt-merged"))
        self.assertIn("would remove (merged): git worktree remove", out)

    def test_cherry_picked_work_is_applied_not_unmerged(self) -> None:
        # The same patch lands on the base under a new SHA. Judging by SHA alone would call this unmerged.
        path = self.add("wt-applied")
        sha = commit_file(path, "feature.txt", "feature\n", "feat: add feature")
        git(self.repo, "cherry-pick", sha)
        code, out = run_report(self.repo)
        self.assertEqual(code, 0, out)
        self.assertIn("applied", row(out, "wt-applied"))

    def test_unique_commit_is_unmerged_and_needs_action(self) -> None:
        path = self.add("wt-unique")
        commit_file(path, "only-here.txt", "x\n", "feat: only on branch")
        code, out = run_report(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("unmerged", row(out, "wt-unique"))
        self.assertIn("needs a look: wt-unique (unmerged)", out)
        self.assertNotIn("would remove (unmerged)", out)

    def test_dirty_worktree_is_flagged_and_not_removable(self) -> None:
        path = self.add("wt-dirty")
        (path / "scratch.txt").write_text("not committed\n", encoding="utf-8")
        code, out = run_report(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("dirty", row(out, "wt-dirty"))
        self.assertNotIn("would remove (merged): git worktree remove", out)

    def test_detached_head_needs_a_look(self) -> None:
        self.add("wt-detached", detach=True)
        code, out = run_report(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("detached", row(out, "wt-detached"))

    def test_deleted_directory_is_missing_and_points_at_prune(self) -> None:
        path = self.add("wt-gone")
        shutil.rmtree(path)
        code, out = run_report(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("missing", row(out, "wt-gone"))
        self.assertIn("git worktree prune", out)

    def test_locked_worktree_is_never_offered_for_removal(self) -> None:
        self.add("wt-locked")
        git(self.repo, "worktree", "lock", str(self.wt_dir / "wt-locked"))
        code, out = run_report(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("locked", row(out, "wt-locked"))
        self.assertNotIn("would remove", out)

    def test_worktree_inside_checkout_without_ignore_rule_is_exposed(self) -> None:
        # Positive control for the trap: the path shows as untracked in the main checkout.
        inside = self.repo / ".worktrees" / "wt-exposed"
        git(self.repo, "worktree", "add", "-b", "wt-exposed", str(inside), "main")
        code, out = run_report(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("exposed", row(out, "wt-exposed"))

    def test_same_worktree_is_not_exposed_once_ignored(self) -> None:
        # The fix: an ignore rule for the folder, committed, clears the flag.
        (self.repo / ".gitignore").write_text(".worktrees/\n", encoding="utf-8")
        git(self.repo, "add", "--", ".gitignore")
        git(self.repo, "commit", "-m", "chore: ignore worktrees")
        inside = self.repo / ".worktrees" / "wt-ok"
        git(self.repo, "worktree", "add", "-b", "wt-ok", str(inside), "main")
        code, out = run_report(self.repo)
        self.assertEqual(code, 0, out)
        self.assertNotIn("exposed", row(out, "wt-ok"))

    def test_stash_is_shared_across_worktrees(self) -> None:
        # The trap, demonstrated: a stash made in one worktree is listed from the main checkout.
        path = self.add("wt-stasher")
        (path / "README.md").write_text("changed\n", encoding="utf-8")
        git(path, "stash", "push", "-m", "from wt-stasher")
        code, out = run_report(self.repo)
        self.assertIn("stash entries (shared by every worktree of this repository): 1", out)

    def test_inside_flag_when_started_from_the_worktree(self) -> None:
        path = self.add("wt-here")
        code, out = run_report(self.repo, here=path)
        self.assertEqual(code, 0)
        self.assertIn("inside", row(out, "wt-here"))
        self.assertNotIn("would remove (merged): git worktree remove", out)

    def test_prefix_filter_limits_the_report(self) -> None:
        self.add("wt-keep")
        self.add("other-skip")
        _, out = run_report(self.repo, prefix="wt-")
        self.assertIn("wt-keep", out)
        self.assertNotIn("other-skip", out)

    def test_missing_base_branch_is_a_usage_error(self) -> None:
        self.add("wt-a")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = wr.main(["-C", str(self.repo), "-b", "no-such-branch"])
        self.assertEqual(code, 2)
        self.assertIn("error:", err.getvalue())

    def test_no_linked_worktrees_is_clean(self) -> None:
        code, out = run_report(self.repo)
        self.assertEqual(code, 0)
        self.assertIn("linked worktrees considered: 0", out)


if __name__ == "__main__":
    unittest.main()
