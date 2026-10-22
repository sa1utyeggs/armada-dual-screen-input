English · [简体中文](zh-CN/compatibility.md)

<a id="兼容范围与已知问题"></a>

# Compatibility and known issues

| Item | Current scope |
| --- | --- |
| Tested hardware | AYN Thor, 16GB / 512GB, Armada installed on internal storage |
| Tested system | Armada `20261010.c3d178c`, Fedora 44 base, Linux 7.2.6, aarch64 |
| Display mode | Steam Game Mode, using the official `armada-plasma-bottom` session |
| Desktop Mode | Disabled by default; the desktop shortcut can start the background supervisor while it waits for Game Mode |
| Other dual-screen devices | A project goal, but untested; out-of-the-box compatibility is not promised |
| Experimental touch driver | Separate from app installation; tested only on the maintainer's current Thor |

The installer checks for Armada, aarch64, a Fedora 44 base and the Thor device tree. Developers on other Armada dual-screen devices may explicitly use `--allow-untested` after reading the limitations. This grants no root privileges and does not adapt unknown screen sizes or orientations.

The app still assumes Thor screen dimensions, output selection and telemetry sources. For another device, collect display-session geometry and input-route evidence, then add an adapter and device results. Renaming a target does not establish general compatibility.

- The Touchscreen page enables input automatically and offers Position and Direct touch. Position uses one finger to aim and a second to confirm one upper-screen contact. Direct touch sends each finger independently at absolute coordinates. The encoder supports 10 contacts; actual capacity depends on the lower-screen hardware, toolkit and receiving app. Mode or target changes release old contacts, then wait for stable focus and all fingers to lift.
- Some Game Mode touch policies convert native touch to a left mouse button. Native multi-touch reception is not guaranteed in every game.
- Automatic ring recovery after closing Steam's right-side menu has been verified. The user confirmed that removing the extra 1.5-second delay on normal switches made recovery noticeably faster while operation remained correct.
- The early intermittent reconnection issue on the *Slay the Spire 2* timeline cannot be considered fully resolved. A later card-viewer investigation captured focus-query timeouts caused by ring rendering / GPU synchronization. Enabling GL only for the ring passed a short user test; see the positioning record.
- The ring is a passive decoration window attached to the current app, allowing coexistence with Steam FPS / mangoapp. This requires support in the current Thor Gamescope build. After integration, the user confirmed simultaneous FPS and ring display, working touch input and Steam quick-access menu round trips. Real direct multi-touch, long sessions and suspend/resume remain unverified. mangoapp, Steam and the system compositor are not modified.
- Ring rendering supports 30 / 60 / 120 FPS / Follow display, defaulting to the upper display. The first candidate produced GL multi-buffer trails and was rolled back. GDK-managed buffer history fixed the issue and passed real-window pixel checks. Final Steam-library measurements were approximately 30 / 60 / 119.9 draws per second. These do not establish a sustained 120 FPS in games, long sessions or every scene. Game limits, display refresh and touch input frequency remain unchanged; higher caps cost more resources. See [frame-rate evidence and resource costs](position-touch.md#2026-10-21按上屏刷新率调度及帧率设置).
- The stock Thor FT5452 driver has shown stuck physical contacts. A separate candidate module passed one 90-second release/drag test and rollback. Long sessions, simultaneous finger-down and suspend/resume remain unverified. See [Issue #757 progress](https://github.com/armada-os/armada/issues/757#issuecomment-6284200266). Installing this app does not fix the physical driver.
- Steam keyboard integration depends on internal client interfaces. If unavailable, the native keyboard remains enabled; switching pages, collapsing or exiting restores it. Steam updates may require revalidation.
- Chinese text uses system Pango/Noto CJK. Personal configuration and font caches are not bundled.

<a id="圆环视觉平滑2026-10-22"></a>

## Visual ring smoothing (2026-10-22)

Visual following uses a continuous-time filter, without predicting physical positions or generating intermediate touch events. It requests draws only during motion and a short settling period. It was installed on the Thor, the user reported smoother motion, and the code is included in v0.1.3. Eight synthetic-trajectory trials through the actual renderer support more even movement steps, with additional CPU / GPU cost. These figures are neither physical touch-to-display latency nor game frame rate. Separate FPS coexistence, multi-touch, long-session and suspend/resume acceptance were not repeated for this revision. See [implementation](position-touch.md#2026-10-22圆环视觉跟随平滑新分支候选) and [real-window measurements](position-touch.md#真实窗口安装用户反馈与八轮资源对比).

<a id="触屏双模式2026-10-21"></a>

## Two touch modes (2026-10-21)

Ring colors, added 2026-10-22: settings offer independent idle / touching colors with eight swatches. Defaults retain the original blue / orange strokes and black outer border. Validation, save / discard / defaults, passing colors to the renderer in both touch modes, Cairo state colors / transparent center / black border and selected-swatch highlighting passed 546 Python checks on Thor. On Mac, 95 Linux checks were skipped and the remainder passed; 15 JavaScript checks passed.

The color-enabled main commit `9c1501b` was then built as local bundle `c40274f7bcb73251`, verified against source and manifest, and installed. Its application code matches v0.1.3. Temporary white / green preferences passed save, reload, discard and defaults checks. Pixel readback from the app's own real GL ring window confirmed both colors, a transparent center and black outline. Only the app's window was read; no game capture or native input was sent. The settings page was checked offscreen with Thor's actual fonts and rendering environment. The personal-config hash, 60 FPS cap, disabled autostart, physical report settings and original Steam / game / official lower-session processes were preserved. Manual acceptance of individual palette controls, long sessions and suspend/resume remain pending; this does not extend the revision range of the earlier smoothing measurements.

Independent contacts, cleanup, native slot encoding and ring IPC for the added mode passed isolated checks. Dropdown selection, outside dismissal, blocking auto-enable while open, menu-touch isolation and preserving the original input-area height were also checked. Of 367 Python checks on Mac, 66 Linux checks were skipped; all 367 passed on Thor. The 15 JavaScript checks passed on Mac. Node was not installed on Thor, so JavaScript checks were not run there in this round. No automated input was sent to games. Real direct gestures, upper-screen multi-touch recognition and long-term use still require user acceptance.

<a id="多语言键盘原型2026-10-20"></a>

## Multilingual keyboard prototype (2026-10-20)

English US and Simplified Chinese full-pinyin input are implemented. The current Thor's system libxkbcommon, libpinyin and dictionary were verified. Unicode, candidate selection, the separate worker and cancellation on hide passed checks in a dedicated upper-screen GTK window. The user confirmed correct candidates, input in both languages and suitable restored key sizes, then reported a smaller touchpad. Win was replaced with a language key, the permanent strip was removed, the full touchpad restored and candidates moved to a transient overlay. Keyboard enlargement was removed. The user then confirmed language switching, input and sizing.

Game Mode text submission uses an isolated private Gamescope protocol adapter; it is not a general Wayland API. Chinese input in Desktop Mode is not enabled. Steam, Chrome, native-game and Proton text fields must be validated separately. See [multilingual keyboard](multilingual-keyboard.md).

<a id="设置页实机验收2026-10-20"></a>

## Device acceptance of settings (2026-10-20)

Application commit `5e127ed` from PR #4 was installed through an offline per-user upgrade in the Thor / Armada / Game Mode environment above. All 72 files matched the manifest, dependencies were available, configuration bytes matched before and after installation, autostart remained disabled and the previous version was retained for rollback.

- The user confirmed that mouse, position-touch and keyboard options could be adjusted and saved, and the UI displayed correctly.
- After reopening, configuration bytes remained identical. The user confirmed retained values and working pointer movement, position touch and English input. Their adjusted values were kept at their request.
- The panel ran without unexpected automatic restarts. Steam, Gamescope and official lower-session processes remained unchanged.

This was short interactive acceptance on one Thor. Other hardware, Desktop Mode, long sessions and suspend/resume were not verified. Isolated checks cover defaults, discard and save-failure protection; users were not asked to repeat each of those cases.

Full historical evidence is in the repository's [position-touch record](https://github.com/sa1utyeggs/armada-dual-screen-input/blob/main/docs/position-touch.md), [driver investigation](https://github.com/sa1utyeggs/armada-dual-screen-input/blob/main/docs/thor-ft5452-contact-lifecycle.md) and [history](https://github.com/sa1utyeggs/armada-dual-screen-input/blob/main/docs/history.md). Short user acceptance is not evidence of long-term stability.

## Unreleased native marker candidate

The optional XCB/EGL backend is currently a tested source candidate, with GTK fallback only before activation. It reduces active service CPU in owned-window comparisons while adding about 16–21 MiB PSS; idle remains unresolved. Separate external counters help distinguish service GPU costs from Xwayland/Gamescope work. The installed release and earlier user acceptance are unchanged; physical game/FPS interaction, long sessions and suspend/resume need new acceptance for this backend. See [measurements and limits](position-touch.md#2026-10-22-native-marker-submission).
