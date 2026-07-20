"""Harness-specific exception types."""


class HarnessError(Exception):
    """Base class for all harness errors."""


class ConfigError(HarnessError):
    """config.json is missing, malformed, or fails validation."""


class UnsafeCommandError(HarnessError):
    """A board command matched a forbidden pattern (NFR4).

    Raised before execution to protect Wi-Fi and SSH access on the
    board; see Board.FORBIDDEN_PATTERNS.
    """


class BoardConnectionError(HarnessError):
    """SSH transport to the board failed after retries (maps to FT7)."""


class CaptureError(HarnessError):
    """ffmpeg frame capture from the host camera failed."""


class PreflightError(HarnessError):
    """A preflight check blocking a selected condition failed (FR1)."""
