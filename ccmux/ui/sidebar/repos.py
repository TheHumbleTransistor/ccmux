"""Repo discovery for the sidebar's new-session panel (no Textual imports)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ccmux import state
from ccmux.config import get_workspace_dirs


@dataclass(frozen=True, slots=True)
class RepoCandidate:
    path: str
    name: str
    display: str
    has_session: bool


def looks_like_repo(path: Path) -> bool:
    """Cheap filesystem check for a git repo: a .git entry or a bare layout."""
    if (path / ".git").exists():
        return True
    return (path / "HEAD").is_file() and (path / "objects").is_dir() and (path / "refs").is_dir()


def resolve_workspace_dirs() -> list[Path]:
    """Configured workspace dirs, or the parents of known session repos when unset."""
    dirs = get_workspace_dirs()
    if dirs:
        return dirs
    for sess in state.get_all_sessions():
        parent = Path(sess.repo_path).parent
        if parent.is_dir() and parent not in dirs:
            dirs.append(parent)
    return dirs


def discover_repos(
    workspace_dirs: Iterable[Path], known_repo_paths: Iterable[str],
) -> list[RepoCandidate]:
    """Repos one level under each workspace dir plus known repos, sorted by name."""
    known = {str(Path(p)) for p in known_repo_paths}
    found: dict[str, Path] = {}
    for workspace in workspace_dirs:
        try:
            children = sorted(Path(workspace).iterdir())
        except OSError:
            continue
        for child in children:
            if child.name.startswith("."):
                continue
            if child.is_dir() and looks_like_repo(child):
                found.setdefault(str(child), child)
    for path in known:
        found.setdefault(path, Path(path))
    name_counts = Counter(path.name for path in found.values())
    candidates = [
        RepoCandidate(
            path=key,
            name=path.name,
            display=path.name if name_counts[path.name] == 1 else f"{path.name}  ({path.parent})",
            has_session=key in known,
        )
        for key, path in found.items()
    ]
    candidates.sort(key=lambda c: c.name.lower())
    return candidates


def filter_repos(candidates: Iterable[RepoCandidate], query: str) -> list[RepoCandidate]:
    """Candidates whose name contains query, case-insensitively; all when query is blank."""
    needle = query.strip().lower()
    if not needle:
        return list(candidates)
    return [c for c in candidates if needle in c.name.lower()]


def resolve_typed_path(text: str) -> str | None:
    """Return the expanded path if text names an existing absolute (or ~) directory."""
    stripped = text.strip()
    if not stripped:
        return None
    path = Path(stripped).expanduser()
    if path.is_absolute() and path.is_dir():
        return str(path)
    return None
