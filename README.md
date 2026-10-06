# Onics for Home Assistant

Personal, read-only test integration. Domain: `onics`; display name: **Onics**.
Based on the integration blueprint; its MIT license is preserved unchanged.
Development stays in this existing `home-assistant-onics-app-api` project.
These changes have not been committed or published.

**Status: independent scaffolding is implemented and tested; the first live
milestone is blocked on authentication configuration.** Onics appears in
Settings → Devices & services → Add integration, but currently explains the
missing configuration and stops. It does not authenticate, select a home, create
a config entry, or expose any sensors yet. Test fixtures are never loaded by the
integration.

## Inputs needed to complete setup

Confirm these non-secret deployment settings before authentication is implemented:

1. API base URL, including any path prefix.
2. Authentication configuration: confirm Basic authentication is enabled for
   this deployment, or supply the OAuth client ID, allowed grant/redirect URI,
   scopes, and token renewal requirements. Enter passwords or client secrets
   locally when the completed setup flow requests them, not into Git or chat.
3. `X-Client-Brand` (the documentation lists `eva`, `qualco`, `viking-guard`).
4. `X-Schema-Version`: explicitly confirm **5 or 7** (or another supported value).
   The client requirements call 5 current; the home-list section describes
   version 7. No production default has been chosen.

The [API authentication documentation](https://onicsas.github.io/home-hla-docs/#authentication)
links to [OAuth discovery](https://login.evasmart.no/auth/realms/eva/.well-known/openid-configuration).
Discovery advertises authorization code, password and refresh-token grants,
among others, but does not establish what this integration's client may use.
There is no permanent-access-token mode.

The [API introduction](https://onicsas.github.io/home-hla-docs/#introduction)
describes foreground app sessions and says continuous backend connections are
outside its intended use. Continuous Home Assistant use remains a personal test,
not a claim of supported Onics service behavior.

## Local installation and separate test instance

Requires Docker Compose:

```sh
./scripts/develop
```

Open <http://localhost:8124>, complete Home Assistant onboarding, then add Onics.
The pinned Home Assistant 2026.9.4 container has its own `config/` directory,
exposes only localhost port 8124, and mounts the integration read-only.
Stop with Ctrl-C; `docker compose down` removes the container but preserves data.
Do not use an existing production configuration directory here.

For manual installation, copy `custom_components/onics` into a test Home
Assistant's `config/custom_components/onics` and restart it. Minimum supported
Home Assistant version for this scaffold: 2026.9.4.

## Implemented independently of authentication

- Async `aiohttp` transport using only documented `GET /homes` and
  `GET /homes/{homeId}/clients/{clientId}` endpoints. The authenticated session
  lifecycle is deliberately not wired yet. No additional runtime dependencies.
- A push `DataUpdateCoordinator`, one SSE stream per entry, initial snapshot
  requirement, partial attribute merging, and complete-home replacement even for
  unknown event types. Device data is read from each room's `devices` array.
- EOF/session-expiry reconnect, SSE `retry` delay, bounded exponential backoff,
  replay via `lastSeenEventId`, 15-second inactivity detection, reset/kill events,
  auth failure handling, and awaited stream cancellation.
- Sensor platform for documented Celsius `temperature`, `airTemperature`, and
  `floorTemperature` attributes. IDs use home ID + device ID + attribute name.
  New attributes can be discovered during updates; removed/offline devices and
  disconnected streams are unavailable. Invalid/null measurements remain unknown.
- No controls, writes, diagnostics dumps, captured API responses, or fake sensors.

## Development and verification

Python 3.14.2 or newer in the 3.14 series:

```sh
./scripts/setup
./scripts/lint
./scripts/test
docker compose config --quiet
```

Tests use Home Assistant 2026.9.4 and its compatible custom-component test
plugin. Network access is disabled for tests. Fixtures contain invented home and
device identifiers. Tests cover snapshots, field-preserving patches, transport
framing/errors, reconnect/replay, auth errors, shutdown, sensor behavior and the
currently implemented UI configuration gate. The successful authentication and
home-selection flow must be implemented and tested after the inputs above arrive.

Verified locally: 31 tests passed, Ruff lint/format passed, Docker Compose
configuration parsed, and Home Assistant 2026.9.4 hassfest reported one valid
integration and zero invalid integrations. The template license is byte-for-byte
unchanged. No live account, home, or device was contacted.

After wiring authentication, live acceptance is: install → sign in → select one
home → receive `initialHome` → compare a real temperature with Onics → observe a
device update → verify reconnect after the documented 10-minute session → unload
and confirm the stream closes. This has **not** been live-tested.

Hassfest, HACS validation, linting and tests are retained in GitHub workflow
files. `hacs.json` and the standard component layout are included for future
distribution. Documentation and issue links point to this project's existing
repository. HACS distribution validation has not run locally. The inherited `brands` check is
ignored until appropriate brand assets are supplied. No publishing is performed.

Home Assistant's [config-flow guidance](https://developers.home-assistant.io/docs/core/integration/config_flow/),
[push coordinator guidance](https://developers.home-assistant.io/docs/integration_fetching_data/#pushing-api-endpoints),
and [HACS layout requirements](https://www.hacs.xyz/docs/publish/integration/)
inform this structure.

Keep credentials in Home Assistant's local configuration storage. `config/`
runtime files, `.env` files, logs, caches, and virtual environments are ignored;
only the sanitized `config/configuration.yaml` is tracked. Review staged files
before any later commit, especially if adding fixtures.
