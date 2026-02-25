"""Exceptions for the ccmux package."""


class SessionExistsError(Exception):
    """Raised when a session name is already in use."""
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Session '{name}' already exists.")
