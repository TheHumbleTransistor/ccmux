"""Tests for ccmux.git_ops branch detection functions."""

import subprocess
from pathlib import Path
from unittest.mock import patch

from ccmux.git_ops import (
    check_for_common_default_branches,
    checkout_detached,
    create_worktree,
    discard_all_changes,
    fetch_origin,
    get_default_branch,
    get_most_recently_used_branch,
    get_repo_root,
    get_worktree_root,
    is_bare_repo,
    remote_ref_exists,
    stash_changes,
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

    @patch("ccmux.git_ops.Path.exists", return_value=True)
    @patch("ccmux.git_ops.subprocess.run")
    def test_bare_repo_returns_project_root(self, mock_run, mock_exists):
        """Bare repo topology: returns the project root, not the .bare dir.

        When --git-common-dir returns a path like /project/.bare (not .git),
        and ``git worktree list`` marks the first entry as ``bare``, the
        project root is the parent of the bare git directory.
        """
        mock_run.side_effect = [
            _make_completed_process("/home/user/project/.bare\n"),
            _make_completed_process(
                "worktree /home/user/project/.bare\nbare\n\n"
                "worktree /home/user/project/main\nHEAD abc123\n"
                "branch refs/heads/main\n\n"
            ),
        ]
        assert get_repo_root() == Path("/home/user/project")
        assert mock_run.call_count == 2

    @patch("ccmux.git_ops.Path.exists", return_value=True)
    @patch("ccmux.git_ops.subprocess.run")
    def test_bare_repo_from_worktree(self, mock_run, mock_exists):
        """Bare repo from inside a worktree still returns the project root.

        Git resolves through the worktree to the shared bare repo, so
        --git-common-dir returns the same .bare path regardless of cwd.
        """
        mock_run.side_effect = [
            _make_completed_process("/home/user/project/.bare\n"),
            _make_completed_process(
                "worktree /home/user/project/.bare\nbare\n\n"
                "worktree /home/user/project/main\nHEAD abc123\n"
                "branch refs/heads/main\n\n"
            ),
        ]
        assert get_repo_root() == Path("/home/user/project")

    @patch("ccmux.git_ops.Path.exists", return_value=False)
    @patch("ccmux.git_ops.subprocess.run")
    def test_bare_repo_without_git_redirect_falls_back(self, mock_run, mock_exists):
        """Bare repo without .git at parent falls back to first worktree path.

        Standalone bare repos (no .git redirect file) should not crash.
        """
        mock_run.side_effect = [
            _make_completed_process("/some/bare-repo.git\n"),
            _make_completed_process(
                "worktree /some/bare-repo.git\nbare\n\n"
            ),
        ]
        assert get_repo_root() == Path("/some/bare-repo.git")


class TestGetWorktreeRoot:
    """Tests for get_worktree_root()."""

    @patch("ccmux.git_ops.subprocess.run")
    def test_returns_worktree_root(self, mock_run):
        """Returns the worktree root when inside a worktree."""
        mock_run.return_value = _make_completed_process("/home/user/project/main\n")
        assert get_worktree_root(Path("/home/user/project/main/src")) == Path("/home/user/project/main")

    @patch("ccmux.git_ops.subprocess.run")
    def test_returns_none_at_bare_root(self, mock_run):
        """Returns None when at a bare repo root (not a worktree)."""
        mock_run.side_effect = subprocess.CalledProcessError(128, "git")
        assert get_worktree_root(Path("/home/user/project")) is None

    @patch("ccmux.git_ops.subprocess.run")
    def test_returns_none_outside_repo(self, mock_run):
        """Returns None when outside any git repo."""
        mock_run.side_effect = subprocess.CalledProcessError(128, "git")
        assert get_worktree_root(Path("/tmp")) is None


class TestIsBareRepo:
    """Tests for is_bare_repo()."""

    @patch("ccmux.git_ops.subprocess.run")
    def test_returns_true_for_bare_repo(self, mock_run):
        """Returns True when git reports bare repository."""
        mock_run.return_value = _make_completed_process("true\n")
        assert is_bare_repo(Path("/home/user/project")) is True

    @patch("ccmux.git_ops.subprocess.run")
    def test_returns_false_for_normal_repo(self, mock_run):
        """Returns False for a normal (non-bare) repository."""
        mock_run.return_value = _make_completed_process("false\n")
        assert is_bare_repo(Path("/home/user/project")) is False

    @patch("ccmux.git_ops.subprocess.run")
    def test_returns_false_on_failure(self, mock_run):
        """Returns False when git command fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        assert is_bare_repo(Path("/home/user/project")) is False

    @patch("ccmux.git_ops.subprocess.run")
    def test_project_root_bare_topology_detected(self, mock_run, tmp_path):
        """Project root with .git redirect to .bare is detected as bare."""
        # Create a .git redirect file at tmp_path
        (tmp_path / ".git").write_text("gitdir: .bare")

        mock_run.side_effect = [
            # First call: --is-bare-repository returns false (project root)
            _make_completed_process("false\n"),
            # Second call: --git-common-dir returns the .bare path
            _make_completed_process(str(tmp_path / ".bare") + "\n"),
            # Third call: --is-bare-repository on .bare returns true
            _make_completed_process("true\n"),
        ]
        assert is_bare_repo(tmp_path) is True

    @patch("ccmux.git_ops.subprocess.run")
    def test_project_root_non_bare_common_dir(self, mock_run, tmp_path):
        """Project root with .git redirect to non-bare dir returns False."""
        (tmp_path / ".git").write_text("gitdir: .worktrees/main")

        mock_run.side_effect = [
            _make_completed_process("false\n"),
            _make_completed_process(str(tmp_path / ".worktrees" / "main") + "\n"),
            _make_completed_process("false\n"),
        ]
        assert is_bare_repo(tmp_path) is False

    @patch("ccmux.git_ops.subprocess.run")
    def test_no_git_redirect_file_returns_false(self, mock_run, tmp_path):
        """Normal repo without .git redirect file returns False after first check."""
        # .git is a directory, not a file
        (tmp_path / ".git").mkdir()

        mock_run.return_value = _make_completed_process("false\n")
        assert is_bare_repo(tmp_path) is False
        # Only the first --is-bare-repository call should be made
        assert mock_run.call_count == 1


class TestResetHelpers:
    """Tests for fetch_origin, discard_all_changes, stash_changes,
    checkout_detached, and remote_ref_exists."""

    @patch("ccmux.git_ops.subprocess.run")
    def test_fetch_origin_uses_C_flag(self, mock_run):
        wt = Path("/wt/path")
        fetch_origin(wt)
        mock_run.assert_called_once_with(
            ["git", "-C", str(wt), "fetch", "origin"],
            check=True, capture_output=True, text=True,
        )

    @patch("ccmux.git_ops.subprocess.run")
    def test_discard_runs_reset_then_clean(self, mock_run):
        wt = Path("/wt/path")
        discard_all_changes(wt)
        assert mock_run.call_count == 2
        assert mock_run.call_args_list[0][0][0] == [
            "git", "-C", str(wt), "reset", "--hard", "HEAD",
        ]
        assert mock_run.call_args_list[1][0][0] == [
            "git", "-C", str(wt), "clean", "-fd",
        ]

    @patch("ccmux.git_ops.subprocess.run")
    def test_stash_uses_include_untracked_and_label(self, mock_run):
        wt = Path("/wt/path")
        stash_changes(wt, "ccmux reset foo")
        mock_run.assert_called_once_with(
            ["git", "-C", str(wt), "stash", "push", "-u", "-m", "ccmux reset foo"],
            check=True, capture_output=True, text=True,
        )

    @patch("ccmux.git_ops.subprocess.run")
    def test_checkout_detached_passes_ref(self, mock_run):
        wt = Path("/wt/path")
        checkout_detached(wt, "origin/main")
        mock_run.assert_called_once_with(
            ["git", "-C", str(wt), "checkout", "--detach", "origin/main"],
            check=True, capture_output=True, text=True,
        )

    @patch("ccmux.git_ops.subprocess.run")
    def test_remote_ref_exists_true(self, mock_run):
        mock_run.return_value = _make_completed_process("")
        assert remote_ref_exists(Path("/wt"), "origin/main") is True

    @patch("ccmux.git_ops.subprocess.run")
    def test_remote_ref_exists_false(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        assert remote_ref_exists(Path("/wt"), "origin/missing") is False


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
