<picture>
  <source media="(prefers-color-scheme: dark)" srcset="custom_components/eva/brand/dark_logo.png">
  <img src="custom_components/eva/brand/logo.png" alt="Eva" width="154" height="46">
</picture>

# Eva for Home Assistant

Personal test integration for [Eva Smarthus](https://evasmart.no/).
Based on the integration blueprint; its MIT license is preserved unchanged.
The display name is **Eva** and the integration domain is `eva`.

## Setup

1. Install `custom_components/eva` in your Home Assistant configuration's
   `custom_components` directory and restart Home Assistant.
2. Open **Settings → Devices & services → Add integration → Eva**.
3. Select **Prod**, **Test**, or **QA**.
4. If this environment has saved logins, choose **Use a saved login** and select
   an account from the list, or choose **Log in with another user**.
5. For a new login, enter your Eva email and password, then select a home.
   The login is saved only after you select an unconfigured home.
6. After the initial SSE snapshot arrives, device capabilities appear as native
   Home Assistant entities. Existing temperature entity IDs are preserved.

| Environment | API base URL |
| --- | --- |
| Test | `https://home-hla.smarthome-test.datek.io` |
| QA | `https://home-hla.smarthome-qa.datek.io` |
| Prod | `https://home.api.evasmart.no` |

All environments use client brand `eva` and schema version **7**. Login uses the
API’s documented HTTP Basic authentication over HTTPS. No Keycloak client or
access to the Keycloak administration console is required. Credentials are sent
only to the selected API; redirects are disabled. Each home keeps its own private
cookie session and persistent random SSE client ID.

Logins are saved once per email and environment using Home Assistant’s private
integration storage. Home entries reference the saved login instead of keeping
separate password copies. Home Assistant’s **Application Credentials** feature is
for OAuth client IDs and secrets, so it is not used for these account passwords.

To connect another home, add another Eva entry, select the same environment,
and choose a saved login. The picker is shown even when only one login is saved.
Accounts with no accessible homes cannot create an entry. A home can be added
once per environment. A rejected saved login opens the email/password form so
its password can be corrected. Updating a password reloads the homes using that
email in that environment; other accounts and environments are unaffected.

Existing password-based entries migrate their credentials to shared storage
without changing home, entity or SSE client IDs. Entries created with the
experimental OAuth flow require an email/password login. Reauthentication checks
access to the existing home before saving the new password.

Saved logins remain available after a home is removed. Passwords are stored
locally, not encrypted by the integration; keep Home Assistant’s storage and
backups private. Do not put credentials or private home/device data in Git,
logs, issues, or test fixtures.

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
- Streams reconnect after the server's normal 10-minute close, using the same
  client ID, replay cursor and server retry delay without marking entities
  unavailable. A silent connection becomes unavailable after 15 seconds;
  failed connections reconnect with backoff and the server retry delay.
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
  Commands are sent immediately. A newer command to the same device or group
  replaces the previous confirmation wait and stops its remaining command steps.
  Superseded results are ignored; the latest command still reports failures and
  timeouts. Other devices stay independent.
- External EV chargers use their separate status endpoint once per minute;
  polling failures make their entities unavailable. Start/stop acceptance is
  followed by the next status poll. Reconnect and Energy Saver restrictions are
  respected.

### Live SSE events

All 117 `SSE:` event types in the [App API event table](https://onicsas.github.io/home-hla-docs/#events-event-types)
are handled. The 65 types documented as containing a complete home replace the
local snapshot, including device/room/group/mood changes, firmware completion,
settings, users and services. Any future event containing a home does the same.
The API itself supplies those snapshots; the integration does not poll for them.

Events without a home update attributes, device firmware progress, alarm profiles
and countdowns, active moods, and Energy Saver enable/disable restrictions directly.
Failed pairing removes the failed device. Scenes expose an `active` attribute
updated by `moodActivated` and `activeMoodsChanged`. Attribute-sent notifications
do not change reported values or complete pending commands.

Every business event also fires `eva_event` on Home Assistant's event bus, even
when no entity state changes. This makes gateway updates, alerts, warnings, scan
progress, electricity limits, access changes, Energy Saver and ARC notifications
available to automations. Stream housekeeping events are excluded. Events include
`config_entry_id`, `home_id`, the API's `eventType`, and supplied event/resource IDs.
Operational data includes scalar `name`/`value`, progress, software update status,
alarm mode/countdowns and active mood IDs. Alert objects expose only scalar
`id`, `type`, `active` and `status` fields; warnings expose only `id`, `type`,
`severity`, `alarm` and `dismissible`. Full homes, user details, PINs, RFID tags,
access labels, free-form warnings and unknown fields are excluded.

For notifications without a documented state payload (such as `arcUpdated` and
`energySaverDeviceStatusUpdated`), the event is the automation signal; no device
values are inferred. Replayed events retain their API `id` when supplied.

Example automation trigger:

```yaml
triggers:
  - trigger: event
    event_type: eva_event
    event_data:
      home_id: YOUR_HOME_ID
      eventType: electricityMainCircuitBreakerLimitExceeded
```

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
supports HTTP Basic authentication. Its [introduction](https://onicsas.github.io/home-hla-docs/#introduction)
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
cover saved-login selection and reuse, environment isolation, credential migration,
home selection, duplicate prevention,
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
