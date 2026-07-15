# ADR-0006 — General config file & display timezones

- **Status:** Accepted
- **Date:** 2026-06-19
- **Related:** [ADR-0003](0003-config-and-secrets-via-env-file.md) (secrets in `.env`).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
General, non-secret options (starting with the **display timezone**) shouldn't be
hard-coded. Secrets already live in `.env` (ADR-0003) and *what to monitor* lives
in `checks/`; general display/runtime options need a home too.

## Decision
- General options live in a YAML **`config.yaml`** (working directory; override with
  `LITTLE_SISTER_CONFIG`), read once at startup into a frozen `Config`. Missing file
  or keys fall back to defaults; an invalid value is logged and defaulted.
- First options: **`timezone`** (an IANA name, default `Europe/Berlin`) and
  **`time_format`** (a `strftime` string). Adding an option is a field + a default.
- Timestamps are **stored as the server's local time** (unchanged); they are
  **converted at display time** to the configured timezone via a `localtime` Jinja
  filter. `zoneinfo` does the conversion, with the `tzdata` package for portability.

## Consequences
- All displayed timestamps (check detail, history, events, system) render in the
  configured zone with a consistent format; the stored model is untouched.
- `config.yaml` is the place for future general options; secrets stay in `.env`
  and check definitions stay in `checks/` — three small, separate config surfaces.

## Alternatives considered
- **Store timestamps in UTC** and convert on display — also correct, but a bigger
  change (model + tests) for no display benefit, since converting the naive local
  value is unambiguous via `datetime.astimezone()`.
- **Reuse `.env` / environment variables** for the timezone — works, but a YAML
  config file reads better for a growing set of general options and matches the
  rest of the app's YAML config.
