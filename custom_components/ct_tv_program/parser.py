"""Normalize Czech Television JSON export payloads."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from typing import Final, cast
from zoneinfo import ZoneInfo

from .errors import CtTvProgramParseError, CtTvProgramScheduleNotAvailableError
from .models import Programme, Schedule

PRAGUE_TIME_ZONE: Final = ZoneInfo("Europe/Prague")
_DURATION_PATTERN: Final = re.compile(r"^(?P<minutes>\d+):(?P<seconds>[0-5]\d)$")
_EPISODE_PATTERN: Final = re.compile(r"^(?P<episode>\d+)\s*/\s*(?P<count>\d+)$")


def _mapping(value: object, *, path: str) -> Mapping[str, object]:
    """Validate and return an object with string keys.

    :param value: Source value expected to contain an object.
    :param path: Diagnostic path of the source value.
    :return: Validated source mapping.
    :raises CtTvProgramParseError: If the value is not an object with string keys.
    """
    if not isinstance(value, Mapping):
        raise CtTvProgramParseError(f"Expected an object at {path}")
    raw_mapping = cast("Mapping[object, object]", value)
    if not all(isinstance(key, str) for key in raw_mapping):
        raise CtTvProgramParseError(f"Expected string object keys at {path}")
    return cast("Mapping[str, object]", raw_mapping)


def _group(parent: Mapping[str, object], key: str, *, path: str) -> Mapping[str, object]:
    """Return an optional nested object using an empty mapping as the default.

    :param parent: Source mapping containing the optional group.
    :param key: Name of the nested group.
    :param path: Diagnostic path of the parent mapping.
    :return: Validated nested mapping or an empty mapping.
    :raises CtTvProgramParseError: If a present group is not an object with string keys.
    """
    value = parent.get(key)
    if value is None or value == {}:
        return {}
    return _mapping(value, path=f"{path}.{key}")


def _optional_text(value: object) -> str | None:
    """Normalize an optional source scalar to text.

    :param value: Optional scalar value from the source payload.
    :return: Normalized text or ``None`` for an empty or unsupported value.
    """
    if value is None or value == {}:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _required_text(value: object, *, path: str) -> str:
    """Validate and normalize a required text value.

    :param value: Required source value.
    :param path: Diagnostic path of the source value.
    :return: Stripped non-empty text.
    :raises CtTvProgramParseError: If the value is not non-empty text.
    """
    if not isinstance(value, str) or not value.strip():
        raise CtTvProgramParseError(f"Missing or invalid required text at {path}")
    return value.strip()


def _flag(value: object, *, path: str) -> bool:
    """Normalize an optional zero-or-one status flag.

    :param value: Source status value.
    :param path: Diagnostic path of the source value.
    :return: Explicit boolean status.
    :raises CtTvProgramParseError: If a non-empty value is neither ``"0"`` nor ``"1"``.
    """
    if value is None or value in ({}, ""):
        return False
    if value == "0":
        return False
    if value == "1":
        return True
    raise CtTvProgramParseError(f"Invalid boolean flag at {path}: {value!r}")


def _start(programme: Mapping[str, object], *, path: str) -> datetime:
    """Parse the timezone-aware start of a programme.

    :param programme: Source programme mapping.
    :param path: Diagnostic path of the programme.
    :return: Start time in the Europe/Prague timezone.
    :raises CtTvProgramParseError: If the date or time is missing or malformed.
    """
    raw_date = _required_text(programme.get("datum"), path=f"{path}.datum")
    raw_time = _required_text(programme.get("cas"), path=f"{path}.cas")
    try:
        parsed_date = date.fromisoformat(raw_date)
        parsed_time = time.fromisoformat(raw_time)
    except ValueError as err:
        raise CtTvProgramParseError(f"Invalid programme start at {path}: {raw_date} {raw_time}") from err
    if parsed_time.second or parsed_time.microsecond or len(raw_time) != 5:
        raise CtTvProgramParseError(f"Invalid programme start at {path}: {raw_date} {raw_time}")
    return datetime.combine(parsed_date, parsed_time, tzinfo=PRAGUE_TIME_ZONE)


def _duration(value: object, *, path: str) -> timedelta:
    """Parse the source programme duration.

    :param value: Source duration in ``mmm:ss`` form.
    :param path: Diagnostic path of the source value.
    :return: Parsed source duration.
    :raises CtTvProgramParseError: If the duration is missing or malformed.
    """
    raw_duration = _required_text(value, path=path)
    match = _DURATION_PATTERN.fullmatch(raw_duration)
    if match is None:
        raise CtTvProgramParseError(f"Invalid programme duration at {path}: {raw_duration!r}")
    return timedelta(minutes=int(match.group("minutes")), seconds=int(match.group("seconds")))


def _episode(value: object) -> tuple[int | None, int | None]:
    """Parse optional episode and episode-count metadata.

    :param value: Source episode value in ``episode/count`` form.
    :return: Episode and episode count, or two ``None`` values when unavailable or malformed.
    """
    raw_episode = _optional_text(value)
    if raw_episode is None:
        return None, None
    match = _EPISODE_PATTERN.fullmatch(raw_episode)
    if match is None:
        return None, None
    return int(match.group("episode")), int(match.group("count"))


def _generated_at(value: object) -> datetime | None:
    """Parse an optional schedule generation timestamp.

    :param value: Source schedule generation timestamp.
    :return: Generation time in the Europe/Prague timezone, or ``None`` when absent.
    :raises CtTvProgramParseError: If a present timestamp is malformed.
    """
    raw_generated_at = _optional_text(value)
    if raw_generated_at is None:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw_generated_at, pattern).replace(tzinfo=PRAGUE_TIME_ZONE)
        except ValueError:
            continue
    raise CtTvProgramParseError(f"Invalid schedule generation time: {raw_generated_at!r}")


def parse_programme(value: object, *, index: int = 0) -> Programme:
    """Parse one raw programme object into an immutable model.

    :param value: Raw programme object from the export payload.
    :param index: Programme index used in diagnostic paths.
    :return: Normalized immutable programme.
    :raises CtTvProgramParseError: If required data or a source status flag is malformed.
    """
    path = f"program.porad[{index}]"
    programme = _mapping(value, path=path)
    names = _group(programme, "nazvy", path=path)
    links = _group(programme, "linky", path=path)
    icons = _group(programme, "ikonky", path=path)
    images = _group(programme, "obrazky", path=path)
    episode, episode_count = _episode(programme.get("dil"))

    return Programme(
        title=_required_text(names.get("nazev"), path=f"{path}.nazvy.nazev"),
        start=_start(programme, path=path),
        duration=_duration(programme.get("stopaz"), path=f"{path}.stopaz"),
        subtitle=_optional_text(names.get("nazev_casti")),
        original_title=_optional_text(names.get("original")),
        supertitle=_optional_text(names.get("nadtitul")),
        description=_optional_text(programme.get("noticka")),
        genre=_optional_text(programme.get("zanr")),
        episode=episode,
        episode_count=episode_count,
        program_url=_optional_text(links.get("program")),
        ivysilani_url=_optional_text(links.get("ivysilani")),
        image=_optional_text(images.get("tv_program")),
        thumbnail=_optional_text(images.get("nahled")),
        audio_description=_flag(icons.get("ad"), path=f"{path}.ikonky.ad"),
        hidden_subtitles=_flag(icons.get("skryte_titulky"), path=f"{path}.ikonky.skryte_titulky"),
        for_deaf=_flag(icons.get("neslysici"), path=f"{path}.ikonky.neslysici"),
        live=_flag(icons.get("live"), path=f"{path}.ikonky.live"),
        premiere=_flag(icons.get("premiera"), path=f"{path}.ikonky.premiera"),
        age_rating=_optional_text(icons.get("labeling")),
        original_audio=_flag(icons.get("puvodni_zneni"), path=f"{path}.ikonky.puvodni_zneni"),
        hd=_flag(icons.get("hd"), path=f"{path}.ikonky.hd"),
        sound=_optional_text(icons.get("zvuk")),
        aspect_ratio=_optional_text(icons.get("pomer")),
        black_and_white=_flag(icons.get("cb"), path=f"{path}.ikonky.cb"),
    )


def _programmes(schedule: Mapping[str, object]) -> tuple[Programme, ...]:
    """Parse all programme entries from a schedule object.

    :param schedule: Raw schedule mapping.
    :return: Normalized immutable programme collection.
    :raises CtTvProgramParseError: If the programme container or an entry is malformed.
    """
    value = schedule.get("porad")
    if value is None or value == {}:
        return ()
    if isinstance(value, Mapping):
        return (parse_programme(cast("object", value)),)
    if not isinstance(value, list):
        raise CtTvProgramParseError("Expected an object or list at program.porad")
    raw_programmes = cast("list[object]", value)
    return tuple(parse_programme(programme, index=index) for index, programme in enumerate(raw_programmes))


def parse_schedule(value: object) -> Schedule:
    """Parse a successful export payload or raise a typed boundary error.

    :param value: Decoded JSON value returned by the official export.
    :return: Normalized immutable broadcasting-day schedule.
    :raises CtTvProgramScheduleNotAvailableError: If the export reports an unavailable schedule.
    :raises CtTvProgramParseError: If the successful response has malformed structure or values.
    """
    root = _mapping(value, path="root")
    error = _optional_text(root.get("error"))
    if error is not None:
        raise CtTvProgramScheduleNotAvailableError(error)

    schedule = _mapping(root.get("program", root), path="program")
    error = _optional_text(schedule.get("error"))
    if error is not None:
        raise CtTvProgramScheduleNotAvailableError(error)

    attributes = _group(schedule, "@attributes", path="program")
    channel = _required_text(attributes.get("kanal"), path="program.@attributes.kanal")
    raw_broadcast_date = _required_text(attributes.get("datum_vysilani"), path="program.@attributes.datum_vysilani")
    try:
        broadcast_date = date.fromisoformat(raw_broadcast_date)
    except ValueError as err:
        raise CtTvProgramParseError(f"Invalid broadcasting date: {raw_broadcast_date!r}") from err

    return Schedule(
        channel=channel,
        broadcast_date=broadcast_date,
        generated_at=_generated_at(attributes.get("generovano")),
        programmes=_programmes(schedule),
    )
