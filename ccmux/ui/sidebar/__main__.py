"""Allow running sidebar as a module: python -m ccmux.ui.sidebar"""

import atexit
import sys

from ccmux.ui.sidebar.sidebar_app import DEMO_POLL_INTERVAL, SidebarApp
from ccmux.ui.sidebar.process_id import remove_pid_file, write_pid_file


def main() -> None:
    """Entry point: python -m ccmux.ui.sidebar"""
    if "--demo" in sys.argv:
        try:
            from tests.demo_sidebar import make_demo_provider
        except ImportError:
            print("Error: demo requires the tests package (not installed)", file=sys.stderr)
            sys.exit(1)

        provider = make_demo_provider()
        app = SidebarApp(
            snapshot_fn=provider,
            poll_interval=DEMO_POLL_INTERVAL,
            on_select=provider.select,
        )
        app.run()
        return

    # PID tracking
    write_pid_file()
    atexit.register(remove_pid_file)

    app = SidebarApp()
    app.run()


if __name__ == "__main__":
    main()
