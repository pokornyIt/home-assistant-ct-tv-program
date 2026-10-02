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
from .schedule import get_current_and_next_programme, merge_programmes, merge_schedules

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
    "get_current_and_next_programme",
    "merge_programmes",
    "merge_schedules",
    "parse_programme",
    "parse_schedule",
]
