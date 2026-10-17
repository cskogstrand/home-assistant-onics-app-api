# Development

[Back to the integration overview](../README.md)

Run commands from the repository root. Use a separate Home Assistant instance
and keep real credentials and home data out of commits, logs and test fixtures.

## Local Home Assistant instance

Requires Docker Compose:

```sh
./scripts/develop
```

Open the [local Home Assistant instance](http://localhost:8124), finish Home Assistant onboarding, then add Eva.
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

## Validation

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
