# Onics for Home Assistant

Personal, read-only test integration. Domain: `onics`; display name: **Onics**.
Based on the integration blueprint; its MIT license is preserved unchanged.
Development stays in this existing `home-assistant-onics-app-api` project.

## Setup

1. Install `custom_components/onics` in your Home Assistant configuration's
   `custom_components` directory and restart Home Assistant.
2. Open **Settings → Devices & services → Add integration → Onics**.
3. Select **Test**, **QA**, or **Prod**, then enter your Onics email and password
   for that environment. Test is the default.
4. Select one of the homes returned for your account.
5. After the initial SSE snapshot arrives, supported temperature attributes
   appear as sensors. No synthetic sensors or measurements are created.

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
To connect another home, add another Onics entry. If authentication later fails,
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

Open <http://localhost:8124>, finish Home Assistant onboarding, then add Onics.
The pinned Home Assistant 2026.9.4 container uses this project's `config/`
directory, exposes only localhost port 8124, and mounts the integration read-only.
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
  fields. Reconnects use the documented replay cursor and server retry delay.
- A silent connection becomes unavailable after 15 seconds. Dropped connections
  reconnect with backoff, including the documented 10-minute session expiry.
- Authentication failures request reauthentication; unloading cancels the stream.
- Celsius `temperature`, `airTemperature`, and `floorTemperature` attributes map
  to sensors. Entity and device IDs include environment and stable API IDs.
  New attributes are discovered during updates; removed/offline devices become
  unavailable. Null or invalid measurements remain unknown.
- This integration sends no device commands. Controls can be added later.

The [Onics API documentation](https://onicsas.github.io/home-hla-docs/#authentication)
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
reauthentication, real Home Assistant sensor setup/unload, state merging and SSE
recovery. Live authentication and real-device updates still require testing with
your own account in the selected environment.

Hassfest, HACS validation, linting and tests are retained in GitHub workflows.
HACS metadata and the standard component layout are included. The inherited
`brands` check remains ignored until appropriate brand assets are supplied.
Runtime configuration, `.env` files, logs, caches, and virtual environments are
ignored; only the sanitized `config/configuration.yaml` is tracked.
