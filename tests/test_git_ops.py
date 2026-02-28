"""Tests for ccmux.git_ops branch detection functions."""

import subprocess
from pathlib import Path
from unittest.mock import call, patch

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
    def test_submodule_falls_back_to_show_toplevel(self, mock_run):
        """Submodule: --git-common-dir is inside .git/modules/, fall back to --show-toplevel."""
        mock_run.side_effect = [
            # First call: --git-common-dir returns a path inside .git/modules/
            _make_completed_process("/home/user/parent/.git/modules/dependencies\n"),
            # Second call: --show-toplevel returns the submodule working tree
            _make_completed_process("/home/user/parent/dependencies\n"),
        ]
        assert get_repo_root() == Path("/home/user/parent/dependencies")
        assert mock_run.call_count == 2
        # Verify the fallback call uses --show-toplevel
        assert "--show-toplevel" in mock_run.call_args_list[1][0][0]

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
