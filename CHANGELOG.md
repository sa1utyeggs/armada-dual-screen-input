English · [简体中文](CHANGELOG.zh-CN.md)

# Changelog

## Unreleased

- Add a downloadable `.desktop` installer on the homepage, with English/Chinese graphical version review, progress, errors and retry. Reuse stable-release digest/path/manifest checks and the per-user installer; keep the selected version fixed and require confirmation before package download/install. Generate self-contained launchers from an explicit source allowlist, with a separate checksum and Release asset, preserving the single-entry app checksum for older updaters. User-assisted stable reinstallation and restoration of the original candidate passed on Thor; the public attachment button and a clean first install remain unverified. See [device evidence](docs/history.md#click-installer-20261026).
- Adapt the installer to the Thor desktop's scaled lower work area, with scrolling content and fixed language/actions. Document Firefox's added `.download` suffix. Discover the first-install version through public Release redirects and pin its HTTPS checksum asset, preserving package/manifest checks while avoiding the anonymous REST API quota. Existing in-app API update validation is unchanged.
- Add opt-in **Settings → General → Show touch contacts** at the bottom of the page. Semi-transparent vector fingers follow actual contacts in Touchpad, the pointer area of Keys+Pad, and Positioning / Direct touch. Lift, cancellation, page changes, collapse and input cleanup remove them. Keyboard, candidates and controls are excluded. Repaint only old/new illustration bounds, with no extra input, focus changes or visual polling timer. Existing preferences and default-off behavior are retained.

## 0.1.5 · 2026-10-22

- Use native XCB/EGL ring submission with an initialization-only GTK fallback and matching Cairo sprite pixels. Controlled whole-service trials measured about 16–22% less active CPU at 60 FPS and 26–31% at 120 FPS, with higher PSS and workload-dependent GPU costs; idle remains a separate limitation. Input timing, focus/route checks and frame caps are unchanged. See [measurements and limits](docs/position-touch.md#2026-10-22-native-marker-submission).
- Reduce touch-page status damage, repeated sender validation and sprite drawing work; decode XCB property metadata directly and resolve target paths with fresh libc calls. Retain independent receiver checks, bounded caches and vector fallback for other transforms. The earlier whole-service idle change was modest and did not establish an active CPU/GPU improvement; see [the follow-up](docs/position-touch.md#2026-10-22-whole-app-idle-cpu).
- Add **Settings → Experimental** with the optional Thor lower-screen driver fix, compatibility/status, confirmed enable-until-reboot and stock restore. A separately prepared root-owned component and administrator authentication are required; the normal app package contains no module, boot rule or automatic activation. Correct Game Mode driver/update/uninstall task dispatch through the actual user manager while retaining the lower desktop bus for notifications/authentication. Real authenticated restore and re-enable both succeeded on the tested Thor; long sessions and suspend/resume remain experimental. See [driver evidence and setup](docs/thor-ft5452-contact-lifecycle.md).
- Show signed **net battery watts** beside charge in the existing status row, reusing cached voltage × current telemetry without extra polling or height. Missing sensors show unavailable. While plugged in, battery flow is not total system, charger or SoC power.
- Move versions, manual update checking and confirmed installation under **Settings → General**, removing the separate Updates tab. Keep confirmation/cancel, unsaved-settings protection and operation locks; changing settings or requesting the other operation clears armed update/uninstall confirmation.
- Resolve Auto UI language from Steam's saved client language in Game Mode when the inherited system locale is C/POSIX. Read the bounded registry once at launch; preserve explicit-language/non-C-locale priority, the English fallback and input settings.
- Validate 652 Python checks on Thor, 15 Node checks on Mac and 18 isolated driver-tool checks; Mac skips 108 Linux checks. Bilingual offscreen layouts and package checks are separate from physical-input and long-session acceptance.

## 0.1.4 · 2026-10-22

- Add a confirmed Settings → General uninstall action with English/Chinese explanations of removed/retained files. It reuses the installer in a detached user task after closing the panel, preserving personal configuration, logs, backups and modified files. A shared update lock, unsaved-settings/source-run/update checks and duplicate-click protection prevent overlapping operations. Persistent results and best-effort desktop notifications report completion. Automated uninstall checks use temporary installations only.
- Add independent UI language selection: English / Simplified Chinese / System language, with English as the missing/invalid-config default. Panel, settings, status, candidate hints and updater text use stable message keys and switch immediately, independently of keyboard input and other preferences. Desktop entries gain localized names/descriptions. Coverage includes catalogs, save failures, legacy update states, font caches and bilingual offscreen layouts; see [interface language](docs/i18n.md).
- Make English the default README and documentation language, with aligned Simplified Chinese guides, reciprocal links and preserved historical anchors. Include both editions in offline bundles. Generate future GitHub Release notes in English then Chinese, refusing missing, empty or duplicate translations; translate existing release bodies without changing tags or assets.

## 0.1.3 · 2026-10-22

- Add separate idle/pressed ring colors under Settings → Touchscreen, with eight palettes and previews; defaults retain blue/orange with black outlines. Saved colors apply to Positioning and Direct touch, survive restarts, and support discard/group defaults. The worker validates/parses colors on startup without changing native touch, smoothing or frame caps.
- Add independent visual ring smoothing: confirmed coordinates converge toward the latest target within the existing drawing cap, without prediction or native input generation. Click/release/mode/reconnect snap to real coordinates, multi-touch uses stable identities, and settled motion stops drawing. Installed on Thor with smoother motion reported by the user. Eight actual-renderer synthetic trials reduced reconstructed step variation about 76% at 60/120 FPS, at the cost of small visual lag and increased motion CPU/GPU use. See [methods and limits](docs/position-touch.md).
- Add ring caps of 30 / 60 / 120 FPS or Follow screen, defaulting to Follow screen and shared by both touch modes. One-shot demand-driven scheduling and public GDK updates retain GL/FPS coexistence; extra Mesa swap waiting is disabled only in the marker child, with no continuous stationary drawing. Actual rates depend on submit waits/load. Game caps, display refresh and input rate are unchanged; see [device results](docs/position-touch.md).
- Coalesce marker updates through one GLib source instead of waiting for the 16ms health timer. Backpressure retains only the latest position; close cancels pending callbacks and send failures use existing recovery. Drawing, input, focus/route checks and preferences remain unchanged; see [delivery comparison](docs/position-touch.md).
- Bind the marker as a passive decoration of the current app, freeing mangoapp's external-overlay slot so Steam FPS and ring can coexist. App/window/server/geometry changes release old contacts and rebuild the marker, preserving GL, native-input checks and preferences. See [coexistence](docs/position-touch.md).
- Enable GTK GL composition only in the upper-marker child to avoid observed XRender/GPU waits in the Slay the Spire 2 card viewer. Lower UI, games and global environment are unchanged. Batch independent focus queries while retaining target/policy/route/expiry checks. See [short comparisons and limits](docs/position-touch.md).
- Remove lower-screen contact circles and redraw requests solely for contact motion/press/release. Status/mode changes still refresh. Upper rings, touch and focus/route checks remain.
- Share runtime-directory resolution and endpoint metadata within one target-identity check, resolving both paths before socket type/owner/identity checks. Every send revalidates; permission is not cached across events. Regressions cover endpoint replacement, escaping aliases, owner changes and replacement during checks; see [native routing](docs/native-touch-routing.md).
- Remove duplicated target/focus/route checks from native touch sending while retaining full checks immediately before every write. No cross-event permission cache; contact cadence, route-scan period/expiry and release on cancellation/failure remain. See [automated and dedicated-window tests](docs/native-touch-routing.md).
- Skip unrelated components/keycaps using GTK's actual dirty region. Direct touch updates only old/new ring bounds with a bounded static-background cache, rebuilt on scale/font changes. Keep key feedback, Chinese candidates, input cadence and focus/route checks; fix the inherited key-end path's missing partial-refresh hook. See [keyboard performance](docs/keyboard-latency.md).
- After install/upgrade/rollback/uninstall, refresh user icon/menu caches and notify actual KDE sessions, including the Game Mode lower screen, where possible. Missing tools/failures warn without undoing a successful install. Official desktop/lower/Steam sessions are never restarted automatically for icons.
- Rollback restores installer-managed old icons/entries and recovers original files/state on failure, preserving config, autostart choice and mobile-home layout. Already-painted mobile-home images may update only after re-entering Game Mode.

## 0.1.2 · 2026-10-21

- Distinguish GitHub rate limiting from other HTTP errors: exhausted limits ask the user to retry later rather than reporting a generic network fault. No automatic repeated requests.
- Add a complete English README and reciprocal language navigation, aligning features, installation and support limits. Offline bundles include both editions.
- Reorganize the GitHub landing page with feature/previews, quick installation, navigation and consistent app/social artwork. Detailed conclusions remain in compatibility/investigation records.
- Redesign the vector icon with a faded Armada sail behind a centered combined keyboard/touchpad and two touch rings, dark styling and blue highlights. Existing icon names/desktop entry remain.

## 0.1.1 · 2026-10-21

- Add Settings → Update: manually check the latest stable GitHub release, then confirm download/verification of the ARM64 bundle. Reuse the installer, retaining config, autostart and rollback. A detached user task survives panel restarts; the page reports checking/downloading/installing/failure. Unsaved settings block update start.
- Restore retry after a 45-second check timeout; stale network results cannot overwrite newer checks. No startup network check or automatic installation.
- Before downloading, validate official origin, version and asset size; then verify SHA-256 and package manifest. Reject unsafe extraction paths and reuse installer rollback on failure.

## 0.1.0 · 2026-10-21

- First stable release combines lower-screen touchpad, two-finger wheel, English/Chinese keyboard, input settings and two touch modes. Manual launch by default; upgrades retain configuration.
- Primary target: AYN Thor / ArmadaOS Steam Game Mode. Desktop Mode is disabled by default; other devices, real direct multi-touch, long sessions and suspend/resume need further validation. See [compatibility](docs/compatibility.md).
- A tag matching `VERSION` triggers GitHub CI checks, ARM64 offline packaging, verification and publication. Preview versions become prereleases; manual builds remain artifact-only.
- Add bounded thread-local Pango layout caching to reduce keyboard paint work in the input loop. Font/scale/render-option changes relayout; existing keycaps and Chinese fallback remain.
- Ordinary key/candidate changes redraw locally; fix highlights after sliding off keys. Modifier/mode/language changes keep full refresh. Partial paint reuses the last full frame's OLED offset to avoid seams.
- During typing/hold-repeat, periodic status updates redraw only the status row. After input pauses, the next status update resumes full refresh/OLED micro-shifts, reducing periodic interference.
- Separate rapid-tap highlights from physical key holding; retain feedback about 60ms after painting so a same-batch press/release remains visible. Keys still send immediately/release normally; page/cancel/close cleans timers.
- Add real GLib timing, dedicated upper-window key reception and Chinese candidate/commit tools. Typical redraw fell from about 14ms to 10ms; occasional long frames and Chinese commit waits remain. See [measurements](docs/keyboard-latency.md).

## 0.1.0-preview.2 · 2026-10-21

- Rename Positioning touch to Touchscreen; remove pause/manual enable. A visible page automatically enables after target/marker/route readiness and all fingers lifted.
- Add Direct touch with absolute coordinates, independent multi-contact begin/move/end and per-contact rings. Existing Positioning, preferences and bilingual keyboard remain.
- Use a same-toolbar Positioning / Direct touch dropdown without another row or reduced input height. Opening it pauses contact sending; selection/dismissal waits for lift and target stability before resuming.
- Submode/page changes, collapse, close or target changes release contacts. Never resume old gestures or alter game touch policy/physical drivers.
- Add keyboard-language selection and Simplified Chinese full-pinyin candidates through system libxkbcommon/libpinyin/dictionaries. Support tap/paging, Space/number selection and Enter for raw pinyin.
- Chinese engine/native text transport run separately. Isolate the private Gamescope Game Mode adapter; cancel on target changes/timeouts and stop on leaving keyboard/collapse/close. Desktop Chinese/third-party compatibility remains pending.
- Add Chinese settings for pointer movement, wheel speed/scale, tap, inertia/resistance and positioning scale.
- Add hold-repeat enable, delay/interval and Shift double-tap interval.
- Apply settings on save with group defaults/discard, atomic config writes and unknown-field preservation. Entering settings releases old input; restart retains input mode; no default autostart.

## 0.1.0-preview.1

- Reorganize app source, independent tests, packaging templates, tools, assets and documentation.
- Add normal-user installation/upgrades, config preservation, failure recovery, rollback, diagnostics and removal. Manual launch by default.
- Add standalone `get.sh` to fetch/install a chosen GitHub commit without Git, SSH keys or manual extraction.
- Add an offline aarch64 bundle with pinned private Fedora runtime and manifest, excluding experimental drivers.
- Retain positioning scale/contact roles/click/input fixes; integrate accepted right-menu marker recovery and faster healthy transitions.
- License project code under MIT while retaining dependency licenses.
- Known limits: other models, Desktop Mode, long sessions and suspend/resume remain unverified; intermittent Slay the Spire 2 timeline reconnection remains unlocated in this record.

Historical behavior and original test conclusions: [docs/history.md](docs/history.md).
