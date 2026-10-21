![Eva](https://raw.githubusercontent.com/cskogstrand/home-assistant-onics-app-api/main/custom_components/eva/brand/logo.svg)

# Eva for Home Assistant

[![Version](https://img.shields.io/github/manifest-json/v/cskogstrand/home-assistant-onics-app-api?filename=custom_components%2Feva%2Fmanifest.json&label=version)](https://github.com/cskogstrand/home-assistant-onics-app-api/releases)
[![HACS custom repository](https://img.shields.io/badge/HACS-Custom-41BDF5)](#install-with-hacs)

Connect your Eva home to Home Assistant for live updates, device controls and
automations. A personal, experimental project, unaffiliated with Eva or Onics.

## Supported features

Lights, plugs, heating, covers, locks, alarm profiles, sensors, energy and water
meters, EV charging, Energy Saver, moods and room groups. Available controls
depend on your devices and home.

Devices are discovered automatically, Eva rooms map to Home Assistant areas,
and you can connect multiple homes with a saved login.

## Get started

Requires **Home Assistant 2026.9.4+**, internet access and an Eva account.
Pair and configure your devices in Eva first.

### Install with HACS

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=cskogstrand&repository=home-assistant-onics-app-api&category=integration)

1. In HACS, open **Custom repositories** from the top-right menu.
2. Add `https://github.com/cskogstrand/home-assistant-onics-app-api` as an **Integration**.
3. Download **Eva** and restart Home Assistant.

### Install manually

Extract `eva.zip` from the [latest release](https://github.com/cskogstrand/home-assistant-onics-app-api/releases/latest)
into `custom_components/eva` in your Home Assistant configuration folder, then restart.

### Connect your home

1. Open **Settings → Devices & services → Add integration → Eva**.
2. Choose **Prod** for your regular home, or **Test** / **QA** for a test account.
3. Sign in with your Eva email and password, or use a saved login, then select your home.

To connect another home, add Eva again. To update, install the new version through
HACS or replace the integration files, then restart Home Assistant.

## Good to know

- Eva requires a cloud connection; controls follow the state reported by Eva.
- Eva room assignments override manual device-area changes in Home Assistant.
- Passwords are stored locally without encryption by the integration. Saved logins
  remain after removing a home. Keep storage and backups private, and remove
  credentials and private home/device data before sharing logs.
- Pairing, account management and mood editing stay in Eva. Camera streams are
  unsupported, and alarm entities show profiles and countdowns, not triggered alerts.
- Continuous background connections are outside the App API's stated intended use.
  Read the [coverage and limitations](docs/API_REVIEW.md) before relying on this integration.

## Documentation

- [Controls and actions](docs/ACTIONS.md)
- [Automation examples](docs/AUTOMATIONS.md)
- [Development and releases](docs/DEVELOPMENT.md)
- [Report an issue or request a feature](https://github.com/cskogstrand/home-assistant-onics-app-api/issues)

[MIT license](LICENSE). Eva names and logos belong to their respective owners.
