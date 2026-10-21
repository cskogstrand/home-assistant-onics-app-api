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

### IntelliJ manifest warnings

If IntelliJ reports that `issue_tracker` or `version` is not allowed in
`custom_components/eva/manifest.json`, it has selected a schema for built-in Home
Assistant integrations. Both fields are required for this HACS custom integration.
Choose a custom-integration schema, or use **Ignore JSON schema for this file**
from the editor's JSON Schema selector. Keep the fields; CI validates the manifest.

## Releases

The version in `custom_components/eva/manifest.json` is the source of truth.
Use `MAJOR.MINOR.PATCH` (for example, `0.1.2`), or append `a1`, `b1` or `rc1`
for a prerelease (for example, `0.2.0b1`). Release tags must match exactly,
with a leading `v`.

1. Update the manifest version, run the checks above, and commit the release changes
   to `main`. Wait for its **Validate** and **Lint and test** workflows to pass.
2. Tag that commit and push the tag. For a manifest version of `0.1.2`:

   ```sh
   git tag -a v0.1.2 -m "Eva 0.1.2"
   git push origin v0.1.2
   ```

3. The **Release** workflow runs the same validation, linting and tests on the
   tagged commit. It rejects a tag that differs from the manifest version, builds
   `eva.zip`, and creates a **draft** GitHub release with generated release notes.
   Alpha, beta and release-candidate versions are marked as prereleases.
4. Open the draft on the repository's **Releases** page, review the notes and
   attached `eva.zip`, then publish it. HACS sees published releases; tags and
   drafts alone do not make a version available.

The archive contains the committed integration files at its root, including
translations and branding, plus the MIT license. Local caches and untracked
files are excluded. Its fixed filename matches `hacs.json`; the tag, release
title and packaged manifest carry the version. No personal access token is
needed: only the release job receives `contents: write` for its `GITHUB_TOKEN`.

If validation or packaging fails, no draft is created. Fix the problem and use
a new version and tag. Do not replace published tags or release assets.
