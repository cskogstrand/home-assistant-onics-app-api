<picture>
  <source media="(prefers-color-scheme: dark)" srcset="custom_components/eva/brand/dark_logo.png">
  <img src="custom_components/eva/brand/logo.png" alt="Eva" width="154" height="46">
</picture>

# Eva for Home Assistant

Personal test integration for [Eva Smarthus](https://evasmart.no/).
Based on the integration blueprint; its MIT license is preserved unchanged.
The display name is **Eva** and the integration domain is `eva`.

Upgrading from Onics: remove the old integration entry and
`custom_components/onics` directory, install `custom_components/eva`, restart Home
Assistant, and add **Eva** again. The domain has changed; existing entries are not
migrated automatically. Check dashboards and automations after adding your devices
again, as entity IDs may change.

## Setup

1. Install `custom_components/eva` in your Home Assistant configuration's
   `custom_components` directory and restart Home Assistant.
2. Open **Settings → Devices & services → Add integration → Eva**.
3. Enter your Eva email and password. **Prod** is the default environment;
   expand **Advanced** to select **Test** or **QA** before signing in.
4. Select one of the homes returned for your account.
5. After the initial SSE snapshot arrives, device capabilities appear as native
   Home Assistant entities. Existing temperature entity IDs are preserved.

| Environment | API base URL |
| --- | --- |
| Test | `https://home-hla.smarthome-test.datek.io` |
| QA | `https://home-hla.smarthome-qa.datek.io` |
| Prod | `https://home.api.evasmart.no` |

All environments use client brand `eva` and schema version **7**, confirmed for
this integration. Login uses the API's documented HTTP Basic authentication over
HTTPS. Credentials are sent only to the selected API; redirects are disabled.
There is no access-token entry field or assumption that tokens are permanent.
Each entry uses its own session cookies and a persistent random SSE client ID.

A rejected login leaves you on the sign-in form. Accounts without accessible
homes cannot create an entry. The same home can be added once per environment.
To connect another home, add another Eva entry. If authentication later fails,
Home Assistant asks for the account's current password and checks that it still
has access to the selected home before reloading the entry.

Home Assistant stores credentials in its local configuration storage. Keep that
storage and its backups private. Do not put credentials or private home/device
data in Git, logs, issues, or test fixtures.

## Separate development instance

Requires Docker Compose:

```sh
./scripts/develop
```

Open <http://localhost:8124>, finish Home Assistant onboarding, then add Eva.
The pinned Home Assistant 2026.9.4 container uses this project's `config/`
directory, exposes only localhost port 8124, and mounts the integration read-only.
If you already have the Onics development container, rerun `./scripts/develop`
to recreate it with the new `eva` mount; a restart alone does not update mounts.
After changing Python code or translations, restart the running dev instance:

```sh
docker compose restart homeassistant
```

If an old setup dialog is still open, close it and start **Add integration** again.
Stop with Ctrl-C; `docker compose down` removes the container but preserves data.
Do not use a production configuration directory here.

## Behavior

- One asynchronous SSE connection and shared coordinator per selected home.
- Complete home snapshots replace state; partial attribute events retain omitted
  fields. Reconnects use the documented replay cursor.
- Streams refresh every 9 minutes, before the API's 10-minute expiry, without
  marking entities unavailable. A silent connection becomes unavailable after
  15 seconds; dropped connections reconnect with backoff and the server retry delay.
- Authentication failures request reauthentication; unloading cancels the stream.
- Device capabilities determine entity types, regardless of vendor or model.
  Entities and device IDs include environment, home and stable API IDs. Devices
  with no exposed capabilities still appear in the device registry.
- New devices, room groups and attributes are discovered during updates. Deleted
  devices and groups are removed with their entities, including after a restart.
  Offline devices stay registered with unavailable entities. Null and invalid
  values remain unknown.
- Commands validate types, ranges, steps and options before sending. Eva's SSE
  action result confirms completion; failed actions and timeouts raise Home
  Assistant errors. Writes are never retried and state is never optimistic.
- External EV chargers use their separate status endpoint once per minute;
  polling failures make their entities unavailable. Start/stop acceptance is
  followed by the next status poll. Reconnect and Energy Saver restrictions are
  respected.

## Supported capabilities

All attributes in the API's documented ZigBee and non-ZigBee attribute tables
are mapped. Only capabilities actually advertised by the device create entities.

| Home Assistant platform | Eva capabilities |
| --- | --- |
| `sensor` | Temperature, humidity, pressure, illuminance, air quality, battery, RSSI, electricity, water, charger status, and unknown scalar attributes |
| `binary_sensor` | Contact, motion, presence, smoke/fire, water, CO, vibration, tamper, battery/fault, safety and car connection states |
| `light` | On/off lamps, dimmers, Kelvin color temperature and HSV color |
| `switch` | Plugs, other on/off devices, boolean settings and external charger start/stop |
| `climate` | Thermostats and devices exposing a setpoint, heating state and sensor selection |
| `cover` | Lift and tilt percentages, converted to Home Assistant's open-percentage convention |
| `lock` | Lock/unlock and jammed state; door-open state is a separate binary sensor |
| `number` | Timers, calibration, thresholds, loads, charging current and other bounded numeric settings |
| `select` | Startup behavior, thermostat mode/sensor and lock configuration options |
| `text` | Thermostat display text and physical mood-button assignments |
| `button` | Identify, only when advertised by the device |
| `update` | Advertised firmware version, progress and user-initiated installation |
| `scene` | Existing home and room moods |
| `alarm_control_panel` | Disarm, home/day, away and night profiles, PIN enforcement and reported entry/exit countdowns |

Room groups use the same capability mappings as individual devices. Cumulative
energy/water readings use statistics suitable for Home Assistant dashboards;
rolling hourly energy estimates do not masquerade as cumulative meters.

Device-provided bounds, steps and options take precedence. Numeric settings
without documented bounds and enum settings without options remain read-only
sensors until that metadata arrives. Unknown scalar attributes also remain
read-only; structured unknown values stay unknown rather than being serialized
into entity states. Long text sensor states are limited to HA's 255 characters.

The published App API has no control contract for cameras, media players,
vacuums, siren activation, cover stop, or generic physical-button press events. Those require an upstream API contract before native controls can
be added. Alarm entities report the documented active profile and countdowns;
no triggered-alarm state is inferred from undocumented alert payloads. Some
voltage/current and min/max readings only update when Eva receives a report;
the integration does not repeatedly wake battery devices to force measurements.

The [App API documentation](https://onicsas.github.io/home-hla-docs/#authentication)
permits Basic authentication. Its [introduction](https://onicsas.github.io/home-hla-docs/#introduction)
describes foreground app sessions and says continuous backend connections are
outside the API's intended use. This remains a personal test integration.

## Development and validation

Requires Python 3.14.2 or newer in the 3.14 series. Minimum Home Assistant: 2026.9.4.

```sh
./scripts/setup
./scripts/lint
./scripts/test
docker compose config --quiet
```

Tests disable network access and use invented identifiers and credentials. They
cover sign-in, environment routing, home selection, duplicate prevention,
reauthentication, all supported native platforms, validated and confirmed
commands, external charger polling, group/mood discovery, deletion, unload, state
merging and SSE recovery. Live authentication and real-device updates still
require testing with your own account in the selected environment.

Hassfest, HACS validation, linting and tests are retained in GitHub workflows.
HACS metadata and the standard component layout are included.
Runtime configuration, `.env` files, logs, caches, and virtual environments are
ignored; only the sanitized `config/configuration.yaml` is tracked.

## Branding

The supplied Eva wordmark is preserved in
[`custom_components/eva/brand/logo.svg`](custom_components/eva/brand/logo.svg).
Home Assistant loads the bundled PNG logos and square icons from the same
[`brand/` directory](https://developers.home-assistant.io/docs/core/integration/brand_images/),
including high-resolution versions and a white logo for dark mode. The icons use
Eva's warm peach (`#f6e4d9`) background from [evasmart.no](https://evasmart.no/).
Setup dialogs keep Home Assistant's native theme and accessibility settings.
The HACS `brands` check is enabled for these local assets.

Eva names and logos belong to their respective owners. This personal integration
is not an official Eva or Onics product.
