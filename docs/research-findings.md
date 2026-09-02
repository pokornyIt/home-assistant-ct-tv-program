# Czech Television programme export findings

## Scope and method

Research was performed on 2026-09-02 against only the official registered Czech
Television programme export with `json=1`. Requests were made sequentially with a
minimum 90-second delay by `scripts/ct_program_research.py`. The registered username
was loaded from an ignored `.env` file and was neither stored in fixtures nor logged.

The generated quantitative analysis is in [research.md](research.md). Raw JSON
responses remain local because the official export terms prohibit redistribution of
the downloaded schedule in a machine-readable format without Czech Television's
consent.

## Supported channels

The following current channels returned complete schedules and are suitable for the
integration:

<!-- markdownlint-disable MD013 -->
| Identifier | Channel  |
| ---------- | -------- |
| `ct1`      | ČT1      |
| `ct2`      | ČT2      |
| `ct24`     | ČT24     |
| `ct4`      | ČT sport |
| `ct5`      | ČT :D    |
| `ct6`      | ČT art   |
<!-- markdownlint-enable MD013 -->

The official documentation still lists `ct7` for the discontinued ČT3 service. A live
probe for 2026-09-02 returned only the JSON error
`XML soubor programu ct7 ... nebyl nalezen` and no schedule. It is therefore verified
as unavailable and is not part of the supported-channel list.

## Availability horizon

ČT1 returned full schedules for offsets +7, +14, +15, +16, +17, and +18 days from
2026-09-02. Offset +19 returned the JSON error
`XML soubor programu ... nebyl nalezen` and no programme list (as did the earlier
+21 probe). At the observation time, the exact available horizon was therefore 18
days. Consumers must handle this as moving availability rather than a fixed contract.

An unavailable schedule has a structurally different top-level object containing
only `error`. It is not an empty valid schedule and should become a typed
not-available response in the future client.

## Response structure

A successful JSON response is an object with:

- `@attributes`: `datum_vysilani`, `kanal`, and `generovano`;
- `porad`: an ordered list of programme objects.

Each programme in the samples contained these groups and scalar fields:

- `linky`: `program`, `ivysilani`;
- `datum`, `cas`;
- `nazvy`: `nadtitul`, `nazev`, `original`, `nazev_casti`;
- `dil`, `zanr`, `stopaz`, `noticka`, `regionalni`, `alternativa`;
- `ikonky`: `zvuk`, `skryte_titulky`, `neslysici`, `ad`, `live`, `premiera`,
  `cb`, `hvezdicka`, `labeling`, `puvodni_zneni`, `pomer`, `hd`;
- `obrazky`: `tv_program`, `nahled`.

The JSON name is `ikonky`, although the current documentation describes the XML group
as `ikony`. All successful channel samples had the same field paths.

## Normalization rules

Optional XML elements are emitted as `{}` in JSON. This was observed for titles,
episode information, genre, description, sound, age labeling, and images. The parser
must normalize `{}`, missing fields, and empty strings to `None` at the transport
boundary.

Boolean/status values are strings (`"0"` and `"1"`), not JSON booleans. They should be
converted explicitly and unknown values must not silently become `True`.

The observed sound values were `M`, `S`, `D`, `E`, and an empty object. These align
with documented mono, stereo, dual, and Dolby values, but the parser should preserve
unknown future values. Observed aspect-ratio values were `16:9`, `16:9-CS`, `4:3`, and
`HD-4:3`; the latter two composite forms are not covered by the documented two-value
description, so this field must not be a closed enum. Observed age labels were `8+`,
`15+`, and empty.

Both programme links were present in all 268 representative current-day entries and
had no filename extension. The documentation says `ivysilani` has contained the same
value as `program` since 2025-02-07. Images were incomplete: `tv_program` was present
for 227/268 entries (`.gif` or `.jpg`) and `nahled` for 238/268 entries (`.jpg`). The
documentation marks images as unsupported, so they may be exposed opportunistically
but cannot be relied upon as stable identifiers.

## Timing and broadcasting-day semantics

The six channel responses started around 06:00. ČT1, ČT2, ČT24, ČT sport, and ČT art
continued into the following calendar day until roughly 05:10-05:45. ČT :D ended at
19:45 and ČT art began at 20:00, reflecting their shared broadcast capacity. A
broadcasting day must therefore not be filtered to its nominal calendar date.

Across the seven representative current/tomorrow samples, calculated slot differences
ranged from -1,560 to +3,337 seconds, with both overlaps and gaps. Consequently:

```text
content_end = start + source duration
effective_end = next programme start
```

`effective_end` is authoritative for current-programme selection. Source duration must
remain separate metadata. The last entry in a response has no trustworthy
`effective_end` until a following schedule has been merged; it must remain `None`
rather than being invented from duration.

Production parsing must combine `datum` and `cas` in `Europe/Prague` using aware
datetimes. Fixtures cover calendar-midnight transitions. Dedicated implementation
tests must additionally cover daylight-saving gaps and folds.

## Recommended normalized model

The first production parser should normalize into a typed immutable `Program` model:

```text
title: str
subtitle: str | None
original_title: str | None
supertitle: str | None
start: aware datetime
duration: timedelta
effective_end: aware datetime | None
description: str | None
genre: str | None
episode: int | None
episode_count: int | None
program_url: str | None
ivysilani_url: str | None
image: str | None
thumbnail: str | None
audio_description: bool
hidden_subtitles: bool
for_deaf: bool
live: bool
premiere: bool
age_rating: str | None
original_audio: bool
hd: bool
sound: str | None
aspect_ratio: str | None
black_and_white: bool
```

Malformed required values such as title, date/time, or duration should reject the
entry with a clear parser error. Malformed optional metadata should be normalized or
preserved as an unknown value according to the field, without losing the schedule.

## Update strategy

Use one coordinator for all selected channels and a central rate limiter. Determine
the relevant broadcasting day locally (approximately 06:00 to the following morning),
fetch one schedule per selected channel, and compute transitions from the cached
ordered schedule. Refresh published schedules approximately every 30 minutes, while
staggering all requests so the registered account never exceeds the official
one-request-per-minute limit; the research tool retains the more conservative
90-second interval.

Near the final known item, obtain and merge the next broadcasting day so its first
start can close the previous final slot. Retain the last valid schedule on transient
network failures. Treat an unavailable future schedule as expected horizon state, not
as a destructive refresh failure. The `generovano` value should support diagnostics
and change detection but should not be exposed as programme metadata.

## Schedule changes

The export documentation and manual observations in issue #1 confirm that generated
schedules can change during the day. This run did not poll solely to manufacture a
second version. The future client must therefore replace schedules atomically after
successful validation and keep previously valid data on failure.

## Constraints and open questions

- Raw fixtures cannot be published without clarifying the export's redistribution
  restriction or obtaining consent from Czech Television.
- `ct7` remains in the official identifier list even though its live response is a
  clean not-available error; documentation consumers must not infer current support
  from that list alone.
- Image fields are returned but explicitly documented as unsupported.
- The export provides no slot-end field, and the last item cannot be closed from a
  single response.

## Proposed follow-up issues

1. Implement the typed client, normalization boundary, programme model, and schedule
   merge/current-next calculations with synthetic fixtures and edge-case tests.
2. Add the Home Assistant config flow, coordinator, lifecycle handling, and one device
   per selected channel with current/next entity data.
3. Add diagnostics, accessibility-focused attributes/translations, and documentation,
   then complete HACS and hassfest validation.
