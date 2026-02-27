"""Git subprocess wrappers for ccmux."""

import subprocess
from pathlib import Path
from typing import Optional


def get_repo_root() -> Optional[Path]:
    """Get the main git repository root directory.

    Uses --git-common-dir to resolve through linked worktrees to the main repo,
    so this always returns the root of the main worktree even when called from
    inside a linked worktree.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
        git_common_dir = Path(result.stdout.strip())
        return git_common_dir.parent
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_default_branch() -> Optional[str]:
    """Get the default branch name from the remote origin."""
    try:
        result = subprocess.run(
            ["git", "remote", "show", "origin"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.split("\n"):
            if "HEAD branch:" in line:
                return line.split(":")[-1].strip()
    except subprocess.CalledProcessError:
        pass
    return None


def check_for_common_default_branches() -> Optional[str]:
    """Check for common default branch names (main, master) locally."""
    for name in ("main", "master"):
        if branch_exists(name):
            return name
    return None


def get_most_recently_used_branch() -> Optional[str]:
    """Get the branch with the most recent commit."""
    try:
        result = subprocess.run(
            ["git", "for-each-ref", "--sort=-committerdate",
             "--format=%(refname:short)", "refs/heads/", "--count=1"],
            capture_output=True,
            text=True,
            check=True,
        )
        branch = result.stdout.strip()
        if branch:
            return branch
    except subprocess.CalledProcessError:
        pass
    return None


def worktree_exists(worktree_path: Path, repo_path: Path | None = None) -> bool:
    """Check if a worktree exists and is registered."""
    try:
        cmd = ["git"]
        if repo_path:
            cmd += ["-C", str(repo_path)]
        cmd += ["worktree", "list"]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        return str(worktree_path) in result.stdout
    except subprocess.CalledProcessError:
        return False


def branch_exists(branch_name: str) -> bool:
    """Check if a git branch exists."""
    try:
        subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def get_all_worktrees(repo_root: Path) -> list[dict[str, str]]:
    """Get all worktrees in the .worktrees directory.

    Returns a list of dicts with keys: name, path, branch
    """
    worktrees_dir = repo_root / ".worktrees"
    if not worktrees_dir.exists():
        return []

    worktrees = []
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        current_worktree = {}
        for line in result.stdout.split("\n"):
            if line.startswith("worktree "):
                if current_worktree:
                    worktrees.append(current_worktree)
                current_worktree = {"path": line[9:]}
            elif line.startswith("branch "):
                current_worktree["branch"] = line[7:].replace("refs/heads/", "")
            elif line.startswith("detached"):
                current_worktree["branch"] = "(detached)"

        if current_worktree:
            worktrees.append(current_worktree)

        filtered = []
        for wt in worktrees:
            path = Path(wt["path"])
            if path.parent == worktrees_dir:
                wt["name"] = path.name
                filtered.append(wt)
        return filtered
    except subprocess.CalledProcessError:
        return []


def create_worktree(repo_path: Path, worktree_path: Path, base_ref: str) -> None:
    """Create a detached git worktree from a base ref."""
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree_path), base_ref],
        check=True,
    )


def move_worktree(repo_path: Path, old_path: Path, new_path: Path) -> None:
    """Move a git worktree to a new location."""
    subprocess.run(
        ["git", "-C", str(repo_path), "worktree", "move", str(old_path), str(new_path)],
        check=True, capture_output=True, text=True,
    )


def remove_worktree(repo_path: Path, worktree_path: Path) -> None:
    """Remove a git worktree (force)."""
    subprocess.run(
        ["git", "-C", str(repo_path), "worktree", "remove", "--force", str(worktree_path)],
        check=True,
    )


def worktree_status(worktree_path: Path) -> list[str]:
    """Check for uncommitted changes in a worktree path.

    Returns a list of dirty file lines (from git status --porcelain),
    or an empty list if the worktree is clean.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(worktree_path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        return [line for line in result.stdout.strip().split("\n") if line]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def get_branch_name(path: str) -> str:
    """Get the current branch name for a git working directory."""
    try:
        result = subprocess.run(
            ["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "(unknown)"
