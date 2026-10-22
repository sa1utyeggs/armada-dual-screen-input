English · [简体中文](zh-CN/position-touch.md)

<a id="触屏定位与直接多指"></a>

# Touchscreen: positioning and direct multi-touch

Version `0.1.0-preview.2` (2026-10-21) added Direct touch to the existing Positioning feature, selected through a top dropdown. The corresponding Git tag identifies the actual released commit. Isolated checks, existing positioning acceptance and pending multi-touch acceptance are recorded separately.
Last updated: 2026-10-21, with subsequent dated records below. Device: AYN Thor / Armada `20261010.c3d178c` / Steam Game Mode.

<a id="目的与操作"></a>

## Purpose and operation

Look at the upper screen while operating the lower one, avoiding mirror transport and repeated changes of gaze.
No capture source, GStreamer pipeline or image copying runs; the feature maintains positions, passive markers and native contacts.
Other devices and Desktop Mode are unverified.

Choose the third top page, Touchscreen, then select Positioning or Direct touch in the same toolbar's dropdown. Its arrowed box adds no second row: the input area still runs from logical y=124 to the lower edge. There is no pause/enable/release-contact button; a visible, ready page enables automatically. Opening the menu releases old contacts and blocks reconnection. Selecting or dismissing it waits for all fingers up and a stable target before resuming. The menu uses existing panel drawing, not a focus-taking popup. Header/status controls and menu gestures never send upper-screen touch.
Enable waits for the upper marker, a foreground target stable for 200ms and all physical fingers lifted for at least 80ms.

Retained Positioning behavior:

| Action | Effect |
| --- | --- |
| First finger down | No marker jump, touch or mouse hover |
| Move first finger | Relative positioning from the ring's current location, without inertia or two-finger decision delay |
| Lift and replace first finger | Continue from the current location, not the starting point |
| Hold first finger, press a second anywhere in the input area | Press one native contact at the marker |
| Hold second finger, move first | Move that same contact for dragging or a one-finger swipe |
| Lift second finger | Release contact; first finger can continue positioning only |
| Lift first finger first | Release contact; remaining fingers never inherit positioning. A new finger can position again; touching still needs a new second-finger begin |
| Third finger | No positioning/touch role or role reassignment |
| Center positioning | Release/reset the gesture, then center; resume after lift/readiness |

Two lower fingers control **one** upper contact, not an upper two-finger gesture. The second finger's location/movement does not change positioning.
The marker is a transparent-center ring: blue while positioning, orange while pressed in the original defaults.
Changing pages, collapsing, hiding, exiting, invalid routing or changing foreground targets releases contacts first.
Re-entering/expanding waits for readiness and lift; old contacts never resume.

<a id="直接触屏子模式2026-10-21"></a>

### Direct touch submode (2026-10-21)

The lower input area maps absolute coordinates to the complete upper image. One finger immediately sends one contact; each additional finger has an independent contact ID and can move/lift separately. Each held upper contact gets an orange transparent ring. An adjustment unreleased at the time on 2026-10-21 removed the corresponding lower rings: instructions/status remain, but contact motion/press/release alone no longer redraws the lower UI. All upper rings clear when fingers lift. Rings indicate position, not sensor-measured finger size or pressure.

The encoder/virtual device supports up to 10 slots; actual simultaneous fingers depend on hardware, GTK reports and receiving apps. No mouse hover/buttons, two-finger wheel or capture is simulated. Gamescope touch mode 1 may translate touch to mouse; mode 4 and the receiver must support native multi-touch. The app does not rewrite Steam touch policy.

Both submodes wait for target stability, marker heartbeat, exclusive routing and all fingers lifted. Switching releases old contacts, clears gestures and waits again so the selector's finger cannot reach the upper screen. Positioning location/scale persist; Direct touch does not use relative scale. `touch_mode` stores the submode; old configs default to Positioning while preserving other values. Adding a mode does not fix known missing physical events.

<a id="移动倍率"></a>

### Movement scale

On 2026-10-20, horizontal/vertical positioning scale changed from 1.0 to 2.0 at the user's request.
Moving 10% of the lower area width/height moves the upper marker 20% of screen width/height, clamped at edges.
Positioning and second-finger-held dragging share that scale. Touchpad, split mode, wheel and abnormal-jump protection remain unchanged.

<a id="实现与隔离"></a>

## Implementation and isolation

| Module | Responsibility |
| --- | --- |
| `position_gesture.py` | I/O-free gesture state machine; fixed first/second roles, at most one contact |
| `position_motion.py` | Isolate abnormal coordinate steps using toolkit sample intervals, without replay or physical-input reads |
| `panel_position.py` | Focus, heartbeat, routing readiness, pause and cleanup, independent of capture |
| `marker_overlay.py` | Marker child process, nonblocking local IPC, latest positioning state only |
| `marker_worker.py` | Separate X11 marker process; native EGL candidate with setup-only GTK fallback, empty input region and passive own-window decoration properties |
| `marker_target.py` | App/window/display/geometry binding; decoration properties written only to its own window |
| `native_input.py` | Native touch, device identity and exclusive upper routing |
| `gamescope_target.py` / `touch_intent.py` / `input_geometry.py` | Target identity, intent and area geometry independent of mirror code |
| `position_input_smoke.py` | Bounded input only to its own upper-screen test window |

The lower GUI uses the official lower KWin Wayland socket. Read-only `:0` discovery identifies the foreground, then creates the marker in the target XWayland belonging to the same upper Gamescope.
GDK backends run in separate processes. Transparency, empty input region, no-focus behavior and passive decorations are configured before mapping; the current marker no longer occupies `GAMESCOPE_EXTERNAL_OVERLAY`. Its origin/canvas follow the app window, while input permission still checks the full physical upper image and matching aspect ratio.
Properties must be acknowledged before display. Only its own window is written; root focus settings, other overlays, cursor and Steam touch policy remain unchanged.
An inherited local socketpair carries state, without network ports or recorded coordinates, images or typed text.
Changed old/new ring bounds form surface damage; stationary rings do not paint continuously. The native EGL candidate clears complete backbuffers before submitting those damage hints, while GTK fallback maintains its own buffer history. Expired heartbeat stops touch.

<a id="steam-右侧菜单关闭后的圆环恢复旧外部叠加层实现的历史"></a>

### Recovery after closing Steam's right menu (historical external-overlay implementation)

On 2026-10-20, the user reported a disappearing ring after opening/closing the right menu; switching modes restored it. The marker process and external-overlay property remained, while mangoapp in the same XWayland used the same overlay category and stacked above it.
[Gamescope's overlay selection](https://github.com/ValveSoftware/gamescope/blob/master/src/steamcompmgr.cpp) chooses one legacy external window by opacity/stacking. That matches the symptom, but current upstream source was not treated as the exact verified local build.

On stable foreground recovery, all fingers up and routing re-establishment, bounded IPC requested one marker restoration.
The child raised only its own input-transparent window and redrew local ring bounds, without `present()`, focus requests or continuous stacking competition.
No mangoapp, Steam, game, cursor or driver changes; old menu-time contacts released and did not resume.
254 Mac checks passed with 36 Linux GTK skips; 20 related device checks passed.
The user confirmed automatic recovery and normal positioning after a right-menu round trip without changing modes. This accepts that behavior briefly, not long sessions or suspend/resume.

Recovery was then reported slow. Ordinary foreground transitions shared a 1.5-second fault retry cooldown, on top of target stability and route confirmation.
Healthy-marker transitions now release old contacts and immediately wait for stability without extra cooldown. Marker/IPC/routing failures retain it.
The 200ms target stability, 80ms all-up period, exclusive/fresh routing and no resumed contacts remain.
35 related checks passed on both Mac and device, covering skipped healthy cooldown, unstable targets, old-contact release and retained fault cooldown.
The user reported noticeably faster recovery with normal operation. These limits/fake-clock tests are not end-to-end latency measurements.

Later, intermittent connection/recovery notices occurred in the Slay the Spire 2 timeline without ring jumps.
A separate read-only focus sample captured 1,240 samples in about 25 seconds with one foreground state and no query errors; it cannot replace internal checks or establish the original fault state.
A temporary device build capped diagnostics at 60 recovery records, containing reason, focus/marker/route ages and contact counts, without coordinates/text or control changes.
A subsequent roughly 20-second user test did not reproduce it. Cause remained unconfirmed; the bounded diagnostic build was retained for another occurrence, not marked fixed.

Current Gamescope/Steam touch modes 1 or 4 remain; mode 1 may turn touch into left mouse, so native multi-touch cannot be claimed for every app.
Initial support is a complete window with matching upper aspect ratio. Crops, mismatched ratios, scale/rotation combinations and other models need checks.
Each real send still validates target, focus, heartbeat and route. Positioning alone sends no app input and does not repeat send checks on every motion.
Background routing scans all process owners every 250ms, expiring at 750ms. `scandir` replaced Path traversal without reducing scope, frequency or identity checks.

<a id="2026-10-21查看牌界面的圆环卡顿与重新识别"></a>

## 2026-10-21: card-viewer ring stutter and re-identification

The user reported ring/drag pauses in Slay the Spire 2's card viewer while game rendering was mostly normal, with occasional re-identification. Bounded manual records captured protective release when focus age exceeded 200ms despite unchanged target identity, valid route and fresh heartbeat. GTK was not persistently blocked, and an input callback usually took under 2ms. This identifies a direct trigger for some reconnections, not every stutter's cause.

Root focus/display-route/touch-policy requests were queued together before reading replies, as were game geometry/input-focus requests. Each round rereads them without caching permission; invalid properties/X errors still refuse input and early failure discards outstanding replies. Common queries shortened, but manual retesting still stuttered/timed out; batching alone was not the fix.

The user noted one automatic rendering comparison was not in the card viewer. That round was excluded. Comparisons below followed explicit confirmation of that scene and no user operation; only the app's passive ring moved, without input devices or game input.

With 6 seconds stationary, 18 moving and 6 stationary, independent focus-query P95 was about 1.01 / 33.00 / 0.80ms. During an approximately 101ms query, four read-only `:0` XWayland main-thread samples showed `dma_fence_default_wait`; `:1` game-server queries were not the main wait. Evidence narrowed the path to X11 marker drawing/GPU synchronization, without proving a driver-version cause.

Drawing into a small Cairo bitmap first still produced about 344ms waits and was rejected. The adopted candidate sets `GDK_GL=always` **only** for the X11 child started by `MarkerOverlay`, using GTK GL composition. Parent, lower UI, game, system and Steam environments stay unchanged. Empty input region, no focus, overlay properties, appearance and local redraw remain.

In the confirmed card viewer, run original → GL → GL → original, each with about 0.8 seconds warmup and 8 seconds sampling:

| Path | Focus-query P95, ms | Maximum query, ms |
| --- | --- | --- |
| Original, first | 32.95 | 34.22 |
| GL, first | 0.90 | 1.88 |
| GL, second | 0.93 | 1.89 |
| Original, second | 33.18 | 33.45 |

These are independent read-only query times, not physical touch-to-display latency, CPU/GPU utilization or game FPS. No GL timeout occurred briefly; that does not establish permanent freedom from stutter. Focus 200ms, heartbeat 1.2 seconds, route 750ms and route-check 250ms limits remain, with all checks before sends. Each round restored the panel, config and autostart.

463 Python checks passed on Thor. Mac ran the same 463 with 87 Linux skips; other checks plus 15 JavaScript checks passed. After manifest verification/installation, the live marker had `GDK_GL=always`; original game/Steam/official upper/lower processes were not restarted. All personal config hashes matched and autostart stayed off.

After installation, about 51 seconds were recorded in the confirmed card viewer, including about 20 seconds of continuous one-finger movement: 1,125 updates, focus P95 1.07ms, maximum 34.45ms, no re-identification. Maximum GTK touch processing was about 1.56ms; a few source gaps exceeded 50ms, so not all input jitter was eliminated. The user confirmed smooth operation without re-identification. This passes short interaction acceptance for that scene; long sessions, other scenes and suspend/resume remain observations to make.

<a id="2026-10-21圆环与-steam-性能叠加显示共存"></a>

## 2026-10-21: coexistence with Steam's performance overlay

Touchscreen hid Slay the Spire 2 FPS while Touchpad did not. Read-only inspection found both `mangoapp overlay window` and the old marker registered as `GAMESCOPE_EXTERNAL_OVERLAY`; the local path selects one external overlay. Opacity/stacking changes select a different winner, not coexistence.

The candidate became a passive decoration of the same app: create an override-redirect window in the verified upper target XWayland, with its own app ID, transparent/noninteractive style and transient association; set neither `GAMESCOPE_EXTERNAL_OVERLAY` nor `STEAM_OVERLAY`. Keep empty input, no focus, GL and local redraw. No writes to mangoapp, Steam, game windows or services.

Binding includes app/window/server/size/origin. Window movement invalidates permission. The ring uses the app canvas but reports the physical upper source size, retaining complete-image/matching-aspect limits. Foreground changes release contacts, end the marker and wait for a stable new target/all-up; verified child-control changes in the same window do not rebuild it. Bounded IPC reports the marker's XID before mapping so it cannot become a new target; exited workers are reaped instead of accumulating.

A roughly 20-second prototype moved only its own ring, without input devices/game input. 1,228 focus checks found no target/focus change. The user confirmed FPS and ring together. As requested, this was any game scene, not specifically the card viewer, and cannot count as its performance regression. It restored the panel, config bytes, autostart and manifest.

The integrated build passed all 475 Thor Python checks. Mac skipped 87 Linux checks with the rest and 15 JavaScript checks passing. Manifest and per-file source comparison preceded installation, bundle `e4b632d44b115e47`. The live marker used target `:1`, `GDK_GL=always` and neither external nor Steam overlay flags. Foreground, original game/Steam/Gamescope/lower processes, config hashes, app running state and autostart were unchanged.

The user tested movement, clicks and a quick-access-menu round trip, confirming simultaneous display and normal touch. This is short coexistence/interaction acceptance on this device. Other Gamescope builds need validation; real direct multi-touch, long sessions, suspend/resume and this round's card-viewer performance were not separately tested. Earlier GL acceptance retains its own scope. At this stage the candidate was installed locally but unreleased.

<a id="2026-10-21圆环位置的事件驱动发送"></a>

## 2026-10-21: event-driven marker delivery

Previously touch callbacks only updated `MarkerOverlay.pending`; the 16ms health timer sent it through `poll()`. Known coordinates could wait for the next timer or longer under load. Updates now schedule one `GLib.PRIORITY_DEFAULT` main-loop callback, coalesce to the newest state and remove themselves after nonblocking delivery. The timer retains health/readiness/backpressure retry duties; congestion does not create busy retries. Ordinary sends never extend the worker heartbeat.

Close cancels pending delivery; even a late callback cannot use a closed channel. Async failure invalidates health for normal release/reconnect instead of escaping the GTK callback and interrupting cleanup. GL/passive decoration, drawing schedule, jump guard, real input and focus/route checks remain unchanged.

New checks cover coalescing, direct-touch clearing, readiness, no duplicate timer send, backpressure, asynchronous recovery, close and real GLib dispatch. All 484 Thor Python checks passed; Mac skipped 88 Linux/GLib checks, with the rest and 15 JavaScript checks passing.

`tools/marker_delivery_bench.py` compared installed and candidate code on real Thor GLib/local datagram sockets. Each source period ran old → new → new → old, with 0.5 seconds warmup and 5 seconds recording. A receiver replaced the marker worker: no windows/input devices/game input, and the official panel stayed running. Means of each version's two rounds:

| Source period | Implementation | Callback-to-receiver P50, ms | P95, ms | P99, ms | Received updates/s |
| --- | --- | --- | --- | --- | --- |
| 17ms, about 59/s | Timer | 8.13 | 15.40 | 16.05 | 58.4 |
| 17ms | Event-driven | 0.17 | 0.47 | 0.58 | 58.4 |
| 8ms, about 124/s | Timer | 4.79 | 7.87 | 8.24 | 62.2 |
| 8ms | Event-driven | 0.09 | 0.32 | 0.47 | 123.8 |

This measures callback-to-test-receiver delay, not physical touch-to-visible-position latency or display FPS. Old high-rate samples were merged; received-only latency cannot evaluate discarded positions. Generator/receiver CPU means were 1.53% → 1.92% of one core at 17ms and 1.71% → 2.68% at 8ms. Full app CPU, GPU, power and game frame times were not measured, so reduced resource use cannot be claimed.

Bundle `20a0f27decf7c8a7` was installed after matching manifest/source checks. The marker still used `:1`, GL and passive decoration without the FPS overlay slot. Foreground/original game/Steam/Gamescope/lower processes, config hashes and disabled autostart remained. An initial install check mistakenly required a marker on Touchpad and rolled back; respecting the selected page fixed the check and installation completed.

The user then tried slow circles, fast reversals and dragging for about 30 seconds in Touchscreen → Positioning, checking FPS. Feedback: more responsive, stable stopping, normal FPS. This accepts short responsiveness/stopping, not any specific card-viewer scene, long sessions, suspend/resume or every app. It is separate from the delivery benchmark and cannot infer physical end-to-end latency.

<a id="2026-10-21实测圆环绘制仍为约-60fps"></a>

## 2026-10-21: measured marker drawing still near 60FPS

After event delivery acceptance, position updates, GTK drawing and final display were separated. GDK reported upper Gamescope XWayland `119930mHz` and lower Wayland `60000mHz`; these are reported information, not independent scanout measurements.

Read-only observation subscribed to X Present on existing marker/foreground windows and created a separate X Damage resource, removing both afterward. No property writes, images or input devices. About 35 seconds of manual motion actually occurred on Steam Home (appid 769). Short marker-content-change intervals had median 17ms; main-interface Pixmap presentation median was 8.44ms. Marker Present events were all `NotifyMSC`, not Pixmap completion, so their count is not a render-frame count.

To rule out insufficient touch samples, only `thor-panel.service` was temporarily stopped for an approximately 8-second ring-only run using installed `MarkerOverlay` / `marker_worker`. Temporary child wrappers observed GTK `draw`, `after-paint` and frame-clock data. New positions arrived about every 4ms; no native device/game input. This round's foreground was Slay the Spire 2 (appid 2868840), so it is not a same-scene performance comparison.

| Metric | Result |
| --- | --- |
| Average supplied-position interval | 4.11ms, about 243/s |
| GTK `draw` average after the first 1 second | 16.667ms, about 60.00/s |
| Draw interval P50 / P95 / P99 | 16.68 / 17.41 / 17.64ms |
| Draw callback duration P50 / P95 | 0.136 / 0.388ms, excluding GPU completion/scanout |
| GTK frame clock | `GdkFrameClockIdle` |
| `get_refresh_info()` refresh interval | Always 16667µs |
| Completed-frame history refresh interval | Always 0; valid refresh information absent |

Drawing remained near 60Hz despite a >120/s source. Missing history and `16667µs` point to GTK's fallback interval, supported by [the API](https://docs.gtk.org/gdk3/method.FrameClock.get_refresh_info.html) and [frame-clock implementation](https://github.com/GNOME/gtk/blob/gtk-3-24/gdk/gdkframeclockidle.c). Earlier statements that the app did not hardcode 60FPS described its own constants, not measured GTK 120Hz drawing.

No backend/frame-clock/new-code change was deployed in this round. Original running state, config bytes, manifest, autostart, foreground and original game/Steam/Gamescope/lower processes were restored or preserved. Physical end-to-end latency, independently verified scanout FPS and production app GPU use remain unmeasured. A 120Hz experiment must separately measure scheduling, input rate, resources and FPS coexistence rather than equating delivery frequency with drawing.

<a id="2026-10-21按上屏刷新率调度及帧率设置"></a>

## 2026-10-21: upper-screen scheduling and frame-cap settings

The initial candidate replaced motion paint requests with independent one-shot scheduling. It reads GDK monitor mHz, preserves the fractional 119.93Hz period, draws only the latest state and skips late slots without replay. Initially it submitted bounded dirty regions through public `Gdk.Window.begin_draw_frame()` / `end_draw_frame()`; GL multi-buffer ghosts later required the correction below. No GTK private-memory/WM-timing/game changes; GL, empty input and passive same-app decoration remain.

Scheduling alone still yielded about 59 draws/s in game: complete draw/submit about 16.5ms versus usually <0.3ms in Cairo. Child-only Mesa `vblank_mode=0` reached about 119/s once; alternating repeats later reached about 62–70/s, waiting mainly in `end_draw_frame()`. Its own GLX drawable already had swap interval 0. Extra swap waiting therefore does not explain every fluctuation; no claim that all GTK/Gamescope/driver waits are fixed, and no Steam cap/compositor changes to chase a number.

Settings → Touchscreen adds Ring frame-rate cap, cycling **Follow screen / 120 / 60 / 30 FPS** and applying on save; default Follow screen. The follow label shows the latest detected upper rate: 119930mHz displays 120Hz, unknown remains unknown. Fixed caps never exceed the screen; invalid screen information conservatively falls back to 60Hz. Both touch submodes share it; send pacing, positioning scale, game cap and focus/route lifetimes stay unchanged. Settings releases input/stops the ring as before, using the selected cap on re-entry; discard/group defaults/upgrade preservation follow existing settings behavior.

With the same Slay the Spire 2 target, automatic ring-only trials ran old → 120 → 60 → 30 → follow → old, each about 1 second warmup, 4 seconds motion and 1 second idle. Latest positions arrived about every 4ms without input devices/game input. Upper reported 119930mHz; candidate swap interval was 0. These are raw results from **the first candidate later rolled back for ghosts**, not final acceptance:

| Cap | Draws/s | Interval P95 / P99, ms | Marker CPU, one-core % | Marker DRM engine busy, ms / about 4 seconds |
| --- | --- | --- | --- | --- |
| Old, before | 59.99 | 17.40 / 17.62 | 17.78 | 19.17 |
| 120 | 119.60 | 10.72 / 11.84 | 24.28 | 7.72 |
| 60 | 59.76 | 17.37 / 17.51 | 16.79 | 4.09 |
| 30 | 30.00 | 34.03 / 34.34 | 11.78 | 1.68 |
| Follow screen | 118.42 | 10.97 / 12.15 | 24.06 | 7.83 |
| Old, after | 59.23 | 17.60 / 24.22 | 14.28 | 5.01 |

All caps reached 0 draws once stationary, with existing health checks—not zero process CPU. The two high-rate runs had maximum intervals about 23.65 / 27.73ms, not every frame at 8.3ms. CPU counts only the marker, 100% = one core. GPU uses deduplicated per-process DRM engine time, not whole-GPU utilization/frequency/power. Old-run GPU times vary substantially; they cannot establish a GPU reduction. Higher rates cost CPU; 30/60 offer tradeoffs. Game frame times, physical scanout and full touch-to-display latency were not measured.

All 507 Python checks passed on Thor. Mac skipped 91 Linux/GLib/Cairo checks with the rest and 15 JavaScript checks passing. Added coverage includes caps, screen changes, fractional periods, skipping backlog, close/failure cleanup, dirty regions/transparency, config validation and save/discard. Incremental/full Cairo pixels permit at most 1/255 rounding at antialiased edges; reference-transparent pixels must clear exactly.

The panel/config/autostart/manifest/foreground/original protected processes were restored or preserved. This was temporary-candidate validation; final installation, real gestures and FPS coexistence require their own record, not inherited acceptance.

After offline candidate `14c52f27a919e532` passed manifest/install checks, the user saw many rings. It immediately rolled back to accepted `20a0f27decf7c8a7`, retaining personal configuration. Installation success is not visual acceptance.

<a id="多缓冲残影修正"></a>

### Multi-buffer ghost correction

Earlier offscreen comparisons used one retained Cairo surface, not real swapped buffers. GL back buffers can contain older frames; direct partial `begin_draw_frame()` bypassed GDK's normal buffer-age repair, so clearing only the previous location was insufficient. RGBA reads of the app's own marker at frames 20 / 40 / 80 / 120 / 180 found nontransparent pixels growing from 2,511 to 15,324 across hundreds of pixels; all five failed the one-ring check.

Full-surface clearing removed ghosts but raised CPU/GPU cost and was not installed. The adopted fix calls public `invalidate_region()` and `process_updates(False)` only on its own window. GDK's normal path maintains buffer age, expands required dirty regions and invokes the original draw callback. One-shot selected-rate scheduling remains independent of default 60Hz paint; no private GTK calls/fields. `process_updates()` is retained but deprecated in GTK 3.24, requiring redesign for GTK 4 rather than a universal toolkit claim.

Reads at the same five frames then showed one approximately 30×30 ring and about 463–468 nontransparent pixels without residue. Only the app's window was read, not game content. GPU-synchronous reads add overhead: this run establishes pixel correctness, **not performance**.

At the user's request, final comparison moved to Steam Library (appid 769, `:0`), repeating all six caps without pixel reads. This is separate from the earlier game scene:

| Cap | Draws/s | Interval P95 / P99, ms | Marker CPU, one-core % | DRM engine busy, ms / about 4 seconds |
| --- | --- | --- | --- | --- |
| Old, before | 59.74 | 17.40 / 17.99 | 19.05 | 17.84 |
| 120 | 119.93 | 9.10 / 9.37 | 30.05 | 24.16 |
| 60 | 60.00 | 17.39 / 17.68 | 19.31 | 17.76 |
| 30 | 30.00 | 34.05 / 34.44 | 12.03 | 2.21 |
| Follow screen | 119.91 | 9.09 / 9.40 | 30.06 | 24.09 |
| Old, after | 60.04 | 17.35 / 17.76 | 18.78 | 18.67 |

All stationary runs reached 0 draws. Maximum 120/follow intervals were 10.40 / 11.22ms. Independent focus-query P95 was 1.64–2.11ms, whole-run maximum about 21.32ms, below the 200ms permission lifetime. These are short Steam-scene results; 120 costs more CPU/GPU than 60. All 507 Thor checks, Mac checks except 91 Linux skips, and 15 JavaScript checks passed. Panel, personal config, autostart, manifest and protected processes were preserved. Foreground was checked before closing the test marker/restoring the panel; helpers sent no game input. An earlier abort for target/input-display mismatch is not a valid comparison.

Five additional real-window pixel checks on Steam showed one approximately 30×30 ring with 462–465 nontransparent pixels. Corrected bundle `2d883b128a4e70f6` was built offline, source-compared and installed, preserving config/autostart/foreground/protected processes. The production `:0` marker used GL and child-only `vblank_mode=0`, still outside the FPS external-overlay slot.

After circles, fast reversals and settings checks, the user confirmed one ring, four selectable caps and normal operation. Ghost correction, cap availability and short interaction passed. Game FPS/coexistence, real direct multi-touch, long use and suspend/resume were not retested here; previous game coexistence remains historical. At that point this was local-only, not committed/pushed/released.

SSH disconnected during log archival, leaving final bulk copy/remote temporary cleanup incomplete as recorded in local diagnostics. Tests were finished; the installed app has its own directory, independent of temporary sources. On reconnection, verify no process references the temporary path before deleting diagnostics; no reinstall/config changes are needed.

Implementation references: [GDK synchronous updates](https://docs.gtk.org/gdk3/method.Window.process_updates.html), [GDK dirty-region maintenance](https://github.com/GNOME/gtk/blob/gtk-3-24/gdk/gdkwindow.c), [X11 GL buffer age/submission](https://github.com/GNOME/gtk/blob/gtk-3-24/gdk/x11/gdkglcontext-x11.c), [Mesa vblank options](https://cgit.freedesktop.org/mesa/mesa/tree/src/util/driconf.h?id=90994e4db7000951be058a956813e4a828f862c9).

<a id="2026-10-22圆环视觉跟随平滑新分支候选"></a>

## 2026-10-22: visual ring smoothing (new-branch candidate)

Earlier GL/FPS/IPC/cap work was saved as `bf6863a`, then this candidate was implemented on `feat/marker-visual-smoothing`.
Initially it was not installed, pushed or released; earlier version acceptance does not automatically cover it.

<a id="目标与实现"></a>

### Goal and implementation

Only the worker's visual trajectory changes. Physical samples, native coordinates/events, click/release order, focus protection, lower driver, game cap and personal config remain.
At about 58Hz real input, demand-driven drawing cannot invent intermediate positions merely from selecting 120 FPS. This candidate keeps converging visually within the existing cap.

- `marker_motion.py` uses a continuous-time first-order follower with an 8ms time constant. It advances the old target before accepting a new sample, avoiding restarted easing per packet. Position stays between the current visual point and latest confirmed target, without extrapolation.
- At 40ms since the last target change, or error <0.2 pixels, snap exactly to the confirmed point and stop animation requests. 40ms is a model convergence bound; actual display still waits for scheduling/event-loop time, not a physical 40ms guarantee.
- New fingers, press changes, release, mode switches and reconnection snap directly. Large jumps, stale samples and render stalls never replay backlog. Stable contact IDs prevent reassigning a removed finger's trajectory by array index.
- Visual IPC carries monotonic time, contact identity/activity and snap flags. Parent and child retain lifecycle flags through batching/backpressure; old/test messages without metadata apply immediately.
- Keep `MarkerFrames` 30 / 60 / 120 / follow-upper caps, GL child, public GDK dirty updates and buffer-age repair. No real-input sender or FPS-overlay property changes.

The tradeoff is small visual lag during motion and possible small alignment corrections on click; actual touch stays at the real coordinate.
At 120Hz drawing with about 58Hz input, motion drawing may nearly double. CPU/GPU/power cannot be promised unchanged.

<a id="离线轨迹回放"></a>

### Offline trajectory replay

Reproduce with `python3 -B tools/marker_smoothing_bench.py --output /tmp/marker-smoothing.json`.
No device reads, windows or native input writes. A 1920×1080 canvas and ideal 57.7144Hz samples compare constant-speed lines, stop, reversal and circles at 120 / 60 / 30Hz rendering samples.

For a 600 pixels/s line, model results in the steady 0.15–0.95-second interval:

| Render sample rate | Immediate / smoothed position changes/s | Immediate / smoothed step coefficient of variation | Added mean equivalent visual lag |
| --- | --- | --- | --- |
| 120Hz | 57.5 / 120.0 | 1.043 / 0.318 | 7.93ms |
| 60Hz | 57.5 / 60.0 | 0.209 / 0.023 | 8.38ms |
| 30Hz | 30.0 / 30.0 | 0.147 / 0.022 | 8.83ms |

Variation describes equal-time step uniformity for that line, not a feel score. At 120Hz, visual error against the latest confirmed point had P50 / P95 / maximum 3.94 / 10.37 / 11.50 pixels. Equivalent lag divides that error by known synthetic speed; it is not measured physical latency. All four trajectories at all three rates ended exactly at the confirmed endpoint without animation.

<a id="隔离检查与边界"></a>

### Isolated checks and boundaries

535 Thor Python checks passed using the production GtkLayerShell dependency path. An earlier run without it failed namespace loading and is not a pass. Mac skipped 92 Linux/Cairo/GLib checks, with remaining checks and 15 JavaScript checks passing.
Coverage includes continuous-time motion, press/release, stopping, backlog skipping, contact identity/order, IPC flags and immediate native events. Linux Cairo compared partial/full rendering for 180 animation frames with exact transparent clearing; this still is not real GL swapped-buffer validation.

Models/checks do not measure device 120 FPS, GPU/compositor/scanout or game frames. Later installation, feedback and real-renderer measurements follow.

<a id="真实窗口安装用户反馈与八轮资源对比"></a>

### Real-window installation, feedback and eight resource trials

On 2026-10-22, bundle `77518bcf59af9a23` (source `51570f5`) passed manifest/per-file checks and was installed. Config hashes, disabled autostart, physical touch-report parameters and original Steam/game/Gamescope/lower processes were unchanged. The user reported noticeably smoother motion. This is short subjective acceptance without a specific game scene, not every game or long-session proof.

Eight automatic no-user-action trials then ran on Steam Home. The installed GTK/GL renderer drew synthetic trajectories in its own passive window; the normal panel stayed running, and no native input was read/generated or sent to Steam/games. Confirmed coordinates arrived at about 57.7144Hz, tracing a 600 pixels/s line reversing every second. At each of 60 and 120 FPS, order was immediate → smooth → smooth → immediate: each round 13 seconds, with 8 seconds measured motion and 3 final idle seconds. Two whole-app idle samples of 10 seconds bracketed the eight rounds.

Both groups used the same installed code, GL and trajectory function; immediate marked synthetic coordinates as snap-only to isolate smoothing cost rather than reinstalling an old version. 120 FPS applied only to test children; the user's saved 60 FPS stayed unchanged. Two-round means:

| Cap and behavior | Actual draws/s | Reconstructed step variation | Marker CPU, one-core % | Marker GPU engine busy, ms/s |
| --- | --- | --- | --- | --- |
| 60 FPS, immediate | 57.75 | 0.205 | 11.25 | 2.33 |
| 60 FPS, smooth | 60.00 | 0.049 | 13.44 | 4.12 |
| 120 FPS, immediate | 57.75 | 1.041 | 12.81 | 3.98 |
| 120 FPS, smooth | 119.81 | 0.253 | 24.25 | 8.49 |

Draw counts come from callbacks, not verified physical presentation. Step variation reconstructs held positions from actual callback centers on fixed 60 / 119.93Hz grids, excluding 80ms around reversals; it is standard deviation/mean, lower = more even, not optical scanout. Both caps reduced variation about 76%, supporting the reported feel without raising game FPS or physical input rate.

Error from the latest received position, divided by 600 pixels/s, averaged 8.49ms / 9.13ms; this is not total physical latency. Smoothed stops reached the exact endpoint in about 38.13ms / 35.45ms without overshoot; all final positions matched. Across all final 3-second segments (24 seconds), draws were 0. Idle test-marker CPU averaged about 0.17% of one core and GPU engine delta 0, with existing health checks retained.

CPU 100% = one core. GPU is deduplicated per-marker DRM engine time, not whole-device GPU utilization, power or Gamescope/KWin composition. The original service cgroup's before/after idle CPU was 16.44% / 15.14% of one core, including lower UI, supervisor, original marker and short-lived children; the original marker itself was about 0.10%. The lower UI exposed no usable independent DRM engine counter, so total app GPU use was not measured. These trials did not drive production lower keyboard/mouse events; adding idle-app and test-marker numbers is not a real continuous-operation total.

Independent focus-query P95 / P99 / maximum were about 1.52 / 2.45 / 13.66ms with no target change. Service, manifest, config bytes, touch parameters and original processes stayed unchanged; temporary files were removed after test windows exited. No panel/game restart, game-cap or physical-input changes. New-version FPS coexistence, real multi-touch, long use and suspend/resume were not reaccepted here; earlier short tests retain their own scope.

<a id="2026-10-20-初版自动实测移除镜像之前"></a>

## 2026-10-20 initial automated device tests (before mirror removal)

- All 333 Thor Python checks passed. Mac ran 333 with 41 Linux GTK skips. All 15 Steam-guard JavaScript checks passed.
- During marker-only display, 145 target checks left Steam's foreground unchanged; closing ended the marker process.
- Integrated lifecycle checks covered auto-enable, positioning only, manual pause/resume, collapse/expand, returning to split and exit. Positioning sent 0 upper touches, capture stayed None, final touch nodes/marker processes were zero and config bytes were unchanged.
- Dedicated upper-window checks: positioning added 0 touches/0 mouse moves; confirmation received 2 presses, 1 motion, 2 releases, 0 cancels. Coordinates matched, all sources were touchscreen. Closing during a held contact released it. No automatic game input.
- A roughly 5-second synthetic positioning run used about 18.47% of one core in the panel and 4.20% in the marker. This includes checker/sampler overhead and excludes Gamescope/XWayland composition. No same-game on/off comparison; no total-power/game-FPS inference.
- Read-only descriptor-scan microbenchmarks, 5 runs per implementation: old traversal about 11.72ms CPU/scan; scandir about 4.91ms. This is workload-specific, not a universal ratio.
- Offscreen lower-UI checks showed complete Chinese labels, four tabs and buttons.

The dedicated input test requires Steam Home in native touch mode 4, briefly shows its own upper window, then closes. It refuses a mismatched foreground. Do not run in a game or alongside the production panel. No sudo:

```bash
PYTHONPATH=src python3 -B tools/position_input_smoke.py
```

Use the same GTK/private-runtime environment as the app; prepare that environment before source-directory tests.

<a id="移除同屏触摸"></a>

## Mirror touch removal

On 2026-10-20, the mirror page, capture sources, image rendering/refresh timers, mouse-compatibility backend and standalone mirror preview were removed at the user's request.
Target validation, temporary native touch and marker remain; old `mirror` falls back to split.
The initial 333-check/four-page result above predates removal, not the current test count/layout.

After removal, all 250 Thor Python regressions passed. Mac skipped 36 Linux GTK checks with the rest passing; all 15 Steam-guard JavaScript checks passed. Three-mode offscreen header checks found 24 labels without missing glyphs/overflow.
No game input was sent, so these are not user-interaction acceptance. Legacy-mode fallback and no config mutation on reads have regression coverage.

<a id="待验证与回退"></a>

## Pending validation and rollback

The initial user saw the ring but reported stopped one-finger motion, sometimes not recovering after lift.
Aggregate diagnostics showed GDK/logical moves increasing, valid focus/heartbeat/route, but a lost first finger with the second retained, `blocked=true`, and no position/draw progress.
The old state machine required every remaining sequence to end before accepting another positioning finger; stale/delayed contacts also blocked new begins.
The fix never promotes old roles, but permits a new begin to position without app input. Old movement/end cannot confirm or release new touch; a fresh second begin is still required.
Regression coverage includes single/multiple stale contacts, new positioning without output and old ends not releasing new confirmation.
This identifies an app state-machine block. The user then confirmed movement, recontact, dragging and separate releases; simultaneous begin sometimes still missed, with drift and occasional orange-after-lift.

<a id="同时落指残留触点早期底层诊断"></a>

### Simultaneous begin and stale contacts: early physical diagnosis

Bounded before/after dispatch records showed received BEGIN/END reached callbacks. When both BEGINs arrived—even with equal source time—confirmation pressed correctly.
Some attempts had only one BEGIN before GTK dispatch, even with fingers 3–5cm apart. These cannot all be called app two-finger failures.

One app bug was also fixed: real `event.touch.emulating_pointer` identified the first finger, while `get_pointer_emulated()` remained false throughout the batch. Reading the public EventTouch field fixes this. On a trusted new-gesture boundary, Positioning releases the old native contact and logical fingers, preserving marker location/verified backend. Cancellation never becomes a click and old roles never promote.
Regressions cover missing private flags, absent old END, no jump on release and late old ends not affecting a new gesture.

Separate private diagnostics queried physical `EVIOCGMTSLOTS` / `EVIOCGKEY` read-only: no queue reads, grabs, writes, coordinate/ID logs.
After all fingers lifted, the device still reported one active slot and `BTN_TOUCH=true`, before GTK/app logic. The physical device was `focaltech,ft5452` / `edt_ft5x06`, kernel `7.2.6`. The normal panel still does not read physical devices; diagnostics changed no driver/DT.

Armada's DT enabled `no-regmap-bulk-read`, whose patch reads frames bytewise with retries on specific errors; upstream cleans slots by explicit contact-ID UP.
These identify paths to inspect but **do not prove** bytewise reads, lost IRQs, firmware or another driver behavior caused residue.
Inactivity cannot establish release: valid long holds can be stationary. No guessed second fingers or forced timed releases hide missing events.

Physical reporting should be the next independent variable before deciding on system patches. At this early stage no kernel/DT experiment was deployed; missed two-finger begin, drift and stale release were not declared fully fixed.

Another Thor Linux project's UP/stale-slot patch was subsequently found and narrowed to Armada's lower FT5452. It applied without fuzzy matching, but the user stopped the kernel build before completion/deployment.
Diagnostics/diff went to [ArmadaOS Issue #757](https://github.com/armada-os/armada/issues/757) for evaluation, not as a validated fix. See [contact lifecycle and candidate](thor-ft5452-contact-lifecycle.md). This is more directly relevant than read-path suspicion; it does not justify guessing sensitivity changes.

A later standalone module, without replacing the boot kernel, passed 90 seconds and automatic rollback. The user confirmed immediate second-finger release and normal dragging, with physical contacts returning to zero. Simultaneous begin, long use and sleep remain pending. Earlier nondeployment statements describe that earlier phase; see [later module results](thor-ft5452-contact-lifecycle.md#后续独立模块路线) for current recorded status/rollback. App installation excludes the experiment.

References: [public EventTouch fields](https://docs.gtk.org/gdk3/struct.EventTouch.html), [Armada read compatibility patch](https://github.com/armada-os/armada/blob/c3d178c/packages/kernel/patches/0029-Input-edt-ft5x06-add-no_regmap_bulk_read-option.patch), [versioned Thor DT](https://github.com/armada-os/armada/blob/c3d178c/packages/kernel/dts/qcs8550-ayn-thor.dts), [upstream edt-ft5x06](https://github.com/torvalds/linux/blob/master/drivers/input/touchscreen/edt-ft5x06.c).

<a id="单指移动同样出现突跳应用侧保护及本轮验收"></a>

### Single-finger jumps: application guard and acceptance

The user confirmed twitching both while holding the first finger and repeatedly tapping the second and during one-finger movement; this was not limited to two-finger click debounce.
Diagnostics captured raw one-step displacement about 535–536 logical units, corresponding to about 738–745 upper pixels, source intervals about 195–293ms, without a native contact held.
Large second-finger movement did not move the ring, so role isolation remained. Abnormal distances were being applied as deltas, but the records do not independently identify controller/driver cause.

`PositionMotion` uses ToolkitTouch source sample intervals only in Positioning, without changing split mode, sensitivity, system or game configuration:

- Normal motion passes immediately, without a universal smoothing delay or reduced input rate.
- Base large-step threshold is 18% of the area's short side; recent speed relaxes it during continuous motion. Source gaps over 120ms discard old speed prediction.
- A suspect step is held without moving the ring. A return to the old point or stable samples near the new one only reanchors, never replays the bad distance or adds a reverse jump.
- Continuous same-direction fast movement may proceed after dropping the first unconfirmed step, avoiding an indefinitely blocked fast swipe.
- The guard also applies while a native contact is held, preserving that contact. Press/release is neither delayed, added nor timed out.
- Lift, cancel and a new positioning finger clear recovery state; nonsampled developer calls retain previous behavior.

Regressions cover one-finger motion, isolated spikes, stable new baselines, alternating bad points, fast swipes, long gaps, bad held-contact motion and new-gesture isolation.
After 333 checks passed, deployment removed temporary jump logging, preserving config bytes/manual launch.
The user tested motion, repeated second-finger taps and dragging and confirmed no more jumps/normal drag. This is short device acceptance without a named app, not all games/long sessions.
It is a coordinate guard, **not a cure for missing physical contacts**. The first step of very fast motion may be dropped if indistinguishable from a spike; zero effect at every speed is not claimed.

That round did not validate real Steam operation, Slay the Spire 2 card-drag feel, sleep, physical upper-touch/controller coexistence or long resource use. Later card-viewer/menu results above cover only their stated scope.
Ring/performance coexistence was unconfirmed then; passive decoration later passed a short local test, recorded under [coexistence](#2026-10-21圆环与-steam-性能叠加显示共存).
The feature never stops/rewrites the system overlay. If the marker is invisible, stop that mode and inspect composition selection; do not silently substitute system-pointer motion.

Return to split or Touchpad to close marker/native touch; upper-right Close exits the panel.
The same desktop shortcut/manual user service remain, with boot/login autostart disabled by default.
Before deployment, back up app/config. To roll back, stop `thor-panel.service`, restore that backup and reopen manually.


<a id="2026-10-22-touch-cpu-candidate"></a>

## 2026-10-22: touch CPU optimization candidate

This local candidate is based on v0.1.4 (`9326d78`) on `perf/touch-cpu`. The device's installed v0.1.3, personal configuration and disabled autostart were preserved; temporary source copies ran only against an owned receiver window on Steam Home. These results are not an installation, release, game test or battery-life measurement.

### Retained changes and tradeoffs

- Validate/copy marker geometry once at the sender boundary instead of two or three times, and compare motion metadata without making two dictionaries per update. The worker still independently validates IPC; timestamp-only updates, contact identities, lifecycle snaps and backpressure handling remain.
- Reuse 36×36 Cairo ring sprites at eight subpixel phases per axis. The 128-entry cache holds at most 648 KiB of pixel data, excluding Python/driver bookkeeping. Colors, open centers, outlines and partial-damage clearing remain. Scaled, translated or rotated contexts retain the vector path.
- Only visual raster coordinates round to the nearest 1/8 pixel: at most 1/16 pixel error per axis (under 0.089 pixel Euclidean error). Native coordinates, event timing/order, focus/route checks, smoothing and frame caps are unchanged. The worker still stops drawing once motion settles.
- An initial per-contact native-write batching experiment did not show a convincing total CPU benefit and increased the five-finger result in its short A/B. It was discarded; the retained candidate uses the original libevdev writer. No input-rate reduction or cross-event permission cache was introduced.

### Component measurements

Thor/aarch64, Python 3.14.8, kernel 7.2.6. Sender preparation used five rounds of 20,000 updates: single/two/five-contact median CPU time changed from 5.616/7.712/13.428 μs to 4.189/4.723/6.821 μs (about 25/39/49% lower). This excludes GTK/IPC submission and real input.

A separate offscreen 1920×1080 dirty-region workload warmed up for 1,000 frames, then took three rounds of 2,000 frames. Median painting/scene CPU time for one/two/five rings changed from 47.02/92.11/227.84 μs to 8.00/13.39/28.87 μs (about 83/85/87% lower). This CPU-only component result is **not** the whole-application reduction. Reproduce on a Linux Cairo runtime with:

```bash
python3 -B /path/to/candidate/tools/marker_paint_bench.py --source-root /path/to/baseline --output /tmp/marker-before.json
python3 -B /path/to/candidate/tools/marker_paint_bench.py --source-root /path/to/candidate --output /tmp/marker-after.json
```

### Completed actual-window A/B

Order: baseline → candidate → candidate → baseline; case order reversed for the last two runs. Each case had a two-second warmup and six-second sampling window. Four cases per run: positioning idle/moving and direct two/five-finger movement. An independent driver sent synthetic lower-panel contacts, guarded against leaving our own upper receiver. It never targeted Steam controls or games. Both versions used a temporary 120 FPS cap; saved preferences were untouched. The interrupted preliminary cache run is excluded.

Two-run means, before → candidate:

| Workload | Panel + children CPU, one-core % | Marker CPU, one-core % | Attributable DRM GPU busy, ms/s |
| --- | --- | --- | --- |
| Positioning, idle | 12.70 → 14.11 | 0.20 → 0.10 | 0.00 → 0.00 |
| Positioning, moving | 41.75 → 41.14 | 23.47 → 23.33 | 12.30 → 11.36 |
| Direct touch, two fingers | 48.28 → 47.35 | 25.79 → 24.97 | 16.85 → 15.38 |
| Direct touch, five fingers | 65.99 → 61.36 | 33.15 → 29.53 | 31.93 → 32.48 |

CPU 100% means one logical core. The CPU scope includes the test panel and its marker children, excluding the independent input driver, receiver, collector, compositor and normal service supervisor. GPU covers deduplicated readable DRM clients belonging to those processes; it does not cover all lower-screen compositor work or total application/device GPU cost.

The five-finger aggregate fell about 7.0%, with marker CPU about 10.9% lower; both candidate repeats were below both baselines. Positioning/two-finger aggregate changes were only about 1.4/1.9% and are too small to establish a reliable general improvement from these short samples. Idle did **not** improve: its baseline repeats ranged from 10.60 to 14.79%, so the higher candidate mean remains inconclusive. GPU did not consistently decrease; no power/battery claim follows.

Active rendering remained about 109–110 draw callbacks/s in both versions, not confirmed physical presentation FPS. Source rates were about 53–54 updates/s per finger; the candidate did not throttle them. Handler P95 stayed around 1.5–1.7 ms, with no demonstrated increase. Five-finger aggregate PSS rose about 1.8 MiB (141.25 → 143.09 MiB); this includes runtime/driver allocation, not just cached pixels.

595 Thor Python checks passed; Mac passed the remainder with 105 Linux checks skipped, plus 15 JavaScript checks. Offscreen comparisons cover all 64 phase combinations for both colors, fallback transforms and partial-frame clearing. Five own-window GL pixel captures covered movement, one/two/five contacts and clearing: no pixels outside the expected circles, and zero nontransparent pixels after clearing. Worker cache counters confirmed actual reuse. After completion, configuration hashes, installed target and service/autostart state matched; test processes and virtual touch nodes were gone. No real-game, FPS-overlay coexistence, long-session or suspend/resume acceptance is claimed for this candidate.

<a id="2026-10-22-whole-app-idle-cpu"></a>

## 2026-10-22: whole-application idle CPU follow-up

The `perf/touch-idle` candidate retains the preceding sender/sprite changes. This round compares that preceding candidate with the additional changes below, **not** installed v0.1.3 against an official new release. The installed release, personal config and disabled autostart remain unchanged. No commit, installation or publication follows from these measurements.

### Attribution and retained changes

Two 30-second complete-service idle baselines were 15.05% / 15.18% of one core. Representative surviving threads accounted for about 5.3–5.7% in route ownership scanning, 4.2–4.3% in the GUI main thread, 2.2–2.3% in foreground queries, 0.8% in supervision and 0.1% in the marker. Service `cpu.stat` also includes short-lived children missed by process snapshots; these categories do not exhaust or independently partition every cost. Idle marker painting was not the principal source of application CPU.

Idle-only ablations disabled one subsystem at a time, with contact injection disabled. Their effects are not additive and the disabled checks are **not** product changes. A first attempt to use concurrent `cProfile` instances conflicted with Python's profiler tool allocation; that failed run is excluded. Replacement wrappers measured selected calls with per-thread CPU clocks. They identified repeated strict path resolution as a main-thread cost, in addition to route scanning and foreground queries.

Retained changes:

- Resolve current endpoint paths through Linux libc's strict `realpath()` instead of issuing each path-component operation through Python. Only function pointers are cached: runtime ownership/type, canonical paths and both socket identities are still checked afresh. Other platforms/unavailable APIs retain strict `Path.resolve()`. Allocated native results are always freed. The [POSIX interface](https://man7.org/linux/man-pages/man3/realpath.3.html) does not add an authorization cache.
- Decode the already-received [XCB property header](https://xcb.freedesktop.org/manual/structxcb__get__property__reply__t.html) directly, avoiding extra value-pointer/length accessor calls for each property. New tests cover layout and truncated bodies; request batching, geometry, ancestry, policy checks and snapshot expiry remain.
- Parse only the required `/proc/*/status` fields during session discovery, ending early for unrelated process names. Relevant processes still require fresh UID/parent/session corroboration.
- Refresh the touch page's status stripe instead of the whole lower page each second. Mode/message changes still request a full repaint. Keyboard/trackpad orbital behavior is retained; status damage is rounded in widget pixels and checked against full-frame output at 1× and 0.55× scale.

No input frequency, frame cap, native contact encoding, per-contact guard, route scan interval/expiry, foreground expiry or marker heartbeat was reduced. No new helper process or compiled library is retained.

### Complete-service comparison

Thor / Python 3.14.8 / kernel 7.2.6, Steam Home, owned receiver only. Temporary settings selected a 120 FPS ring cap; saved settings were untouched. CPU comes from the entire transient service cgroup: supervisor, lower GUI, marker and transient children. The receiver, external input driver and collector are excluded.

Idle used two 20-second samples per implementation, with a separate process experiment interleaved: baseline → candidate → experiment → experiment → candidate → baseline. Active tests used baseline → candidate → candidate → baseline, reversing workload order for the latter two runs, with two-second warmups and ten-second CPU samples. Synthetic contacts targeted only the owned receiver; no real game input was sent.

| Workload | Service CPU: preceding → new candidate, one-core % | Relative change | Readable DRM GPU busy, ms/s |
| --- | --- | --- | --- |
| Touch page idle | 14.66 → 13.25 | −9.6% | 0 → 0 |
| Positioning drag | 44.42 → 44.11 | −0.7% | 12.56 → 12.57 |
| Direct touch, two moving fingers | 47.52 → 48.51 | +2.1% | 16.59 → 16.58 |
| Direct touch, five moving fingers | 62.91 → 61.59 | −2.1% | 32.01 → 31.93 |

100% CPU means one logical core, **not** the entire handheld. Idle repeats were 14.44/14.89% before and 13.57/12.93% after; both candidate observations were below both baselines. The active ±2% differences do not establish a reliable overall active CPU reduction. The engineering targets of 30% less idle CPU and 15% less active CPU were not reached.

Marker draw callbacks stayed around 116.5–117.4/s in both versions; this is not physical presentation FPS. Positioning source rate was 54.34 → 54.53 events/s, with comparable per-finger rates in multi-touch. Handler P95 for positioning/two/five fingers was 1.74/1.47/1.50 → 1.57/1.49/1.40ms: no consistent material regression was demonstrated, but this is not physical touch-to-display latency or long-session acceptance.

Idle service PSS was 150.33 → 152.62 MiB; active end-of-sample PSS increased about 0.53/3.77/1.94 MiB by workload. These short point samples include runtime/driver allocations and cannot establish a leak or a permanent allocation delta. GPU figures deduplicate readable service-process DRM clients, largely the marker; they omit lower-compositor work without an independent counter. No total-GPU, game-frame-time, power or battery-life improvement is established.

### Experiments not retained and validation

- Moving the Python ownership scan into a separate process produced variable CPU and about 163.42 MiB idle PSS versus 152.62 MiB for the normal candidate. It was not retained.
- A small independently compiled C scanner preserved complete owner detection, including duplicate descriptors, inherited descriptors in another process, close/recheck and root errors. Its additional idle comparison was 13.63 → 12.77% on average, with overlapping repeats and only two observations each. That evidence did not justify adding a compiled runtime/build dependency; source/binary remain experiment artifacts only.
- Empty marker IPC polling was comparatively small. No check intervals or freshness limits were relaxed to manufacture a lower number. Active renderer submission remains a candidate for further attribution, rather than a proven GTK-only cause.

The Thor suite passed all 603 Python checks. Mac ran the same 603 checks with 107 Linux-specific skips, plus 15 passing JavaScript checks. Pixel comparisons cover partial status repaint; target tests retain alias retargeting, endpoint replacement during partner lookup, ownership/type failures and metadata failures. Steam FPS coexistence and real-game behavior were not newly accepted by a user in this round.

Each controller compared config hashes, installed target and service/autostart state before/after. Temporary windows, service units, input devices and test copies are removed after collection. Detailed raw evidence is retained locally under `outputs/ads-touch-idle-20261022`; it is not bundled into releases.


<a id="2026-10-22-native-marker-submission"></a>

## 2026-10-22: native EGL marker submission candidate

The preceding idle optimization did not achieve the intended active reduction. This follow-up compares that same `perf/touch-idle` candidate with a native marker backend, rather than comparing the installed v0.1.3 with a new release. Formal installation and saved preferences remain unchanged. The saved cap was 60 FPS; both that cap and a temporary 120 FPS test cap were measured in isolated copies on Steam Home, sending contacts only to the benchmark's own receiver.

### Cost attribution and implementation

Explicit per-thread timing in two ten-second ring-only runs attributed about 16 / 21% of one core to the existing `Gdk.Window.process_updates(False)` path for one / five rings, including its draw callback and driver work. Circle drawing itself accounted for about 0.7 / 1.7%. These nested timings are not additive, and this is evidence about this GTK 3/GDK submission path, not a claim about every GTK application. The measured marker process used about 25.90 / 35.40% CPU. A Gtk.GLArea atlas prototype increased that to 32.60 / 38.10% and was rejected. A direct XCB/EGL prototype reached 10.90 / 12.70% and motivated the integrated tests below.

The retained candidate:

- Creates a checked, override-redirect RGBA8 XCB window on the verified target display, with an empty input shape, `WM_HINTS.input=false`, the existing matching-app decoration properties and no focus request. It claims neither the Steam overlay nor external FPS-overlay slot.
- Uses a private GLES 3 context and two small texture atlases generated from the existing Cairo subpixel sprites. Premultiplied alpha, colors, outline, transparent center and coordinate quantization remain the same. There is no new compiled helper or installed RPM.
- Clears and redraws every complete backbuffer, then submits current surface-damage hints through the advertised swap-damage extension. Damage hints do not imply preserved backbuffer contents. This deliberately avoids the earlier partial-buffer trail failure. No readback or `glFinish()` occurs in the application frame loop.
- Preserves the existing motion filter, latest-state IPC, demand-driven pacer, 30/60/120/follow-display caps, native contact sender, per-contact checks and all freshness limits. Only the marker child changes; the lower GUI stays GTK.
- Falls back to the existing GTK backend only when native setup is unavailable, after cleaning its unmapped resources and before consuming IPC or publishing a window. Known software-renderer setups are rejected. A post-activation error closes the worker and triggers normal parent protection, rather than switching a live backend. Optional GL/EGL/XCB-shape libraries use the existing host runtime; their absence must not become a new mandatory installation dependency.

The prototype initially declared the XCB restack function with an incomplete native signature. The first whole-app attempt therefore hit BadWindow during restore and correctly disarmed input; it is excluded. The corrected four-argument signature retains the complete 32-bit XID and has a regression test. An unavailable-entry `ValueError` was subsequently added to setup-only fallback; the 60 FPS and compositor rounds below include that final exception-handling change. Normal rendering code was unchanged from the 120 FPS round.

References: [EGL XCB platform](https://registry.khronos.org/EGL/extensions/EXT/EGL_EXT_platform_xcb.txt), [swap-damage semantics](https://registry.khronos.org/EGL/extensions/KHR/EGL_KHR_swap_buffers_with_damage.txt), [XCB Shape API](https://xcb.freedesktop.org/manual/group__XCB__Shape__API.html).

### Complete-service CPU, GPU and memory

Each cap used baseline → candidate → candidate → baseline, with workload order reversed for the latter two runs. Warmup was two seconds; CPU samples were 15 seconds at 60 FPS and 20 seconds at 120 FPS. CPU comes from the entire transient service cgroup, including supervisor, lower GUI, marker and transient children; the receiver, input driver and collector are excluded. Table values are the means of two observations per implementation.

| Temporary cap | Workload | Service CPU, one-core % | Relative CPU change | Readable service DRM busy, ms/s | Service PSS, MiB |
| --- | --- | --- | --- | --- | --- |
| 60 | Positioning drag | 33.44 → 27.46 | -17.9% | 3.67 → 8.83 | 155.13 → 175.57 |
| 60 | Direct touch, two fingers | 35.85 → 30.08 | -16.1% | 2.68 → 8.95 | 157.83 → 174.12 |
| 60 | Direct touch, five fingers | 47.61 → 37.21 | -21.9% | 18.88 → 9.19 | 156.72 → 173.16 |
| 120 | Positioning drag | 43.03 → 30.35 | -29.5% | 12.62 → 17.54 | 155.93 → 172.94 |
| 120 | Direct touch, two fingers | 46.57 → 34.65 | -25.6% | 16.73 → 17.83 | 155.62 → 174.75 |
| 120 | Direct touch, five fingers | 61.37 → 42.21 | -31.2% | 32.33 → 18.43 | 155.81 → 172.92 |

100% CPU means one logical core, not the whole handheld. The active target of at least 15% lower service CPU was reached in these cases: about 16–22% at the saved 60 FPS cap and 26–31% at 120 FPS. Both candidate observations were below both baselines for every active case. This does not establish a game-frame-time or battery-life improvement.

Idle still did **not** meet its target: the final 120 FPS series was 15.30 → 14.95%, with overlapping repeats (16.20/14.40 before, 15.51/14.38 after). Idle marker draw counts were zero. The rendering change does not resolve the foreground, route-verification and other persistent idle costs.

At 60 FPS, marker callbacks stayed about 59.1–59.5/s; at 120 FPS, about 117.9–118.9/s, using heartbeat count windows rather than physical presentation timestamps. Positioning input stayed about 55 events/s, with comparable per-finger rates for multi-touch. Handler P95 remained about 1.3–1.6ms, without a consistent meaningful change. Sampled readiness stayed true; non-idle rounds delivered native movement with no cancellation, so reduced CPU was not produced by disabling touch mid-run.

PSS increased about 16–21 MiB. These process/runtime/driver point samples do not isolate texture memory or establish a leak. Service-only GPU busy increased for positioning and two fingers, while decreasing for five fingers; CPU reduction alone must not be described as universally lower GPU work.

### External rendering costs and validation limits

The first external sampler included Xwayland/KWin but missed Gamescope's actual `gamescope-wl` process name. A separate 120 FPS baseline → candidate → candidate → baseline follow-up explicitly included both Gamescope processes, Xwayland and readable related DRM clients, using two-second warmups and twelve-second samples for positioning/five fingers.

For positioning, Xwayland CPU was 39.32 → 20.86% and Gamescope CPU 13.66 → 14.23%; for five fingers, 45.44 → 25.34% and 15.48 → 17.34%. Gamescope's small increase was considerably smaller than the service plus Xwayland reduction; KWin stayed about 0.2–0.3%. The deduplicated readable application-plus-selected-external GPU engine time was 123.54 → 33.85ms/s and 160.79 → 34.76ms/s. This broader evidence supports reduced work in the measured rendering path, but it remains a selected-process counter scope, not total device GPU utilization, power, or all compositor activity.

Native framebuffer readback covered 381 frames: every 8×8 subpixel phase for both colors, clipped edges, overlapping rings, ten contacts, repeated two/five-ring moves and clearing across swapped buffers. All channels exactly matched the existing Cairo reference, with zero alpha outside reference pixels. Readback touched only the test window. A real X Shape query confirmed an empty input region; the owned receiver retained foreground. These checks do not replace physical scanout or in-game interaction acceptance.

Thor passed all 615 Python checks. Mac ran the same suite with 107 Linux-specific skips; the remainder and 15 JavaScript checks passed. Earlier incomplete test exports lacked repository metadata/documentation and are excluded from pass claims. Resource controllers compare configuration hashes, installed target and inactive/disabled service state, then close their own windows, transient units and virtual devices. No official Steam, Gamescope or Armada service was restarted, and no driver, kernel or real game setting changed. Raw evidence remains local under `outputs/ads-marker-submit-20261022`, outside release bundles. Long-session, suspend/resume and real-game/FPS coexistence acceptance have not been repeated for this native candidate.

A separate passive-window cap check measured about 29.98 / 59.95 / 119.86 / 119.90 draw callbacks/s for 30 / 60 / 120 / Follow display on the reported 119930mHz upper monitor. Every cap added zero stationary draws over a three-second settled window. Intentionally rejecting native surface setup in a fresh child produced a ready GTK marker on the same owned receiver; foreground and saved state stayed unchanged. These are callback/functional checks, not physical scanout measurements.

A further read-only directory-FD ownership-scan experiment opened directories, never event devices. Four batches of 200 scans gave baseline 4.463/4.475ms CPU per scan versus 3.960/3.979ms, with identical owner sets. At the unchanged four checks/s, this isolated difference is roughly 0.2 percentage points of a core under those conditions, far below the idle target. It was not adopted; the native input/route module is unchanged in this renderer stage.
