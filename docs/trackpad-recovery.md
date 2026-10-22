English · [简体中文](zh-CN/trackpad-recovery.md)

<a id="双指滚动后的触点恢复与指针隔离"></a>

# Contact recovery and pointer isolation after two-finger scrolling

Status: the second fix was installed on Thor on 2026-10-19. In this round's short test, the user confirmed normal single-finger movement before and after two-finger scrolling.

<a id="问题与证据"></a>

## Problem and evidence

The user reported upward pointer movement after continuous two-finger scrolling. Jumps could occur at scroll start, when stopping, moving one finger or lifting everything. Later, panel buttons remained clickable while the pointer stopped moving.

An in-memory reproduction confirmed one drift path: as fingers lifted in succession, the remaining finger's tail motion became single-finger pointer movement. Forty upward-scroll cycles produced cumulative pointer Y=-520 in the old version. The same input produced zero pointer movement and retained 80 scroll outputs with multi-finger isolation. This does not explain every reported instantaneous jump.

In one device snapshot, both app and engine retained one contact, with a group maximum of 2 fingers. The contact had not updated for about 24 seconds, but keepalive still refreshed engine liveness. Read-only kernel metadata in the same round showed one active lower-screen slot and BTN_TOUCH. This establishes that new-group protection alone did not cover the observed state. The snapshot cannot prove the user's fingers had lifted or establish a driver fault. The panel restarted before later capture, so an empty state after cleanup cannot be claimed as recovery of the original failure.

<a id="修复方式"></a>

## Fix

1. GTK Wayland supplies a pointer-emulating marker when a group truly begins from no contacts. A real TOUCH_BEGIN with that marker cancels old logical contacts before starting the new group. Ordinary release does not synthesize a click. This protects against missed END/CANCEL in the app.
2. Once a group has contained multiple fingers, its remaining single finger stays part of that group until all lift. Tail motion no longer sends pointer movement or inertia. A normal two-finger tap still right-clicks. Lift everything and start a fresh single-finger group to move after scrolling.
3. A conservative fallback applies only on Touchpad/Keys+Pad: the old group was multi-finger, only one touchpad contact remains, no key/mouse button/drag is held, and the entire group's real events have been quiet for at least 3 seconds. A different new touchpad sequence may cancel that old logical group. Keepalive does not count as real activity; any real UPDATE/release restarts the timer. It is not periodic cleanup and does not time out ordinary single-finger holds or keyboard keys.
4. Fallback uses a distinct `cancel_previous` flag rather than pretending GTK confirmed all fingers lifted. Tap/long-press is disabled for the recovered group to prevent false left/right clicks if a genuinely stationary scroll anchor was regrouped. Movement/scrolling remain available; normal clicking returns with the next group.
5. Physical sequences used to gate automatic native touch are cleared only by trusted GTK markers or real END/CANCEL. The heuristic does not claim physical fingers are gone and cannot prematurely enable position touch with fingers still down.

A genuinely stationary anchor for over 3 seconds is indistinguishable from a residual contact. Keeping one finger still after scrolling and later adding another may regroup input; that recovered group will not click. Continuous UPDATE or reuse of the same old sequence prevents the fallback, requiring further live diagnosis. This is app-level recovery, not a driver fix.

GTK marker source: [official Wayland backend](https://github.com/GNOME/gtk/blob/gtk-3-24/gdk/wayland/gdkdevice-wayland.c#L2317). Separate in-memory output capture confirmed vertical scrolling sends only REL_WHEEL/REL_WHEEL_HI_RES, not pointer REL_Y.

<a id="验证与安装原则"></a>

## Validation and installation principles

Automated checks use fake events/memory output, creating no real input device. They cover continuous scrolling, lift order, tail motion, new single-finger movement, missing END, real-event quiet timing, repeated stationary-anchor scrolling, false-click protection after a 3-second pause, long holds and held keys.

At that time installation replaced only `panel_app.py`, `toolkit_touch.py` and `vendor/ratatoskr/bin/engine.py`. `panel_app.py` was adapted from the installed version, retaining the then-existing mirroring feature and other recent UI. Mirroring was separately removed on 2026-10-20. Files were backed up/hash-checked with automatic failure recovery. Configuration, scroll sensitivity, keyboard integration, shortcuts, autostart and other app files were preserved.

All 104 related checks passed in a temporary device copy. Mac collected 161 checks: 137 passed and 24 Linux integration checks were skipped. Installation verification confirmed unchanged hashes for other app files, configuration and unit; the service was running with autostart still disabled. Thor backup: `~/.local/state/thor-panel-scroll-drift-20261019-203529/`. Local receipt: workspace `outputs/thor-scroll-drift-20261019/verification.json`.

<a id="用户复测"></a>

## User retest

On 2026-10-19, after the second fix, the user explicitly reported that single-finger movement and movement after scrolling both worked. This short test passed; it does not establish no recurrence in every scene or long session.

Lift all fingers, move with one, then repeat two-finger scroll → all up → single-finger movement. Watch for upward drift or a stuck pointer. If stuck, leave the lower screen for about 3 seconds, then begin a fresh single-finger press/move to check recovery. The recovered group's first tap will not click; the next normal tap can.

Passing simulated checks does not establish resolution of the intermittent hardware experience. Any remaining scroll-start jump needs separate pointer/glide-source tracing rather than being attributed to multi-finger tail isolation without evidence.
