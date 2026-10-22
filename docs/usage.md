English · [简体中文](zh-CN/usage.md)

<a id="使用虚拟键鼠"></a>

# Using Virtual Keyboard & Mouse

Open **Virtual Keyboard & Mouse / 虚拟键鼠** from the desktop/menu and enter Steam Game Mode. Only the official lower-screen session is used; its service is not stopped. Interface-language selection and in-app uninstall are included in v0.1.4.

| Control/mode | Action |
| --- | --- |
| Touchpad | One-finger movement, tap to click, two-finger scrolling |
| Keys+Pad | Touchpad above keyboard; temporarily suppress Steam's native keyboard while this page is visible |
| Touchscreen → Position | Move the first finger to aim the ring; keep it down and hold a second finger to touch; move the first to drag, lift the second to release |
| Touchscreen → Direct touch | Lower-screen positions map directly to the upper screen; each finger presses, moves and releases independently, with an upper ring per contact |
| Center | Position mode only; release old contacts, center the ring, then resume once fingers lift |
| Settings | Adjust pointer, positioning multiplier, input language and repeat; save to apply |
| Release keys | Clear held keys on Keys+Pad / Touchpad; the touch page has no pause/release-contact button |
| Hide | Collapse to a strip; tap to expand |
| Close | Release input and exit, without automatic reopening |

Blue means aiming without a pressed contact; orange means touching, by default. Both colors can be changed independently. Default positioning multiplier is 2.0. Lift all fingers after switching UI; old gestures are not continued.

While the touch page is visible, it automatically waits for the upper target and route, then enables input. The existing header dropdown selects Position / Direct touch and retains the choice. It adds no row: input still starts below the original status ribbon. Opening the menu overlays the page and pauses sent contacts. Selection or outside dismissal waits for all fingers to lift and the target to stabilize before resuming. Opening, selecting and dismissing the menu never sends those touches to the upper app.

Direct touch maps absolute positions in the input area, ignores the positioning multiplier and does not convert two fingers to scrolling. Up to 10 independent contacts can be tracked; real capacity depends on hardware/app support. Each ring uses the selected touching color, orange by default. It does not represent measured pressure or actual contact area. Some Steam/Gamescope policies turn touch into mouse input. Native multi-touch needs support from the app and its touch policy; game touch settings are not silently overwritten.

The panel does not dim itself when idle. Header telemetry is read-only; Armada continues to manage power, brightness and the official lower-screen service.

<a id="输入设置"></a>

## Input settings

Select Settings, then Mouse / Touchscreen / Keyboard / General / Updates. Drag sliders or use minus/plus, then Save settings. No restart or manual file editing is needed. A failed save keeps the draft and original configuration and displays an error.

| Group | Options |
| --- | --- |
| Mouse | Speed 0.2–5.0×, scroll level 1–5, multiplier 0.01–1.0×, tap to click, glide and friction |
| Touchscreen | Position multiplier 0.1–4.0×, default 2.0×; ring cap 30 / 60 / 120 FPS / Follow display; independent idle / touching colors |
| General | System language / Simplified Chinese / English UI; missing preference defaults to English, independent of input; confirmed app removal |
| Keyboard | English US / Chinese pinyin; repeat toggle, delay 150–800 ms, interval 20–200 ms, Shift double-tap interval 150–800 ms |

Choose Settings → General → Interface language and save; no restart is required. Older configurations missing the field also default to English. See [resolution, migration and validation](i18n.md).

Reset this page changes only the selected group and still requires Save. Discard changes restores saved values. Switching to another input mode discards unsaved edits. Entering settings releases held keys and positioning contacts; the page takes no upper-screen keyboard focus and sends no slider touches as mouse movement. Restart returns to the previous input mode, not settings.

Cycle the ring cap with its right-side button, then save. Follow display is the default. Once detected it shows e.g. Follow display (120 Hz); before detection no rate is shown. Fixed caps do not exceed upper refresh. They limit ring rendering in both modes, changing neither game limit, display refresh nor touch-send frequency. Submission waits/load can reduce actual FPS; there is no continuous drawing at rest. Higher caps can use more CPU/GPU; see [measurements](position-touch.md#2026-10-21按上屏刷新率调度及帧率设置). Positioning speed does not affect direct touch.

For Ring color · Idle and Ring color · Touching, choose a swatch and save. Ice blue, orange, green, yellow, red, purple, pink and white are available. The left caption shows name/hex and the selected swatch is highlighted. Idle means aiming without an upper press; touching means a pressed contact and also colors each direct-touch ring. Defaults retain blue/orange, transparent centers and black outlines. New colors apply when re-entering the touch page, without exiting the app. Discard, touch-page defaults and persistence use the existing settings lifecycle. Input, frame caps and game settings are unchanged.

The former Win key, **中/EN**, switches and saves English/Chinese input immediately. Chinese full pinyin uses system libpinyin in Game Mode. Candidates appear transiently above the keyboard and disappear after selection/cancel, leaving the full touchpad when idle. Tap a candidate or Space; 1–6 selects from the current page; Enter commits raw pinyin; Cancel/Esc clears composition. System libraries and receiving-app text support are required. English retains its key channel, and Chinese does not change a global input method. See [interfaces, limits and evidence](multilingual-keyboard.md).

Preferences are in `~/.config/thor-panel/config.json` (respecting `XDG_CONFIG_HOME`). Existing/unknown fields remain; the installer does not overwrite preferences. For fast scrolling, try level 1 and 0.25×. Positioning speed changes neither finger roles nor experimental-driver state. Settings adjustment, save, reopen and keyboard/mouse/position-touch operation passed Thor Game Mode user acceptance on 2026-10-20. See [scope](compatibility.md).

Use Release keys if a held Ctrl/Shift causes unintended combinations. Collapse the panel or switch to Touchpad when Steam's own full-text input dialog is needed.

Visual smoothing continuously moves only the ring toward the latest true position within its existing cap. Actual clicks/touches stay immediate. Click, lift or mode switch aligns the ring with the real position; drawing stops at rest. Smoothing adds slight visual lag and potentially more moving draws, not higher-frequency game input. See [algorithm, replay and acceptance limits](position-touch.md#2026-10-22圆环视觉跟随平滑新分支候选). Smoothing itself adds no preference and changes no lower driver.

<a id="检查与安装更新"></a>

## Check and install updates

Select Settings → General → Updates → Check for updates to view current/latest stable versions. Checks are manual and run in the background: no startup network request/download or switch to prereleases. An exhausted anonymous GitHub quota shows a rate-limit message; wait and manually retry rather than reinstalling.

When a version is available, select Update to v…, then Confirm update and restart. First save/discard any input edits. Downloads verify official asset SHA-256, `SHA256SUMS` and the internal manifest before the existing installer upgrades. Personal settings, autostart and the previous-version rollback entry are retained.

The updater runs independently. Installation briefly closes the panel; a panel running through its user service reopens automatically. Return to the page to inspect results. Network, checksum, dependency or install failures show an error and allow a new check/retry. The task survives a panel crash under the user manager; interruption of the task itself prompts a fresh check. Interrupted updates are not automatically restarted.

Only installer-managed per-user app files are updated. No sudo, Armada/Steam update or experimental driver is involved. Source runs can check versions but cannot install through this button. [Manual upgrade/rollback](installation.md) remains available.

[Installation and commands](installation.md) · [Compatibility and known issues](compatibility.md)

The app provides Settings → General → Uninstall app. Review the scope, then confirm on the right. It keeps personal settings/logs and blocks removal during updates or unsaved edits. See [scope, result records and terminal fallback](installation.md#卸载).

<a id="battery-power"></a>

## Battery power in the status row

The existing one-line status row shows battery charge and signed net watts, e.g. `Bat. 96% −5.0W`. Negative is discharge, positive is charging, and `0.0W` is near-zero battery flow. A missing or invalid voltage/current reports `—W`, not zero. These are cached samples at the existing sampler cadence, rounded to 0.1 W; painting performs no sensor reads and no extra polling is added.

Watts are computed from `/sys/class/power_supply/battery/voltage_now` × `current_now` / 10¹² (µV × µA). On the tested Thor / Linux 7.2.6, `power_now` disagreed substantially with this pair, so it is not used. This is a battery-side estimate: unplugged it approximates battery draw including device losses; plugged in or with charging held, it cannot measure total system/charger/SoC power. Zero battery flow does not mean the device uses no power. Sensors are not calibrated by this application.

Settings → Experimental contains the separately installed Thor lower-screen driver fix; see [setup, confirmation and restore](../extras/thor-touch-driver/README.md#settings-controls).
