"""Schedule merging and current/next programme selection for Czech Television."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from .models import Programme, Schedule


def _deduplication_key(programme: Programme) -> tuple[datetime, str, str | None]:
    """Return a deterministic deduplication key for a programme entry.

    The key consists of the start timestamp converted to UTC, normalized title,
    and programme URL. Converting the start timestamp to UTC ensures that distinct
    instants during daylight saving transition folds (such as fold=0 CEST vs fold=1 CET)
    produce distinct keys, while identical broadcast slots across merged schedules are deduplicated.

    :param programme: Programme entry to compute key for.
    :return: Composite key tuple used for deduplication.
    """
    return (programme.start.astimezone(UTC), programme.title, programme.program_url)


def merge_programmes(*programme_collections: Iterable[Programme]) -> tuple[Programme, ...]:
    """Merge, deduplicate, and order programme entries chronologically.

    Deduplication uses a key combining start time (in UTC), title, and programme URL.
    When duplicate entries are encountered across collections, the latest entry
    in the iteration order takes precedence.

    Programmes are sorted by their actual UTC instant, correctly ordering distinct
    instants within the Europe/Prague autumn DST fold.

    The ``effective_end`` of each programme is updated to match the start time
    of the next scheduled programme. The final programme in the merged sequence always
    retains ``effective_end=None`` because its true end boundary is unknown until a
    subsequent schedule is merged.

    :param *programme_collections: One or more programme iterables to merge.
    :return: Chronologically sorted tuple of normalized programmes with updated effective end times.
    """
    deduplicated: dict[tuple[datetime, str, str | None], Programme] = {}
    for collection in programme_collections:
        for programme in collection:
            deduplicated[_deduplication_key(programme)] = programme

    if not deduplicated:
        return ()

    sorted_programmes = sorted(deduplicated.values(), key=lambda p: p.start.astimezone(UTC))
    total = len(sorted_programmes)

    merged: list[Programme] = []
    for index, programme in enumerate(sorted_programmes):
        if index < total - 1:
            next_start = sorted_programmes[index + 1].start
            updated = dataclasses.replace(programme, effective_end=next_start)
        else:
            updated = dataclasses.replace(programme, effective_end=None)
        merged.append(updated)

    return tuple(merged)


def merge_schedules(*schedules: Schedule) -> Schedule:
    """Merge multiple broadcasting-day schedules for a single channel.

    All schedules must belong to the same Czech Television channel. The resulting
    schedule combines all programme entries, deduplicating duplicates and setting
    ``effective_end`` boundaries between adjacent broadcasts.

    :param *schedules: One or more broadcasting-day schedules for the same channel.
    :return: Merged schedule containing the consolidated programme sequence.
    :raises ValueError: If no schedules are provided or if schedules belong to different channels.
    """
    if not schedules:
        raise ValueError("At least one schedule is required to merge")

    channel = schedules[0].channel
    for schedule in schedules[1:]:
        if schedule.channel != channel:
            raise ValueError(f"Cannot merge schedules for different channels: {channel!r} and {schedule.channel!r}")

    broadcast_date = min(s.broadcast_date for s in schedules)
    generated_at = max(
        (s.generated_at for s in schedules if s.generated_at is not None),
        key=lambda dt: dt.astimezone(UTC),
        default=None,
    )
    merged_programmes = merge_programmes(*(s.programmes for s in schedules))

    return Schedule(
        channel=channel,
        broadcast_date=broadcast_date,
        generated_at=generated_at,
        programmes=merged_programmes,
    )


def get_current_and_next_programme(
    programmes: Sequence[Programme],
    now: datetime,
) -> tuple[Programme | None, Programme | None]:
    """Determine the currently airing programme and the next scheduled programme.

    A programme is considered currently airing if ``start <= now < effective_end``
    comparing actual UTC instants.
    If a programme has ``effective_end=None`` (the final programme in the known schedule),
    it is NOT claimed as currently airing once its start time has been reached. Instead,
    ``(None, None)`` is returned when ``now >= final_programme.start`` with no known end
    boundary. This signals to the update coordinator that another schedule must be fetched.

    :param programmes: Ordered sequence of merged programme entries.
    :param now: Timezone-aware timestamp for the lookup instant.
    :return: Tuple of ``(current_programme, next_programme)``, each of which may be ``None``.
    :raises ValueError: If ``now`` is naive (lacks timezone information).
    """
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError("Timestamp 'now' must be timezone-aware")

    now_utc = now.astimezone(UTC)

    for index, programme in enumerate(programmes):
        if programme.effective_end is not None:
            p_start_utc = programme.start.astimezone(UTC)
            p_end_utc = programme.effective_end.astimezone(UTC)
            if p_start_utc <= now_utc < p_end_utc:
                next_programme = programmes[index + 1] if index + 1 < len(programmes) else None
                return programme, next_programme

    next_programme = next((p for p in programmes if p.start.astimezone(UTC) > now_utc), None)
    return None, next_programme
