# Home Assistant controls and actions

The integration exposes native device entities plus the actions below in
**Developer tools → Actions** and the automation editor. Home actions require an
HA administrator or an automation. Select the Eva config entry to scope each
request to its home and environment. User account permissions in Eva still apply.

## Native controls

- **Gateway:** connection binary sensor, last-activity/setup diagnostics, a
  connection-check button, firmware update entity, and read-only automatic-update
  enablement/hour when both settings are reported. Use `configure_gateway_updates`
  to set both values together. The hour uses the Eva home's time zone. Keep the
  gateway powered and connected during firmware installation.
- **Energy Saver:** an enable switch on eligible/already configured devices.
  Turning it off is permitted while Energy Saver blocks ordinary manual device
  control. Switch state follows Eva's report, not the submitted command.
- **Locks:** optional numeric PIN on the standard `lock.unlock` action. HA's
  default lock code setting is supported. Empty code uses the original unlock
  route. The API's PIN-bearing device-update acknowledgement confirms gateway
  acceptance, not physical unlocking; the entity waits for reported lock state.
- **Features:** explicit `homeFeatures` flags gate corresponding devices,
  thermostats, locks, chargers, groups and moods. An existing entity becomes
  unavailable when its feature is disabled. Streams without flags retain the
  original capability discovery behavior.

## Available actions

All actions require `config_entry_id`. Device fields use **Eva API device IDs**,
not HA device-registry IDs or entity IDs. Find these in ordinary `eva_event`
payloads. The action picker includes field descriptions and selectors.

| Action | Additional fields | Result |
| --- | --- | --- |
| `eva.configure_gateway_updates` | `enabled`, `hour_of_day` (0–23) | Sets both automatic firmware update settings together. The hour uses the Eva home’s time zone. |
| `eva.read_attribute` | `device_id`, `attribute` | Requests a fresh report of one known attribute; its later SSE report updates the entity. No automatic polling/retries. |
| `eva.calibrate_lock` | `device_id` | Starts calibration for a reported Danalock V3. Follow the manufacturer's physical setup procedure first. |
| `eva.get_groups` | None | Response `groups`: top-level group IDs, names and member device IDs. |
| `eva.set_group_attribute` | `group_id` (integer), `attribute`, `value` | One group command after validating the value for every member. Rejects offline, missing, feature-disabled or Energy Saver managed members. No aggregate state is fabricated. |
| `eva.configure_energy_saver` | `device_id`, `settings` object | Updates settings using the device's reported `externalDeviceId`, or creates settings for an eligible device using its ordinary ID. Newly created settings may require a later home update before the external ID is known. |
| `eva.configure_home_energy_saver` | `settings` object | Updates home away scheduling and/or throttling strategy. |
| `eva.set_energy_saver_priority` | `device_ids` list | Resolves ordinary IDs to Energy Saver IDs and sets priority in list order. Omitted devices become lowest priority; `[]` clears the ordering. |
| `eva.get_energy_saver` | `kind`; other fields depend on kind below | On-demand response `data` containing the API result. |
| `eva.get_measurements` | `device_id`, `attribute`, `time_start`, `time_stop`, `time_zone` | Response `data` with historical measurements. Optional `aggregate`, `window_aggregate`, `window_duration`, `window_time`, `transform`. |
| `eva.get_charger_statistics` | `device_id`, `time_start`, `time_stop`, `time_zone` | Response `data` with hourly consumption for an external EV charger. |
| `eva.get_home_events` | Optional `device_id`, `mood_id`, `offset` (default 0), `count` (default 100) | Response `data` with private home activity history. `offset` is a page index: 0, 1, 2, etc. |

Read actions require a `response_variable` in scripts/automations. They neither
create history entities nor import old measurements into HA statistics. No
background price/plan/history polling is added. Home history can contain names
and descriptions; handle returned data as private. It is not forwarded on the
public automation event bus.

Manual attribute reads are for awake, reported, non-external devices. Three or
more unanswered reads can make a sleepy device appear offline in Eva. A read
request acknowledgement does not guarantee a new measurement will arrive.

## Energy Saver fields

For `get_energy_saver`:

| `kind` | Required fields | Optional fields |
| --- | --- | --- |
| `settings`, `summary` | `device_id` | None |
| `plan` | `device_id`, `time_start`, `time_stop` | None |
| `eventlog` | `device_id` | `count` (20), `start_time_key` |
| `prices` | `time_start`, `time_stop` | None; uses the home's configured price setup |
| `priority` | None | None |
| `home_eventlog` | None | `count` (20), `start_time_key` |

Copy a returned `nextPageStartTimeKey` unchanged into `start_time_key` for device
event-log pagination. All range/scheduling timestamps must include a timezone;
`time_stop` must be later than `time_start`. Historical query time zones use an
IANA name such as `Europe/Oslo`.

Device `settings` accepts these documented API field names:

| Setting group | Fields |
| --- | --- |
| Common | `enabled`, `throttleByMainCircuitBreaker`, `throttleByGridTariffLevel`, `throttlePriority` (positive integer or null) |
| Override | `overrideUntil` (timestamp or null), `overrideDesiredState` (`NUMERIC`, `HEAT`, `NO_HEAT`, `CHARGE`, `NO_CHARGE`, or null), `overrideDesiredStateNumeric` (finite number or null) |
| Charger | `readyTime` (`HH:MM`), `hoursToCharge`, `maxCurrent` (nonnegative integers) |
| Thermostat | `setPoint`, `setPointAway`, `setPointAdjustmentNight`, `setPointAdjustmentPrice` (finite numbers), `nightStart`, `nightStop` (`HH:MM`) |
| Water heater | `priorityTimes` (list of `HH:MM`), `size` (`SMALL`, `MEDIUM`, `LARGE`), `savingLevel` (`LOW`, `HIGH`), `hoursToHeat` (nonnegative integer) |

Only supply settings appropriate to the device type. Eva validates device-specific
ranges and combinations not specified in its published settings contract.
Use `get_energy_saver` to inspect current settings and results. Overrides are
requested through Energy Saver; they do not bypass the integration's manual
control restriction while `energySaverEnabled` remains true.

Home `settings` accepts `away` with `enabled`, `validFrom`, `validTo`, and/or
`throttleStrategy` (`STATIC` or `INCREMENTAL`). With away mode enabled, null
`validFrom` means now and null `validTo` means indefinitely.

## Examples

Read top-level groups, then turn off a selected group. Replace the example IDs
with values from your own entry and group response:

```yaml
actions:
  - action: eva.get_groups
    data:
      config_entry_id: YOUR_ENTRY_ID
    response_variable: eva_groups
  - action: eva.set_group_attribute
    data:
      config_entry_id: YOUR_ENTRY_ID
      group_id: 7
      attribute: "on"
      value: false
```

Request charging until a specific time using the device's Eva ID:

```yaml
actions:
  - action: eva.configure_energy_saver
    data:
      config_entry_id: YOUR_ENTRY_ID
      device_id: YOUR_CHARGER_ID
      settings:
        overrideUntil: "2026-10-10T07:00:00+02:00"
        overrideDesiredState: CHARGE
```

Fetch the home's configured electricity prices for one day:

```yaml
actions:
  - action: eva.get_energy_saver
    data:
      config_entry_id: YOUR_ENTRY_ID
      kind: prices
      time_start: "2026-10-09T00:00:00+02:00"
      time_stop: "2026-10-10T00:00:00+02:00"
    response_variable: eva_prices
```

Use current/future timestamps for actual overrides. Examples do not run until
you save/call an action yourself. No hardware commands are sent while installing
the integration or discovering these controls.

App administration, provider OAuth reconnection, native camera streaming and
recording, rule/mood editing and undocumented physical controls remain outside
this implementation. See [API coverage](API_REVIEW.md) and
[automation events](AUTOMATIONS.md).
