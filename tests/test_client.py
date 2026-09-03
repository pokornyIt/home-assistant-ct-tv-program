"""Offline tests for the asynchronous Czech Television client."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from types import TracebackType
from typing import cast

import aiohttp
import pytest

from custom_components.ct_tv_program import (
    CtTvProgramHttpError,
    CtTvProgramInvalidJsonError,
    CtTvProgramNetworkError,
    CtTvProgramParseError,
    CtTvProgramScheduleNotAvailableError,
    CzechTelevisionClient,
)
from custom_components.ct_tv_program.client import EXPORT_URL, USER_AGENT


def _payload() -> dict[str, object]:
    return {
        "program": {
            "@attributes": {"datum_vysilani": "2026-09-03", "kanal": "ct1"},
            "porad": [
                {
                    "datum": "2026-09-03",
                    "cas": "08:00",
                    "nazvy": {"nazev": "Synthetic programme"},
                    "stopaz": "030:00",
                }
            ],
        }
    }


class _Response:
    def __init__(self, body: str, *, status: int = 200) -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body


class _RequestContext:
    def __init__(self, response: _Response) -> None:
        self._response = response

    async def __aenter__(self) -> _Response:
        return self._response

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class _Session:
    def __init__(self, response: _Response | BaseException) -> None:
        self._response = response
        self.request: tuple[str, dict[str, str], dict[str, str], aiohttp.ClientTimeout] | None = None

    def get(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
        timeout: aiohttp.ClientTimeout,
    ) -> _RequestContext:
        self.request = (url, params, headers, timeout)
        if isinstance(self._response, BaseException):
            raise self._response
        return _RequestContext(self._response)


def _client(session: _Session, **kwargs: float) -> CzechTelevisionClient:
    return CzechTelevisionClient(cast("aiohttp.ClientSession", session), "export-user", **kwargs)


def test_client_fetches_official_json_export_and_returns_models() -> None:
    """The client uses caller-owned aiohttp transport and returns normalized data."""
    session = _Session(_Response(json.dumps(_payload())))

    schedule = asyncio.run(_client(session).async_fetch_schedule(" ct1 ", date(2026, 9, 3)))

    assert schedule.channel == "ct1"
    assert schedule.programmes[0].title == "Synthetic programme"
    assert session.request is not None
    url, params, headers, timeout = session.request
    assert url == EXPORT_URL
    assert params == {"user": "export-user", "date": "03.09.2026", "channel": "ct1", "json": "1"}
    assert headers == {"Accept": "application/json", "User-Agent": USER_AGENT}
    assert timeout.total == 30


def test_client_uses_configurable_explicit_timeout() -> None:
    """Every export request receives an explicit timeout."""
    session = _Session(_Response(json.dumps(_payload())))

    asyncio.run(_client(session, request_timeout=12.5).async_fetch_schedule("ct1", date(2026, 9, 3)))

    assert session.request is not None
    assert session.request[3].total == 12.5


@pytest.mark.parametrize("error", [aiohttp.ClientConnectionError("offline"), TimeoutError("timeout")])
def test_client_wraps_network_failures(error: BaseException) -> None:
    """Transport failures have a stable error independent of aiohttp details."""
    with pytest.raises(CtTvProgramNetworkError, match="Failed to request"):
        asyncio.run(_client(_Session(error)).async_fetch_schedule("ct1", date(2026, 9, 3)))


def test_client_reports_http_failure_separately() -> None:
    """HTTP status failures remain distinguishable from network errors."""
    with pytest.raises(CtTvProgramHttpError, match="503") as error:
        asyncio.run(
            _client(_Session(_Response("unavailable", status=503))).async_fetch_schedule("ct1", date(2026, 9, 3))
        )

    assert error.value.status == 503


def test_client_reports_malformed_json_separately() -> None:
    """A successful HTTP response with invalid JSON has a dedicated error."""
    with pytest.raises(CtTvProgramInvalidJsonError, match="malformed JSON"):
        asyncio.run(_client(_Session(_Response("not-json"))).async_fetch_schedule("ct1", date(2026, 9, 3)))


def test_client_preserves_not_available_result() -> None:
    """Top-level export errors are expected horizon state, not valid empty data."""
    response = _Response(json.dumps({"error": "schedule not found"}))

    with pytest.raises(CtTvProgramScheduleNotAvailableError, match="schedule not found"):
        asyncio.run(_client(_Session(response)).async_fetch_schedule("ct1", date(2026, 10, 3)))


def test_client_preserves_parser_failure() -> None:
    """Structurally corrupt JSON remains distinct from malformed JSON."""
    with pytest.raises(CtTvProgramParseError):
        asyncio.run(_client(_Session(_Response("[]"))).async_fetch_schedule("ct1", date(2026, 9, 3)))


def test_client_rejects_invalid_configuration_and_request() -> None:
    """Required caller configuration fails before any network access."""
    session = cast("aiohttp.ClientSession", _Session(_Response("{}")))

    with pytest.raises(ValueError, match="username"):
        CzechTelevisionClient(session, " ")
    with pytest.raises(ValueError, match="timeout"):
        CzechTelevisionClient(session, "user", request_timeout=0)
    with pytest.raises(ValueError, match="channel"):
        asyncio.run(CzechTelevisionClient(session, "user").async_fetch_schedule(" ", date(2026, 9, 3)))
