"""Normalized Czech Television programme data models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True, slots=True)
class Programme:
    """Represent one immutable normalized programme entry."""

    title: str
    start: datetime
    duration: timedelta
    subtitle: str | None = None
    original_title: str | None = None
    supertitle: str | None = None
    effective_end: datetime | None = None
    description: str | None = None
    genre: str | None = None
    episode: int | None = None
    episode_count: int | None = None
    program_url: str | None = None
    ivysilani_url: str | None = None
    image: str | None = None
    thumbnail: str | None = None
    audio_description: bool = False
    hidden_subtitles: bool = False
    for_deaf: bool = False
    live: bool = False
    premiere: bool = False
    age_rating: str | None = None
    original_audio: bool = False
    hd: bool = False
    sound: str | None = None
    aspect_ratio: str | None = None
    black_and_white: bool = False


@dataclass(frozen=True, slots=True)
class Schedule:
    """Represent one immutable normalized broadcasting-day schedule."""

    channel: str
    broadcast_date: date
    generated_at: datetime | None
    programmes: tuple[Programme, ...]
