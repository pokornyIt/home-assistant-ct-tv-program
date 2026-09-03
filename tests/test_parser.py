"""Tests for Czech Television programme payload normalization."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta
from typing import cast

import pytest

from custom_components.ct_tv_program import (
    CtTvProgramParseError,
    CtTvProgramScheduleNotAvailableError,
    Programme,
    parse_programme,
    parse_schedule,
)
from custom_components.ct_tv_program.parser import PRAGUE_TIME_ZONE


def _programme(**overrides: object) -> dict[str, object]:
    programme: dict[str, object] = {
        "linky": {
            "program": "https://example.test/programme",
            "ivysilani": "https://example.test/stream",
        },
        "datum": "2026-09-03",
        "cas": "20:15",
        "nazvy": {
            "nadtitul": "Series",
            "nazev": "Synthetic programme",
            "original": "Synthetic original",
            "nazev_casti": "Synthetic episode",
        },
        "dil": "1/8",
        "zanr": "Documentary",
        "stopaz": "047:30",
        "noticka": "Synthetic description",
        "ikonky": {
            "zvuk": "S",
            "skryte_titulky": "1",
            "neslysici": "1",
            "ad": "1",
            "live": "1",
            "premiera": "1",
            "cb": "1",
            "labeling": "15+",
            "puvodni_zneni": "1",
            "pomer": "16:9",
            "hd": "1",
        },
        "obrazky": {
            "tv_program": "https://example.test/programme.jpg",
            "nahled": "https://example.test/thumbnail.jpg",
        },
    }
    programme.update(overrides)
    return programme


def _schedule(*programmes: object, wrapped: bool = True) -> dict[str, object]:
    schedule: dict[str, object] = {
        "@attributes": {
            "datum_vysilani": "2026-09-03",
            "kanal": "ct1",
            "generovano": "2026-09-03 19:45:30",
        },
        "porad": list(programmes),
    }
    return {"program": schedule} if wrapped else schedule


def test_parse_valid_programme_normalizes_all_model_fields() -> None:
    """A complete synthetic entry becomes immutable typed programme data."""
    programme = parse_programme(_programme())

    assert programme == Programme(
        title="Synthetic programme",
        start=datetime(2026, 9, 3, 20, 15, tzinfo=PRAGUE_TIME_ZONE),
        duration=timedelta(minutes=47, seconds=30),
        subtitle="Synthetic episode",
        original_title="Synthetic original",
        supertitle="Series",
        description="Synthetic description",
        genre="Documentary",
        episode=1,
        episode_count=8,
        program_url="https://example.test/programme",
        ivysilani_url="https://example.test/stream",
        image="https://example.test/programme.jpg",
        thumbnail="https://example.test/thumbnail.jpg",
        audio_description=True,
        hidden_subtitles=True,
        for_deaf=True,
        live=True,
        premiere=True,
        age_rating="15+",
        original_audio=True,
        hd=True,
        sound="S",
        aspect_ratio="16:9",
        black_and_white=True,
    )
    assert programme.effective_end is None
    attribute = "title"
    with pytest.raises(FrozenInstanceError):
        setattr(programme, attribute, "Changed")


def test_empty_objects_and_missing_optional_fields_become_safe_defaults() -> None:
    """Empty XML elements and omitted groups do not leak source quirks."""
    programme = parse_programme(
        _programme(
            linky={},
            nazvy={"nazev": "Required title", "nadtitul": {}, "original": {}, "nazev_casti": ""},
            dil={},
            zanr={},
            noticka="",
            ikonky={},
            obrazky={},
        )
    )

    assert programme.subtitle is None
    assert programme.original_title is None
    assert programme.supertitle is None
    assert programme.description is None
    assert programme.genre is None
    assert programme.episode is None
    assert programme.episode_count is None
    assert programme.program_url is None
    assert programme.ivysilani_url is None
    assert programme.image is None
    assert programme.thumbnail is None
    assert not programme.audio_description
    assert not programme.hidden_subtitles
    assert not programme.for_deaf
    assert not programme.live
    assert not programme.premiere
    assert not programme.original_audio
    assert not programme.hd
    assert not programme.black_and_white


def test_explicit_zero_flags_remain_false() -> None:
    """Every observed zero-valued source flag is normalized explicitly."""
    icons = cast("dict[str, object]", _programme()["ikonky"])
    for field in ("ad", "skryte_titulky", "neslysici", "live", "premiera", "puvodni_zneni", "hd", "cb"):
        icons[field] = "0"

    programme = parse_programme(_programme(ikonky=icons))

    assert not any(
        (
            programme.audio_description,
            programme.hidden_subtitles,
            programme.for_deaf,
            programme.live,
            programme.premiere,
            programme.original_audio,
            programme.hd,
            programme.black_and_white,
        )
    )


def test_optional_scalars_accept_numbers_but_not_boolean_values() -> None:
    """Optional scalar normalization avoids Python bool/int ambiguity."""
    programme = parse_programme(_programme(zanr=42, noticka=True))

    assert programme.genre == "42"
    assert programme.description is None


@pytest.mark.parametrize(
    "field",
    ["ad", "skryte_titulky", "neslysici", "live", "premiera", "puvodni_zneni", "hd", "cb"],
)
def test_unknown_boolean_flags_fail_explicitly(field: str) -> None:
    """Unknown source status values never become truthy implicitly."""
    icons = cast("dict[str, object]", _programme()["ikonky"])
    icons[field] = "unknown"

    with pytest.raises(CtTvProgramParseError, match=rf"ikonky\.{field}"):
        parse_programme(_programme(ikonky=icons))


@pytest.mark.parametrize(
    ("raw_episode", "expected"),
    [("1/8", (1, 8)), ({}, (None, None)), ("", (None, None)), ("episode one", (None, None))],
)
def test_episode_parsing_is_safe(raw_episode: object, expected: tuple[int | None, int | None]) -> None:
    """Only the documented episode/count shape is converted to integers."""
    programme = parse_programme(_programme(dil=raw_episode))

    assert (programme.episode, programme.episode_count) == expected


@pytest.mark.parametrize(("sound", "aspect_ratio"), [("D", "4:3"), ("FUTURE", "21:9-FUTURE")])
def test_open_ended_metadata_values_are_preserved(sound: str, aspect_ratio: str) -> None:
    """Known and future sound/aspect values remain lossless strings."""
    icons = cast("dict[str, object]", _programme()["ikonky"])
    icons.update({"zvuk": sound, "pomer": aspect_ratio})

    programme = parse_programme(_programme(ikonky=icons))

    assert programme.sound == sound
    assert programme.aspect_ratio == aspect_ratio


@pytest.mark.parametrize(("age_rating", "expected"), [("8+", "8+"), ({}, None), ("", None)])
def test_age_rating_is_normalized(age_rating: object, expected: str | None) -> None:
    """Age ratings remain open text while empty values become None."""
    icons = cast("dict[str, object]", _programme()["ikonky"])
    icons["labeling"] = age_rating

    assert parse_programme(_programme(ikonky=icons)).age_rating == expected


def test_missing_image_group_is_supported() -> None:
    """Images are optional because the export does not guarantee them."""
    programme = _programme()
    del programme["obrazky"]

    assert parse_programme(programme).image is None
    assert parse_programme(programme).thumbnail is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"nazvy": {"nazev": {}}}, "nazvy.nazev"),
        ({"datum": "invalid"}, "programme start"),
        ({"cas": "25:00"}, "programme start"),
        ({"cas": "20:15:30"}, "programme start"),
        ({"stopaz": "invalid"}, "duration"),
        ({"stopaz": "010:99"}, "duration"),
    ],
)
def test_malformed_required_programme_values_fail(overrides: dict[str, object], message: str) -> None:
    """Corrupt required fields never create a partial programme."""
    with pytest.raises(CtTvProgramParseError, match=message):
        parse_programme(_programme(**overrides))


@pytest.mark.parametrize("wrapped", [True, False])
def test_parse_successful_schedule_response(wrapped: bool) -> None:
    """Both observed wrapper shapes produce immutable schedule data."""
    schedule = parse_schedule(_schedule(_programme(), wrapped=wrapped))

    assert schedule.channel == "ct1"
    assert schedule.broadcast_date == date(2026, 9, 3)
    assert schedule.generated_at == datetime(2026, 9, 3, 19, 45, 30, tzinfo=PRAGUE_TIME_ZONE)
    assert len(schedule.programmes) == 1
    assert isinstance(schedule.programmes, tuple)


def test_single_and_empty_programme_containers_are_distinct_valid_schedules() -> None:
    """XML-to-JSON cardinality variants and a valid empty schedule are supported."""
    direct = _schedule(wrapped=False)
    direct["porad"] = _programme()
    empty = _schedule(wrapped=False)
    empty["porad"] = {}

    assert len(parse_schedule(direct).programmes) == 1
    assert parse_schedule(empty).programmes == ()


def test_optional_generation_time_variants_are_normalized() -> None:
    """Minute precision and missing generation timestamps remain supported."""
    minute_precision = _schedule(wrapped=False)
    attributes = cast("dict[str, object]", minute_precision["@attributes"])
    attributes["generovano"] = "2026-09-03 19:45"
    missing = _schedule(wrapped=False)
    del cast("dict[str, object]", missing["@attributes"])["generovano"]

    assert parse_schedule(minute_precision).generated_at == datetime(2026, 9, 3, 19, 45, tzinfo=PRAGUE_TIME_ZONE)
    assert parse_schedule(missing).generated_at is None


@pytest.mark.parametrize("payload", [{"error": "not found"}, {"program": {"error": "not found"}}])
def test_not_available_response_has_a_dedicated_error(payload: dict[str, object]) -> None:
    """The export horizon response is not confused with an empty schedule."""
    with pytest.raises(CtTvProgramScheduleNotAvailableError, match="not found"):
        parse_schedule(payload)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {1: "non-string key"},
        {"program": []},
        {"program": {"@attributes": {}, "porad": []}},
        _schedule(wrapped=False) | {"porad": "bad"},
        {
            "@attributes": {
                "datum_vysilani": "invalid",
                "kanal": "ct1",
            },
            "porad": [],
        },
        {
            "@attributes": {
                "datum_vysilani": "2026-09-03",
                "kanal": "ct1",
                "generovano": "invalid",
            },
            "porad": [],
        },
    ],
)
def test_malformed_schedule_structure_fails(payload: object) -> None:
    """Raw objects cannot escape through a structurally invalid schedule."""
    with pytest.raises(CtTvProgramParseError):
        parse_schedule(payload)
