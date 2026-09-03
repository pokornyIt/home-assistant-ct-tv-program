"""Tests for the Czech Television programme export research tool."""

from datetime import datetime
from pathlib import Path

import pytest

from scripts.ct_program_research import (
    MIN_REQUEST_DELAY_SECONDS,
    PRAGUE_TIME_ZONE,
    JsonObject,
    ResearchError,
    _extract_programmes,
    _horizon_requests,
    _text,
    calculate_timings,
    collect_fixtures,
    load_export_username,
)


def test_text_normalizes_empty_source_values() -> None:
    """Empty XML values represented in JSON do not leak past the boundary."""
    assert _text({}) is None
    assert _text("") is None
    assert _text(None) is None
    assert _text("value") == "value"


def test_extract_programmes_accepts_single_object() -> None:
    """A single XML element converted to an object remains supported."""
    programme: JsonObject = {"nazvy": {"nazev": "Test"}}

    assert _extract_programmes({"porad": programme}) == [programme]


def test_calculate_timings_uses_next_start_across_midnight() -> None:
    """The next start defines effective end even across calendar midnight."""
    programmes = [
        {"datum": "2026-09-02", "cas": "23:50", "stopaz": "005:00"},
        {"datum": "2026-09-03", "cas": "00:00", "stopaz": "010:00"},
    ]

    timings = calculate_timings(programmes)

    assert timings[0].content_end == datetime(2026, 9, 2, 23, 55, tzinfo=PRAGUE_TIME_ZONE)
    assert timings[0].effective_end == datetime(2026, 9, 3, tzinfo=PRAGUE_TIME_ZONE)
    assert timings[0].gap_seconds == 300
    assert timings[1].effective_end is None
    assert timings[1].gap_seconds is None


def test_calculate_timings_reports_overlap() -> None:
    """A programme whose duration exceeds its slot has a negative gap."""
    programmes = [
        {"datum": "2026-09-02", "cas": "10:00", "stopaz": "031:00"},
        {"datum": "2026-09-02", "cas": "10:30", "stopaz": "030:00"},
    ]

    assert calculate_timings(programmes)[0].gap_seconds == -60


def test_collect_rejects_short_delay(tmp_path: Path) -> None:
    """Live collection cannot bypass the issue's conservative request delay.

    :param tmp_path: Temporary directory supplied by pytest.
    """
    with pytest.raises(ResearchError, match="at least 90 seconds"):
        collect_fixtures(
            username="test",
            requests=[("ct1", datetime.now(tz=PRAGUE_TIME_ZONE).date())],
            output_dir=tmp_path,
            delay_seconds=MIN_REQUEST_DELAY_SECONDS - 1,
        )


def test_export_username_is_loaded_from_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The request username comes from CT_USER in the selected .env file.

    :param tmp_path: Temporary directory supplied by pytest.
    :param monkeypatch: Pytest environment monkeypatch fixture.
    """
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("CT_USER=fixture-user\n", encoding="utf-8")
    monkeypatch.delenv("CT_USER", raising=False)

    assert load_export_username(dotenv_path) == "fixture-user"


def test_horizon_requests_are_sorted_and_deduplicated() -> None:
    """Future schedule probes progress monotonically without duplicate requests."""
    base = datetime(2026, 9, 2, tzinfo=PRAGUE_TIME_ZONE).date()

    assert _horizon_requests(base, [14, 7, 14, 21]) == [
        ("ct1", datetime(2026, 9, 9, tzinfo=PRAGUE_TIME_ZONE).date()),
        ("ct1", datetime(2026, 9, 16, tzinfo=PRAGUE_TIME_ZONE).date()),
        ("ct1", datetime(2026, 9, 23, tzinfo=PRAGUE_TIME_ZONE).date()),
    ]
