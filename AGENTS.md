# Project guide

- Application code: `src/armada_dual_screen_input/`; tests: `tests/`; installation/release tools: `tools/`; desktop/systemd templates: `packaging/`.
- Use `python3 -B tools/run_tests.py --with-node` for application checks. Linux GTK checks skipped on Mac must be reported as skipped, not as device passes.
- Use `python3 -B tools/build_release.py` to build an offline bundle. Do not package a user's installed application/runtime snapshot, credentials, logs, configuration, caches or Git directory.
- Default installation is per-user, with no autostart and no sudo. Preserve the existing `thor-panel` configuration/service identifiers for migration. Never manage official Armada/Steam/Gamescope services through the installer.
- Keep kernel experiments under `extras/`, separately licensed and excluded from application bundles. Application changes are not authorization to load a kernel module or change boot files.
- Do not automate real input against a game as a test. Interactive device checks need explicit task context; test helpers should target only their own windows.
- Preserve vendor provenance, licenses and `UPSTREAM` change notes. The root MIT license does not replace dependency licenses.
- Keep README concise; installation in `docs/installation.md`, compatibility in `docs/compatibility.md`, detailed historical evidence in the existing docs. Separate measured, user-reported and unverified outcomes.
- Use English by default: `README.md`, `CHANGELOG.md` and `docs/*.md`. Maintain aligned Simplified Chinese editions in `README.zh-CN.md`, `CHANGELOG.zh-CN.md` and `docs/zh-CN/`, with reciprocal language links. Keep commands, measurements, provenance and validation limits consistent; preserve old anchors. `README.en.md` is a compatibility link. Every version needs matching nonempty English/Chinese changelog sections; GitHub Release notes must be English first, then Simplified Chinese. Do not alter existing release tags/assets when translating historical notes.
- Do not change repository visibility or publish a public Release without a direct user request. Preparing a package or a PR does not authorize broader access.
- Pushing a `v<VERSION>` tag triggers the authorized release pipeline: keep tag/version/changelog validation, full checks and package checksum verification before publishing. Manual workflow runs and PR builds must remain artifact-only.
