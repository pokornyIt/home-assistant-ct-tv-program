"""Additional coverage for the Czech Television research CLI."""

from __future__ import annotations

import argparse
import json
import urllib.error
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Self

import pytest

from scripts import ct_program_research as research


def _programme(
    *,
    day: str = "2026-09-02",
    clock: str = "10:00",
    duration: str = "025:00",
    sound: object = "S",
) -> research.JsonObject:
    """Build a synthetic raw programme payload."""
    return {
        "linky": {"program": "https://example.test/show", "ivysilani": {}},
        "datum": day,
        "cas": clock,
        "nazvy": {
            "nadtitul": {},
            "nazev": "Test programme",
            "original": {},
            "nazev_casti": {},
        },
        "dil": {},
        "zanr": "Test",
        "stopaz": duration,
        "noticka": "Description",
        "regionalni": "N",
        "alternativa": "N",
        "ikonky": {
            "zvuk": sound,  # type: ignore[dict-item]
            "skryte_titulky": "1",
            "neslysici": "0",
            "ad": "1",
            "live": "0",
            "premiera": "1",
            "cb": "0",
            "hvezdicka": "0",
            "labeling": {},
            "puvodni_zneni": "0",
            "pomer": "16:9",
            "hd": "1",
        },
        "obrazky": {
            "tv_program": "https://example.test/image.GIF?size=small",
            "nahled": "https://example.test/preview.jpg",
        },
    }


def _schedule(*programmes: research.JsonObject) -> research.JsonObject:
    """Build a synthetic raw schedule payload."""
    return {
        "@attributes": {
            "datum_vysilani": "2026-09-02",
            "kanal": "ct1",
            "generovano": "2026-09-02 12:00:00",
        },
        "porad": list(programmes),
    }


class _Response:
    """Represent a synthetic synchronous HTTP response."""

    def __init__(self, payload: bytes) -> None:
        """Initialize a synthetic response.

        :param payload: Response body bytes.
        """
        self.payload = payload

    def __enter__(self) -> Self:
        """Enter the response context.

        :return: This response.
        """
        return self

    def __exit__(self, *args: object) -> None:
        """Exit the response context.

        :param *args: Context-manager exception details.
        """
        return None

    def read(self) -> bytes:
        """Return the response body bytes.

        :return: Response body bytes.
        """
        return self.payload


def test_fixture_properties_use_attributes_and_filename_fallback(tmp_path: Path) -> None:
    """Fixture metadata comes from attributes and has deterministic fallbacks.

    :param tmp_path: Temporary directory supplied by pytest.
    """
    schedule = _schedule(_programme())
    fixture = research.Fixture(tmp_path / "ct1-sample.json", schedule, schedule, [])
    fallback = research.Fixture(tmp_path / "ct2-sample.json", {}, {}, [])

    assert fixture.channel == "ct1"
    assert fixture.broadcast_date == "2026-09-02"
    assert fallback.channel == "ct2"
    assert fallback.broadcast_date == "unknown"


def test_scalar_and_request_helpers() -> None:
    """Scalar normalization and request construction preserve source semantics."""
    requested_date = date(2026, 9, 2)

    assert research._text(12) == "12"
    assert research._text(1.5) == "1.5"
    assert research._text(True) is None
    assert research._format_export_date(requested_date) == "02.09.2026"
    url = research._request_url("user name", "ct1", requested_date)
    assert "user=user+name" in url
    assert "date=02.09.2026" in url
    assert "channel=ct1" in url
    assert "json=1" in url


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"not-json", "invalid JSON"),
        (b"[]", "non-object JSON root"),
    ],
)
def test_download_rejects_invalid_responses(monkeypatch: pytest.MonkeyPatch, payload: bytes, message: str) -> None:
    """Downloads reject malformed and non-object JSON responses.

    :param monkeypatch: Pytest monkeypatch fixture.
    :param payload: Synthetic response body.
    :param message: Expected error message fragment.
    """

    def fake_urlopen(_request: object, *, timeout: int) -> _Response:
        """Return a synthetic response for the patched downloader.

        :param _request: Ignored request object.
        :param timeout: Request timeout.
        :return: Synthetic response.
        """
        assert timeout == 30
        return _Response(payload)

    monkeypatch.setattr(research.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(research.ResearchError, match=message):
        research._download("user", "ct1", date(2026, 9, 2))


def test_download_handles_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Network failures are wrapped in the research error type.

    :param monkeypatch: Pytest monkeypatch fixture.
    """

    def failing_urlopen(_request: object, *, timeout: int) -> _Response:
        """Raise a synthetic network failure.

        :param _request: Ignored request object.
        :param timeout: Request timeout used in the error message.
        :return: Never returns because the stub always raises.
        :raises urllib.error.URLError: Always raised by the stub.
        """
        raise urllib.error.URLError(f"timeout after {timeout}")

    monkeypatch.setattr(research.urllib.request, "urlopen", failing_urlopen)

    with pytest.raises(research.ResearchError, match="Failed to download ct1"):
        research._download("user", "ct1", date(2026, 9, 2))


def test_download_returns_valid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid JSON object bytes are returned without semantic rewriting.

    :param monkeypatch: Pytest monkeypatch fixture.
    """
    payload = json.dumps(_schedule(_programme())).encode()

    def fake_urlopen(_request: object, *, timeout: int) -> _Response:
        """Return the requested synthetic payload.

        :param _request: Ignored request object.
        :param timeout: Request timeout.
        :return: Synthetic response.
        """
        return _Response(payload)

    monkeypatch.setattr(research.urllib.request, "urlopen", fake_urlopen)

    assert research._download("user", "ct1", date(2026, 9, 2)) == payload


def test_collect_writes_sequential_fixtures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Collection waits between requests and atomically stores returned bytes.

    :param tmp_path: Temporary directory supplied by pytest.
    :param monkeypatch: Pytest monkeypatch fixture.
    :param capsys: Pytest output capture fixture.
    """
    payload = json.dumps(_schedule(_programme())).encode()
    delays: list[float] = []

    def fake_download(_username: str, _channel: str, _requested_date: date) -> bytes:
        """Return the synthetic schedule payload.

        :param _username: Ignored export username.
        :param _channel: Ignored channel.
        :param _requested_date: Ignored broadcast date.
        :return: Synthetic response bytes.
        """
        return payload

    monkeypatch.setattr(research, "_download", fake_download)
    monkeypatch.setattr(research.time, "sleep", delays.append)

    written = research.collect_fixtures(
        username="user",
        requests=[("ct1", date(2026, 9, 2)), ("ct2", date(2026, 9, 2))],
        output_dir=tmp_path,
        delay_seconds=90,
    )

    assert delays == [90]
    assert [path.name for path in written] == ["ct1-2026-09-02.json", "ct2-2026-09-02.json"]
    assert all(path.read_bytes() == payload for path in written)
    assert "Waiting 90 seconds" in capsys.readouterr().out


def test_collect_stops_at_empty_schedule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Horizon collection stops as soon as the export has no programmes.

    :param tmp_path: Temporary directory supplied by pytest.
    :param monkeypatch: Pytest monkeypatch fixture.
    """
    payload = b'{"error":"not found"}'

    def fake_download(_username: str, _channel: str, _requested_date: date) -> bytes:
        """Return the synthetic empty-schedule response.

        :param _username: Ignored export username.
        :param _channel: Ignored channel.
        :param _requested_date: Ignored broadcast date.
        :return: Synthetic response bytes.
        """
        return payload

    def skip_sleep(_delay: float) -> None:
        """Skip the collection delay in the test.

        :param _delay: Ignored delay value.
        """
        return None

    monkeypatch.setattr(research, "_download", fake_download)
    monkeypatch.setattr(research.time, "sleep", skip_sleep)

    written = research.collect_fixtures(
        username="user",
        requests=[("ct1", date(2026, 9, 2)), ("ct1", date(2026, 9, 3))],
        output_dir=tmp_path,
        delay_seconds=90,
        stop_on_empty=True,
    )

    assert len(written) == 1


def test_object_and_programme_validation() -> None:
    """JSON object and programme container variants are validated explicitly."""
    assert research._as_object({"key": "value"}, context="root") == {"key": "value"}
    with pytest.raises(research.ResearchError, match="Expected an object"):
        research._as_object([], context="root")
    with pytest.raises(research.ResearchError, match="string object keys"):
        research._as_object({1: "value"}, context="root")

    wrapped: research.JsonObject = {"program": _schedule(_programme())}
    assert research._extract_schedule(wrapped)["porad"]
    assert research._extract_programmes({"porad": {}}) == []
    assert research._extract_programmes({"porad": None}) == []
    assert research._extract_programmes({}) == []
    with pytest.raises(research.ResearchError, match="object or list"):
        research._extract_programmes({"porad": "invalid"})
    with pytest.raises(research.ResearchError, match=r"porad\[0\]"):
        research._extract_programmes({"porad": ["invalid"]})


def test_load_fixture_success_and_errors(tmp_path: Path) -> None:
    """Fixture loading reports filesystem and JSON failures with path context.

    :param tmp_path: Temporary directory supplied by pytest.
    """
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(_schedule(_programme())), encoding="utf-8")

    fixture = research.load_fixture(valid)

    assert fixture.channel == "ct1"
    assert len(fixture.programmes) == 1
    with pytest.raises(research.ResearchError, match="Cannot load fixture"):
        research.load_fixture(tmp_path / "missing.json")
    invalid = tmp_path / "invalid.json"
    invalid.write_text("invalid", encoding="utf-8")
    with pytest.raises(research.ResearchError, match="Cannot load fixture"):
        research.load_fixture(invalid)


def test_walk_value_types_and_formatting_helpers() -> None:
    """Recursive structural analysis covers objects, lists, empties, and scalars."""
    walked = list(research._walk({"items": [{"name": "one"}], "empty": {}, "list": []}))

    assert ("items[].name", "one") in walked
    assert ("empty", {}) in walked
    assert ("list[]", []) in walked
    assert research._value_type({}) == "empty object"
    assert research._value_type(None) == "null"
    assert research._value_type("value") == "str"
    assert research._extension(None) is None
    assert research._extension("https://example.test/no-extension") == "(none)"
    assert research._extension("https://example.test/image.JPG?x=1") == ".jpg"
    assert research._nested({}, "group", "field") is None
    assert research._format_values([]) == "none"
    assert research._format_values(["b", "a", "a"]) == '`"a"`, `"b"`'


@pytest.mark.parametrize(
    ("programme", "message"),
    [
        ({"cas": "10:00", "stopaz": "010:00"}, "missing datum or cas"),
        ({"datum": "bad", "cas": "10:00", "stopaz": "010:00"}, "Invalid programme start"),
        ({"datum": "2026-09-02", "cas": "10:00"}, "missing stopaz"),
        ({"datum": "2026-09-02", "cas": "10:00", "stopaz": "bad"}, "Invalid stopaz"),
    ],
)
def test_timing_validation_errors(programme: dict[str, object], message: str) -> None:
    """Missing or malformed required timing fields fail clearly.

    :param programme: Synthetic programme payload.
    :param message: Expected error message fragment.
    """
    with pytest.raises(research.ResearchError, match=message):
        research.calculate_timings([programme])


def test_build_report_covers_structure_timing_and_empty_fixture(tmp_path: Path) -> None:
    """The report includes observed differences, timings, links, and MD013 guards.

    :param tmp_path: Temporary directory supplied by pytest.
    """
    first = _programme()
    second = _programme(clock="10:30", sound={})
    schedule = _schedule(first, second)
    fixture = research.Fixture(tmp_path / "ct1.json", schedule, schedule, [first, second])
    empty = research.Fixture(tmp_path / "empty.json", {"error": "missing"}, {"error": "missing"}, [])

    report = research.build_report([fixture, empty])

    assert report.count("<!-- markdownlint-disable MD013 -->") == 5
    assert report.count("<!-- markdownlint-enable MD013 -->") == 5
    assert "empty object" in report
    assert "missing `alternativa`" in report
    assert "slot gaps range" in report
    assert '`".gif"`' in report


def test_build_report_without_programmes(tmp_path: Path) -> None:
    """An entirely empty fixture still produces a useful deterministic report.

    :param tmp_path: Temporary directory supplied by pytest.
    """
    fixture = research.Fixture(tmp_path / "ct1.json", {}, {}, [])

    report = research.build_report([fixture])

    assert "No inconsistent leaf types were observed." in report
    assert "| `ct1.json` | none | none | 0s | 0s | 0 | 0 |" in report


def test_argument_and_path_helpers(tmp_path: Path) -> None:
    """Date, request-list, and fixture-path helpers validate and sort inputs.

    :param tmp_path: Temporary directory supplied by pytest.
    """
    requested_date = date(2026, 9, 2)
    assert research._parse_date("2026-09-02") == requested_date
    with pytest.raises(argparse.ArgumentTypeError, match="Invalid ISO date"):
        research._parse_date("02.09.2026")
    with pytest.raises(research.ResearchError, match="positive whole days"):
        research._horizon_requests(requested_date, [0])
    assert len(research._sample_requests(requested_date)) == 7

    directory = tmp_path / "fixtures"
    directory.mkdir()
    first = directory / "b.json"
    second = directory / "a.json"
    first.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")
    assert research._fixture_paths([directory, first]) == [second, first]
    assert research._build_parser().parse_args(["analyse", "fixtures"]).command == "analyse"


def test_missing_export_username(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing CT_USER produces a non-sensitive configuration error.

    :param tmp_path: Temporary directory supplied by pytest.
    :param monkeypatch: Pytest monkeypatch fixture.
    """
    monkeypatch.delenv(research.EXPORT_USER_ENV, raising=False)
    with pytest.raises(research.ResearchError, match="Set CT_USER"):
        research.load_export_username(tmp_path / "missing.env")


@pytest.mark.parametrize("command", ["collect", "fetch", "probe-horizon"])
def test_main_download_commands(command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every download CLI branch passes resolved arguments to collection.

    :param command: CLI command under test.
    :param tmp_path: Temporary directory supplied by pytest.
    :param monkeypatch: Pytest monkeypatch fixture.
    """
    calls: list[dict[str, object]] = []

    def fake_collect(**kwargs: object) -> list[Path]:
        """Record synthetic collection arguments.

        :param **kwargs: Collection arguments.
        :return: Empty list of written paths.
        """
        calls.append(kwargs)
        return []

    monkeypatch.setattr(research, "load_export_username", lambda: "user")
    monkeypatch.setattr(research, "collect_fixtures", fake_collect)
    arguments = [command, "--date", "2026-09-02", "--output-dir", str(tmp_path)]
    if command == "fetch":
        arguments.extend(["--channel", "ct1"])
    if command == "probe-horizon":
        arguments.extend(["--offsets", "7", "14"])

    assert research.main(arguments) == 0
    assert calls[0]["username"] == "user"
    assert calls[0]["output_dir"] == tmp_path


def test_main_analyse_output_and_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Analysis CLI can write a report file or emit it to stdout.

    :param tmp_path: Temporary directory supplied by pytest.
    :param capsys: Pytest output capture fixture.
    """
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps(_schedule(_programme())), encoding="utf-8")
    output = tmp_path / "nested" / "report.md"

    assert research.main(["analyse", str(fixture), "--output", str(output)]) == 0
    assert output.read_text(encoding="utf-8").startswith("# Czech Television")
    assert research.main(["analyse", str(fixture)]) == 0
    assert "# Czech Television" in capsys.readouterr().out


def test_main_reports_expected_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Expected runtime errors return status one without a traceback.

    :param tmp_path: Temporary directory supplied by pytest.
    :param monkeypatch: Pytest monkeypatch fixture.
    :param capsys: Pytest output capture fixture.
    """

    def no_fixture_paths(_paths: Sequence[Path]) -> list[Path]:
        """Return no paths for the error-path test.

        :param _paths: Ignored input paths.
        :return: Empty path list.
        """
        return []

    monkeypatch.setattr(research, "_fixture_paths", no_fixture_paths)

    assert research.main(["analyse", str(tmp_path)]) == 1
    assert "No JSON fixtures found" in capsys.readouterr().err
