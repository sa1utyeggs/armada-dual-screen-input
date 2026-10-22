English · [简体中文](zh-CN/thor-ft5452-contact-lifecycle.md)

<a id="thor-下屏漏落指--漏抬指内核修复候选"></a>

# Missed contact begin/end on the Thor lower screen: kernel candidate

2026-10-20. Status: the whole-kernel build was stopped before completion; no candidate kernel was installed or booted. A later standalone-module experiment passed a 90-second physical-touch test and automatic rollback, followed by an authorized extended trial. These are separate results, and neither establishes long-session or suspend/resume reliability.
This is device-specific system research, outside the application's general installer.
[ArmadaOS Issue #757](https://github.com/armada-os/armada/issues/757) contains the environment, aggregate diagnostics, reproduction steps, references and candidate diff. No PR presents it as a validated fix.

<a id="现象及已验证范围"></a>

## Symptoms and established scope

The user reported occasional missed second-finger presses and an orange marker after lifting the finger. After the coordinate guard was installed, the user confirmed that jumps stopped and dragging worked, but these two contact-lifecycle problems remained.
Passing the coordinate-guard test therefore does not establish stable positioning touch overall, and missing events should not be described as insufficient sensitivity.

Earlier read-only MT-slot and BTN_TOUCH queries still reported one contact and `BTN_TOUCH=true` after the user confirmed all fingers were lifted.
Records around GTK dispatch showed that received BEGIN / END events reached the application, while some physical actions produced no event before dispatch. The stale contact existed before application processing.
A read-only snapshot on 2026-10-20 returned zero contacts normally, confirming intermittency.

Environment: Armada `20261010.c3d178c`, Linux `7.2.6`, root DT compatible `ayn,thor`, lower controller `focaltech,ft5452`, builtin `edt_ft5x06` driver, and lower-screen `no-regmap-bulk-read` enabled.
Changing gesture delays or sensitivity, or guessing release from inactivity, is inappropriate: a valid long press can have no motion events.

<a id="找到的对应修复"></a>

## Corresponding upstream fix

The [SteamOS ARM Port release notes](https://github.com/hashtagbasit/SteamOS-ARM-Port/releases) mention a Thor stale-touch fix.
Its [driver patch](https://github.com/hashtagbasit/SteamOS-ARM-Port/blob/e54dac93afccf76e5fefe998399b6c1b1a23f3a1/external-and-mods/kernel-sm8550/patches/0030-input-edt-ft5x06-thor-release-contacts-a-frame-leaves-out.patch) explains that FT5452 sometimes omits UP, while the old driver depends on explicit UP events to clear slots. Each controller frame contains all active contacts, so `INPUT_MT_DROP_UNUSED` plus `input_mt_sync_frame()` clears old slots missing from the frame.
This closely matches local observations, but another distribution's fix claim cannot replace boot and touch validation on Armada.

Compared with earlier suspicions about byte-at-a-time reads, the patch directly addresses contacts left indefinitely after a missing UP.
It does not change `no-regmap-bulk-read`. Disabling that property is no longer the preferred initial experiment, and its read path has not been established as the cause.

<a id="针对-armada-的整内核候选早期阶段"></a>

## Whole-kernel candidate for Armada (early stage)

The [candidate patch](patches/0030-input-edt-ft5x06-thor-bottom-drop-unused.patch) retains attribution, was regenerated against Armada's source, and narrows the condition to both `ayn,thor` and `focaltech,ft5452`.
Unlike the reference's whole-device match, it affects only the identified lower controller, leaving the upper FT5426 and other devices unchanged.
It does not change reads, IRQs, coordinates, DT, input permissions, Steam or application configuration.

Preparation and checks:

1. Read the Linux `v7.2.6` driver source.
2. In a temporary local directory, apply Armada `c3d178c`'s two existing ft5x06 patches, for input names and no-regmap-bulk-read, in `patches/series` order.
3. Run `patch --dry-run -p1 -F0` against the candidate: passed without fuzzy matching.
4. In a separate ARM64 build container on the Mac, all 192 existing patches plus the candidate—193 total—applied with zero failures. The generated kernel configuration matched the device, and the built Thor DTB was byte-identical to the installed version.
5. Stop the main kernel compilation at the user's request before completion. This route produced no completed deployable kernel or module package, boot test, touch test or recovery-media test.

These checks establish source applicability and consistent build inputs, not successful full compilation, independently proven complete controller frames, or a fix for every missing DOWN. Independent DOWN loss, incomplete frames or absent subsequent IRQs still require diagnosis.

<a id="整内核路线的后续边界"></a>

## Boundaries for further whole-kernel work

The driver is builtin; replacing Python code cannot fix it. This route prepared an Armada-compatible test kernel, requiring saved games, an original-kernel rollback path and reboot validation.
It did not change the device's kernel, DT, boot entries or services, or deploy another distribution's kernel.
The user asked to stop kernel changes. Resuming requires explicit renewed authorization and prior verification of spare Armada boot media and an independent recovery path. Merging these documents does not authorize continued compilation or installation.
System experiments need a separate scope decision; source matching is insufficient justification to replace boot files.

Validate separately: hold one finger while repeatedly pressing/lifting the second; simultaneous two-finger begin/end; long holds and drags; zero kernel slots after all fingers lift; upper physical touch and controller coexistence.
If ineffective, preserve evidence and roll back the test kernel instead of hiding missing events through looser app rules or timed releases.

<a id="后续独立模块路线"></a>

## Later standalone-module experiment

After the user requested an update-friendly alternative on 2026-10-20, a separate optional [Thor lower-screen module experiment](../extras/thor-touch-driver/README.md) was added.
An independently named driver, matched only to the lower controller, takes over the physical device without replacing the boot kernel. Offline compilation, 69 imported-symbol checks and the device's read-only plan check completed; 18 tool checks passed.
After the user saved and exited the game, three runtime trials took place: the first two were interrupted because the panel was not visible and both restored the stock driver; the third completed 90 seconds with a visible panel.
In the third trial, the user confirmed that lifting the second finger while holding the first immediately returned the marker to blue and dragging worked. Read-only aggregates included 2 → 1 → 0 contacts, then repeated zero contacts and `BTN_TOUCH=false`.
The deadline triggered a clean rollback: the lower screen returned to `edt_ft5x06`, the candidate unloaded, and the upper driver/input device remained unchanged. No boot files or boot-loading rules changed.
This supports a fix for the second-finger release residue in that trial; simultaneous begin, long sessions and suspend/resume still require dedicated validation.
The user then explicitly authorized continued use. The same module was enabled with `apply` until manual rollback or reboot, and the panel reopened. Only the lower driver changed; the original upper input device remained, with no boot autoload. Long-session feedback remains pending.
The earlier whole-kernel build stayed stopped; the module used a separate workspace.

The driver changes, 90-second test, rollback, extended-trial status and limits were added to [Issue #757's follow-up comment](https://github.com/armada-os/armada/issues/757#issuecomment-6284200266) on 2026-10-20.
The comment also separates application marker-recovery/wait improvements and intermittent timeline reconnections from driver observations; unconfirmed app problems were not attributed to the driver. The issue remains open in this historical record.

## 2026-10-22 follow-up and Settings integration

After a reboot the original `edt_ft5x06` driver was active again; the experimental module had no autoload rule. The user reproduced a stuck orange marker by holding the first finger and quickly tapping twice with the second. After all fingers lifted, read-only snapshots still reported one physical slot and `BTN_TOUCH=true`, including 31 samples across 15 seconds.

Isolated application replay completed 20,000 double-tap cycles (40,000 confirming taps) with complete events and no retained native press. Deliberately omitting the first confirming END reproduced orange remaining after the second tap until the aim finger lifted. This models the failure but does not locate every real lost event. The CPU renderer candidate was not installed when the user reported the failure.

The same fingerprint-matched module was reapplied with explicit authorization, with the app and configuration unchanged. The lower driver changed to `armada_thor_ft5452`, stale physical slots cleared, the upper driver/input stayed unchanged, and the user confirmed recovery. The CPU candidate was installed later while keeping that module active. This further supports the driver cleanup fix for this observed problem; it does not establish universal DOWN delivery or long-session/suspend reliability.

The current source adds **Settings → Experimental** through a separately installed root-owned component. Normal app installation remains unprivileged and excludes the kernel experiment. Status is read-only and requested only on opening/refreshing the page; enable/restore require confirmation and administrator authentication, preserve preferences and operate only on the lower screen. No boot loading is added. See [component preparation, controls and rollback](../extras/thor-touch-driver/README.md#settings-controls).
