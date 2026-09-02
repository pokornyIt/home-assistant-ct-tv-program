"""Download and analyse official Czech Television programme export data."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Final, cast
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

EXPORT_URL: Final = "https://www.ceskatelevize.cz/services-old/programme/xml/schedule.php"
DEFAULT_CHANNELS: Final = ("ct1", "ct2", "ct24", "ct4", "ct5", "ct6")
MIN_REQUEST_DELAY_SECONDS: Final = 90.0
USER_AGENT: Final = (
    "home-assistant-ct-tv-program-research/0.1 (+https://github.com/pokornyIt/home-assistant-ct-tv-program)"
)
EXPORT_USER_ENV: Final = "CT_USER"
PRAGUE_TIME_ZONE: Final = ZoneInfo("Europe/Prague")
LARGE_GAP_SECONDS: Final = 300
type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | JsonObject | list[JsonValue]
type JsonObject = dict[str, JsonValue]


class ResearchError(Exception):
    """Represent an expected research-tool failure."""


@dataclass(frozen=True, slots=True)
class Fixture:
    """A loaded schedule fixture and its source path."""

    path: Path
    root: JsonObject
    schedule: JsonObject
    programmes: list[JsonObject]

    @property
    def channel(self) -> str:
        """Return the channel declared by the schedule."""
        value = _nested(self.schedule, "@attributes", "kanal")
        return _text(value) or self.path.stem.split("-")[0]

    @property
    def broadcast_date(self) -> str:
        """Return the broadcasting date declared by the schedule."""
        value = _nested(self.schedule, "@attributes", "datum_vysilani")
        return _text(value) or "unknown"


@dataclass(frozen=True, slots=True)
class TimingRow:
    """Timing values calculated for a programme entry."""

    start: datetime
    content_end: datetime
    effective_end: datetime | None
    gap_seconds: int | None


def _text(value: object) -> str | None:
    """Normalize an optional scalar source value to text."""
    if value is None or value in ({}, ""):
        return None
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _format_export_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _request_url(username: str, channel: str, broadcast_date: date) -> str:
    query = urllib.parse.urlencode(
        {
            "user": username,
            "date": _format_export_date(broadcast_date),
            "channel": channel,
            "json": "1",
        }
    )
    return f"{EXPORT_URL}?{query}"


def _download(username: str, channel: str, broadcast_date: date) -> bytes:
    request = urllib.request.Request(
        _request_url(username, channel, broadcast_date),
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
    except (TimeoutError, urllib.error.URLError) as err:
        msg = f"Failed to download {channel} for {broadcast_date}: {err}"
        raise ResearchError(msg) from err

    try:
        parsed = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        msg = f"Export returned invalid JSON for {channel} on {broadcast_date}"
        raise ResearchError(msg) from err
    if not isinstance(parsed, dict):
        msg = f"Export returned a non-object JSON root for {channel} on {broadcast_date}"
        raise ResearchError(msg)
    return payload


def _write_payload(payload: bytes, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(target)


def collect_fixtures(
    *,
    username: str,
    requests: Sequence[tuple[str, date]],
    output_dir: Path,
    delay_seconds: float,
    stop_on_empty: bool = False,
) -> list[Path]:
    """Download schedule requests sequentially with an enforced safe delay."""
    if delay_seconds < MIN_REQUEST_DELAY_SECONDS:
        msg = f"Request delay must be at least {MIN_REQUEST_DELAY_SECONDS:.0f} seconds"
        raise ResearchError(msg)

    written: list[Path] = []
    for index, (channel, broadcast_date) in enumerate(requests):
        if index:
            print(
                f"Waiting {delay_seconds:.0f} seconds before the next request...",
                flush=True,
            )
            time.sleep(delay_seconds)
        print(f"Downloading {channel} for {broadcast_date.isoformat()}...", flush=True)
        payload = _download(username, channel, broadcast_date)
        target = output_dir / f"{channel}-{broadcast_date.isoformat()}.json"
        _write_payload(payload, target)
        written.append(target)
        print(f"Saved {target} ({len(payload)} bytes)", flush=True)
        if stop_on_empty:
            parsed = _as_object(json.loads(payload), context="root")
            programme_count = len(_extract_programmes(_extract_schedule(parsed)))
            print(f"Found {programme_count} programmes", flush=True)
            if programme_count == 0:
                print("Stopping at the first empty schedule.", flush=True)
                break
    return written


def _as_object(value: object, *, context: str) -> JsonObject:
    if not isinstance(value, dict):
        msg = f"Expected an object at {context}"
        raise ResearchError(msg)
    mapping = cast("dict[object, object]", value)
    if not all(isinstance(key, str) for key in mapping):
        msg = f"Expected string object keys at {context}"
        raise ResearchError(msg)
    return cast("JsonObject", mapping)


def _extract_schedule(root: JsonObject) -> JsonObject:
    candidate = root.get("program", root)
    return _as_object(candidate, context="program")


def _extract_programmes(schedule: JsonObject) -> list[JsonObject]:
    raw = schedule.get("porad", [])
    if raw == {} or raw is None:
        return []
    if isinstance(raw, dict):
        return [_as_object(raw, context="program.porad")]
    if not isinstance(raw, list):
        message = "Expected program.porad to be an object or list"
        raise ResearchError(message)
    return [_as_object(item, context=f"program.porad[{index}]") for index, item in enumerate(raw)]


def load_fixture(path: Path) -> Fixture:
    """Load and validate one JSON schedule fixture."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
        msg = f"Cannot load fixture {path}: {err}"
        raise ResearchError(msg) from err
    root = _as_object(raw, context="root")
    schedule = _extract_schedule(root)
    return Fixture(path, root, schedule, _extract_programmes(schedule))


def _walk(value: object, prefix: str = "") -> Iterable[tuple[str, object]]:
    if isinstance(value, dict):
        mapping = cast("dict[object, object]", value)
        if not mapping:
            yield prefix, value
        for key, child in mapping.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            yield from _walk(child, child_path)
    elif isinstance(value, list):
        items = cast("list[object]", value)
        if not items:
            yield f"{prefix}[]", value
        for child in items:
            yield from _walk(child, f"{prefix}[]")
    else:
        yield prefix, value


def _value_type(value: object) -> str:
    if value == {}:
        return "empty object"
    if value is None:
        return "null"
    return type(value).__name__


def _parse_start(programme: Mapping[str, object]) -> datetime:
    day = _text(programme.get("datum"))
    clock = _text(programme.get("cas"))
    if day is None or clock is None:
        message = "Programme is missing datum or cas"
        raise ResearchError(message)
    try:
        return datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M").replace(tzinfo=PRAGUE_TIME_ZONE)
    except ValueError as err:
        msg = f"Invalid programme start: {day} {clock}"
        raise ResearchError(msg) from err


def _parse_duration(value: object) -> timedelta:
    duration = _text(value)
    if duration is None:
        message = "Programme is missing stopaz"
        raise ResearchError(message)
    try:
        minutes, seconds = (int(part) for part in duration.split(":"))
    except (TypeError, ValueError) as err:
        msg = f"Invalid stopaz value: {duration}"
        raise ResearchError(msg) from err
    return timedelta(minutes=minutes, seconds=seconds)


def calculate_timings(programmes: Sequence[Mapping[str, object]]) -> list[TimingRow]:
    """Calculate content and effective end times for ordered programmes."""
    starts = [_parse_start(programme) for programme in programmes]
    rows: list[TimingRow] = []
    for index, (programme, start) in enumerate(zip(programmes, starts, strict=True)):
        content_end = start + _parse_duration(programme.get("stopaz"))
        effective_end = starts[index + 1] if index + 1 < len(starts) else None
        gap = int((effective_end - content_end).total_seconds()) if effective_end is not None else None
        rows.append(TimingRow(start, content_end, effective_end, gap))
    return rows


def _programme_paths(programme: JsonObject) -> set[str]:
    return {path for path, _ in _walk(programme)}


def _extension(value: object) -> str | None:
    text = _text(value)
    if text is None:
        return None
    suffix = Path(urlsplit(text).path).suffix.lower()
    return suffix or "(none)"


def _nested(programme: Mapping[str, object], group: str, field: str) -> object:
    parent = programme.get(group)
    if not isinstance(parent, dict):
        return None
    return cast("dict[object, object]", parent).get(field)


def _format_values(values: Iterable[object]) -> str:
    rendered = sorted({json.dumps(value, ensure_ascii=False, sort_keys=True) for value in values})
    return ", ".join(f"`{value}`" for value in rendered) or "none"


def build_report(fixtures: Sequence[Fixture]) -> str:
    """Build a deterministic Markdown analysis for schedule fixtures."""
    all_programmes = [programme for fixture in fixtures for programme in fixture.programmes]
    entry_paths: dict[str, set[str]] = {}
    field_types: dict[str, Counter[str]] = defaultdict(Counter)
    empty_counts: Counter[str] = Counter()
    presence: Counter[str] = Counter()

    for fixture in fixtures:
        channel_paths: set[str] = set()
        for programme in fixture.programmes:
            paths = _programme_paths(programme)
            channel_paths.update(paths)
            presence.update(paths)
            for path, value in _walk(programme):
                field_types[path][_value_type(value)] += 1
                if value in ({}, "", None):
                    empty_counts[path] += 1
        entry_paths[fixture.path.name] = channel_paths

    union_paths: set[str] = set()
    for paths in entry_paths.values():
        union_paths.update(paths)
    inconsistent = {path: counts for path, counts in field_types.items() if len(counts) > 1}
    enum_fields = (
        ("regionalni", None),
        ("alternativa", None),
        ("zvuk", "ikonky"),
        ("pomer", "ikonky"),
        ("labeling", "ikonky"),
        ("ad", "ikonky"),
        ("skryte_titulky", "ikonky"),
        ("neslysici", "ikonky"),
        ("live", "ikonky"),
        ("premiera", "ikonky"),
        ("puvodni_zneni", "ikonky"),
        ("hd", "ikonky"),
    )

    lines = [
        "# Czech Television programme export research",
        "",
        ("> Generated by `scripts/ct_program_research.py analyse` from raw JSON fixtures."),
        "",
        "## Fixture coverage",
        "",
        "<!-- markdownlint-disable MD013 -->",
        "",
        "| Fixture | Declared channel | Broadcasting day | Programmes | Generated |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for fixture in fixtures:
        generated_value = _nested(fixture.schedule, "@attributes", "generovano")
        generated = _text(generated_value) or "unknown"
        lines.append(
            f"| `{fixture.path.name}` | `{fixture.channel}` | "
            f"{fixture.broadcast_date} | {len(fixture.programmes)} | {generated} |"
        )

    lines.extend(["", "<!-- markdownlint-enable MD013 -->", "", "## Structure", ""])
    schedule_keys = sorted({key for fixture in fixtures for key in fixture.schedule})
    lines.append(f"Schedule fields: {', '.join(f'`{key}`' for key in schedule_keys)}.")
    lines.extend(["", "<!-- markdownlint-disable MD013 -->", ""])
    lines.append(f"Programme leaf paths: {', '.join(f'`{path}`' for path in sorted(union_paths))}.")
    lines.extend(
        [
            "",
            "<!-- markdownlint-enable MD013 -->",
            "",
            "### Missing or empty values",
            "",
            "<!-- markdownlint-disable MD013 -->",
            "",
        ]
    )
    lines.append("| Field path | Missing entries | Empty entries |")
    lines.append("| --- | ---: | ---: |")
    total = len(all_programmes)
    for path in sorted(union_paths):
        missing = total - presence[path]
        empty = empty_counts[path]
        if missing or empty:
            lines.append(f"| `{path}` | {missing} | {empty} |")

    lines.extend(["", "<!-- markdownlint-enable MD013 -->", "", "### Inconsistent JSON types", ""])
    if inconsistent:
        for path, counts in sorted(inconsistent.items()):
            summary = ", ".join(f"{kind}: {count}" for kind, count in sorted(counts.items()))
            lines.append(f"- `{path}`: {summary}")
    else:
        lines.append("No inconsistent leaf types were observed.")

    lines.extend(["", "### Structure differences by fixture", "", "<!-- markdownlint-disable MD013 -->", ""])
    for name, paths in sorted(entry_paths.items()):
        missing = sorted(union_paths - paths)
        lines.append(
            f"- `{name}`: "
            + (f"missing {', '.join(f'`{path}`' for path in missing)}" if missing else "no missing observed paths")
        )
    lines.extend(["", "<!-- markdownlint-enable MD013 -->"])

    lines.extend(["", "## Observed values", ""])
    for field, group in enum_fields:
        values = [_nested(programme, group, field) if group else programme.get(field) for programme in all_programmes]
        lines.append(f"- `{group + '.' if group else ''}{field}`: {_format_values(values)}")

    lines.extend(["", "## Timing", "", "<!-- markdownlint-disable MD013 -->", ""])
    lines.append("| Fixture | First start | Last start | Min gap | Max gap | Overlaps | Midnight transitions |")
    lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: |")
    all_gaps: list[int] = []
    for fixture in fixtures:
        timings = calculate_timings(fixture.programmes)
        gaps = [gap for row in timings if (gap := row.gap_seconds) is not None]
        all_gaps.extend(gaps)
        overlaps = sum(gap < 0 for gap in gaps)
        midnight = sum(
            row.effective_end is not None and row.start.date() != row.effective_end.date() for row in timings
        )
        first = timings[0].start.isoformat(timespec="minutes") if timings else "none"
        last = timings[-1].start.isoformat(timespec="minutes") if timings else "none"
        minimum = min(gaps) if gaps else 0
        maximum = max(gaps) if gaps else 0
        lines.append(
            f"| `{fixture.path.name}` | {first} | {last} | {minimum}s | {maximum}s | {overlaps} | {midnight} |"
        )
    lines.extend(["", "<!-- markdownlint-enable MD013 -->"])
    if all_gaps:
        lines.extend(
            [
                "",
                (f"Across all non-final entries, slot gaps range from {min(all_gaps)} to {max(all_gaps)} seconds."),
                (
                    f"The samples contain {sum(gap < 0 for gap in all_gaps)} overlaps and "
                    f"{sum(abs(gap) >= LARGE_GAP_SECONDS for gap in all_gaps)} "
                    "gaps with an absolute size of at least five minutes."
                ),
                (
                    "The final entry in each response has no trustworthy "
                    "`effective_end` because no following start is present."
                ),
            ]
        )

    lines.extend(["", "## Links and images", ""])
    for group, field in (
        ("linky", "program"),
        ("linky", "ivysilani"),
        ("obrazky", "tv_program"),
        ("obrazky", "nahled"),
    ):
        values = [_nested(programme, group, field) for programme in all_programmes]
        present = [value for value in values if _text(value) is not None]
        extensions = [_extension(value) for value in present]
        lines.append(
            f"- `{group}.{field}`: {len(present)}/{len(values)} present; extensions {_format_values(extensions)}."
        )

    lines.extend(
        [
            "",
            "## Normalization implications",
            "",
            ("- Normalize `{}`, empty strings, and missing optional scalar values to `None` at the parser boundary."),
            ("- Parse `datum` plus `cas` as a Europe/Prague timezone-aware start in production code."),
            (
                "- Preserve `stopaz` as source duration and derive `effective_end` "
                "only from the following programme start."
            ),
            ("- Treat each response as a broadcasting-day schedule that may continue past calendar midnight."),
            ("- Preserve accessibility fields independently: audio description, hidden subtitles,"),
            "  sign-language support, age labeling, and original audio.",
            (
                "- Treat observed values as samples, not closed enums, unless the "
                "official documentation defines the domain."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as err:
        msg = f"Invalid ISO date: {value}"
        raise argparse.ArgumentTypeError(msg) from err


def load_export_username(dotenv_path: Path = Path(".env")) -> str:
    """Load the registered export username from the project environment file."""
    load_dotenv(dotenv_path=dotenv_path, override=False)
    username = os.environ.get(EXPORT_USER_ENV)
    if not username:
        message = f"Set {EXPORT_USER_ENV} in {dotenv_path}; the value is never logged"
        raise ResearchError(message)
    return username


def _sample_requests(broadcast_date: date) -> list[tuple[str, date]]:
    return [
        ("ct1", broadcast_date),
        ("ct1", broadcast_date + timedelta(days=1)),
        *((channel, broadcast_date) for channel in DEFAULT_CHANNELS[1:]),
    ]


def _horizon_requests(broadcast_date: date, offsets: Sequence[int]) -> list[tuple[str, date]]:
    if any(offset < 1 for offset in offsets):
        message = "Horizon offsets must be positive whole days"
        raise ResearchError(message)
    return [("ct1", broadcast_date + timedelta(days=offset)) for offset in sorted(set(offsets))]


def _fixture_paths(paths: Sequence[Path]) -> list[Path]:
    result: list[Path] = []
    for path in paths:
        if path.is_dir():
            result.extend(sorted(path.glob("*.json")))
        else:
            result.append(path)
    return sorted(set(result))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect", help="download required sample coverage")
    collect.add_argument(
        "--date",
        type=_parse_date,
        default=datetime.now(tz=PRAGUE_TIME_ZONE).date(),
    )
    collect.add_argument("--output-dir", type=Path, default=Path("fixtures"))
    collect.add_argument("--delay", type=float, default=MIN_REQUEST_DELAY_SECONDS)

    fetch = subparsers.add_parser("fetch", help="download explicitly selected schedules")
    fetch.add_argument("--date", type=_parse_date, required=True)
    fetch.add_argument("--channel", action="append", required=True)
    fetch.add_argument("--output-dir", type=Path, default=Path("fixtures"))
    fetch.add_argument("--delay", type=float, default=MIN_REQUEST_DELAY_SECONDS)

    horizon = subparsers.add_parser("probe-horizon", help="probe progressively later ČT1 schedule dates")
    horizon.add_argument(
        "--date",
        type=_parse_date,
        default=datetime.now(tz=PRAGUE_TIME_ZONE).date(),
        help="base date (default: today in Europe/Prague)",
    )
    horizon.add_argument("--offsets", type=int, nargs="+", default=[7, 14, 21, 28])
    horizon.add_argument("--output-dir", type=Path, default=Path("fixtures/horizon"))
    horizon.add_argument("--delay", type=float, default=MIN_REQUEST_DELAY_SECONDS)

    analyse = subparsers.add_parser("analyse", help="analyse downloaded fixtures")
    analyse.add_argument("paths", nargs="+", type=Path)
    analyse.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line research tool."""
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "collect":
            collect_fixtures(
                username=load_export_username(),
                requests=_sample_requests(args.date),
                output_dir=args.output_dir,
                delay_seconds=args.delay,
            )
        elif args.command == "fetch":
            requests = [(channel, args.date) for channel in args.channel]
            collect_fixtures(
                username=load_export_username(),
                requests=requests,
                output_dir=args.output_dir,
                delay_seconds=args.delay,
            )
        elif args.command == "probe-horizon":
            collect_fixtures(
                username=load_export_username(),
                requests=_horizon_requests(args.date, args.offsets),
                output_dir=args.output_dir,
                delay_seconds=args.delay,
                stop_on_empty=True,
            )
        else:
            fixtures = [load_fixture(path) for path in _fixture_paths(args.paths)]
            if not fixtures:
                message = "No JSON fixtures found"
                raise ResearchError(message)
            report = build_report(fixtures)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(report, encoding="utf-8")
                print(f"Saved {args.output}")
            else:
                print(report)
    except ResearchError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
