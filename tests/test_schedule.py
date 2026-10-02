"""Tests for Czech Television schedule merging and current/next programme selection."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from custom_components.ct_tv_program import (
    Programme,
    Schedule,
    get_current_and_next_programme,
    merge_programmes,
    merge_schedules,
)
from custom_components.ct_tv_program.parser import PRAGUE_TIME_ZONE


def _programme(
    title: str = "Synthetic show",
    start: datetime | None = None,
    duration: timedelta = timedelta(minutes=30),
    program_url: str | None = "https://example.test/show",
    **overrides: object,
) -> Programme:
    """Build a synthetic Programme instance for schedule testing.

    :param title: Programme title string.
    :param start: Timezone-aware start time, defaulting to 2026-09-03 10:00.
    :param duration: Programme duration timedelta.
    :param program_url: Canonical programme URL.
    :param **overrides: Additional field overrides.
    :return: Synthetic Programme model.
    """
    if start is None:
        start = datetime(2026, 9, 3, 10, 0, tzinfo=PRAGUE_TIME_ZONE)
    kwargs: dict[str, object] = {
        "title": title,
        "start": start,
        "duration": duration,
        "program_url": program_url,
    }
    kwargs.update(overrides)
    return Programme(**kwargs)  # type: ignore[arg-type]


def _schedule(
    channel: str = "ct1",
    broadcast_date: date = date(2026, 9, 3),
    generated_at: datetime | None = datetime(2026, 9, 3, 8, 0, tzinfo=PRAGUE_TIME_ZONE),
    programmes: tuple[Programme, ...] = (),
) -> Schedule:
    """Build a synthetic Schedule instance for testing.

    :param channel: Channel identifier string.
    :param broadcast_date: Broadcasting date.
    :param generated_at: Generation timestamp.
    :param programmes: Tuple of programme entries.
    :return: Synthetic Schedule model.
    """
    return Schedule(
        channel=channel,
        broadcast_date=broadcast_date,
        generated_at=generated_at,
        programmes=programmes,
    )


def test_merge_schedules_empty_input_raises_error() -> None:
    """Merging zero schedules fails with a clear ValueError."""
    with pytest.raises(ValueError, match="At least one schedule is required to merge"):
        merge_schedules()


def test_merge_schedules_mismatched_channel_raises_error() -> None:
    """Merging schedules for different channels raises a ValueError."""
    s1 = _schedule(channel="ct1")
    s2 = _schedule(channel="ct2")

    with pytest.raises(ValueError, match="Cannot merge schedules for different channels"):
        merge_schedules(s1, s2)


def test_merge_schedules_single_schedule_calculates_effective_end() -> None:
    """Merging a single schedule sets effective_end for all entries except the last."""
    p1 = _programme(title="First", start=datetime(2026, 9, 3, 10, 0, tzinfo=PRAGUE_TIME_ZONE))
    p2 = _programme(title="Second", start=datetime(2026, 9, 3, 10, 30, tzinfo=PRAGUE_TIME_ZONE))
    sched = _schedule(programmes=(p1, p2))

    merged = merge_schedules(sched)

    assert len(merged.programmes) == 2
    assert merged.programmes[0].effective_end == datetime(2026, 9, 3, 10, 30, tzinfo=PRAGUE_TIME_ZONE)
    assert merged.programmes[1].effective_end is None


def test_merge_schedules_multiple_days_consolidates_metadata() -> None:
    """Merging multi-day schedules derives earliest date, latest generation time, and combined programmes."""
    p1 = _programme(title="Day 1 Show", start=datetime(2026, 9, 3, 20, 0, tzinfo=PRAGUE_TIME_ZONE))
    p2 = _programme(title="Day 2 Show", start=datetime(2026, 9, 4, 6, 0, tzinfo=PRAGUE_TIME_ZONE))

    s1 = _schedule(
        broadcast_date=date(2026, 9, 3),
        generated_at=datetime(2026, 9, 3, 12, 0, tzinfo=PRAGUE_TIME_ZONE),
        programmes=(p1,),
    )
    s2 = _schedule(
        broadcast_date=date(2026, 9, 4),
        generated_at=datetime(2026, 9, 4, 8, 0, tzinfo=PRAGUE_TIME_ZONE),
        programmes=(p2,),
    )

    merged = merge_schedules(s1, s2)

    assert merged.channel == "ct1"
    assert merged.broadcast_date == date(2026, 9, 3)
    assert merged.generated_at == datetime(2026, 9, 4, 8, 0, tzinfo=PRAGUE_TIME_ZONE)
    assert len(merged.programmes) == 2
    assert merged.programmes[0].effective_end == datetime(2026, 9, 4, 6, 0, tzinfo=PRAGUE_TIME_ZONE)
    assert merged.programmes[1].effective_end is None


def test_deduplication_preserves_separate_broadcasts_with_same_title() -> None:
    """Separate broadcasts with the same title at different start times are not deduplicated."""
    morning = _programme(
        title="Události",
        start=datetime(2026, 9, 3, 6, 0, tzinfo=PRAGUE_TIME_ZONE),
        program_url="https://example.test/udalosti",
    )
    evening = _programme(
        title="Události",
        start=datetime(2026, 9, 3, 19, 0, tzinfo=PRAGUE_TIME_ZONE),
        program_url="https://example.test/udalosti",
    )

    merged = merge_programmes([morning, evening])

    assert len(merged) == 2
    assert merged[0].start == datetime(2026, 9, 3, 6, 0, tzinfo=PRAGUE_TIME_ZONE)
    assert merged[1].start == datetime(2026, 9, 3, 19, 0, tzinfo=PRAGUE_TIME_ZONE)


def test_deduplication_overwrites_identical_key_entries_with_later_version() -> None:
    """Duplicate entries with identical start time, title, and URL keep the latest version."""
    start_time = datetime(2026, 9, 3, 10, 0, tzinfo=PRAGUE_TIME_ZONE)
    initial = _programme(title="News", start=start_time, description="Draft schedule")
    updated = _programme(title="News", start=start_time, description="Final schedule description")

    merged = merge_programmes([initial], [updated])

    assert len(merged) == 1
    assert merged[0].description == "Final schedule description"


def test_autumn_dst_fold_ordering_and_current_next_lookup() -> None:
    """Programmes within the Europe/Prague autumn DST fold are ordered and looked up by actual UTC instant."""
    fold0_time = datetime(2026, 10, 25, 2, 30, fold=0, tzinfo=PRAGUE_TIME_ZONE)
    fold1_time = datetime(2026, 10, 25, 2, 30, fold=1, tzinfo=PRAGUE_TIME_ZONE)
    after_fold_time = datetime(2026, 10, 25, 3, 30, tzinfo=PRAGUE_TIME_ZONE)

    p_a = _programme(title="Show A", start=fold0_time, program_url="https://example.test/a")
    p_b = _programme(title="Show B", start=fold1_time, program_url="https://example.test/b")
    p_c = _programme(title="Show C", start=after_fold_time, program_url="https://example.test/c")

    merged = merge_programmes([p_b, p_c, p_a])

    assert len(merged) == 3
    assert merged[0].title == "Show A"
    assert merged[1].title == "Show B"
    assert merged[2].title == "Show C"
    assert merged[0].effective_end == fold1_time
    assert merged[1].effective_end == after_fold_time

    # At 02:45 fold=0 (00:45 UTC): expected current = Show A, next = Show B
    now_0245_fold0 = datetime(2026, 10, 25, 2, 45, fold=0, tzinfo=PRAGUE_TIME_ZONE)
    curr, nxt = get_current_and_next_programme(merged, now_0245_fold0)
    assert curr is not None and curr.title == "Show A"
    assert nxt is not None and nxt.title == "Show B"

    # At 02:15 fold=1 (01:15 UTC): expected current = Show A, next = Show B
    now_0215_fold1 = datetime(2026, 10, 25, 2, 15, fold=1, tzinfo=PRAGUE_TIME_ZONE)
    curr, nxt = get_current_and_next_programme(merged, now_0215_fold1)
    assert curr is not None and curr.title == "Show A"
    assert nxt is not None and nxt.title == "Show B"

    # Exact boundary 02:30 fold=0 (00:30 UTC): returns Show A, next = Show B
    curr_b0, nxt_b0 = get_current_and_next_programme(merged, fold0_time)
    assert curr_b0 is not None and curr_b0.title == "Show A"
    assert nxt_b0 is not None and nxt_b0.title == "Show B"

    # Exact boundary 02:30 fold=1 (01:30 UTC): returns Show B, next = Show C
    curr_b1, nxt_b1 = get_current_and_next_programme(merged, fold1_time)
    assert curr_b1 is not None and curr_b1.title == "Show B"
    assert nxt_b1 is not None and nxt_b1.title == "Show C"


def test_autumn_dst_fold_generation_time_selection() -> None:
    """Merging schedules selects the latest generated_at timestamp during autumn DST fold."""
    fold0_gen = datetime(2026, 10, 25, 2, 30, fold=0, tzinfo=PRAGUE_TIME_ZONE)
    fold1_gen = datetime(2026, 10, 25, 2, 30, fold=1, tzinfo=PRAGUE_TIME_ZONE)

    s1 = _schedule(generated_at=fold0_gen)
    s2 = _schedule(generated_at=fold1_gen)

    merged = merge_schedules(s1, s2)
    assert merged.generated_at == fold1_gen


def test_spring_forward_dst_transitions() -> None:
    """Schedule merging and lookup operate seamlessly across spring-forward DST jumps."""
    start_cet = datetime(2026, 3, 29, 1, 30, tzinfo=PRAGUE_TIME_ZONE)
    start_cest = datetime(2026, 3, 29, 3, 0, tzinfo=PRAGUE_TIME_ZONE)

    p1 = _programme(title="Night show", start=start_cet)
    p2 = _programme(title="Morning show", start=start_cest)

    merged = merge_programmes([p1, p2])

    assert merged[0].effective_end == start_cest

    now_cet = datetime(2026, 3, 29, 1, 45, tzinfo=PRAGUE_TIME_ZONE)
    curr, nxt = get_current_and_next_programme(merged, now_cet)
    assert curr is not None and curr.title == "Night show"
    assert nxt is not None and nxt.title == "Morning show"

    now_cest = datetime(2026, 3, 29, 3, 15, tzinfo=PRAGUE_TIME_ZONE)
    curr, nxt = get_current_and_next_programme(merged, now_cest)
    assert curr is None
    assert nxt is None


def test_exact_programme_start_and_effective_end_boundaries() -> None:
    """Current/next selection handles exact start and effective_end boundaries correctly."""
    t1 = datetime(2026, 9, 3, 10, 0, tzinfo=PRAGUE_TIME_ZONE)
    t2 = datetime(2026, 9, 3, 10, 30, tzinfo=PRAGUE_TIME_ZONE)
    t3 = datetime(2026, 9, 3, 11, 0, tzinfo=PRAGUE_TIME_ZONE)

    p1 = _programme(title="Show 1", start=t1)
    p2 = _programme(title="Show 2", start=t2)
    p3 = _programme(title="Show 3", start=t3)

    programmes = merge_programmes([p1, p2, p3])

    curr1, nxt1 = get_current_and_next_programme(programmes, t1)
    assert curr1 is not None and curr1.title == "Show 1"
    assert nxt1 is not None and nxt1.title == "Show 2"

    curr2, nxt2 = get_current_and_next_programme(programmes, t2)
    assert curr2 is not None and curr2.title == "Show 2"
    assert nxt2 is not None and nxt2.title == "Show 3"


def test_calendar_midnight_transitions() -> None:
    """Schedule merging and lookup handle broadcasts spanning calendar midnight."""
    t1 = datetime(2026, 9, 3, 23, 30, tzinfo=PRAGUE_TIME_ZONE)
    t2 = datetime(2026, 9, 4, 0, 30, tzinfo=PRAGUE_TIME_ZONE)

    p1 = _programme(title="Late Show", start=t1)
    p2 = _programme(title="Midnight Movie", start=t2)

    merged = merge_programmes([p1, p2])

    assert merged[0].effective_end == t2

    now_before = datetime(2026, 9, 3, 23, 45, tzinfo=PRAGUE_TIME_ZONE)
    now_after = datetime(2026, 9, 4, 0, 15, tzinfo=PRAGUE_TIME_ZONE)

    curr_b, nxt_b = get_current_and_next_programme(merged, now_before)
    curr_a, nxt_a = get_current_and_next_programme(merged, now_after)

    assert curr_b is not None and curr_b.title == "Late Show"
    assert nxt_b is not None and nxt_b.title == "Midnight Movie"
    assert curr_a is not None and curr_a.title == "Late Show"
    assert nxt_a is not None and nxt_a.title == "Midnight Movie"


def test_adjacent_broadcasting_days_merging_with_overlapping_duplicates() -> None:
    """Merging adjacent broadcasting days deduplicates entries at day boundary and links schedule."""
    d1_p1 = _programme(
        title="Night News", start=datetime(2026, 9, 4, 5, 0, tzinfo=PRAGUE_TIME_ZONE), description="Draft"
    )
    d2_p1 = _programme(
        title="Night News", start=datetime(2026, 9, 4, 5, 0, tzinfo=PRAGUE_TIME_ZONE), description="Final"
    )
    d2_p2 = _programme(title="Morning News", start=datetime(2026, 9, 4, 6, 0, tzinfo=PRAGUE_TIME_ZONE))

    s1 = _schedule(broadcast_date=date(2026, 9, 3), programmes=(d1_p1,))
    s2 = _schedule(broadcast_date=date(2026, 9, 4), programmes=(d2_p1, d2_p2))

    merged = merge_schedules(s1, s2)

    assert len(merged.programmes) == 2
    assert merged.programmes[0].description == "Final"
    assert merged.programmes[0].effective_end == datetime(2026, 9, 4, 6, 0, tzinfo=PRAGUE_TIME_ZONE)
    assert merged.programmes[1].effective_end is None


def test_negative_duration_overlap_uses_next_start_as_effective_end() -> None:
    """Source duration does not control effective_end or current selection when slots overlap."""
    t1 = datetime(2026, 9, 3, 10, 0, tzinfo=PRAGUE_TIME_ZONE)
    t2 = datetime(2026, 9, 3, 10, 30, tzinfo=PRAGUE_TIME_ZONE)
    t3 = datetime(2026, 9, 3, 11, 0, tzinfo=PRAGUE_TIME_ZONE)

    p1 = _programme(title="Overlapping Show", start=t1, duration=timedelta(minutes=50))
    p2 = _programme(title="Early Interruption", start=t2, duration=timedelta(minutes=30))
    p3 = _programme(title="Next Show", start=t3, duration=timedelta(minutes=30))

    programmes = merge_programmes([p1, p2, p3])

    assert programmes[0].effective_end == t2

    now = datetime(2026, 9, 3, 10, 35, tzinfo=PRAGUE_TIME_ZONE)
    curr, nxt = get_current_and_next_programme(programmes, now)

    assert curr is not None and curr.title == "Early Interruption"
    assert nxt is not None and nxt.title == "Next Show"


def test_get_current_and_next_programme_empty_schedule_returns_none() -> None:
    """Lookup against an empty programme sequence returns (None, None)."""
    now = datetime(2026, 9, 3, 10, 0, tzinfo=PRAGUE_TIME_ZONE)
    assert get_current_and_next_programme([], now) == (None, None)


def test_merge_programmes_empty_input_returns_empty_tuple() -> None:
    """Merging empty programme collections returns an empty tuple."""
    assert merge_programmes([], []) == ()


def test_get_current_and_next_programme_during_broadcast() -> None:
    """Lookup during a programme's slot returns that programme and the next one."""
    t1 = datetime(2026, 9, 3, 10, 0, tzinfo=PRAGUE_TIME_ZONE)
    t2 = datetime(2026, 9, 3, 10, 30, tzinfo=PRAGUE_TIME_ZONE)
    t3 = datetime(2026, 9, 3, 11, 0, tzinfo=PRAGUE_TIME_ZONE)

    p1 = _programme(title="Show 1", start=t1)
    p2 = _programme(title="Show 2", start=t2)
    p3 = _programme(title="Show 3", start=t3)

    programmes = merge_programmes([p1, p2, p3])

    now = datetime(2026, 9, 3, 10, 15, tzinfo=PRAGUE_TIME_ZONE)
    current, next_prog = get_current_and_next_programme(programmes, now)

    assert current is not None and current.title == "Show 1"
    assert next_prog is not None and next_prog.title == "Show 2"


def test_get_current_and_next_programme_during_gap() -> None:
    """Lookup during a programme's slot before the next start time returns that programme as current."""
    t1 = datetime(2026, 9, 3, 10, 0, tzinfo=PRAGUE_TIME_ZONE)
    t2 = datetime(2026, 9, 3, 11, 0, tzinfo=PRAGUE_TIME_ZONE)

    p1 = _programme(title="Show 1", start=t1)
    p2 = _programme(title="Show 2", start=t2)

    programmes = merge_programmes([p1, p2])

    now = datetime(2026, 9, 3, 10, 45, tzinfo=PRAGUE_TIME_ZONE)
    current, next_prog = get_current_and_next_programme(programmes, now)

    assert current is not None and current.title == "Show 1"
    assert next_prog is not None and next_prog.title == "Show 2"


def test_get_current_and_next_programme_gap_when_explicit_end_precedes_next_start() -> None:
    """Lookup in an explicit time gap returns None for current programme."""
    t1 = datetime(2026, 9, 3, 10, 0, tzinfo=PRAGUE_TIME_ZONE)
    t1_end = datetime(2026, 9, 3, 10, 30, tzinfo=PRAGUE_TIME_ZONE)
    t2 = datetime(2026, 9, 3, 10, 40, tzinfo=PRAGUE_TIME_ZONE)

    p1 = Programme(title="Show 1", start=t1, duration=timedelta(minutes=30), effective_end=t1_end)
    p2 = Programme(title="Show 2", start=t2, duration=timedelta(minutes=30), effective_end=None)

    programmes = (p1, p2)

    now_gap = datetime(2026, 9, 3, 10, 35, tzinfo=PRAGUE_TIME_ZONE)
    current, next_prog = get_current_and_next_programme(programmes, now_gap)

    assert current is None
    assert next_prog is not None and next_prog.title == "Show 2"


def test_get_current_and_next_programme_before_schedule_start() -> None:
    """Lookup before the first programme starts returns no current programme and the first programme as next."""
    t1 = datetime(2026, 9, 3, 10, 0, tzinfo=PRAGUE_TIME_ZONE)
    p1 = _programme(title="First", start=t1)

    programmes = merge_programmes([p1])

    now = datetime(2026, 9, 3, 9, 30, tzinfo=PRAGUE_TIME_ZONE)
    current, next_prog = get_current_and_next_programme(programmes, now)

    assert current is None
    assert next_prog is not None and next_prog.title == "First"


def test_get_current_and_next_programme_at_or_after_final_programme_start() -> None:
    """Lookup once the final programme's start time is reached returns (None, None) due to effective_end=None."""
    t1 = datetime(2026, 9, 3, 10, 0, tzinfo=PRAGUE_TIME_ZONE)
    t2 = datetime(2026, 9, 3, 10, 30, tzinfo=PRAGUE_TIME_ZONE)

    p1 = _programme(title="Show 1", start=t1)
    p2 = _programme(title="Final Show", start=t2)

    programmes = merge_programmes([p1, p2])

    now_at_start = datetime(2026, 9, 3, 10, 30, tzinfo=PRAGUE_TIME_ZONE)
    now_after_start = datetime(2026, 9, 3, 11, 00, tzinfo=PRAGUE_TIME_ZONE)

    current_at, next_at = get_current_and_next_programme(programmes, now_at_start)
    current_after, next_after = get_current_and_next_programme(programmes, now_after_start)

    assert current_at is None
    assert next_at is None
    assert current_after is None
    assert next_after is None


def test_get_current_and_next_programme_requires_timezone_aware_now() -> None:
    """Passing a naive datetime for now raises a ValueError."""
    p1 = _programme()
    naive_now = datetime(2026, 9, 3, 10, 15)

    with pytest.raises(ValueError, match="must be timezone-aware"):
        get_current_and_next_programme([p1], naive_now)
