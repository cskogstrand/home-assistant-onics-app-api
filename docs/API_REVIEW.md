# API functionality review

Reviewed **2026-10-09** against the published
[Onics/Eva App API](https://onicsas.github.io/home-hla-docs/) and integration
revision `09c3b30`. This review changes documentation only.

**The integration covers the main device attribute tables, but does not provide
full App API functionality.** Event forwarding, entity state, and usable controls
are separate capabilities. Recognizing an action result in `events.py` does not
create a Home Assistant action for that operation.

## Confirmed issues

| Priority | Finding and user impact | Evidence and needed change |
| --- | --- | --- |
| High before camera provisioning | A camera provisioning secret can reach the HA event bus. `event_data()` passes scalar `value` through for every event type. `cameraProvisioningQrCreated.value` contains a provisioning QR string that the API says must not be logged. An Eva app performing provisioning could produce this event even though this integration has no camera controls. | [Camera events](https://onicsas.github.io/home-hla-docs/#cameras-sse-camera-events); [`events.py`](../custom_components/eva/events.py), `event_data`. Redact provisioning values before forwarding; use event-specific safe fields for new payloads. Reproduced using an invented string, with no real credentials. |
| High | An unrelated full-home event clears an active alarm countdown. Snapshot reconstruction retains only mode and PIN requirement, losing `entry_at` and `exit_at`; the alarm entity can leave `pending`/`arming` before the countdown completes. | [Alarm countdowns](https://onicsas.github.io/home-hla-docs/#burglar-alarm); [`state.py`](../custom_components/eva/state.py), `HomeState.apply`, and [`alarm_control_panel.py`](../custom_components/eva/alarm_control_panel.py), `alarm_state`. Reconstruct/preserve countdowns consistently with the authoritative profile, including mode changes and reconnects. |
| High for affected locks | PIN-required unlocking is unsupported. `EvaLock.async_unlock(**kwargs)` ignores a supplied code and writes only `locked=false`. The documented device update accepts `authPin` inside an attribute update. | [Device update payload](https://onicsas.github.io/home-hla-docs/#devices-update-device-payload-parameters); [`lock.py`](../custom_components/eva/lock.py), [`entity.py`](../custom_components/eva/entity.py). Add the documented authenticated unlock path and HA code handling without exposing the PIN. |
| Medium | Home feature flags are ignored. The server sends `homeFeatures` before `initialHome`, but the integration neither stores nor applies it. An advertised device or mood alone can therefore expose a control whose home feature is disabled. | [Home features](https://onicsas.github.io/home-hla-docs/#homes-get-home-features); [`coordinator.py`](../custom_components/eva/coordinator.py), `_async_listen`, and [`state.py`](../custom_components/eva/state.py). Apply feature flags to supported platforms; account for the documented differences between gateway families. |
| Medium | Camera motion and home-log events lose their useful detail. Their event names can reach automations, but structured `value` and `homeEvent` are removed. Camera motion cannot distinguish person/motion or start/end; home logs cannot identify the reported activity. | [Camera motion](https://onicsas.github.io/home-hla-docs/#cameras-motion-detection), [SSE events](https://onicsas.github.io/home-hla-docs/#sse-stream-sse-event-types); [`events.py`](../custom_components/eva/events.py). Add narrowly selected operational fields if these event families are supported; do not forward complete private payloads. |

Priorities describe the effect when the relevant feature is used. The camera
section is explicitly **upcoming, not in production**, and its contract may
change. The privacy issue is conditional on receiving that event; it is not
evidence that any real secret has been exposed.

## Coverage and missing functionality

| API area | Current integration | Missing for API parity |
| --- | --- | --- |
| [Authentication and SSE](https://onicsas.github.io/home-hla-docs/#sse-stream) | Basic login, home selection, separate sessions, replay cursor, reconnect/backoff, reset/kill handling. | Home feature handling above. Continuous unattended sessions are outside the API's stated intended use. |
| [Device attributes](https://onicsas.github.io/home-hla-docs/#attributes) | Every distinct name in the main ZigBee/non-ZigBee tables is mapped. Dynamic bounds/options, compound platforms and command confirmation are implemented. | Explicit attribute reads and historical measurement queries. `onTime` and some electrical readings can remain stale until the device reports; there is no manual refresh action. |
| [Locks](https://onicsas.github.io/home-hla-docs/#devices-update-device) | Lock/unlock, bolt-jam state and door-open reporting, plus advertised configuration attributes. | PIN-required unlock above and documented Danalock auto-calibration. The attribute table labels door-lock `open` writable; integration deliberately exposes it as a binary sensor, so mapping every name does not mean every advertised write is supported. Confirm device semantics before adding an open action. |
| [Groups](https://onicsas.github.io/home-hla-docs/#groups) | Room groups become native entities through their aggregated attributes. | Top-level `home.groups` are not read or controlled. Those groups have `deviceIds`, not aggregated attributes, so they need a distinct control strategy rather than fabricated entity state. Group creation/deletion are also absent. |
| [Moods](https://onicsas.github.io/home-hla-docs/#moods) and [rules](https://onicsas.github.io/home-hla-docs/#rules) | Existing home/room moods can be activated; active moods update scene attributes. | Mood creation/update/deletion and rule creation/update/deletion. No timeline/calendar entities or editing. HA automations remain separate from Eva's gateway rules. |
| [Device onboarding](https://onicsas.github.io/home-hla-docs/#devices) | Devices added in Eva are discovered, moved/renamed devices are refreshed, deleted devices are removed. Identify is exposed when advertised. | Starting/canceling pairing, device metadata editing and remote deletion. HA registry removal is not an API delete operation. |
| [Gateway operations](https://onicsas.github.io/home-hla-docs/#gateways) | Gateway online state controls device availability; gateway events reach automations. Device firmware updates have native update entities. | Gateway identity/diagnostics, firmware update entity and install action, automatic-update setting and MQTT ping. Device firmware support does not cover gateway firmware. |
| [Alarm](https://onicsas.github.io/home-hla-docs/#burglar-alarm) | Four modes, PIN handling, entry/exit events and an alarm entity. | Reliable countdown retention above; profile duration editing, profile device membership, entry-device configuration and home alarm settings. Alert forwarding does not set HA's `triggered` state. |
| [Warnings](https://onicsas.github.io/home-hla-docs/#warnings) and alerts | Selected fields are forwarded as events; advertised sensor attributes create entities. | No persistent home warning/alert entities or initial warning-state projection. An alert event is a notification, not proof that every alarm feature is implemented. |
| [External devices](https://onicsas.github.io/home-hla-docs/#external-devices) | External EV charger charging/plug/power status polls every minute; start/stop is exposed. | Provider connection/reconnection flow and charger statistics. `externalReconnectRequired` makes entities unavailable; the user must reconnect outside HA. |
| [Energy Saver](https://onicsas.github.io/home-hla-docs/#energy-saver) | Enable/disable events update the control restriction; related notifications are forwarded. | Home/device configuration, plans, summaries, event logs, throttle priority, prices and override controls. An override notification does not itself clear `energySaverEnabled` in local state. |
| [Electricity prices](https://onicsas.github.io/home-hla-docs/#electricity-prices) and [settings](https://onicsas.github.io/home-hla-docs/#settings) | Meter attributes and breaker/tariff notifications. | Price data and price settings, breaker/tariff settings, correction-factor settings and their native controls/sensors. |
| [ARC](https://onicsas.github.io/home-hla-docs/#arc-integration) | `arcUpdated` and test-mode notifications. | Incident/summary data, contacts and ARC test-mode configuration. No ARC state is inferred from `arcUpdated`. |
| [Homes](https://onicsas.github.io/home-hla-docs/#homes), [users](https://onicsas.github.io/home-hla-docs/#users), [subscriptions](https://onicsas.github.io/home-hla-docs/#subscriptions), [notifications](https://onicsas.github.io/home-hla-docs/#notifications) | Select an existing home; forward related business events after removing private fields. | Home/account administration, user PIN changes, subscriptions, push registration/preferences and user-specific settings. These are app administration features, not prerequisites for basic HA device control. |
| [Home event history](https://onicsas.github.io/home-hla-docs/#homes-home-event-log) | `homeEventCreated` notification only. | History fetch, initial history projection and selected event details. Do not treat a translated log title as a stable automation event type. |
| [Cameras — upcoming](https://onicsas.github.io/home-hla-docs/#cameras) | Generic scalar attributes can appear as read-only sensors; battery fields use existing mappings. Event names are generically forwarded after a snapshot. | Native camera entities, WebRTC live view/playback, recording controls, pan/tilt, onboarding, motion/person event details, privacy and ARC consent controls. Camera attributes are documented in a separate table and are not covered by the main attribute mapping claim. Honor Squid-only support, `homeFeatures`, `cameraFeatures` and user roles. |

The main event table also names lock-access management and timed-off command
results. This integration forwards those results but has no corresponding
actions. Event names alone are insufficient to implement writes: verify a
complete request/permission contract before adding those actions. An `onTime`
number entity does not implement the separate timed-off command sequence.

The API's device-type list is not a control contract. The reviewed documentation
does not establish generic media-player/vacuum controls, siren activation, cover
stop, or a general physical-button press payload. `buttonEvent` appears in the
measurement discussion without a general live press-event schema.

## Verification and next work

- Downloaded and inspected the current public docs; the main event table has
  **117** names, **65** with a home snapshot. Names, fields and snapshot flags
  match `tests/fixtures/sse_events.json` exactly.
- Checked the separate SSE and upcoming camera sections. The 117-event fixture
  does not cover `homeEventCreated`, the new camera-specific names, or
  `actionFailed`. Generic forwarding is not a semantic coverage test.
- Compared the main ZigBee/non-ZigBee attribute names with `ATTRIBUTES` and
  traced command callers, state handling and public event filtering.
- Ran the existing offline test suite: **257 passed**. Additional temporary
  assertions confirmed countdown loss, ignored features/top-level groups,
  removed structured event data and forwarding of an invented QR string.
- Checked the automation catalogue against all 117 main events and the 19
  camera-table names; validated all four YAML examples against HA trigger
  schemas and checked local links and upstream section anchors.

First address event redaction, countdown correctness and PIN-required unlock;
then feature flags and useful missing controls such as gateway updates,
top-level groups and Energy Saver. Treat upcoming cameras as a separate feature
with contract and device validation. App administration can remain in Eva unless
full app replacement is explicitly wanted.

No live login, hardware commands, gateway-specific behavior or production camera
availability was tested. Passing the existing suite does not resolve the
findings above. See [Automation events](AUTOMATIONS.md) for the current behavior.
