"""Backward-compatibility shim -- real code lives in ccmux.ui."""

from ccmux.ui import (  # noqa: F401
    SidebarApp,
    NonInteractiveStatic,
    InstanceRow,
    RepoHeader,
    SIDEBAR_PIDS_DIR,
    write_pid_file,
    remove_pid_file,
)
from ccmux.ui.app import main

if __name__ == "__main__":
    main()
