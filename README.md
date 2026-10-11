# HA WaterSmart for Home Assistant

Track your WaterSmart water usage in Home Assistant. Sign in with your utility
portal email and password to view hourly consumption and available historical
usage in the Energy dashboard. The integration checks for updates every 30 minutes
and discovers your active account automatically.

## Install

Requires Home Assistant 2026.10 or newer. Tested against 2026.10.1.
No YAML configuration or additional runtime packages are required.

### HACS

Install and configure [HACS](https://www.hacs.dev/) first if it is not already
available. HA WaterSmart is a custom repository and is not listed in the default
HACS store.

1. Open **HACS** in the Home Assistant sidebar.
2. Select the **⋮** menu in the upper-right corner, then **Custom repositories**.
3. Enter `https://github.com/sivagorrepati/ha-watersmart` in **Repository**.
4. Choose **Integration** as the repository type/category and select **Add**.
5. Close the custom repositories dialog, search HACS for **HA WaterSmart**, and open it.
6. Select **Download**, confirm the version to install, and wait for it to finish.
7. Restart Home Assistant, then follow **Configure HA WaterSmart** below.

See the [HACS custom repository instructions](https://www.hacs.dev/docs/faq/custom_repositories/)
for details about adding a GitHub repository.

### Manual

Download `ha-watersmart.zip` from the
[latest release](https://github.com/sivagorrepati/ha-watersmart/releases/latest)
and extract it into your Home Assistant configuration directory. Restart Home
Assistant, then follow **Configure HA WaterSmart** below. Alternatively:

1. Copy `custom_components/ha_watersmart` into your Home Assistant configuration
   directory under `custom_components/ha_watersmart`.
2. Restart Home Assistant.
3. Follow **Configure HA WaterSmart** below.

## Configure HA WaterSmart

Before setup, make sure Home Assistant's configured timezone matches your water
utility's timezone. For Milpitas, use `America/Los_Angeles`.

1. Open **Settings → Devices & services → Add integration**.
2. Search for and select **HA WaterSmart**.
3. Enter your utility portal URL (defaults to `https://milpitas.watersmart.com`),
   email, and password.
4. Submit the form and wait for the first download to complete. The integration
   discovers your active account number and creates its hourly water usage sensor.

## Add water usage to the Energy dashboard

Complete HA WaterSmart setup and its first successful download before adding water
consumption. The integration imports historical readings into long-term statistics
using their original local dates and hours, interpreted in Home Assistant's
configured timezone.

1. Open **Settings → Dashboards → Energy**.
2. Find the **Water consumption** section and select **Add water source** to open
   the **Configure water consumption** dialog.
3. In **Water consumption**, select **HA WaterSmart <account_number> hourly water usage**
   with **HA WaterSmart** shown as its source. For example, the fictional account `1234567` appears
   as **HA WaterSmart 1234567 hourly water usage** and uses statistic ID
   `ha_watersmart:1234567_water_usage_hourly`.
4. Leave **Water flow rate** empty. This integration provides hourly consumption
   in gallons and does not provide an instantaneous flow rate. **No statistics
   available** in this optional dropdown is expected when you have no separate
   flow-rate sensor; it does not prevent saving water consumption.
5. Select **Do not track costs**. You
   can configure costs separately later if you have a price or cost source.
6. Select **Save**.
7. Open **Energy** in the sidebar and select the **Water** tab. Use the date
   controls to view daily or monthly consumption, including imported history.
   Allow the dashboard to refresh after the initial statistics import.

Choose the **HA WaterSmart statistic** in the consumption selector. The live entity
`sensor.ha_watersmart_<account_number>_water_usage_hourly` displays the latest hourly
reading and is not a cumulative consumption sensor, so it is not offered as an
Energy consumption source. Its normal History starts when the integration is
installed; the imported statistic supplies earlier consumption to Energy.

If the **Water consumption** selector has no HA WaterSmart entry:

- Check **Settings → Devices & services → HA WaterSmart** for setup or authentication
  errors and confirm that the first download succeeded.
- Open **Developer tools → States**, find your hourly sensor, and check that
  it has a numeric value and a `historical_statistic_id` attribute.
- Open **Developer tools → Statistics** and look for that statistic ID. If it
  remains missing, check **Settings → System → Logs** for HA WaterSmart or recorder
  errors. Home Assistant's recorder integration must be enabled to import history.

See [Home Assistant's water usage documentation](https://www.home-assistant.io/docs/energy/water/)
for more about water consumption in the Energy dashboard.

## Sensor and history

The sensor is created as:

```text
sensor.ha_watersmart_<account_number>_water_usage_hourly
```

The sensor shows **gallons used during the latest completed hour available from
WaterSmart**. Your utility may publish readings with a delay, so this is not always
the previous hour. The integration treats reading dates and hours as local time
in Home Assistant's configured timezone.

To check when data was recorded or downloaded, open **Developer tools → States**
and select your hourly sensor:

| Attribute | Meaning |
|---|---|
| `reading_start` | Start of the water usage hour, shown as a UTC timestamp. |
| `last_download` | Time of the last successful download, shown in UTC. |
| `historical_statistic_id` | Statistic to use for historical charts and the Energy dashboard. |

Available historical readings are imported under this statistic ID:

```text
ha_watersmart:<account_number>_water_usage_hourly
```

Use this statistic to view earlier consumption. The sensor's normal **History**
starts when you install the integration. Select the statistic in the Energy
water consumption selector, as described above.

Missing readings remain unknown. During daylight-saving fall-back, repeated
readings for the same local hour are combined into one hourly total. During
spring-forward, the skipped hour remains absent.

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
  - ha_watersmart:1234567_water_usage_hourly
```

## Authentication and failures

The integration renews expired login sessions automatically. If your credentials
are rejected, open **Settings → Devices & services → HA WaterSmart** and follow the
reauthentication prompt. Use credentials for the same utility account.

If WaterSmart cannot be reached, the sensor becomes unavailable and the integration
retries. `last_download` continues to show the last successful download. Initial
setup requires a working portal connection.

Home Assistant stores your login credentials in its integration configuration.
No HAR file or captured login session is needed for installation.

The integration supports one active account per entry. MFA, CAPTCHA, and switching
between accounts within a portal are not supported. It was developed for the
Milpitas portal; other WaterSmart utility portals may behave differently.

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
and uploads `ha-watersmart.zip`. The ZIP contains the integration under
`custom_components/ha_watersmart` and the Apache license. HACS downloads the tagged
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
python3 scripts/build_release.py --output dist/ha-watersmart.zip
```

## License

Licensed under the [Apache License 2.0](LICENSE).
