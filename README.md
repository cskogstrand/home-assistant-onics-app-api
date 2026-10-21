<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/cskogstrand/home-assistant-onics-app-api/main/custom_components/eva/brand/dark_logo.png">
  <img src="https://raw.githubusercontent.com/cskogstrand/home-assistant-onics-app-api/main/custom_components/eva/brand/logo.png" alt="Eva" width="154" height="46">
</picture>

# Eva for Home Assistant

[![Version](https://img.shields.io/github/manifest-json/v/cskogstrand/home-assistant-onics-app-api?filename=custom_components%2Feva%2Fmanifest.json&label=version)](https://github.com/cskogstrand/home-assistant-onics-app-api/releases)
[![Downloads](https://img.shields.io/github/downloads/cskogstrand/home-assistant-onics-app-api/total)](https://github.com/cskogstrand/home-assistant-onics-app-api/releases)
[![HACS custom repository](https://img.shields.io/badge/HACS-Custom-41BDF5)](#install-with-hacs)
[![Minimum Home Assistant version](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fcskogstrand%2Fhome-assistant-onics-app-api%2Fmain%2Fhacs.json&query=%24.homeassistant&label=Home%20Assistant&suffix=%2B&color=41BDF5)](#get-started)
[![Validation](https://github.com/cskogstrand/home-assistant-onics-app-api/actions/workflows/validate.yml/badge.svg?branch=main)](https://github.com/cskogstrand/home-assistant-onics-app-api/actions/workflows/validate.yml)
[![Lint and tests](https://github.com/cskogstrand/home-assistant-onics-app-api/actions/workflows/lint.yml/badge.svg?branch=main)](https://github.com/cskogstrand/home-assistant-onics-app-api/actions/workflows/lint.yml)
[![License](https://img.shields.io/github/license/cskogstrand/home-assistant-onics-app-api)](LICENSE)

Bring your Eva smart home into Home Assistant. Control supported devices, follow
live updates, and build automations with native Home Assistant entities.

[Get started](#get-started) · [Supported features](#supported-features) · [Documentation](#documentation)

> A personal, experimental integration. This is not an official Eva or Onics product.

## Supported features

The integration discovers devices and room groups in your Eva home and exposes
the features they support. Available controls depend on each device's capabilities
and the features enabled for your home.

| In your home | In Home Assistant |
| --- | --- |
| Lights and plugs | On/off, dimming, color temperature and color controls |
| Heating | Thermostats, target temperatures and supported heating settings |
| Blinds and covers | Position and tilt controls |
| Locks and alarms | Lock/unlock with optional PIN, alarm profiles and entry/exit countdowns |
| Sensors | Temperature, humidity, air quality, motion, contact, smoke, leaks and more |
| Energy and water | Meter readings for dashboards, plus supported power and consumption sensors |
| EV charging | External charger status and start/stop controls |
| Energy Saver | Enable switches for eligible devices, with settings and data available through actions |
| Moods and room groups | Existing Eva moods as scenes and supported room-group controls |
| Device management | Battery and connection diagnostics, supported settings and firmware updates |

- **Live updates:** device state follows changes reported by Eva.
- **Automatic discovery:** newly added devices appear, and removed devices are cleaned up.
- **Room organization:** Eva rooms map to Home Assistant areas.
- **Multiple homes:** add each home separately and reuse a saved Eva login.
- **Automations:** use native entities or Eva events for alerts, activity and energy notifications.

See the [controls and actions guide](docs/ACTIONS.md) for advanced controls and examples.

## Get started

You will need **Home Assistant 2026.9.4 or newer**, an Eva account with access to
an existing home, and an internet connection. Pair and configure your devices in
Eva before adding the integration.

### Install with HACS

[![Open this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=cskogstrand&repository=home-assistant-onics-app-api&category=integration)

Eva is available as a [HACS custom repository](https://www.hacs.xyz/docs/faq/custom_repositories/).
HACS downloads require a published release. Before the first release, use the
manual source installation below.

1. In HACS, open the menu in the top right and choose **Custom repositories**.
2. Add `https://github.com/cskogstrand/home-assistant-onics-app-api` with type **Integration**.
3. Find **Eva**, download it, and restart Home Assistant.

### Install manually

1. Download `eva.zip` from the [latest release](https://github.com/cskogstrand/home-assistant-onics-app-api/releases/latest)
   and extract its contents into `custom_components/eva` inside your Home Assistant
   configuration folder. Create that directory if it does not exist.
2. Restart Home Assistant.

Before the first release, copy this repository's `custom_components/eva` folder
into your Home Assistant `custom_components` directory instead.

### Updates

Install new versions through HACS, or replace the files in `custom_components/eva`
with the contents of the new release archive. Restart Home Assistant after updating.
See the [release notes](https://github.com/cskogstrand/home-assistant-onics-app-api/releases)
for changes and any upgrade instructions.

If HACS still shows an older commit or README, open Eva and select **⋮ → Update
information**, then update or **Redownload** and select the release version.
Restart Home Assistant after installation. HACS shows the README for the installed
revision; tags and draft releases alone do not appear as release choices.

### Connect your home

1. Open **Settings → Devices & services → Add integration** and search for **Eva**.
2. Choose **Prod** for your regular Eva home, or **Test** / **QA** for a test account.
3. Enter your Eva email and password. If you already have a saved login in that
   environment, choose **Use a saved login** or **Log in with another user**.
4. Select the home you want to connect.

Your supported devices and entities appear when the first home update arrives.
To connect another home, add Eva again and reuse your saved login. Each home can
be added once per environment.

## Good to know

- **Cloud connection:** Eva requires internet access. Most updates arrive live;
  external EV charger status refreshes once per minute. Controls reflect Eva's
  reported state, so a command may take a moment to appear.
- **Rooms:** Eva room assignments take precedence over manual device-area changes
  in Home Assistant.
- **Accounts:** logins are saved locally per email and environment. Updating a
  saved password reloads the homes using that login. Saved logins remain available
  after removing a home.
- **Privacy:** passwords are not encrypted by the integration. Keep Home Assistant
  storage and backups private, and remove credentials and private home/device
  data before sharing logs or reporting issues.
- **Scope:** device pairing, account administration and mood editing stay in Eva.
  Native camera controls and streams are not implemented. Alarm entities report
  profiles and countdowns; they do not infer a triggered alarm from alerts.
- **Experimental use:** continuous background connections are outside the App API's
  stated intended use. See the [coverage and limitations review](docs/API_REVIEW.md)
  before relying on the integration.

## Branding

Eva includes its icons and light/dark logos in `custom_components/eva/brand/`.
Home Assistant uses these local images under **Settings → Devices & services**
after installation and restart. Refresh your browser or companion app if it still
shows a cached placeholder.

The HACS repository-list icon is separate: HACS 2.0.5 still uses the old remote
brand catalog and can show a placeholder even when the installed icon works.
This is a [known HACS issue](https://github.com/hacs/integration/issues/5179#issuecomment-6222990038).
Maintainers report it fixed in the Marketplace integration planned for Home
Assistant 2026.11. Another Eva release or redownload does not fix the HACS icon.

## Documentation

| Guide | What you will find |
| --- | --- |
| [Controls and actions](docs/ACTIONS.md) | Advanced device controls, Energy Saver settings and on-demand data |
| [Automation events](docs/AUTOMATIONS.md) | Event triggers, payloads and ready-to-use YAML examples |
| [Coverage and limitations](docs/API_REVIEW.md) | Implemented API features and known gaps |
| [Development](docs/DEVELOPMENT.md) | Local Home Assistant setup, linting, tests and releases |

Found a problem or have an idea? [Report an issue or request a feature](https://github.com/cskogstrand/home-assistant-onics-app-api/issues).

---

Based on the integration blueprint and released under the [MIT license](LICENSE).
Eva names and logos belong to their respective owners.
