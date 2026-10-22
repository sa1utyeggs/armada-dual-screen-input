English · [简体中文](zh-CN/native-touch-routing.md)

<a id="原生触摸路由验证"></a>

# Native touch-route validation

Historical validation: 2026-10-19; integration update: 2026-10-20. Scope: AYN Thor, ArmadaOS `20261010.c3d178c`, Steam Game Mode.

<a id="结论"></a>

## Conclusion

**A temporary virtual touchscreen was verified to deliver real touch events to a dedicated upper-screen test window; the lower screen received none.** It was later integrated with a separate mirroring UI. The user confirmed Steam single-finger swipes/taps and *Slay the Spire 2* card selection/dragging/menus. At the user's request, native mode emulated no two-finger scrolling and imposed no two-finger classification delay, forwarding up to two independent contacts.

Those are historical results of the first route test. Mirroring was removed at the user's request on 2026-10-20; the native route remains for [position touch](position-touch.md). Steam settings, physical touchscreens, udev rules, the official lower service and autostart rules were unchanged.

<a id="为什么可以这样路由"></a>

## Why the route works

Upper Gamescope reads input through libinput, with `--ignore-touch-device bottom_touchscreen`, `--force-orientation right` and `--default-touch-mode 4`. The route test and Steam UI had `STEAM_TOUCH_CLICK_MODE=4`, touch passthrough. *Slay the Spire 2* showed 1, mapping touch to left mouse. That existing policy is retained rather than overwritten. Apps may therefore receive native touch or Gamescope-converted mouse events, as with the physical upper touchscreen.

Armada's DRM-lease patch forwards touch matching the physical lower-screen name through the lease socket. Lower Gamescope does not open `/dev/input/event*` directly. A new touchscreen with a different name can enter the upper route. This follows this source revision, descriptor inspection and real input checks, not an assumption about other hardware or updated routes.

<a id="隔离检查与实测"></a>

## Isolated checks and device test

Dependency: system `libevdev-1.13.7-1.fc44.aarch64` via ctypes; no Python evdev installation. Gamescope: `terra-gamescope-3.16.31^1-1.100601.fc44.armada.aarch64`.

1. libevdev created temporary Type B multi-touch device `Armada native touch probe <pid>`, declaring `INPUT_PROP_DIRECT`, two slots, tracking IDs, absolute coordinates and `BTN_TOUCH`, but no left mouse button.
2. No contacts were sent initially. udev classified it as `ID_INPUT_TOUCHSCREEN=1`; descriptors showed only upper Gamescope opened it. Closing removed the device node.
3. The app opened its own full-screen upper test window and a lower observer that only counted, never forwarded input. Each send checked that its own upper window remained focused, policy remained passthrough, and only the same Gamescope held the device.
4. A single-finger sequence and a two-finger contact sequence gave:

| Check | Observed |
| --- | --- |
| Upper native source | GDK `touchscreen` |
| Down / move / up | 3 / 4 / 3 |
| Simultaneous contacts | 2 |
| Coordinates | Matched within 3 window pixels |
| Lower down / move / up / cancel | 0 / 0 / 0 / 0 |
| Virtual device after exit | Removed |

Coordinates acted only on the app's own windows. No contacts were sent to Steam or games. XWayland/GTK may additionally produce pointer-compatibility events. Native-touch evidence comes from received TOUCH sequences, not pointer movement alone.

<a id="坐标的重要区别"></a>

### Important coordinate distinction

The first send inverted physical `right` rotation. Routing worked but coordinates did not match. The received coordinates were unrotated, showing the virtual device did not inherit the physical output association/rotation. Using `normal` with upper logical normalized coordinates passed.

Example: logical `(0.25, 0.30)` and `(0.75, 0.70)` arrived at `(480, 323)` and `(1439, 755)` in a 1920×1080 test window. Thor's physical orientation must not be copied directly to the virtual device.

<a id="开发检查入口"></a>

## Developer check entry points

`native_touch.py`: I/O-free contact encoding and the libevdev temporary device shared by probe/position touch. `native_touch_probe.py`: bounded two-window route check. `test_native_touch.py`: encoding, two-finger slots, release, route-failure and write-failure cleanup. `native_input.py`: positioning sender/backend route inspection. `gamescope_target.py` / `touch_intent.py`: separate target identity and input intent, independent of capture sources.

All 9 native-touch unit tests passed on Mac and Thor; Thor had 85 passes including earlier mirroring checks. GUI routing was tested separately and is not established by unit tests. After direct-touch integration, 104 related mirror/native checks passed on each platform. An early backend test also closed while holding a contact, correctly releasing it/removing the device. After a real game test of the final direct-touch revision, capture stopped, processes exited and no virtual touchscreen remained.

In an explicitly confirmed development session with Steam home and no game:

```bash
PYTHONPATH=src python3 -B tools/native_touch_probe.py --x-display :0 --rotation normal \
  --gtk-runtime-root "$HOME/.local/share/thor-panel/runtime" \
  --report /tmp/native-touch-route.json
```

The test briefly displays its own windows and closes them automatically. Do not touch the device during it, to avoid contaminating observer counts. Report coordinates are generated contacts in the dedicated window. No text, game imagery, IP or credentials are recorded. No sudo, physical evdev reads or exclusive touchscreen grab is needed.

<a id="当前接入与待验证"></a>

## Integration status and pending validation

- At this integration stage, the daily entry was Position touch: first finger aims relatively, second confirms, at most one held upper native contact; no image transmission.
- A temporary screen is created after a stable target/all-fingers-up. Pause, page exit, collapse or close releases/destroys it. The existing manual launch is retained, with no new autostart.
- The mirror page, separate preview, mirror-specific mouse backend and capture-runtime settings were removed. Old results remain route provenance, not currently supported features.
- **Abnormal cleanup currently appears as up, not a true touch cancel**, potentially committing an already started app action. Other games, suspend and long coexistence need validation.
- Missing lower down/up remains a separate issue: [ArmadaOS #757](https://github.com/armada-os/armada/issues/757).

<a id="2026-10-21消除发送路径中的重复校验"></a>

## 2026-10-21: remove duplicate sender validation

After [drawing optimization](keyboard-latency.md#第五轮组件裁剪触屏静态层和遗漏的按键结束刷新), only the `native_input.py` validation chain changed. Contact frames, input frequency, route-scan period, expiry, sensitivity and preferences remained unchanged.

The old send entered `poll()`, `ready` and `VirtualTouchProbe.contact()`; `poll()` called `ready` again. Target/focus/route were each checked 4 times before a write. The final full check inside `contact()` is now retained directly; standalone `poll()` checks each once. Every new event revalidates, never reuses permission from a previous event. Cancel may release contacts after target expiry; failure of the last check releases held contacts and clears backend state.

A real Type B encoder with only kernel output replaced created no device. Moving each of five fingers once reduced each check from 20 to 5 calls. Encoded events were identical, with 5 separate `SYN_REPORT`s. This is 75% fewer duplicate checks, not proof of 75% less CPU. Tests cover target/focus/route loss between sends, cancel, close and release.

Same-device A/B baseline `a845f7d` already had drawing optimization. Only `native_input.py` differed between bundles. Steam home was idle; each mode warmed for 4 seconds and sampled for 10, over two reversed-order rounds. A separate process generated input only for a dedicated upper receiver. Real route checks, encoder and virtual device remained active. Driver/sampler CPU was separate from app-tree CPU. Each scene retained about 18 seconds of non-overlapping valid CPU/GPU samples.

| Scene | Mean app CPU, one-core %, before / after | Mean CPU reduction | Contact handling p95, ms, before / after | Display GPU full-frequency equivalent %, before / after |
| --- | --- | --- | --- | --- |
| Direct touch idle | 18.44 / 16.39 | 11.1% | No input | 0.096 / 0.096 |
| Position drag | 33.67 / 23.66 | 29.7% | 4.95 / 1.90 | 0.337 / 0.337 |
| Direct touch: two fingers | 58.41 / 51.25 | 12.3% | 1.52 / 0.76 | 5.209 / 5.196 |
| Direct touch: five fingers | 60.89 / 58.55 | 3.8% | 1.21 / 0.55 | 5.460 / 5.432 |

Position drag and two-finger CPU fell in both rounds. Five-finger gains were limited, only about 0.5 one-core percentage point in round one. The first idle round was almost unchanged; its 11.1% mean is not a stable guaranteed reduction. Event rates were position 54.47 / 54.12, two fingers 110.21 / 109.07 and five fingers 277.06 / 276.93 per second, maximum deviation about 1.1%. Frequency was not reduced to get these results. GPU was essentially unchanged. The main gain was in the CPU send path; remaining work cannot be attributed to one function from this test alone.

CPU 100% means one logical core. GPU covers the display scene including both-screen composition, normalized to 680 MHz; the app has no independent DRM client. Contact handling p95 is a synthetic-event callback, not physical touch-to-image latency. App-tree PSS changed about 107–113 MiB to 110–117 MiB without a new cache; short samples cannot establish long-term memory differences. No game-FPS, battery, suspend or physical multi-touch acceptance was performed.

All 443 Python checks passed on Thor. On Mac, 86 of 443 Linux checks were skipped and the remainder passed, plus 15 JavaScript checks. Node was absent on Thor. After tests, temporary processes/screens were gone, original Steam/Gamescope/lower-session processes remained, installed v0.1.2 files verified unchanged, and configuration/autostart/CPU-GPU policy matched the baseline. The actual install stayed `8f4e8d5`; these figures came from temporary bundles.

<a id="2026-10-21降低单次目标身份校验成本"></a>

## 2026-10-21: reduce per-call target identity cost

Baseline `1658774` had the previous deduplication. Only repeated work inside `GamescopeTarget.resolve()` was simplified: each invocation resolves/checks the runtime directory once; both endpoint aliases still resolve within it; after both paths resolve, socket type, owner and device/inode are reread to form identity. Every `is_current()` call still performs all checks, with no cross-event authorization cache. Encoding, commits, periods, expiry, drawing and preferences remain unchanged.

Read-only timing used real Thor runtime paths/aliases, without connecting graphical sockets or opening input devices. Three profiler-independent rounds of 2,000 calls reduced mean validation CPU time from 75.09 to 51.84 microseconds, about 31%. Separate operation counting found `stat` 8 → 3, `lstat` 18 → 12 and `readlink` still 1. Counts depend on this Python/alias setup, not every environment. Profiling ran separately and its overhead was not included in timing.

New temporary Unix-socket tests cover direct/directory aliases, retargeting each call, endpoint replacement/disappearance/regular files, escaping aliases, redirected/file runtime directories, owner changes and read failures for directory/both endpoints. In particular, replacing the primary endpoint while resolving the other path must use freshly read identity, never authorize the old endpoint.

A dedicated real-window test followed. Only `gamescope_probe.py` and `gamescope_target.py` differed between sealed bundles. Each scene warmed 4 seconds, sampled 10, over two reversed-order rounds, retaining about 18 seconds of CPU/GPU data. Separate input/sampling processes were excluded from app CPU; real routing/encoding remained enabled.

| Scene | Mean app CPU, one-core %, before / after | Mean CPU reduction | Contact handling p95, ms, before / after | Display GPU full-frequency equivalent %, before / after |
| --- | --- | --- | --- | --- |
| Direct touch idle | 15.72 / 14.05 | 10.6% | No input | 0.116 / 0.096 |
| Position drag | 24.55 / 23.10 | 5.9% | 1.67 / 1.29 | 0.335 / 0.357 |
| Direct touch: two fingers | 52.59 / 50.58 | 3.8% | 0.67 / 0.55 | 5.181 / 5.199 |
| Direct touch: five fingers | 60.58 / 58.01 | 4.2% | 0.53 / 0.47 | 5.460 / 5.418 |

Two/five-finger CPU fell in both rounds, but total gains were limited and cannot inherit the local 31% reduction. Position round one and idle round two were almost unchanged; their means are not stable guarantees. Event rates were about 54.12 / 53.72, 109.50 / 109.46 and 273.87 / 271.99 per second, maximum deviation below 0.8%, with no frequency change. GPU showed no consistent reduction. Five-finger candidate CPU remained about 58% of one core; the rest needs separate investigation.

CPU 100% again means one logical core; GPU includes both-screen composition normalized to 680 MHz. Callback p95 is not physical touch-to-image latency. No game/battery/suspend/physical-touch acceptance was done. App-tree PSS was about 110–117 MiB and 111–114 MiB, with no new cache. Short differences are not long-term memory conclusions.

Thor passed 453 Python checks. Mac skipped 86 of 453 Linux checks and passed the remainder plus 15 JavaScript checks. Node was absent on Thor. Although the user had closed the panel, its service was still running during preparation; this app's service was normally stopped to isolate tests and left stopped afterward, with autostart disabled. Installed v0.1.2 bundle/manifest, personal configuration and CPU/GPU policy stayed unchanged; original Steam/Gamescope/lower-session processes remained and temporary processes/screens exited. The install remained `8f4e8d5`.

<a id="2026-10-21触点圆环仅在上屏显示未发布"></a>

## 2026-10-21: contact rings on the upper screen only (unreleased at the time)

At the user's request, lower direct-touch rings and contact-position/pressed-triggered lower redraws were removed. The area retains static instructions; state/mode/menu changes still refresh. Upper rings, gesture state machine, route/focus checks, contact sends and periodic health checks remain unchanged. Lower repaint decisions no longer inspect the ring list; its lower-ring damage helper was removed.

Thor offscreen checks found identical lower pixels with no contacts versus multi-finger down/move/independent up/all up, at normal/double device scale. Periodic health checks still ran. Contact changes requested no lower full/partial repaint, while status changes still did. Thor passed 453 Python checks; Mac skipped 87 of 453 Linux checks and passed the rest plus 15 JavaScript checks. No window/input device or new CPU/GPU measurement was used. Earlier tables describe revisions still drawing lower rings and cannot be treated as measurements of this change. The actual install was not replaced.

<a id="参考"></a>

## References

- [Linux uinput](https://docs.kernel.org/input/uinput.html)
- [Linux multi-touch Type B](https://docs.kernel.org/input/multi-touch-protocol.html)
- [libevdev uinput](https://www.freedesktop.org/software/libevdev/doc/latest/group__uinput.html)
- [Armada DRM-lease touch forwarding](https://github.com/armada-os/armada/blob/c3d178c/packages/gamescope/patches/0013-feat-drm-run-a-compositor-from-the-leased-output.patch)
- [Armada ignored lower-touch isolation](https://github.com/armada-os/armada/blob/c3d178c/packages/gamescope/patches/0014-wlserver-always-swallow-ignored-touch-device.patch)
- [Current position touch](position-touch.md)
