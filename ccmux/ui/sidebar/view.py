"""Sidebar rendering layer — builds widgets from model snapshots."""

from textual.widgets import Static

from ccmux.ui.sidebar.model import group_by_repo
from ccmux.ui.sidebar.widgets import InstanceRow, NonInteractiveStatic, RepoHeader


def build_widgets(snapshot: list[tuple], session_name: str) -> list[Static]:
    """Build widget list from a snapshot."""
    if not snapshot:
        return [NonInteractiveStatic("  No instances", classes="dim")]

    repos = group_by_repo(snapshot)

    widgets: list[Static] = []
    repo_items = list(repos.items())
    for idx, (repo_name, repo_entries) in enumerate(repo_items):
        if idx > 0:
            widgets.append(NonInteractiveStatic("", classes="repo-spacer"))
        widgets.append(RepoHeader(f"● {repo_name}/", id=f"repo-{repo_name}"))
        for i, (_, inst_name, inst_type, is_active, is_current, alert_state) in enumerate(
            repo_entries
        ):
            widgets.append(
                InstanceRow(
                    instance_name=inst_name,
                    instance_type=inst_type,
                    is_active=is_active,
                    is_current=is_current,
                    is_last=(i == len(repo_entries) - 1),
                    session=session_name,
                    alert_state=alert_state,
                    id=f"inst-{inst_name}",
                )
            )
    return widgets
