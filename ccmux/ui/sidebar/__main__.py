"""Allow running sidebar as a module: python -m ccmux.ui.sidebar"""

import atexit
import sys

from ccmux.ui.sidebar.sidebar_app import DEMO_POLL_INTERVAL, SidebarApp
from ccmux.ui.sidebar.process_id import remove_pid_file, write_pid_file


def main() -> None:
    """Entry point: python -m ccmux.ui.sidebar <session>"""
    if "--demo" in sys.argv:
        try:
            from tests.demo_sidebar import make_demo_provider
        except ImportError:
            print("Error: demo requires the tests package (not installed)", file=sys.stderr)
            sys.exit(1)

        app = SidebarApp(
            session="demo",
            snapshot_fn=make_demo_provider(),
            poll_interval=DEMO_POLL_INTERVAL,
        )
        app.run()
        return

    if len(sys.argv) < 2:
        print("Usage: python -m ccmux.ui.sidebar <session>", file=sys.stderr)
        print("       python -m ccmux.ui.sidebar --demo", file=sys.stderr)
        sys.exit(1)

    session = sys.argv[1]

    # PID tracking
    write_pid_file(session)
    atexit.register(remove_pid_file, session)

    app = SidebarApp(session=session)
    app.run()


if __name__ == "__main__":
    main()
