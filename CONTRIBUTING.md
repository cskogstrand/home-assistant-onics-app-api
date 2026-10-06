# Contributing

Work in this repository. Use Python 3.14.2 or newer in the 3.14 series:

```sh
./scripts/setup
./scripts/lint
./scripts/test
```

Use `./scripts/develop` for the separate Docker Home Assistant test instance at
<http://localhost:8124>. See [README.md](README.md) for setup and pending API inputs.

Keep API changes read-only for this milestone. Add focused tests with invented,
sanitized data. Never include credentials, tokens, or private home/device data in
code, fixtures, logs, or issues. Preserve the existing [MIT license](LICENSE).
