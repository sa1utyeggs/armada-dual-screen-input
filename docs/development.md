English · [简体中文](zh-CN/development.md)

<a id="开发与打包"></a>

# Development and packaging

<a id="目录边界"></a>

## Directory boundaries

- `src/armada_dual_screen_input/` is a Python package with relative imports. Session discovery, input state machines and GTK presentation are separated; drawing never waits for network/X11 queries.
- `tests/` runs fake or isolated checks, without starting the panel or sending input to a real game. Linux GTK integration checks are skipped on Mac.
- `tools/manage.py` manages per-user installation, `tools/release.py` prepares/verifies packages, and `tools/build_release.py` creates archives.
- `tools/run.py` gives source and installed bundles the same launch context. Children get an explicit application `PYTHONPATH`, independent of the working directory.
- `vendor/ratatoskr/` retains the pinned snapshot, licenses, credits and local-change notes. Update `UPSTREAM` when changing it.
- `extras/thor-touch-driver/` is a separate GPL experiment, excluded from the app installer and release bundles. Kernel builds/trials stay outside default tests; the optional GUI bridge is checked with fake privilege and devices. Do not describe its state as a general application dependency.

<a id="检查"></a>

## Checks

```bash
python3 -B tools/run_tests.py
python3 -B tools/run_tests.py --with-node
```

The second command also runs 15 Steam-keyboard JavaScript checks and needs Node.js. Full Linux GTK checks need PyGObject, Cairo, GTK3 and GtkLayerShell. With those dependencies they run without a display, using fake windows/input objects. Bilingual glyph checks also need the Noto CJK fonts installed by CI.

Skipped Mac checks are not Linux device passes. Input, focus or window-lifetime changes also need interactive acceptance after games have been saved.

Probe session/dependencies without creating input devices:

```bash
python3 -B tools/run.py --probe
```

Manual UI execution creates this app's own virtual input devices:

```bash
python3 -B tools/run.py --run
```

Only Game Mode is discovered by default. Do not automatically run `native_touch_probe.py` or `position_input_smoke.py` in CI or while a user's game is running. These tools target only their own test windows and require explicit scheduling. An import example is `PYTHONPATH=src python3 -B tools/position_input_smoke.py`; the private GTK library/typelib environment must also be correct.

Keyboard timing uses a real GLib clock. By default it renders offscreen and records a fake device, without creating windows or input devices:

```bash
python3 -B tools/keyboard_latency_bench.py --output /tmp/keyboard-timing.json
```

During an arranged interactive test with Steam's home screen idle, explicitly run a dedicated upper-screen test window:

```bash
python3 -B tools/keyboard_latency_bench.py --run-own-window-test --output /tmp/keyboard-native.json
python3 -B tools/keyboard_ime_latency_bench.py --run-own-window-test --output /tmp/keyboard-ime.json
python3 -B tools/keyboard_window_latency_bench.py --run-own-window-test --output /tmp/keyboard-window.json
python3 -B tools/keyboard_window_latency_bench.py --run-own-window-test --defer-status-during-typing --output /tmp/keyboard-window-status.json
python3 -B tools/keyboard_window_latency_bench.py --run-own-window-test --defer-status-during-typing --short-taps --output /tmp/keyboard-feedback.json
```

Run these tools one at a time. The first two use fixed test text and require their own upper window to stay focused; they stop on focus loss. They never type into a game or Steam search, save personal text or change input settings. The third briefly covers the lower screen and compares full/partial painting on a real Wayland target with synthetic state; it creates no input device. Checks include 5/10/15 taps per second, held letters/Backspace and pinyin candidates/Space commits. `passed` means correct content/order/release or enough completed draws. Timings are comparative figures, not physical end-to-end touch latency or a long-term stutter-free guarantee. See [measurement boundaries and results](keyboard-latency.md).

`--short-taps` also checks 2/5/8/12/20/40ms taps and down/up received in one main-thread batch. It records whether the draw callback selected the pressed color, not whether the physical display presented it. Missing visual feedback is not counted as a lost native key.

<a id="构建离线包"></a>

## Build an offline package

```bash
python3 -B tools/build_release.py
```

The builder downloads a pinned Fedora ARM64 gtk-layer-shell RPM, verifies SHA-256 and extracts only the five manifest-listed files. Use an already downloaded RPM for a fully offline build:

```bash
python3 -B tools/build_release.py --offline --runtime-rpm /路径/gtk-layer-shell-0.10.0-1.fc44.aarch64.rpm
```

Mac uses the system libarchive tar with RPM support; Linux can use `rpm2cpio` + `cpio`. Output goes to `dist/`:

```text
armada-dual-screen-input-<VERSION>-aarch64.tar.gz
SHA256SUMS
```

`manifest.json` contains each file's SHA-256, source revision and bundle ID. Uncommitted sources get a `-dirty` revision suffix. With the same source tree and revision, archive ordering, permissions, uid/gid and timestamps are fixed for reproducibility. Whitelisted sources, templates, licenses, bilingual documentation and the pinned runtime are included. Tests, personal configuration, logs, caches, Git history and driver experiments are excluded.

<a id="发布"></a>

## Releases

1. Finish feature checks and compatibility notes on a feature branch, commit and obtain PR review.
2. Update `VERSION`, place this release's changes under matching nonempty `## <VERSION>` headings in **both** `CHANGELOG.md` and `CHANGELOG.zh-CN.md`, then merge to `main`. Use SemVer, e.g. `0.1.0-preview.3`. A `-preview.3` / `-rc.1` suffix marks a prerelease; `+build` metadata alone does not.
3. Create and push the exact matching tag on a clean `main` commit. **Pushing the tag publishes a release**, so do this only when publication is intended:

   ```bash
   (
     set -eu
     git switch main
     git pull --ff-only
     test -z "$(git status --porcelain)"
     release_version=$(cat VERSION)
     git tag -a "v$release_version" -m "Release v$release_version"
     git push origin "v$release_version"
   )
   ```

4. Open Actions → **Build and release offline package**. After full Linux/Python/JavaScript checks pass, CI verifies matching tag and `VERSION`, membership in `main` and both changelog entries. It builds the pinned-dependency aarch64 bundle from that commit and checks SHA-256. The publishing job checks that the remote tag still targets that source revision.
5. CI creates a draft, uploads `armada-dual-screen-input-<VERSION>-aarch64.tar.gz` and its `SHA256SUMS`, then publishes. Notes include English first, Simplified Chinese second, with installation/checksum instructions in both languages. Prereleases are not Latest. Only the publishing job has `contents: write`; checks/builds remain read-only, without a personal access token.
6. Validate fresh installation, configuration-preserving upgrade, rollback and uninstall on AYN Thor before expanding device support. Record isolated checks separately from device acceptance. GitHub's generated Source code archives are not the installer bundle. Private-repository releases cannot be anonymously downloaded.

The manual **Run workflow** entry remains artifact-only: checks, build and an Actions artifact containing the package, checksum and release notes. Release-related PRs also build without publishing.

Failed checks, version validation or build create no release; failed uploads leave a draft. **Re-run failed jobs** can finish that draft. Reruns do not overwrite a published release: use a new version and tag, and never move a published tag. Updating historical release prose does not replace its assets or tags.

The workflow changes no repository visibility, connects to no handheld, and installs neither the app nor a driver. Do not bundle a snapshot of a personal runtime directory: binaries must come from the pinned dependency manifest and a verifiable source.

References: [reusable GitHub workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows), [GitHub CLI releases](https://cli.github.com/manual/gh_release_create).
