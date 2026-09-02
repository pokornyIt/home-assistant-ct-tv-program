# Home Assistant CT TV Program

Research and future Home Assistant integration for the official Czech Television
programme export.

## Research setup

The downloader uses the registered export username from a local `.env` file. Raw
responses are intentionally ignored by Git because the export terms restrict
redistribution in a machine-readable format.

```bash
cp .env.example .env
# Set CT_USER in .env
uv sync
```

Collect the representative channel set for a broadcasting day:

```bash
uv run python -m scripts.ct_program_research collect --date 2026-09-02
```

Probe progressively later ČT1 dates, stopping at the first unavailable schedule:

```bash
uv run python -m scripts.ct_program_research probe-horizon \
  --date 2026-09-02 --offsets 7 14 21 28
```

Generate the analysis from locally collected fixtures:

```bash
uv run python -m scripts.ct_program_research analyse \
  fixtures fixtures/horizon --output docs/research.md
```

All live requests are sequential and the tool enforces at least 90 seconds between
requests in a single invocation.

## Validation

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv run pre-commit run --all-files
```
