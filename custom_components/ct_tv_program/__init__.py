"""Czech Television programme integration data boundary."""

from .client import CzechTelevisionClient
from .errors import (
    CtTvProgramError,
    CtTvProgramHttpError,
    CtTvProgramInvalidJsonError,
    CtTvProgramNetworkError,
    CtTvProgramParseError,
    CtTvProgramScheduleNotAvailableError,
)
from .models import Programme, Schedule
from .parser import parse_programme, parse_schedule

__all__ = [
    "CtTvProgramError",
    "CtTvProgramHttpError",
    "CtTvProgramInvalidJsonError",
    "CtTvProgramNetworkError",
    "CtTvProgramParseError",
    "CtTvProgramScheduleNotAvailableError",
    "CzechTelevisionClient",
    "Programme",
    "Schedule",
    "parse_programme",
    "parse_schedule",
]
