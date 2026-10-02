# Contributing

Thank you for helping. The guiding rule is **keep it simple and secure**: the simplest
implementation of each feature, safe defaults, input validated at the boundary, and no
new dependencies.

## Development setup

You need Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.14 .venv && uv pip install --python .venv/bin/python -r requirements_test.txt
```

## Test, lint and translations

```bash
.venv/bin/pytest                      # tests (coverage gate: 95 %)
.venv/bin/ruff check .                # lint
.venv/bin/ruff format .               # format
.venv/bin/python scripts/build_translations.py   # after editing strings.json
.venv/bin/python scripts/make_brand.py           # redraw the brand images
```

Rules for changes:

- Keep `protocol.py`, `render.py` and `presets.py` pure (no Home Assistant imports, no I/O).
- No runtime dependencies beyond what Home Assistant core bundles.
- Every BLE write costs battery. Do not add a path that writes when nothing changed.
- Commit messages: a short imperative subject line.

## Release steps

Never release without the maintainer's go-ahead.

1. Bump `version` in `manifest.json` and update `CHANGELOG.md` in a pull request.
2. After merging, push the tag `vX.Y.Z`. The `manifest.json` version must equal the tag.
3. `release.yml` runs the tests and validation, then runs `gh release create` with that
   CHANGELOG section.

Versions follow SemVer. `0.1.0` is the first public pre-release, after hardware checks H1
to H8 pass. `1.0.0` follows the H9 soak test and at least one other tester. See
[docs/hardware-checks.md](docs/hardware-checks.md).

## Repository settings checklist

Set these by hand in GitHub:

- [ ] Branch protection on `main`, with required checks and no force-push
- [ ] Secret scanning and push protection
- [ ] Private vulnerability reporting
- [ ] CodeQL default setup
- [ ] Description, and topics `home-assistant`, `hacs`, `bluetooth`, `lywsd03mmc`, `pvvx`, `display`

## CI policy

- Every `uses:` in a workflow is pinned to a 40-character commit SHA with a `# vX.Y.Z` comment.
- Workflows set `permissions: {}`, with job-level grants only where needed.
- No `pull_request_target`.
- Dev dependencies are pinned exactly in `requirements_test.txt`.
