"""Exceptions raised by the Czech Television data boundary."""

from __future__ import annotations


class CtTvProgramError(Exception):
    """Base exception for Czech Television programme data errors."""


class CtTvProgramNetworkError(CtTvProgramError):
    """Represent a network failure while requesting a schedule."""


class CtTvProgramHttpError(CtTvProgramError):
    """Represent an unsuccessful HTTP response from the export."""

    def __init__(self, status: int) -> None:
        """Initialize the error without exposing request configuration."""
        self.status = status
        super().__init__(f"Czech Television export returned HTTP status {status}")


class CtTvProgramInvalidJsonError(CtTvProgramError):
    """Represent a response body that is not valid JSON."""


class CtTvProgramScheduleNotAvailableError(CtTvProgramError):
    """Represent an expected unavailable schedule response."""


class CtTvProgramParseError(CtTvProgramError):
    """Represent malformed schedule data at the normalization boundary."""
