# API functionality review

Reviewed **2026-10-09** against the published
[Onics/Eva App API](https://onicsas.github.io/home-hla-docs/) and integration
revision `09c3b30`; updated below after implementing the agreed Home Assistant
scope. See [HA controls and actions](ACTIONS.md) for usage.

**The integration covers the main device attribute tables, but does not provide
full App API functionality.** Event forwarding, entity state, and usable controls
are separate capabilities. Recognizing an action result in `events.py` does not
create a Home Assistant action for that operation.

## Confirmed issues — addressed

| Original priority | Finding | Implemented behavior |
| --- | --- | --- |
| High before camera provisioning | Generic scalar `value` forwarding could expose provisioning QR strings. | [`events.py`](../custom_components/eva/events.py) now forwards scalar values only for attribute changes/reports. Provisioning, session and unknown values are withheld. [Camera contract](https://onicsas.github.io/home-hla-docs/#cameras-sse-camera-events). |
| High | Full snapshots discarded alarm countdowns. | [`state.py`](../custom_components/eva/state.py) retains deadlines for an unchanged profile and reconstructs the exit deadline from `modeChangedAt` and profile duration. A changed/disarmed profile clears stale entry state. [`alarm_control_panel.py`](../custom_components/eva/alarm_control_panel.py) schedules the exit timer on initial setup too. An entry event missed offline cannot be reconstructed: the [API](https://onicsas.github.io/home-hla-docs/#burglar-alarm) does not replay it. |
| High for affected locks | Supplied unlock PINs were ignored. | [`lock.py`](../custom_components/eva/lock.py) accepts a numeric code and sends the documented attribute `authPin` in the [device update body](https://onicsas.github.io/home-hla-docs/#devices-update-device-payload-parameters). Empty code retains the single-attribute route. State remains reported, not optimistic. |
| Medium | Home feature flags were ignored. | [`coordinator.py`](../custom_components/eva/coordinator.py) retains flags received before the first snapshot; discovery, availability and commands honor explicit flags. The server supplies gateway-specific defaults through [home features](https://onicsas.github.io/home-hla-docs/#homes-get-home-features). Older streams without flags retain prior capability discovery. |
| Medium | Motion and activity notifications lost their operational details. | [`events.py`](../custom_components/eva/events.py) retains selected string fields for [camera motion](https://onicsas.github.io/home-hla-docs/#cameras-motion-detection), plus activity ID/timestamp/icon type for `homeEventCreated`. Translated/private text and session credentials remain excluded. |

Priorities describe the effect when the relevant feature is used. The camera
section is explicitly **upcoming, not in production**, and its contract may
change. The original privacy finding was reproduced with invented data; no
real provisioning credential was used or observed.

## Coverage and missing functionality

| API area | Current integration | Missing for API parity |
| --- | --- | --- |
| [Authentication and SSE](https://onicsas.github.io/home-hla-docs/#sse-stream) | Basic login, home selection, separate sessions, replay cursor, reconnect/backoff, reset/kill handling. | Continuous unattended sessions are outside the API's stated intended use. |
| [Device attributes](https://onicsas.github.io/home-hla-docs/#attributes) | Every distinct name in the main ZigBee/non-ZigBee tables is mapped. Dynamic bounds/options, compound controls, command confirmation, on-demand reads and measurement queries are implemented. | No forced battery-device polling or historical-statistics import. |
| [Locks](https://onicsas.github.io/home-hla-docs/#devices-update-device) | Lock/unlock with optional PIN, Danalock calibration, bolt-jam state and door-open reporting, plus advertised configuration attributes. | The attribute table labels door-lock `open` writable; integration deliberately exposes it as a binary sensor, so mapping every name does not mean every advertised write is supported. Confirm device semantics before adding an open action. |
| [Groups](https://onicsas.github.io/home-hla-docs/#groups) | Room groups become native entities through their aggregated attributes. Top-level groups have discovery/control actions with member validation and no fabricated aggregate state. | Group creation/deletion remain in Eva. |
| [Moods](https://onicsas.github.io/home-hla-docs/#moods) and [rules](https://onicsas.github.io/home-hla-docs/#rules) | Existing home/room moods can be activated; active moods update scene attributes. | Mood creation/update/deletion and rule creation/update/deletion. No timeline/calendar entities or editing. HA automations remain separate from Eva's gateway rules. |
| [Device onboarding](https://onicsas.github.io/home-hla-docs/#devices) | Devices added in Eva are discovered, moved/renamed devices are refreshed, deleted devices are removed. Identify is exposed when advertised. | Starting/canceling pairing, device metadata editing and remote deletion. HA registry removal is not an API delete operation. |
| [Gateway operations](https://onicsas.github.io/home-hla-docs/#gateways) | Gateway identity, connection diagnostics, firmware update/install, automatic-update configuration and ping are implemented. Gateway events reach automations and online state controls device availability. | No remaining documented gateway operation in this scope. |
| [Alarm](https://onicsas.github.io/home-hla-docs/#burglar-alarm) | Four modes, PIN handling, entry/exit events, countdown retention/reconstruction and an alarm entity. | Profile duration editing, profile device membership, entry-device configuration and home alarm settings. Alert forwarding does not set HA's `triggered` state. |
| [Warnings](https://onicsas.github.io/home-hla-docs/#warnings) and alerts | Selected fields are forwarded as events; advertised sensor attributes create entities. | No persistent home warning/alert entities or initial warning-state projection. An alert event is a notification, not proof that every alarm feature is implemented. |
| [External devices](https://onicsas.github.io/home-hla-docs/#external-devices) | External EV charger charging/plug/power status polls every minute; start/stop and on-demand statistics are exposed. | Provider connection/reconnection remains external. `externalReconnectRequired` makes entities unavailable; the user must reconnect outside HA. |
| [Energy Saver](https://onicsas.github.io/home-hla-docs/#energy-saver) | Home/device settings, overrides, plans, summaries, logs, throttle priority and configured prices are available as HA actions. Eligible devices have an enable switch; enable/disable events update manual-control restrictions. | No automatic plan/price/history polling or dedicated price entities. |
| [Electricity prices](https://onicsas.github.io/home-hla-docs/#electricity-prices) and [settings](https://onicsas.github.io/home-hla-docs/#settings) | Meter attributes, breaker/tariff notifications and on-demand configured home prices through Energy Saver. | Price configuration, breaker/tariff/correction settings and dedicated price entities remain absent. |
| [ARC](https://onicsas.github.io/home-hla-docs/#arc-integration) | `arcUpdated` and test-mode notifications. | Incident/summary data, contacts and ARC test-mode configuration. No ARC state is inferred from `arcUpdated`. |
| [Homes](https://onicsas.github.io/home-hla-docs/#homes), [users](https://onicsas.github.io/home-hla-docs/#users), [subscriptions](https://onicsas.github.io/home-hla-docs/#subscriptions), [notifications](https://onicsas.github.io/home-hla-docs/#notifications) | Select an existing home; forward related business events after removing private fields. | Home/account administration, user PIN changes, subscriptions, push registration/preferences and user-specific settings. These are app administration features, not prerequisites for basic HA device control. |
| [Home event history](https://onicsas.github.io/home-hla-docs/#homes-home-event-log) | On-demand history fetch and safe live activity fields in `homeEventCreated`. | No initial history entities or statistics import; translated titles are not stable trigger names. |
| [Cameras — upcoming](https://onicsas.github.io/home-hla-docs/#cameras) | Generic scalar attributes can appear as read-only sensors; battery fields use existing mappings. Event names are generically forwarded after a snapshot. | Native camera entities, WebRTC live view/playback, recording controls, pan/tilt, onboarding, privacy and ARC consent controls. Selected motion/person event details are implemented. Camera attributes are documented in a separate table and are not covered by the main attribute mapping claim. Honor Squid-only support, `homeFeatures`, `cameraFeatures` and user roles. |

The main event table also names lock-access management and timed-off command
results. This integration forwards those results but has no corresponding
actions. Event names alone are insufficient to implement writes: verify a
complete request/permission contract before adding those actions. An `onTime`
number entity does not implement the separate timed-off command sequence.

The API's device-type list is not a control contract. The reviewed documentation
does not establish generic media-player/vacuum controls, siren activation, cover
stop, or a general physical-button press payload. `buttonEvent` appears in the
measurement discussion without a general live press-event schema.

## Verification and remaining scope

- Downloaded and inspected the current public docs; the main event table has
  **117** names, **65** with a home snapshot. Names, fields and snapshot flags
  match `tests/fixtures/sse_events.json` exactly.
- Checked the separate SSE and upcoming camera sections. The 117-event fixture
  does not cover `homeEventCreated`, the new camera-specific names, or
  `actionFailed`. Generic forwarding is not a semantic coverage test.
- Compared the main ZigBee/non-ZigBee attribute names with `ATTRIBUTES` and
  traced command callers, state handling and public event filtering.
- The original review ran 257 tests. Implementation adds regression tests for
  the five findings, native controls, action routes, validation, permissions,
  transport encoding/failures and non-optimistic state. See the final test result
  accompanying this change.
- Checked the automation catalogue against all 117 main events and the 19
  camera-table names; validated all four YAML examples against HA trigger
  schemas and checked local links and upstream section anchors.

The agreed HA scope is implemented through the native controls and 12 actions
in [ACTIONS.md](ACTIONS.md). App administration and the upcoming native camera
stack remain in Eva. Other gaps above are retained explicitly rather than
claiming full API parity.

No live login, hardware commands, gateway-specific behavior or production camera
availability was tested. The addressed findings have regression tests; remaining
gaps are listed above. See [Automation events](AUTOMATIONS.md) for current behavior.
