"""Asynchronous client for the official Czech Television programme export."""

from __future__ import annotations

import json
from datetime import date
from typing import Final, cast

import aiohttp

from .errors import CtTvProgramHttpError, CtTvProgramInvalidJsonError, CtTvProgramNetworkError
from .models import Schedule
from .parser import parse_schedule

EXPORT_URL: Final = "https://www.ceskatelevize.cz/services-old/programme/xml/schedule.php"
USER_AGENT: Final = "home-assistant-ct-tv-program/0.1 (+https://github.com/pokornyIt/home-assistant-ct-tv-program)"
DEFAULT_REQUEST_TIMEOUT: Final = 30.0


class CzechTelevisionClient:
    """Fetch and normalize schedules using a caller-owned aiohttp session."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        *,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        """Initialize the client without taking ownership of the shared session."""
        if not username.strip():
            raise ValueError("Czech Television export username must not be empty")
        if request_timeout <= 0:
            raise ValueError("Request timeout must be greater than zero")
        self._session = session
        self._username = username.strip()
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)

    async def async_fetch_schedule(self, channel: str, broadcast_date: date) -> Schedule:
        """Fetch one broadcasting-day schedule and return normalized typed data."""
        normalized_channel = channel.strip()
        if not normalized_channel:
            raise ValueError("Czech Television channel must not be empty")

        try:
            async with self._session.get(
                EXPORT_URL,
                params={
                    "user": self._username,
                    "date": broadcast_date.strftime("%d.%m.%Y"),
                    "channel": normalized_channel,
                    "json": "1",
                },
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                timeout=self._timeout,
            ) as response:
                if response.status < 200 or response.status >= 300:
                    raise CtTvProgramHttpError(response.status)
                payload = await response.text()
        except CtTvProgramHttpError:
            raise
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CtTvProgramNetworkError("Failed to request Czech Television programme export") from err

        try:
            decoded = cast("object", json.loads(payload))
        except json.JSONDecodeError as err:
            raise CtTvProgramInvalidJsonError("Czech Television export returned malformed JSON") from err
        return parse_schedule(decoded)
