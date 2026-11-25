#!/usr/bin/env python3
"""Report the state of every linked git worktree against a base branch. Read-only.

Standard library only (Python 3.12). Nothing is changed: no checkout, stash, branch, worktree or
tag is created, moved or removed. The script prints the commands that a person could run, and
does not run them.

Verdicts per linked worktree:
  merged    every commit on the branch is already reachable from the base
  applied   the branch has commits the base lacks by SHA, but every one has an equivalent patch on
            the base (git cherry marks them "-"). Typical after a cherry-pick or a rebase.
  unmerged  at least one commit's patch is not on the base. Work would be lost by removing it.
  detached  the worktree has no branch checked out
  missing   the directory is gone; `git worktree prune` clears the record
  base      the worktree has the base branch checked out itself

Flags, each independent of the verdict:
  dirty     uncommitted changes in the worktree
  locked    the worktree is locked (git worktree lock)
  inside    this script was started from inside the worktree
  exposed   the worktree sits inside the main checkout and its path is NOT ignored there, so it
            shows as untracked in the main checkout and `git add -A` would take it in

Exit codes: 0 nothing needs action; 1 at least one worktree needs action; 2 usage error or a
repository or base branch that does not exist.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Worktree:
    path: Path
    branch: str | None = None
    detached: bool = False
    locked: bool = False
    prunable: bool = False
    head: str = ""
    verdict: str = ""
    unique_commits: int = 0
    dirty: bool = False
    inside: bool = False
    exposed: bool = False
    flags: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def safe_to_remove(self) -> bool:
        return (
            self.verdict in ("merged", "applied")
            and not self.dirty
            and not self.locked
            and not self.inside
            and not self.exposed
        )

    @property
    def needs_action(self) -> bool:
        return (
            self.verdict in ("unmerged", "detached", "missing")
            or self.dirty
            or self.locked
            or self.exposed
        )


class GitError(RuntimeError):
    pass


def git(cwd: Path, *args: str, ok_codes: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in ok_codes:
        raise GitError(f"git {' '.join(args)} failed in {cwd} (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc


def parse_porcelain(text: str) -> list[Worktree]:
    """Parse `git worktree list --porcelain`. Blocks are separated by blank lines."""
    worktrees: list[Worktree] = []
    current: dict[str, str] = {}
    blocks: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line:
            if current:
                blocks.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        blocks.append(current)
    for block in blocks:
        branch = block.get("branch")
        worktrees.append(
            Worktree(
                path=Path(block["worktree"]),
                branch=branch.removeprefix("refs/heads/") if branch else None,
                detached="detached" in block,
                locked="locked" in block,
                prunable="prunable" in block,
                head=block.get("HEAD", ""),
            )
        )
    return worktrees


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def classify(repo: Path, base: str, wt: Worktree, here: Path) -> None:
    wt.inside = is_inside(here, wt.path) if wt.path.exists() else False
    if wt.prunable or not wt.path.exists():
        wt.verdict = "missing"
        return
    if wt.branch == base:
        wt.verdict = "base"
    elif wt.detached or wt.branch is None:
        wt.verdict = "detached"
    else:
        ahead = git(repo, "rev-list", "--count", f"{base}..{wt.branch}").stdout.strip()
        if ahead == "0":
            wt.verdict = "merged"
        else:
            cherry = git(repo, "cherry", base, wt.branch).stdout.splitlines()
            plus = [line for line in cherry if line.startswith("+")]
            wt.unique_commits = len(plus)
            wt.verdict = "applied" if not plus else "unmerged"
    status = git(wt.path, "status", "--porcelain").stdout
    wt.dirty = bool(status.strip())


def check_exposed(repo: Path, main: Path, wt: Worktree) -> None:
    """A linked worktree inside the main checkout must be ignored there, or it shows as untracked."""
    if not is_inside(wt.path, main) or wt.path.resolve() == main.resolve():
        return
    rel = wt.path.resolve().relative_to(main.resolve()).as_posix()
    proc = git(repo, "check-ignore", "-q", "--", rel, ok_codes=(0, 1))
    wt.exposed = proc.returncode == 1


def suggest(wt: Worktree) -> str:
    if wt.verdict == "missing":
        return "git worktree prune"
    if wt.branch is None:
        return f"git worktree remove {wt.path}"
    flag = "-d" if wt.verdict == "merged" else "-D"
    return f"git worktree remove {wt.path} && git branch {flag} {wt.branch}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-C", "--repo", type=Path, default=Path.cwd(), help="repository (default: current directory)")
    p.add_argument("-b", "--base", default="main", help="base branch the work must be on (default: main)")
    p.add_argument("--prefix", default="", help="only report worktrees whose name or branch starts with this")
    return p


def run(repo: Path, base: str, prefix: str, here: Path) -> int:
    top = Path(git(repo, "rev-parse", "--show-toplevel").stdout.strip())
    git(top, "rev-parse", "--verify", "--quiet", f"refs/heads/{base}", ok_codes=(0,))
    listing = git(top, "worktree", "list", "--porcelain").stdout
    entries = parse_porcelain(listing)
    # git lists the main worktree first, whichever linked worktree this command was started in.
    main = entries[0].path
    linked = entries[1:]
    if prefix:
        linked = [wt for wt in linked if wt.name.startswith(prefix) or (wt.branch or "").startswith(prefix)]

    for wt in linked:
        classify(top, base, wt, here)
        check_exposed(top, main, wt)

    print(f"repository: {top}")
    print(f"base: {base}; linked worktrees considered: {len(linked)}")
    stash = git(top, "stash", "list").stdout.splitlines()
    print(f"stash entries (shared by every worktree of this repository): {len(stash)}")
    print()
    header = f"{'name':<22} {'branch':<26} {'verdict':<9} {'unique':>6}  flags"
    print(header)
    for wt in linked:
        flags = [f for f, on in (("dirty", wt.dirty), ("locked", wt.locked), ("inside", wt.inside), ("exposed", wt.exposed)) if on]
        print(f"{wt.name:<22} {(wt.branch or '(detached)'):<26} {wt.verdict:<9} {wt.unique_commits:>6}  {','.join(flags) or '-'}")
    print()
    for wt in linked:
        if wt.safe_to_remove and wt.verdict == "merged":
            print(f"would remove (merged): {suggest(wt)}")
        elif wt.safe_to_remove:
            print(f"review git cherry first, then remove ({wt.verdict}): {suggest(wt)}")
        elif wt.needs_action:
            print(f"needs a look: {wt.name} ({wt.verdict}) - {suggest(wt)}")
    print("nothing was run: copy a command after reading its verdict")
    return 1 if any(wt.needs_action for wt in linked) else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args.repo.resolve(), args.base, args.prefix, Path.cwd().resolve())
    except GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
