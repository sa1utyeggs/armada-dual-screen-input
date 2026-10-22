English · [简体中文](zh-CN/history.md)

<a id="历史实现与实测记录"></a>

# Historical implementation and device tests

These are records from before the repository refactor. For current installation and support, use the README and installation guide.

<a id="armada-dual-screen-input虚拟键鼠"></a>

# Armada Dual Screen Input (virtual keyboard and mouse)

A secondary-screen input tool for ArmadaOS dual-screen devices, providing a keyboard, touchpad, device monitoring and positioning touch without mirroring.
The project aims to adapt screen sizes, orientation and input devices across models.

**AYN Thor** is the device tested so far, mainly in **Steam Game Mode**.
Other dual-screen ArmadaOS devices remain untested: device discovery, screen parameters, touch mapping and monitoring require per-model validation.
Desktop Mode remains experimental and disabled by default.

<a id="源码与版本管理"></a>

## Source and version control

This is an independently Git-managed project named `armada-dual-screen-input`. The main repository is
[`sa1utyeggs/armada-dual-screen-input`](https://github.com/sa1utyeggs/armada-dual-screen-input), default branch `main`, remote `origin`.
Its earlier name was `thor-virtual-input`. The local directory initially remained `thor-panel-prototype` for existing workflows.
Existing `thor-panel` installation/configuration paths and user-service names are retained for compatible migration; renaming does not change device configuration.

`vendor/ratatoskr/` is a pinned third-party snapshot. See [`UPSTREAM`](../vendor/ratatoskr/UPSTREAM) for origin, commit and local changes; licenses and credits remain alongside it.
The personal GitHub repository and Ratatoskr provenance are recorded separately; Ratatoskr was not added as a Git remote.

Source, tests, icons and desktop/user-service templates are tracked. `.gitignore` excludes Python caches, device runtime libraries, personal configuration, logs and backups.
The historical Mac command was `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v`; Linux GTK checks skip there, so complete validation requires the Thor.
The separate Steam guard checks used `node --test test_steam_keyboard_guard.js` with fake Steam objects, without connecting to a real client.

On 2026-10-20, mirroring touch and the standalone mirror preview were removed at the user's request, leaving Touchpad, Keyboard & mouse and Positioning touch.
No capture, image-copy or mirror-refresh task runs; existing two-finger scrolling and sensitivity remain. Legacy `mirror` falls back to `split` without rewriting other settings while reading configuration.
All 250 Thor regression checks passed after removal, including three-page Chinese label/bounds checks. See [the removal record](../docs/position-touch.md#移除同屏触摸).

<a id="定位触摸"></a>

## Positioning touch

Positioning touch was merged into `main`, retaining trackpad recovery fixes. Native input, target checks and geometry were separated from the removed mirror implementation.
The page was added on 2026-10-20 as the third page: one finger moves an upper-screen ring relatively, without app hover or touch; holding that finger and pressing a second anywhere in the input area creates one native contact at the ring.
Move the first finger while holding the second to drag. Lifting either releases the contact; roles never swap.
No PipeWire/GStreamer capture runs. An independent input-transparent overlay displays the ring without moving the system pointer.
Dedicated-window checks passed and the user confirmed basic positioning/dragging. After single-finger jumps on the Thor, an application guard passed 333 checks and the user confirmed no more jumps and normal dragging. Missed physical contacts and occasional stale presses remained separate: read-only diagnostics still found a pressed physical lower-screen contact after all fingers lifted. Long game sessions and performance-overlay coexistence were pending at this stage.
See [positioning touch](../docs/position-touch.md) for operations, implementation and boundaries.
[ArmadaOS Issue #757](https://github.com/armada-os/armada/issues/757) records missed physical events, evidence and a lower-screen-only candidate. The whole-kernel build was stopped before compilation/device validation completed; merging this project does not install or enable it.
A separate optional [Thor module experiment](../extras/thor-touch-driver/README.md) later passed one 90-second physical-touch trial and automatic rollback. Long sessions and suspend/resume remain unverified; the default app entry point never installs or enables it.

<a id="ayn-thor-实测环境与当前状态"></a>

## AYN Thor environment and state

AYN Thor 16GB / 512GB, Armada OS `20261010.c3d178c`.

Installed as an independent per-user Linux application on 2026-10-15, normally displayed only on the Game Mode lower screen. The user confirmed keyboard, touchpad, upper touch and controller operation. Boot/login autostart was subsequently removed in favor of the desktop shortcut; Desktop Mode display remained disabled.

<a id="使用"></a>

## Usage

Since 2026-10-19, the panel uses a Steam-style dark keyboard: solid dark-gray keycaps, blue pressed/modifier feedback, vector editing icons and consistent touchpad/status/collapsed controls. `steam_style.py` and `steam_keys.py` draw these without copied Valve artwork. Key arrangement and keyboard bounds in split mode stayed unchanged.

- Default split mode: touchpad above the keyboard, with one status row at the top.
- Three top modes: Touchpad, Keyboard & mouse, Positioning touch. Status is read-only. Legacy `keyboard/settings/mirror` values normalize to `split`; the last mode uses existing persistence, while touch-enabled state is not saved. Keyboard position/size stay unchanged.
- **Close**: the red upper-right button releases virtual keys/buttons and exits; the background does not immediately reopen it.
- **Collapse**: leaves a narrow strip exposing the official lower interface; tap to expand.
- **Release keys**: clears held Ctrl, Alt, Shift, Super and mouse buttons. Tapped modifiers may latch until the next key; use this to reset uncertain state.
- No app-added idle dimming; Armada still controls system brightness and sleep.
- A tap allows small jitter within 350ms. Movement uses maximum displacement from the starting point rather than accumulated jitter. Acceleration uses speed to reduce changes caused by batched touch delivery.
- Scrolling uses `scroll_speed` (1–5) and `scroll_scale` (>0, ≤1, default 1). On 2026-10-19, `scroll_output.py` added scaling before high-resolution/legacy wheel events while retaining fractional remainder because the lowest speed was still fast. The device then used `scroll_speed=1`, `scroll_scale=0.25`, requiring a panel reopen. Pointer/click/system scrolling were unchanged; user retesting was pending at that stage.
- In Game Mode, suppress Steam's keyboard (including Steam+X) only while the expanded split page is visible; restore on touchpad, collapse, hide or exit. `steam_keyboard_guard.py` uses existing local Steam CDP (`127.0.0.1:8080`) and system `websocket-client` in a background thread, without GTK-thread network work or Steam-file/preference/autostart changes. `steam_keyboard_guard.js` leases the interception for 4 seconds: a killed panel, missing UI heartbeat or broken connection expires independently, restoring functions without replaying old requests. Unavailable debugging or mismatched internals leaves the native keyboard available.
- Dedicated whole-text game-input requests are cancelled through Steam's protocol while suppressed. Physical keys cannot replace those APIs' text callback. Use the touchpad page or collapse to permit the dialog. This depends on current Steam internals and needs rechecking after updates. [BetterKeyboard](https://github.com/chenx-dust/BetterKeyboard/blob/01d52c6abd9cff20fa2b981a5b7f91a572eb6d02/src/utility/context.ts) informed display interception; this project does not deploy its input capture.
- Ctrl+P remains a standard shortcut and can open an app's print window; Esc dismisses it. Release keys, red Close and Collapse remain separate controls.

**No autostart by default.** Manual launch waits for the official Game Mode lower session; it neither takes over nor stops that service. Mode changes reclaim old windows/input. A Desktop Mode shortcut launch waits for Game Mode without showing a desktop panel. Click again after closing to reopen.

Device shortcut: `~/Desktop/虚拟键鼠.desktop`; application-menu name: **虚拟键鼠**. It needs no administrator password and does not re-enable autostart.

Manual management, without sudo:

```bash
systemctl --user restart thor-panel.service
systemctl --user stop thor-panel.service
```

The service should be `disabled` for autostart and may also be `active` after manual launch. Optional autostart management:

```bash
systemctl --user disable --now thor-panel.service
systemctl --user enable --now thor-panel.service
```

<a id="安装位置与排查"></a>

## Installation paths and troubleshooting

| Contents | Path |
| --- | --- |
| App, provenance and runtime | `~/.local/share/thor-panel/` |
| Configuration | `~/.config/thor-panel/config.json` |
| Log | `~/.local/state/thor-panel/panel.log` |
| User service | `~/.config/systemd/user/thor-panel.service` |
| App entry | `~/.local/share/applications/thor-panel.desktop` |
| Desktop shortcut | `~/Desktop/虚拟键鼠.desktop` |
| Historical keyboard/mouse icon | `~/.local/share/icons/hicolor/scalable/apps/thor-virtual-input.svg` |

These are persistent user paths, not a transient system overlay. Extra libraries are private to the app; no host loader configuration/global environment changes.

```bash
python3 ~/.local/share/thor-panel/supervisor.py --probe
systemctl --user status thor-panel.service --no-pager
journalctl --user -u thor-panel.service -n 60 --no-pager
```

A Desktop Mode probe returning `session: null` is expected for the current Game-Mode-only behavior.

<a id="已验证与限制"></a>

## Validated behavior and limitations

- Application contact recovery after scrolling was installed on 2026-10-19. The user confirmed single-finger movement before/after scrolling in a short test; this does not fix physical missed events. See [contact recovery](../docs/trackpad-recovery.md).
- System GTK3/Cairo and normal-user `/dev/uinput` permissions work; the GUI uses native GTK.
- Keyboard/mouse uses its own `/dev/uinput`. Positioning touch creates a temporary touchscreen only after page readiness, target stability and all fingers lifted; pause/leaving destroys it. No raw evdev reads or physical touchscreen grabs.
- Game Mode connects to the official underlying KWin, `armada-plasma-bottom`, rather than bottom Gamescope directly. Its unique output is `X11-0`, logical `689×600`.
- Official `armada-bottom-gamescope` and `armada-bottom-screen` remain active while the panel runs.
- An initial Steam web UI hang persisted after stopping the panel and recovered after rebuilding that Steam UI process. A later panel-only `NO_AT_BRIDGE=1` test passed keyboard, touch and controller checks. **The initial cause is unconfirmed; accessibility warnings alone do not establish it.** The setting does not change system accessibility.
- 63 base session/output/touch checks passed locally; an earlier 48 passed on the Thor. Two additional Close lifecycle checks cover stopping the background and avoiding reopening when the session also vanishes. Desktop-file launch showed `active` while autostart stayed `disabled`. Ten historical top controls passed offscreen font/bounds checks, which do not establish long-term graphics compatibility.
- After reducing the header to 7 controls on 2026-10-19, 12 original/actual-size previews had no missing glyphs. 54 Linux layout/key/touch/scroll/guard checks passed on the Thor. Real lower-screen callbacks confirmed read-only status, page switching, collapse/expand/close guard transitions and unchanged saved config. No upper-screen text was sent; this is not game/long-session acceptance.
- For occasional drag stops/jumps, an overly strict focus comparison was relaxed only for verified child controls in the same visible window. Real window/app/size/server/display/touch-policy changes or lost focus still release. 260 Thor checks passed and the user confirmed drag/tap/control changes; a pre-fix diagnostic round also passed, so this is not proof of every stutter's cause. Logs contain state, ages, changed field names and aggregate send counts, never coordinates/text.
- Suspend/resume, long games and dual-screen emulator takeover remain unverified. Desktop code stays experimental and disabled by default.

<a id="实现与来源"></a>

## Implementation and sources

Reuse Ratatoskr's Cairo keyboard, gestures and monitoring with GTK window touch events and a monotonic clock. PangoCairo draws Chinese controls/status/collapsed text, preferring Noto Sans CJK SC with fallback; 16 UI strings and header bounds passed device checks. Cancellation, collapse or exit releases keys/stops inertia. GTK layer shell selects an output without taking keyboard focus.

On 2026-10-19, local vendor `engine.py` changes used maximum tap displacement, a 350ms window, movement only beyond 12 logical pixels, fractional reset on each new touch, and bounded time-based acceleration. `UPSTREAM` records these modifications. Eight hardware-free pointer regressions ran alongside input-isolation/session/Close checks; simulation does not replace physical feel tests.

The user confirmed no idle dimming and working taps but still reported movement stutter. Short aggregate diagnostics showed no sustained render-thread block. GDK source intervals were then used separately for pointer speed/acceleration/inertia to avoid mistaking batched delivery for high-speed motion. Tap duration/contact liveness remain monotonic. Twelve source-time/wrap/duplicate/batch checks passed; physical acceptance was still pending then, so this was not recorded as a complete fix.

The user next reported smoother movement with occasional pauses, then intermittent typing pauses across apps. `tap_key()` was found synchronously waiting 20ms inside GTK touch callbacks; app-owned `KeyboardPulses` timer releases replaced it. Hold-repeat also moved to event-loop timers, keeping 350/60ms. Per-press tokens protect rapid same-key taps from old releases; pending pulses finish before modifier changes, and cancel/Close clears timers. Seventeen device checks without real input passed; typing feel still awaited confirmation at that stage. Mouse engine, system input services and autostart were unchanged.

The private runtime is Fedora's official `gtk-layer-shell-0.10.0-1.fc44.aarch64.rpm`; device `rpmkeys --checksig` returned `digests signatures OK`.

- RPM SHA256: `de2a27df40ae7cffd3b858f46f73744ec2f0b153a2870120f88cd0b40660fb92`
- [Official RPM](https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Everything/aarch64/os/Packages/g/gtk-layer-shell-0.10.0-1.fc44.aarch64.rpm)
- [Fedora source RPM](https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Everything/source/tree/Packages/g/gtk-layer-shell-0.10.0-1.fc44.src.rpm)
- Runtime licenses remain in `runtime/usr/share/licenses/gtk-layer-shell/`.

Other sources:

- [Ratatoskr](https://github.com/venatrix-ritz/Ratatoskr), pinned commit `24471899b5923b73f0ecb7ae67aba54ad7b6d73e`. `vendor/ratatoskr` retains MIT LICENSE/CREDITS. Its installer, Decky backend and service-switch manager are not deployed.
- [Armada Thor device configuration](https://github.com/armada-os/armada/blob/c3d178c/system_files/usr/lib/armada/devices/ayn-thor.conf)
- [Official lower-screen session](https://github.com/armada-os/armada/blob/c3d178c/system_files/usr/libexec/armada/armada-plasma-session)
- [Official lower-screen service](https://github.com/armada-os/armada/blob/c3d178c/system_files/usr/lib/systemd/user/armada-bottom-screen.service)
- [GTK layer shell API](https://wmww.github.io/gtk-layer-shell/)
- [GDK touch events](https://docs.gtk.org/gdk3/struct.EventTouch.html)
