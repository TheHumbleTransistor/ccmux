"""Tests for ccmux.git_ops branch detection functions."""

import subprocess
from pathlib import Path
from unittest.mock import patch

from ccmux.git_ops import (
    check_for_common_default_branches,
    create_worktree,
    get_default_branch,
    get_most_recently_used_branch,
    get_repo_root,
)


def _make_completed_process(stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


class TestGetDefaultBranch:
    """Tests for get_default_branch() — remote only, no fallback."""

    @patch("ccmux.git_ops.subprocess.run")
    def test_returns_branch_from_remote(self, mock_run):
        """Remote detection returns the HEAD branch."""
        mock_run.return_value = _make_completed_process(
            "* remote origin\n  HEAD branch: develop\n"
        )
        assert get_default_branch() == "develop"

    @patch("ccmux.git_ops.subprocess.run")
    def test_returns_none_on_remote_failure(self, mock_run):
        """Returns None when remote check fails (no fallback)."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        assert get_default_branch() is None


class TestCheckForCommonDefaultBranches:
    """Tests for check_for_common_default_branches()."""

    @patch("ccmux.git_ops.branch_exists")
    def test_returns_main_when_exists(self, mock_branch_exists):
        """Returns 'main' when it exists locally."""
        mock_branch_exists.side_effect = lambda name: name == "main"
        assert check_for_common_default_branches() == "main"

    @patch("ccmux.git_ops.branch_exists")
    def test_falls_back_to_master(self, mock_branch_exists):
        """Returns 'master' when 'main' doesn't exist but 'master' does."""
        mock_branch_exists.side_effect = lambda name: name == "master"
        assert check_for_common_default_branches() == "master"

    @patch("ccmux.git_ops.branch_exists")
    def test_prefers_main_over_master(self, mock_branch_exists):
        """When both 'main' and 'master' exist, prefers 'main'."""
        mock_branch_exists.return_value = True
        assert check_for_common_default_branches() == "main"

    @patch("ccmux.git_ops.branch_exists")
    def test_returns_none_when_neither_exists(self, mock_branch_exists):
        """Returns None when neither 'main' nor 'master' exists."""
        mock_branch_exists.return_value = False
        assert check_for_common_default_branches() is None


class TestGetMostRecentlyUsedBranch:
    """Tests for get_most_recently_used_branch()."""

    @patch("ccmux.git_ops.subprocess.run")
    def test_returns_most_recent_branch(self, mock_run):
        """Returns the branch with the most recent commit."""
        mock_run.return_value = _make_completed_process("feature-x\n")
        assert get_most_recently_used_branch() == "feature-x"

    @patch("ccmux.git_ops.subprocess.run")
    def test_returns_none_on_failure(self, mock_run):
        """Returns None when git command fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        assert get_most_recently_used_branch() is None

    @patch("ccmux.git_ops.subprocess.run")
    def test_returns_none_on_empty_output(self, mock_run):
        """Returns None when no branches exist."""
        mock_run.return_value = _make_completed_process("")
        assert get_most_recently_used_branch() is None


class TestGetRepoRoot:
    """Tests for get_repo_root()."""

    @patch("ccmux.git_ops.subprocess.run")
    def test_normal_repo_returns_parent_of_git_dir(self, mock_run):
        """Normal repo: --git-common-dir ends in .git, return its parent."""
        mock_run.return_value = _make_completed_process("/home/user/myrepo/.git\n")
        assert get_repo_root() == Path("/home/user/myrepo")
        # Only one call needed (no fallback)
        mock_run.assert_called_once()

    @patch("ccmux.git_ops.subprocess.run")
    def test_submodule_uses_worktree_list(self, mock_run):
        """Submodule: --git-common-dir is inside .git/modules/, use worktree list.

        When inside a submodule, --git-common-dir returns a path like
        /parent/.git/modules/dep — a real directory (not a symlink) where
        git stores the submodule's object database, refs, and config.
        Since we can't derive the working tree from that path, we fall back
        to ``git worktree list --porcelain`` whose first entry is the main
        worktree.
        """
        mock_run.side_effect = [
            # First call: --git-common-dir returns a path inside .git/modules/
            _make_completed_process("/home/user/parent/.git/modules/dep\n"),
            # Second call: worktree list returns the main worktree first
            _make_completed_process(
                "worktree /home/user/parent/dep\nHEAD abc123\nbranch refs/heads/main\n\n"
            ),
        ]
        assert get_repo_root() == Path("/home/user/parent/dep")
        assert mock_run.call_count == 2
        # Verify the fallback call uses worktree list
        assert mock_run.call_args_list[1][0][0] == [
            "git", "worktree", "list", "--porcelain",
        ]

    @patch("ccmux.git_ops.subprocess.run")
    def test_submodule_worktree_uses_main_worktree(self, mock_run):
        """Worktree of a submodule: returns the submodule's main worktree root.

        When inside a linked worktree created from a submodule,
        --git-common-dir still points to .git/modules/dep, and
        --show-toplevel would incorrectly return the linked worktree's root.
        ``git worktree list`` always lists the main worktree first, so we
        get the correct submodule root.
        """
        mock_run.side_effect = [
            # --git-common-dir still points inside .git/modules/
            _make_completed_process("/home/user/parent/.git/modules/dep\n"),
            # worktree list: main worktree is first, linked worktree second
            _make_completed_process(
                "worktree /home/user/parent/dep\nHEAD abc123\nbranch refs/heads/main\n\n"
                "worktree /home/user/parent/dep/.ccmux/worktrees/duck\nHEAD abc123\ndetached\n\n"
            ),
        ]
        assert get_repo_root() == Path("/home/user/parent/dep")
        assert mock_run.call_count == 2

    @patch("ccmux.git_ops.subprocess.run")
    def test_returns_none_on_failure(self, mock_run):
        """Returns None when git command fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        assert get_repo_root() is None


class TestCreateWorktree:
    """Tests for create_worktree()."""

    @patch("ccmux.git_ops.subprocess.run")
    def test_create_worktree_uses_C_flag(self, mock_run):
        """create_worktree passes -C repo_path to git."""
        repo = Path("/home/user/myrepo")
        wt = Path("/home/user/myrepo/.ccmux/worktrees/duck")
        create_worktree(repo, wt, "HEAD")
        mock_run.assert_called_once_with(
            ["git", "-C", str(repo), "worktree", "add", "--detach", str(wt), "HEAD"],
            check=True,
        )
