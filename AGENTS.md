# Repository Instructions

## Scope and source of truth

These instructions apply to the entire repository.

GitHub issues define the product scope and implementation roadmap.

Read the active issue and relevant open roadmap issues before making architectural
decisions. Implement only the active issue unless the user explicitly expands the
scope.

The project is a Home Assistant integration for Czech Television programme data.

The primary product goals are:

* expose the programme currently airing on selected Czech Television channels;
* expose when the current programme started and when its broadcast slot ends;
* expose the next programme and its start time;
* provide useful programme metadata;
* provide accessibility metadata suitable for Home Assistant UI, automations, Assist, and voice output.

Accessibility is a first-class use case. Do not remove or unnecessarily simplify
metadata related to audio description, subtitles, deaf viewers, age rating, or similar
programme properties.

## Communication and language

* Communicate with the user in Czech.
* Write source code and technical artifacts in English.
* Keep English and Czech translation files synchronized whenever user-facing integration text changes.
* Use English for identifiers, comments, docstrings, tests, logs, errors,
  configuration comments, documentation, commit messages, issue implementation
  summaries, and pull request text.
* Use `pokornyIt` whenever the repository owner or author's name is required.

## Data source

Use only the official Czech Television registered programme export documented at:

* [TV programme export](https://www.ceskatelevize.cz/xml/tv-program/)
* [TV programme export information](https://www.ceskatelevize.cz/xml/tv-program/informace/)

Do not build production functionality on undocumented or internal Czech Television APIs such as `/api/tv-program`.

Prefer the official JSON representation using `json=1` unless an active issue explicitly requires XML handling.

The registered export username is configuration data and must not be hard-coded into production code.

Never require or store activation hashes, passwords, browser cookies, API tokens, or
credentials obtained from Czech Television applications.

Respect Czech Television request limits.

For research tools and tests that perform live requests:

* requests must be sequential;
* wait at least 90 seconds between requests unless official documentation explicitly permits a shorter interval;
* do not perform unnecessary polling;
* do not parallelize programme export requests.

Production integration code should minimize network requests and determine current/next
programme locally from cached schedule data whenever possible.

## Programme data semantics

Do not assume that programme duration (`stopaz`) is the end of the broadcast slot.

The expected model is:

```text
content_end = start + duration
effective_end = next programme start
```

For determining which programme is currently on air, prefer `effective_end` based on the next scheduled programme.

Keep the source duration separately as programme metadata.

Do not silently invent an effective end for the last known programme if the next programme is unavailable.

Czech Television programme responses may span calendar midnight. Treat the returned
data as a broadcasting schedule, not as a simple calendar-day list.

Use timezone-aware datetimes and Home Assistant datetime helpers. Do not implement
programme selection using naive local datetimes.

Normalize inconsistent empty source values at the data boundary. The JSON export may
represent empty XML elements as objects such as `{}` rather than `null` or empty
strings.

Do not leak source-format quirks into Home Assistant entities or the rest of the application.

## Home Assistant architecture

Target the current Home Assistant architecture defined by the active roadmap issues
and current Home Assistant developer documentation.

Use native Home Assistant integration patterns:

* config entries;
* config flow;
* options flow when needed;
* translations;
* asynchronous APIs;
* `DataUpdateCoordinator` or an equally appropriate current Home Assistant coordinator pattern;
* device and entity registries;
* diagnostics where useful.

Configuration is UI-only unless an active issue explicitly requires otherwise. Do not add YAML configuration.

Keep the integration under:

```text
custom_components/ct_tv_program/
```

Use the domain:

```text
ct_tv_program
```

A selected Czech Television channel should normally be represented as one Home Assistant device.

Avoid creating large numbers of entities for individual programme fields when
attributes or another native Home Assistant representation provide a cleaner model.

Do not expose internal transport details or raw Czech Television payloads as user-facing entities.

Keep setup, unload, reload, coordinator shutdown, and resource cleanup lifecycle-safe.

## Network access

Use Home Assistant's shared asynchronous HTTP infrastructure for production network access.

Do not use synchronous `requests` in integration code.

Use explicit request timeouts and handle temporary network failures without destroying
previously valid schedule data when retaining cached data is safe.

Do not perform network access from entity properties.

Entities should read already normalized coordinator data.

## Code organization

Keep responsibilities in focused modules with clear boundaries between:

* Home Assistant lifecycle;
* configuration and options flows;
* Czech Television HTTP client;
* source payload parsing and normalization;
* programme data models;
* schedule/current-next calculation;
* coordinator/update logic;
* Home Assistant devices and entities;
* diagnostics;
* Assist/conversation functionality when introduced.

Do not place unrelated behaviour into `__init__.py`, `config_flow.py`, or entity modules.

Keep Czech Television protocol details outside Home Assistant entity classes.

Prefer a small typed client/parser boundary so raw upstream data is converted into
stable internal models before Home Assistant consumes it.

Avoid premature abstractions and do not implement roadmap work before its issue.

## Programme model

Prefer explicit typed internal models over passing raw nested dictionaries through the integration.

The expected programme model may include concepts such as:

```text
title
subtitle
original_title
supertitle

start
duration
effective_end

description
genre
episode
episode_count

program_url
ivysilani_url
image
thumbnail

audio_description
hidden_subtitles
for_deaf
live
premiere
age_rating
original_audio
hd
sound
aspect_ratio
```

This list is guidance, not a requirement to expose every upstream field.

Preserve useful accessibility information even if it is not initially exposed as a
dedicated Home Assistant entity.

## Python toolchain and style

* Use the Python version pinned in `.python-version`.
* Use `uv` for dependency management, environments, locking, and tool execution.
* Keep the project environment in `.venv`.
* Declare development dependencies in `pyproject.toml`.
* Keep `uv.lock` synchronized.
* Do not use `pip install` for project setup.
* Do not add `requirements.txt` for development tooling.
* Do not add a production dependency without a concrete need and an explanation in the change summary.
* Add precise type annotations and concise English docstrings to integration code.
* Prefer small, async, deterministic functions and Home Assistant helpers.
* Do not perform blocking I/O in the Home Assistant event loop.

## Research code and fixtures

Research tooling must remain clearly separated from production integration code.

When available, local raw Czech Television research responses conventionally live
under `fixtures/`. The repository intentionally ignores `fixtures/**/*.json` because
raw programme exports must never be committed, published, redistributed, attached to
issues or pull requests, included in CI artifacts, snapshots, logs, documentation, or
releases. Agents may inspect these local files when useful for understanding the real
source structure, ordering, timing, and edge cases.

These local raw files are research/reference input only; they are not repository test
fixtures in the publishable sense. Tests must use separately constructed synthetic
data derived from documented structure and observed behaviour, never copies or
mechanically reduced extracts of raw schedules that reproduce machine-readable
programme data. The implementation must not fail when the local `fixtures/` directory
or particular raw files are absent, and no production code may depend on it.

Scripts used to inspect Czech Television data may live under:

```text
scripts/
```

Raw Czech Television programme responses must never be committed, published,
redistributed, or embedded in repository fixtures or examples. This prohibition also
applies to pull requests, release assets, CI artifacts, snapshots, logs, and
documentation attachments.

Tests, examples, and documentation may use only:

* synthetic fixtures based on the documented or observed response structure;
* derived statistics and findings that do not reproduce a machine-readable schedule;
* manually constructed edge-case data.

Research tools may download raw responses locally when explicitly required. All such
downloads must remain ignored by Git and untracked, and must not be copied into any
published artifact.

Do not make normal unit tests depend on live Czech Television access.

Historical project:

```text
https://github.com/pokornyIt/ha-tv-program-ct-devel
```

may be inspected for historical research and edge cases only.

Do not copy its AppDaemon architecture into this project.

## Security and privacy

Never commit:

* activation links or activation hashes;
* passwords;
* authentication cookies;
* private tokens;
* unrelated personal data.

Avoid logging complete request URLs when doing so would expose configuration values unnecessarily.

Diagnostics must contain only information useful for troubleshooting and should not
include raw schedules when a smaller normalized diagnostic representation is
sufficient.

## Testing and validation

Add or update tests with each behaviour change.

Tests must cover important schedule edge cases, including when relevant:

* empty values represented as `{}`;
* missing optional metadata;
* programme transitions;
* gaps between `start + duration` and the next programme;
* overlaps;
* transitions across midnight;
* missing next programme;
* schedule refresh failures;
* accessibility flags;
* timezone and daylight-saving transitions.

Tests must not require:

* live Home Assistant services;
* live Czech Television access;
* real user credentials;
* wall-clock waiting.

Use time-freezing or Home Assistant time helpers rather than actual sleeps for programme-transition tests.

For a normal Python change, run all configured checks:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv run pre-commit run --all-files
```

Run HACS and hassfest validation when their workflows or local tooling are introduced.

Do not report a check as passing if it could not be run.

## Change discipline

* Inspect the working tree before editing and preserve unrelated user changes.
* Make focused changes and avoid unrelated refactoring.
* Do not edit generated files manually when a generator is available.
* Keep manifest metadata, translations, tests, documentation, and fixtures consistent.
* Do not broaden an issue into later roadmap work without explicit user approval.
* Record important architectural decisions and research findings in the active GitHub
  issue when issue-based tracking is being used.
* Do not mark work complete before relevant validation passes.
* Report implemented behaviour, architectural decisions, validation results,
  discovered upstream quirks, and intentionally deferred work.

## GitHub workflow

Use GitHub issues as the implementation unit.

Before starting implementation:

1. read the active issue completely;
2. inspect relevant linked or roadmap issues;
3. inspect current repository instructions;
4. inspect existing implementation before proposing structural changes.

Prefer one focused branch and pull request per implementation issue unless the issue
explicitly defines another workflow.

Do not close research or implementation issues merely because code exists. Confirm
that the issue acceptance criteria are satisfied.

## Project-local Codex skills

Project-local skills live under:

```text
.agents/skills/<skill-name>/
```

Skills may be introduced later for repeatable project workflows.

Do not assume a project-local skill exists unless it is present in the repository.

## Markdown tables

Surround every Markdown table with comments that disable and then re-enable the
MD013 line-length rule:

```markdown
<!-- markdownlint-disable MD013 -->
| Column | Column |
| ------ | ------ |
| Value  | Value  |
<!-- markdownlint-enable MD013 -->
```
