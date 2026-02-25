"""Claude Code Multiplexer - Manage multiple Claude Code sessions."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ccmux")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
