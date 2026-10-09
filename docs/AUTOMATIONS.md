# Automation events

Verified **2026-10-09** against the
[main event table](https://onicsas.github.io/home-hla-docs/#events-event-types),
[SSE-specific events](https://onicsas.github.io/home-hla-docs/#sse-stream-sse-event-types),
the [upcoming camera contract](https://onicsas.github.io/home-hla-docs/#cameras-sse-camera-events),
and this integration's code. These are the triggers available today; see the
[API review](API_REVIEW.md) for missing functionality.

## Choose the trigger

Use a Home Assistant **state trigger** for an entity changing state, such as a
contact opening or a light turning on. Use **numeric state** for a threshold
crossing. Use an **event trigger** on `eva_event` to react to an API notification,
including repeated reports with the same value and events without an entity.
The integration does not supply a custom Eva device-trigger picker or native
`event` entities. Standard HA state/event triggers work in automations.

Receiving an API event only fires matching automations that you have configured.
It does not automatically create an automation. Eva's own rules and physical
mood switches can produce these events as well as actions from HA or the app.

| What happens | Useful HA trigger | Behavior |
| --- | --- | --- |
| Contact opens/closes; motion, presence, smoke, water, tamper or panic is reported | Entity state, or `deviceAttributeChanged`/`deviceAttributeReport` with `deviceId`, `name`, `value` | API values are booleans; binary-sensor states are `on`/`off`. Event reports can repeat without a state transition. |
| Temperature, humidity, power or another measurement crosses a limit | Numeric state on the sensor | Fires on entering the configured range; an event trigger on each report is a different behavior. |
| A mood is activated | `moodActivated` with `moodId` | Means the mood's target attributes are active. It does not identify a physical button or prove a human pressed one. |
| A scene becomes active/inactive | Scene `active` attribute, or `activeMoodsChanged` | `activeMoodsChanged` carries the full list of active mood IDs, including an empty list. |
| A gateway/device is reported online/offline | Corresponding `eva_event`, or entity availability state | Online/offline events may repeat. An unavailable entity can also indicate an SSE or polling failure. |
| Alarm arming/disarming, exit completion or entry countdown | Alarm entity state or profile/countdown event | Modes are `disarmed`, `dayArmed`, `nightArmed`, `armed`. Alert events do not set the alarm entity to `triggered`. See the countdown issue in the review. |
| Breaker/tariff limit changes, warning, pairing progress or action failure | Matching `eva_event` | These signals need not change an entity state. |
| External charger starts/stops or a car plugs in | Charger entity state | Status is polled about once per minute; the poll itself does not fire `eva_event`. |

## Delivery rules

- A valid home snapshot must have arrived **on the current SSE connection**.
  Business events received before that snapshot are not forwarded. Events that
  fail validation/state application are not forwarded either; malformed state
  causes a reconnect for a fresh snapshot.
- Once ready, every successfully processed event except the excluded stream
  events below fires `eva_event`, including unknown future event names. The
  event is fired even when the resulting entity state is unchanged.
- `initialHome`, `homeFeatures`, `reconnectInfo` and `keepAlive` never fire
  `eva_event`. `resetClient` requests a fresh connection/snapshot; `killClient`
  stops the connection. Neither is forwarded as `eva_event`.
- A snapshot can update entity states without firing a business event (notably
  `initialHome`). State automations can therefore run during startup/recovery;
  use explicit `from` and `to` states when that distinction matters.
- The replay cursor requests missed events after reconnect. There is no local
  event-ID deduplication or exactly-once guarantee. If a notification is
  delivered again after the snapshot, it fires again. `id` is retained when
  supplied; duplicate-sensitive actions need their own guard. The upcoming
  `cameraMotionDetected` event is explicitly not replayed by the API.
- `deviceAttributeSent` and `groupAttributeSent` mean a write is pending. They
  do not change the reported value or confirm completion. Correlate a result
  using `actionId` when present; physical changes may have no `actionId`.
- Attribute reports and gateway/device connectivity notifications do not
  necessarily represent transitions. Broad event triggers can also react to
  their own commands, so filter them to avoid feedback loops.

## Event data available to templates

Every forwarded event has `config_entry_id`, `home_id` and `eventType`. Other
fields are optional and are preserved only when supplied in an allowed shape.
Use `trigger.event.data.get(...)` for optional fields. `home_id` is added by
the integration; it is not the API's `homeId`. Use `config_entry_id` to isolate
an entry when the same home identifier exists in multiple environments.

| Fields | Allowed shape |
| --- | --- |
| `id`, `timestamp`, `actionId`, `deviceId`, `groupId`, `moodId`, `roomId`, `ruleId`, `timelineId`, `subscriptionId`, `externalDeviceId` | Scalar string, boolean, number or null, as supplied. Device/home/mood IDs normally use strings; group IDs use integers. |
| `name`, `value`, `updatedAt`, `progress`, `softwareVersion`, `automaticSoftwareUpdates`, `estimatedExitDelayExpiresAt`, `estimatedEntryDelayExpiresAt`, `testModeUntil` | Scalar string, boolean, number or null. Object/array `value` is omitted. |
| `activeProfile` | Object retaining only scalar `mode`. |
| `softwareUpdate` | Object retaining only scalar `status`, `version`, `progress`. |
| `alert` | Object retaining scalar `id`, `type`, `active`, `status`; alternatively a string or boolean. The API may supply different shapes, so inspect before filtering nested fields. |
| `activeMoods` | List retaining only strings. |
| `warnings` | List of objects retaining only string/boolean `id`, `type`, `severity`, `alarm`, `dismissible`. |

Full `home`, `homeFeatures`, `homeEvent`, `userEmail`, user details, `deviceName`,
`homeUserId`, PIN/RFID fields, lock-access identifiers/labels/types, free-form
errors/warnings, attribute metadata such as `options`/`preview`, and unknown
fields are not forwarded. Changes to a snapshot alone do not make its fields
available in `trigger.event.data`.

**Known exception:** scalar `value` is not filtered by event type. An upcoming
`cameraProvisioningQrCreated` event would include its sensitive QR string.
Do not log or publish its payload; see the [redaction finding](API_REVIEW.md#confirmed-issues).

## Trigger examples

These are trigger blocks for the automation editor; add your own actions.
Replace the example IDs with your home/device/mood IDs. For ordinary events,
listen to `eva_event` in **Developer tools → Events** to inspect the available
fields; avoid capturing camera provisioning payloads.

Run on a contact changing from closed to open, excluding startup from unavailable:

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.example_door_open
    from: "off"
    to: "on"
```

Run on each reported motion detection, even if already detected:

```yaml
triggers:
  - trigger: event
    event_type: eva_event
    event_data:
      home_id: YOUR_HOME_ID
      eventType: deviceAttributeChanged
      deviceId: YOUR_DEVICE_ID
      name: movement
      value: true
  - trigger: event
    event_type: eva_event
    event_data:
      home_id: YOUR_HOME_ID
      eventType: deviceAttributeReport
      deviceId: YOUR_DEVICE_ID
      name: movement
      value: true
```

The two event types are separate notifications; if both arrive for one detection,
both can run the automation. Use a state transition when only one run per
detected/not-detected change is wanted. Substitute `open`, `presenceIndication`,
`fireIndication`, `waterOverflowIndication`, `panic` or another advertised
attribute as appropriate. `deviceAttributeReport` has no detailed field list in
the main API table; this integration expects the usual attribute payload.

Run when a specific mood reaches its target state:

```yaml
triggers:
  - trigger: event
    event_type: eva_event
    event_data:
      home_id: YOUR_HOME_ID
      eventType: moodActivated
      moodId: YOUR_MOOD_ID
```

Run when the main breaker limit is reported exceeded:

```yaml
triggers:
  - trigger: event
    event_type: eva_event
    event_data:
      home_id: YOUR_HOME_ID
      eventType: electricityMainCircuitBreakerLimitExceeded
```

For a room group use `groupAttributeChanged`, `groupId: 1` (unquoted integer),
`name` and `value`. Do not use the internal entity identifier `group:1` as the
API `groupId`. For an alarm entry countdown use `activeProfileEntryTimeStarted`;
the optional deadline is `trigger.event.data.get('estimatedEntryDelayExpiresAt')`.

## Main event catalogue

All **117** names in the main API event table are listed below. Every listed
name can fire `eva_event`, subject to the delivery rules above, whether or not
the corresponding operation can be initiated from HA. Use these case-sensitive
camel-case SSE names, not the dotted AMQP names also shown in the API docs.
In particular, `scanAEnded` is the spelling in the published contract.

| `eventType` | What causes the notification |
| --- | --- |
| `homeCreated`, `homeUpdated`, `homeDeleted` | Home creation, metadata update or deletion. |
| `activeProfileUpdated` | Alarm mode is reported changed; can carry an exit deadline. |
| `activeProfileUpdateFailed`, `activeProfileUpdateFailedPinAuthentication` | Alarm mode request fails, including invalid PIN. |
| `activeProfileEntryTimeStarted`, `activeProfileExitTimeExpired` | Entry countdown starts (Squid) or exit delay finishes. |
| `devicesInProfilesUpdated`, `devicesInProfilesUpdateFailed` | Alarm device membership update succeeds/fails. |
| `alarmEntryDevicesUpdated`, `alarmEntryDevicesUpdateFailed` | Entry-device configuration succeeds/fails. |
| `profilesUpdated`, `profilesUpdateFailed` | Alarm profile configuration succeeds/fails. |
| `cameraCreated`, `cameraCreateFailed` | Camera creation succeeds/fails. |
| `captureImage`, `captureImageFailed` | Capture result names. The main table repeats camera-creation descriptions, so it does not establish precise capture behavior. |
| `alertActivated`, `alertDeactivated` | An alert is raised or cleared. |
| `warningsUpdated` | The warning collection changes. |
| `gatewayOnline`, `gatewayOffline` | Gateway connectivity is reported; may repeat the previous status. |
| `gatewayPowerStatusChanged`, `gatewayOnBackupConnection`, `gatewayOnPrimaryConnection` | Gateway power or internet connection source changes. |
| `gatewayAttachedToHome`, `gatewayDetachedFromHome` | Gateway/home association changes. |
| `gatewaySoftwareVersionUpdated` | Gateway installed firmware version changes. |
| `gatewaySoftwareUpdateAvailable`, `gatewaySoftwareUpdateAssigned`, `gatewaySoftwareUpdateInProgress` | Gateway firmware becomes available, is queued or is installing. |
| `gatewayAutomaticSoftwareUpdatesSaved` | Automatic gateway update preference is saved. |
| `scanActivated`, `scanAEnded`, `scanCanceled` | Pairing scan starts, ends (Squid) or is canceled. |
| `scanFailed`, `scanFailedInstallCodeValidation` | Scan fails, including install-code validation failure. |
| `deviceFound`, `deviceAdded`, `deviceAddFailed` | Pairing discovery/progress, completion or failure; failed pairing removes the failed device. |
| `externalDeviceReconnected`, `externalDeviceReconnectFailed` | Provider reconnection succeeds/fails. |
| `deviceOnline`, `deviceOffline` | Device connectivity is reported; may repeat the previous status. |
| `deviceAttributeSent` | A device attribute write is pending. |
| `deviceAttributeChanged`, `deviceAttributeReport` | A device attribute value or its metadata is reported. A new value is not required. |
| `deviceUpdated`, `deviceDeleted` | Device metadata/multiple attributes change, or the device is deleted. |
| `deviceIdentified` | The gateway acknowledges forwarding an identify command. |
| `deviceSoftwareVersionUpdated`, `deviceSoftwareUpdateAssigned`, `deviceSoftwareUpdateInProgress` | Device firmware version changes, installation is queued or progress is reported. |
| `moodSaved`, `moodDeleted` | A mood is created/edited or deleted. |
| `moodActivated`, `activeMoodsChanged` | A mood reaches its target state or the active mood set changes. |
| `roomSaved`, `roomDeleted` | Room creation/editing or deletion. |
| `groupSaved`, `groupOnTopLevelCreated`, `groupOnTopLevelUpdated`, `groupDeleted` | Room/top-level group configuration or deletion. |
| `groupAttributeSent`, `groupAttributeChanged` | A group write is pending, or a group attribute is reported. |
| `timelineItemSaved`, `timelineItemDeleted` | Calendar item creation/editing or deletion; not a notification that a scheduled action has executed. |
| `ruleSaved`, `ruleDeleted` | Rule creation/editing or deletion; not a notification that a rule has fired. |
| `userAddedToHome`, `userUpdated`, `userRemovedFromHome` | Invitation/access, home-user update or removal. User details are omitted. |
| `userPinUpdated`, `userPinUpdateFailedPinCollision` | User PIN update succeeds or collides with another PIN. |
| `transferRegistered` | A home ownership transfer is requested. |
| `supportAccessRequested`, `supportAccessApproved`, `supportAccessRejected` | Support access request or decision. |
| `doorLockAccessCreated`, `doorLockAccessUpdated`, `doorLockAccessDeleted` | Lock access entry creation, change or deletion. |
| `doorLockFailedAuthPin`, `doorLockAccessPinCollision`, `doorLockAccessTagCollision`, `doorLockAccessNoAvailableSlot` | Lock authorization or access-entry operation fails. |
| `doorLockUnknownTag` | An unrecognized tag is scanned; its RFID value is omitted. |
| `doorLockAutoCalibrationStarted` | The gateway forwards a lock calibration request; not calibration completion. |
| `deviceOnWithTimedOffSent`, `deviceTimedOffCancelSent` | Timed-off command or cancellation is forwarded; not confirmation of a physical on/off transition. |
| `homeElectricityPriceSettingsUpdated`, `homeElectricityMainCircuitBreakerSettingsUpdated`, `homeElectricityGridTariffLevelSettingsUpdated`, `homeElectricityCorrectionFactorSettingsUpdated` | Corresponding electricity configuration is saved. |
| `homeAlarmSettingsUpdated`, `homeArcSettingsUpdated`, `homeEnergySaverSettingsUpdated` | Alarm, ARC or Energy Saver home settings are saved. |
| `electricityMainCircuitBreakerLimitExceeded`, `electricityMainCircuitBreakerLimitOk` | Breaker-load limit is reported exceeded or back within bounds. |
| `electricityGridTariffLevelLimitExceeded`, `electricityGridTariffLevelLimitOk` | Grid-tariff consumption limit is reported exceeded or back within bounds. |
| `deviceEnergySaverOverridden`, `deviceEnergySaverOverriddenPausedUntilMidnight` | Manual Energy Saver override, optionally pausing until midnight. |
| `deviceEnergySaverEnabled`, `deviceEnergySaverDisabled`, `deviceEnergySaverSettingsUpdated` | Device Energy Saver enablement or settings change. |
| `actionTimeout` | A tracked action times out or fails; match the optional `actionId`. |
| `subscriptionAdded`, `subscriptionUpdated`, `subscriptionRemoved` | Home subscription lifecycle changes. |
| `serviceAdded`, `serviceUpdated`, `serviceRemoved`, `serviceExpired` | Home service lifecycle changes. |
| `energySaverDeviceStatusUpdated` | Energy Saver reports a device-status change; the main table defines no identifying/status payload. |
| `arcUpdated`, `arcTestModeUntilUpdated` | ARC details or the test-mode deadline change. |

Of these, 65 carry a complete home according to the main table. The integration
replaces its entity snapshot for any event containing `home`, including unknown
future events. The individual snapshot flags and upstream field lists are kept
in [`tests/fixtures/sse_events.json`](../tests/fixtures/sse_events.json).

## Events outside the main table

`homeEventCreated` means a new home activity-log item exists. It fires
`eva_event` after the snapshot, but its `homeEvent` object is discarded, so
automations cannot inspect the log item's `iconType`, title or body.

The following names are in the separate **upcoming** camera documentation.
Their event names and allowed envelope fields are generically forwarded, but
this does not mean native camera functionality is implemented. Structured
`value` data is omitted; scalar `value` data is forwarded unchanged.

| `eventType` | Cause and current payload limitation |
| --- | --- |
| `cameraProvisioningWifiUpdated`, `cameraProvisioningQrCreated` | Provisioning acknowledgement/QR generation. QR scalar is sensitive and currently forwarded: see the review. |
| `cameraScanUpdated` | Camera discovery progress; scan detail object is omitted. |
| `cameraLiveViewOffered` | Live/playback offer; session/SDP/candidate object is omitted. |
| `cameraLiveViewAnswered`, `cameraLiveViewEnded` | Session answer/end acknowledged; scalar session ID can remain in `value`. |
| `cameraMoveAccepted` | Movement request accepted; detail object is omitted. |
| `cameraMotionDetected` | Camera motion/person start or end; kind/state/timing object is omitted. Not replayed. |
| `cameraRecordingUpdated`, `cameraRecordingRemoved` | Recording status changes or recording deletion; structured recording detail is omitted. |
| `cameraRecordingsRefreshed`, `cameraRecordingsDeleted` | Recording list refresh or bulk deletion completes; structured counts are omitted. |
| `cameraRecordingRetentionUpdated`, `cameraAlarmRecordingUpdated` | Retention or alarm-recording configuration changes; structured settings are omitted. |
| `cameraArcMediaSharingUpdated` | ARC media-sharing policy changes; structured detail is omitted. |
| `cameraArcMediaRequestCreated`, `cameraArcMediaRequestAnswered`, `cameraArcMediaRequestRevoked` | ARC media request, response or consent withdrawal; structured detail is omitted. |
| `actionFailed` | Camera action failure; allowed envelope fields remain. Immediate HTTP rejection need not generate an SSE event. |

Camera onboarding can also emit the already-listed `deviceFound`, `deviceAdded`
and `deviceUpdated`; camera settings can emit the usual attribute events. No
generic physical-button press trigger is established by these contracts.
Physical mood buttons can cause `moodActivated`, but that event can also result
from the app, HA, a gateway rule or another source.
