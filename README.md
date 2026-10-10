# WaterSmart for Home Assistant

A custom integration built from the Milpitas WaterSmart HAR. It logs in with
email/password, downloads `RealTimeChart` history, and polls every 30 minutes.
The active account number is discovered from the portal.

## Install

Requires Home Assistant 2026.10 or newer. Tested against 2026.10.1.
No YAML configuration or additional runtime packages are required.

### HACS

Install and configure [HACS](https://www.hacs.dev/) first if it is not already
available. WaterSmart is a custom repository and is not listed in the default
HACS store.

1. Open **HACS** in the Home Assistant sidebar.
2. Select the **⋮** menu in the upper-right corner, then **Custom repositories**.
3. Enter `https://github.com/sivagorrepati/ha-watersmart` in **Repository**.
4. Choose **Integration** as the repository type/category and select **Add**.
5. Close the custom repositories dialog, search HACS for **WaterSmart**, and open it.
6. Select **Download**, confirm the version to install, and wait for it to finish.
7. Restart Home Assistant, then follow **Configure WaterSmart** below.

See the [HACS custom repository instructions](https://www.hacs.dev/docs/faq/custom_repositories/)
for details about adding a GitHub repository.

### Manual

Download `watersmart.zip` from the
[latest release](https://github.com/sivagorrepati/ha-watersmart/releases/latest)
and extract it into your Home Assistant configuration directory. Alternatively:

1. Copy `custom_components/watersmart` into your Home Assistant configuration
   directory under `custom_components/watersmart`.
2. Restart Home Assistant.
3. Follow **Configure WaterSmart** below.

## Configure WaterSmart

1. Open **Settings → Devices & services → Add integration**.
2. Search for and select **WaterSmart**.
3. Enter your utility portal URL (defaults to `https://milpitas.watersmart.com`),
   email, and password.
4. Submit the form and wait for the first download to complete. The integration
   discovers your active account number and creates its hourly water usage sensor.

## Add water usage to the Energy dashboard

Complete WaterSmart setup and its first successful download before adding water
consumption. The integration imports historical readings into long-term statistics
using their original hourly timestamps.

1. Open **Settings → Dashboards → Energy**.
2. Find the **Water consumption** section and select **Add water source** to open
   the **Configure water consumption** dialog.
3. In **Water consumption**, select **WaterSmart <account_number> hourly water usage**
   with **WaterSmart** shown as its source. For example, the fictional account `1234567` appears
   as **WaterSmart 1234567 hourly water usage** and uses statistic ID
   `watersmart:1234567_water_usage_hourly`.
4. Leave **Water flow rate** empty. This integration provides hourly consumption
   in gallons and does not provide an instantaneous flow rate. **No statistics
   available** in this optional dropdown is expected when you have no separate
   flow-rate sensor; it does not prevent saving water consumption.
5. Select **Do not track costs**, as shown in the configuration screenshot. You
   can configure costs separately later if you have a price or cost source.
6. Select **Save**.
7. Open **Energy** in the sidebar and select the **Water** tab. Use the date
   controls to view daily or monthly consumption, including imported history.
   Allow the dashboard to refresh after the initial statistics import.

Choose the **WaterSmart statistic** in the consumption selector. The live entity
`sensor.watersmart_<account_number>_water_usage_hourly` displays the latest hourly
reading and is not a cumulative consumption sensor, so it is not offered as an
Energy consumption source. Its normal History starts when the integration is
installed; the imported statistic supplies earlier consumption to Energy.

If the **Water consumption** selector has no WaterSmart entry:

- Check **Settings → Devices & services → WaterSmart** for setup or authentication
  errors and confirm that the first download succeeded.
- Open **Developer tools → States**, find your hourly sensor, and check that
  `cached_hours` is greater than zero and `historical_statistic_id` is present.
- Open **Developer tools → Statistics** and look for that statistic ID. If it
  remains missing, check **Settings → System → Logs** for WaterSmart or recorder
  errors. Home Assistant's recorder integration must be enabled to import history.

See [Home Assistant's water usage documentation](https://www.home-assistant.io/docs/energy/water/)
for more about water consumption in the Energy dashboard.

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

The [Release workflow](.github/workflows/release.yml) uses semantic versions,
conventional commit release notes, and GitHub releases.
Release names and new tags use plain versions such as `0.1.1`, without a `v`
prefix. The workflow recognizes existing prefixed tags using temporary local
aliases in the runner; those aliases are not pushed and old releases are unchanged.
It runs manually from GitHub Actions. Automatic releases on pushes and weekly
runs are disabled until release versioning is requested. It publishes only when
releasable changes exist. The first release
uses the existing `0.1.0` version; subsequent releases are calculated from commits:

- `fix: ...` creates a patch release.
- `feat: ...` creates a minor release.
- A `BREAKING CHANGE:` commit footer creates a major release.
- `docs: ...`, `test: ...`, and `chore: ...` do not create releases on their own.

When squash-merging a pull request, retain the conventional prefix in the final
commit title, for example `fix: repair WaterSmart session cleanup`. A title such
as `Fix WaterSmart session cleanup` does not trigger a semantic release; the
version calculation action reports `no info regarding next release` and stops
before ZIP creation or publication.

Before publication, tests and lint must pass. The workflow keeps `manifest.json`
and `pyproject.toml` versions aligned, commits the version bump, tags the release,
and uploads `watersmart.zip`. The ZIP contains the integration under
`custom_components/watersmart` and the Apache license. HACS downloads the tagged
repository using `hacs.json`; the ZIP is for manual installation.

Maintainers can run **Actions → Release → Run workflow** on `main`. The workflow
has an optional **version** field: leave it blank for conventional commit
versioning, or enter an explicit version such as `0.1.1` to release changes whose
squash commit did not retain a conventional prefix. Explicit versions must be
newer than the latest release and must not have an existing tag. This mode skips
semantic-release calculation, generates notes from commits since the last tag,
and runs the same validation, ZIP build, tag push, and publication steps.
The workflow
uses the built-in `GITHUB_TOKEN` with `contents: write`; it requires no personal
access token. Branch rules must allow its version commit and tag push.

Build an installation ZIP locally with:

```sh
python3 scripts/build_release.py --output dist/watersmart.zip
```

## License

Licensed under the [Apache License 2.0](LICENSE).
