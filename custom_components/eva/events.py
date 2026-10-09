"""SSE action outcomes and public automation data from the App API contract."""

EVENT_TYPE = "eva_event"
STREAM_EVENTS = {"initialHome", "homeFeatures", "reconnectInfo", "keepAlive"}
ACTION_SUCCESS_EVENTS = {
    "activeProfileUpdated",
    "cameraCreated",
    "captureImage",
    "scanActivated",
    "externalDeviceReconnected",
    "deviceAttributeChanged",
    "deviceUpdated",
    "deviceDeleted",
    "deviceIdentified",
    "deviceSoftwareUpdateAssigned",
    "moodActivated",
    "groupSaved",
    "groupOnTopLevelCreated",
    "groupOnTopLevelUpdated",
    "groupAttributeChanged",
    "groupDeleted",
    "timelineItemSaved",
    "timelineItemDeleted",
    "ruleSaved",
    "ruleDeleted",
    "doorLockAccessCreated",
    "doorLockAccessUpdated",
    "doorLockAccessDeleted",
    "doorLockAutoCalibrationStarted",
    "deviceOnWithTimedOffSent",
    "deviceTimedOffCancelSent",
    "deviceEnergySaverOverridden",
    "deviceEnergySaverOverriddenPausedUntilMidnight",
    "deviceEnergySaverEnabled",
    "deviceEnergySaverDisabled",
    "deviceEnergySaverSettingsUpdated",
}
ACTION_FAILURE_EVENTS = {
    "actionTimeout",
    "scanCanceled",
    "doorLockAccessPinCollision",
    "doorLockAccessTagCollision",
    "doorLockAccessNoAvailableSlot",
}


def action_failed(event_type: str) -> bool:
    """Some documented failures lack 'Failed' in their event name."""
    return "Failed" in event_type or event_type in ACTION_FAILURE_EVENTS


def event_data(event: dict) -> dict:
    """Allow operational fields only; never publish homes, users, PINs or RFID tags."""
    data = {
        key: value
        for key, value in event.items()
        if key
        in {
            "eventType",
            "id",
            "timestamp",
            "actionId",
            "deviceId",
            "groupId",
            "moodId",
            "roomId",
            "ruleId",
            "timelineId",
            "subscriptionId",
            "externalDeviceId",
            "name",
            "value",
            "updatedAt",
            "progress",
            "softwareVersion",
            "automaticSoftwareUpdates",
            "estimatedExitDelayExpiresAt",
            "estimatedEntryDelayExpiresAt",
            "testModeUntil",
        }
        and (value is None or type(value) in (str, bool, int, float))
        and (
            key != "value"
            or event.get("eventType")
            in {
                "deviceAttributeChanged",
                "deviceAttributeReport",
                "groupAttributeChanged",
                "groupAttributeReport",
            }
        )
    }
    for key, fields in {
        "activeProfile": {"mode"},
        "softwareUpdate": {"status", "version", "progress"},
        "alert": {"id", "type", "active", "status"},
        "automaticSoftwareUpdates": {"enabled", "hourOfDay"},
        "homeEvent": {"id", "timestamp", "iconType"},
    }.items():
        value = event.get(key)
        if isinstance(value, dict):
            data[key] = {
                name: item
                for name, item in value.items()
                if name in fields
                and (item is None or type(item) in (str, bool, int, float))
            }
        elif key == "alert" and type(value) in (str, bool):
            data[key] = value
    if event.get("eventType") == "cameraMotionDetected" and isinstance(
        event.get("value"), dict
    ):
        data["value"] = {
            key: value
            for key, value in event["value"].items()
            if key in {"deviceId", "kind", "state", "cameraEventType", "detectedAt"}
            and isinstance(value, str)
        }
    if isinstance(event.get("activeMoods"), list):
        data["activeMoods"] = [
            value for value in event["activeMoods"] if isinstance(value, str)
        ]
    if isinstance(event.get("warnings"), list):
        data["warnings"] = [
            {
                key: value
                for key, value in warning.items()
                if key in {"id", "type", "severity", "alarm", "dismissible"}
                and type(value) in (str, bool)
            }
            for warning in event["warnings"]
            if isinstance(warning, dict)
        ]
    return data
