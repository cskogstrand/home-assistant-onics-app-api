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

## Deploying from main

After `./scripts/setup`, commit your code changes, then run
`./deploy.sh` from a clean `main` checkout. The script operates only on this
repository and patch-bumps `custom_components/eva/manifest.json` without reformatting it. It fetches
`origin/main` and refuses behind or diverged branches. Committed local changes
ahead of `origin/main` are included in the push.

It runs `./scripts/lint`, `./scripts/test` and `docker compose config --quiet` before committing the manifest and `CHANGELOG.md` together and pushing `main`.
**If any check fails, the original version and changelog are restored and nothing
is committed or pushed.** Concurrent edits are preserved. If a commit or push fails after
testing, inspect the local release commit and finish the push manually; do not
run the script again and bump twice. It never force-pushes or resets your work.

The changelog lists commit subjects since the previous recorded release, excluding
merge commits and automated version-bump commits. Historical entries are kept,
and a hidden `release-source` marker records each boundary; preserve these markers
when editing notes. Missing or invalid markers and duplicate version entries stop
the deployment before tests or a push. The current published release is included
as the initial changelog boundary.

GitHub publishes the matching version entry as release notes after CI passes.
Manual version bumps without an entry retain GitHub's generated-notes fallback;
when releasing manually, add a `## VERSION` section with a `release-source` marker
for the source commit so the next `./deploy.sh` can continue from it.

Automatic patch bumps require stable `MAJOR.MINOR.PATCH` versions. Use the manual
release process for minor, major or prerelease changes. GitHub's release workflow
still performs Hassfest and HACS validation before publishing.

## Releases

The version in `custom_components/eva/manifest.json` is the source of truth.
Use `MAJOR.MINOR.PATCH`, or append `a1`, `b1` or `rc1` for a prerelease (for example,
`0.2.0b1`). **Pushing or merging a version increase to `main` requests automatic
publication.** Choose patch for fixes, minor for features, and major for breaking
changes. Prereleases remain marked as prereleases and do not replace the latest
stable release.

1. Increase the manifest version, for example from `0.1.2` to `0.1.3`, run the checks
   above, and commit the changes. Push or merge that commit into `main`.
2. The **Release** workflow compares the manifest before and after the whole push.
   An unchanged version skips release jobs; malformed versions and decreases fail
   without publishing. Prereleases progress in alpha, beta, release-candidate,
   then stable order.
3. Hassfest, HACS validation, linting and tests run against that exact commit.
   When all pass, the workflow builds and verifies `eva.zip`, creates the matching
   tag (for example, `v0.1.3`), and publishes the release with the matching changelog entry (or GitHub-generated
   notes if no entry exists).
   The release stays a draft during upload so HACS receives a complete ZIP.

Ordinary pushes continue to run CI. Other branches and manually pushed tags do
not publish releases. A separate release branch or personal access token is not
needed; `./deploy.sh` automates the local patch-release steps. Only the release job receives `contents: write` for its
`GITHUB_TOKEN`; the workflow never edits or commits the manifest for you.

The archive contains the committed integration files at its root, including
translations and branding, plus the MIT license. Local caches and untracked
files are excluded. Its fixed filename matches `hacs.json`; the tag, release
title and packaged manifest carry the version.

If checks fail, fix the problem and increase the version again, or rerun the
original workflow for a transient failure. An existing tag is never overwritten:
if a run stops after tag creation or draft upload, inspect that tag and draft
before completing publication manually or choosing a new version. Published
tags and assets must not be replaced.
