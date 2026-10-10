# WaterSmart for Home Assistant

A custom integration built from the Milpitas WaterSmart HAR. It logs in with
email/password, downloads `RealTimeChart` history, and polls every 30 minutes.
The active account number is discovered from the portal.

## Install

### HACS

Add `https://github.com/sivagorrepati/ha-watersmart` under HACS → Custom repositories
with category **Integration**, then download **WaterSmart** and restart Home Assistant.
This repository is installed as a custom repository; it is not listed in the default store.

### Manual

Download `watersmart.zip` from the
[latest release](https://github.com/sivagorrepati/ha-watersmart/releases/latest)
and extract it into your Home Assistant configuration directory. Alternatively:

1. Copy `custom_components/watersmart` into your Home Assistant configuration
   directory under `custom_components/watersmart`.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → WaterSmart**.
4. Enter your utility portal URL (defaults to `https://milpitas.watersmart.com`),
   email, and password.

Requires Home Assistant 2026.10 or newer. Tested against 2026.10.1.
No YAML configuration or additional runtime packages are required.

## Sensor and history

The sensor is created as:

```text
sensor.watersmart_<account_number>_water_usage_hourly
```

Its state is **gallons for the latest completed hour returned by the utility**,
not necessarily the previous wall-clock hour. `reading_start` is that reading's
UTC timestamp. Additional attributes expose `last_download`, `cached_hours`, and
`historical_statistic_id`. Home Assistant preserves an existing entity registry
name; name collisions get the usual suffix. Account numbers are normalized to
valid entity IDs, preserving leading zeros.

All downloaded hours, the last hour, and the last successful download time are
persisted in `.storage/watersmart.<entry_id>.hourly`. Older data remains cached
when the API's history window rolls forward. Repeated timestamps are deduplicated;
revised readings replace earlier values. Missing readings remain unknown.
The API capture demonstrates a full-history request; unsupported incremental
query parameters are not invented. Each poll fetches the history and merges it.

Historical readings are also imported into recorder's long-term statistics as:

```text
watersmart:<account_number>_water_usage_hourly
```

Home Assistant cannot backdate live sensor states through its entity API, so the
sensor's normal History begins at installation; the imported statistic supplies
earlier hourly history. It stores cumulative gallons and supports hourly `change`
charts. Only new or corrected hours and affected later sums are imported during
normal polling. On restart, cached history is reimported idempotently so an
interrupted recorder write can recover. The live hourly sensor intentionally has
no `state_class`: a declining interval volume is not a cumulative meter, and
polling delayed readings should not produce misleading water totals.

Example dashboard card (replace `1234567` with your account number):

```yaml
type: statistics-graph
title: Hourly water usage
chart_type: bar
period: hour
days_to_show: 7
stat_types:
  - change
entities:
  - watersmart:1234567_water_usage_hourly
```

## Authentication and failures

Each entry has its own in-memory cookie jar. Login fetches the hidden form token
and posts `token`, `email`, and `password` with `forceEmail=1`, matching the capture.
On an expired session it logs in again automatically and retries once. Rejected
credentials trigger Home Assistant's reauthentication dialog. Reauthentication
must resolve to the same portal account. Network/service failures mark the sensor
unavailable and are retried; the disk cache is retained. Initial setup requires a
successful online fetch, even if a cache exists.

Credentials are stored by Home Assistant in its config entry and never written
to the hourly cache. HTTPS certificate checks remain enabled and redirects must
stay within the utility portal. The integration does not ship the HAR or reuse
captured cookies. Treat the original HAR as sensitive.

The capture covers one active account and does not establish a multi-account
switch API, MFA, or CAPTCHA handling. Those workflows are not supported. Different
utility portals may have different markup. No live login is performed during
development tests.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

The implementation follows Home Assistant recommendations for
[coordinated polling](https://developers.home-assistant.io/docs/integration_fetching_data/),
[reauthentication](https://developers.home-assistant.io/docs/core/integration/config_flow/#reauthentication),
and [sensor semantics](https://developers.home-assistant.io/docs/core/entity/sensor/).

## Releases

The [Release workflow](.github/workflows/release.yml) follows the
[Kia Uvo release workflow](https://github.com/Hyundai-Kia-Connect/kia_uvo/blob/master/.github/workflows/release.yml)
pattern: semantic versions, conventional commit release notes, and GitHub releases.
It runs on pushes to `main`, manually from GitHub Actions, and weekly on Sunday
at 08:00 UTC. It publishes only when releasable changes exist. The first release
uses the existing `0.1.0` version; subsequent releases are calculated from commits:

- `fix: ...` creates a patch release.
- `feat: ...` creates a minor release.
- A `BREAKING CHANGE:` commit footer creates a major release.
- `docs: ...`, `test: ...`, and `chore: ...` do not create releases on their own.

Before publication, tests and lint must pass. The workflow keeps `manifest.json`
and `pyproject.toml` versions aligned, commits the version bump, tags the release,
and uploads `watersmart.zip`. The ZIP contains the integration under
`custom_components/watersmart` and the Apache license. HACS downloads the tagged
repository using `hacs.json`; the ZIP is for manual installation.

Maintainers can run **Actions → Release → Run workflow** on `main`. The workflow
uses the built-in `GITHUB_TOKEN` with `contents: write`; it requires no personal
access token. Branch rules must allow its version commit and tag push.

Build an installation ZIP locally with:

```sh
python3 scripts/build_release.py --output dist/watersmart.zip
```

## License

Licensed under the [Apache License 2.0](LICENSE).
