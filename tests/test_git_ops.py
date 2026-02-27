"""Tests for ccmux.git_ops branch detection functions."""

import subprocess
from unittest.mock import patch

from ccmux.git_ops import (
    check_for_common_default_branches,
    get_default_branch,
    get_most_recently_used_branch,
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
