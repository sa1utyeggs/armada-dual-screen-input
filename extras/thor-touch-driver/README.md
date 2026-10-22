English · [简体中文](README.zh-CN.md)

<a id="thor-下屏驱动独立模块实验"></a>

# Standalone Thor lower-screen driver module (experimental)

2026-10-20. Optional driver research only for the AYN Thor lower FT5452, not a default dependency of the dual-screen application.
The application does not import, load or install this directory's code. Its desktop entry and autostart settings remain unchanged.

<a id="当前验证"></a>

## Validation so far

- Compiled for Armada `20261010.c3d178c` / Linux `7.2.6` / AArch64.
- The stripped module is 39,648 bytes; `vermagic` is `7.2.6 SMP preempt mod_unload aarch64`.
- All 69 undefined imports were checked against running-kernel exports and corresponding source declarations. MODPOST and final linking passed.
- 18 tool/symbol checks passed, covering version refusal, lower-only operations, rollback after load/probe/input failures, update ordering and interrupted trials.
- After matching `status` and `plan`, device tests loaded the module, rebound only the lower screen and recreated its input device. The upper screen retained its original driver/input device.
- The first two trials stopped because the panel was invisible; Ctrl+C restored the stock driver and unloaded the module both times. These do not count as touch acceptance. After closing LocalSend on the lower screen, the user confirmed the panel was visible.
- The third trial completed 90 seconds. The user reported immediate return to blue and normal dragging: with the first finger held, lifting the second released positioning touch. Read-only contact records transitioned between two, one and zero contacts, ending with repeated zero contacts and `BTN_TOUCH=false`.
- At the 90-second deadline, the tool exited normally; both screens were checked as `edt_ft5x06`, and the candidate module was unloaded. Kernel/boot files remained unchanged, the panel stayed manually launched, and the root-managed experiment package/state remained.
- **This was a short test. Simultaneous two-finger begin, long sessions, suspend/resume and other system builds have not received dedicated validation.** It does not establish a fix for all touch problems.
- The user subsequently authorized a longer trial. The same candidate was enabled with `apply` and the panel reopened. Only the lower driver changed; the upper retained its original driver/input device. This trial has no 90-second deadline: manual `revert` or reboot restores the stock driver. No boot autoload was installed; long-session feedback is pending.

<a id="方法"></a>

## Method

Build an independently named `armada_thor_ft5452` module from Linux 7.2.6, Armada's existing patches and the [DROP_UNUSED candidate](../../docs/patches/0030-input-edt-ft5x06-thor-bottom-drop-unused.patch).
Retain only FT5452 OF / I2C matches. Probe additionally requires:

- Machine compatible `ayn,thor`;
- Controller compatible `focaltech,ft5452`, I2C address `0x38`;
- DT label `bottom_touchscreen`.

Preserve Armada's input names, read path, IRQ, power/PM logic and the candidate's complete-frame synchronization.
Do not replace DT, the upper driver or boot images. Attribution and provenance remain in source and `source.json`; see [LICENSE](LICENSE).

At runtime, register the new driver before unbinding the lower stock driver, then bind the same physical lower device to the new driver. The upper screen always stays with the original driver.
The tool selects a unique DT-matched target; `/dev/input/event5` and `1-0038` are not universal fixed addresses.
Rebinding recreates the lower input device. Whether current Gamescope/KWin picks it up correctly requires a real test.

<a id="包与兼容性"></a>

## Packages and compatibility

A candidate contains `manifest.json`, `armada_thor_ft5452.ko`, `touchfix.py`, licenses and module source/build records.
Only explicit operations copy the module/manifest into root-managed `/var/lib/armada-touch-fix/packages/<SHA256>/`; old packages remain.
The tool does not download code. Trusted release downloads and a graphical update interface are not implemented.

Each enable checks architecture, kernel release, running-config SHA-256, `/sys/kernel/notes` SHA-256, module name, vermagic and file checksums.
Other builds named `7.2.6` are therefore refused too. Continue using official system updates; on mismatch, keep the stock driver and wait for a matching package.
This provides no cross-kernel ABI guarantee and uses no forced loading, version bypass or signature bypass.

The current package supports only these fingerprints:

```text
kernel notes: 868b1eab0643a777197361333300dea114aabf6ae65549c4750b11e8a0f18775
kernel config: 3cae56750274cbd5b90a788335389dfbd38ad9fcb526505593ee878dc208a04f
```

<a id="操作入口"></a>

## Commands

From the candidate directory, inspect status and the read-only plan without sudo:

```bash
python3 -B touchfix.py status
python3 -B touchfix.py plan .
```

For the initial foreground, timed trial, first save and exit games and keep the device awake with SSH available:

```bash
sudo python3 -B touchfix.py trial . --experimental --seconds 90
```

While the tool is running normally, it restores the stock driver after 90 seconds; Ctrl+C, SIGTERM and SIGHUP also initiate rollback.
The trial holds the operation lock. Do not update/revert concurrently from another terminal, or close SSH instead of ending normally.
Stop this app first to release virtual input, then reopen it after switching. Official upper/lower services need no changes.

After real acceptance, explicitly enable until reboot, or update to a compatible package through the same entry point:

```bash
sudo python3 -B touchfix.py apply . --experimental
sudo python3 -B touchfix.py revert --experimental
```

An update returns the lower screen to stock and unloads the old module before loading the new one. Ordinary load, probe or input-creation failures attempt stock recovery.
`state.json` records pending before device operations; failures are never marked active. Failed recovery is recorded as `recovery-needed`.
These are userspace recovery mechanisms: **they cannot roll back a hung or panicking kernel**; manual reboot is then necessary.

No boot-loading rules, udev rules, systemd services or sudoers rules are installed. Kernel / DTB / initramfs / ABL / `KERNEL` remain unchanged.
A normal reboot uses the original boot kernel and stock driver. An external module still runs in kernel address space; device matching cannot isolate a kernel crash.
Loading may also leave an out-of-tree taint until reboot. Do not run an initial trial with an unsaved game.

<a id="离线构建与符号来源"></a>

## Offline build and symbol provenance

Use matching ARM64 GCC 16.2.1 and the device config. Unpack verified Linux 7.2.6 in a separate workspace; apply Armada's 192 patches plus this candidate, 193 total.
`build-offline.sh` runs only `modules_prepare` and this external-module build. It neither resumes the stopped whole-kernel build nor installs artifacts.
Prepare these read-only inputs and separate output paths; corresponding environment variables can redirect them:

| Path | Contents |
| --- | --- |
| `/kernel-cache` | Verified `linux-7.2.6.tar.xz` |
| `/kernel-recipe` | Armada c3d178c kernel recipe plus the candidate series |
| `/module-source` | This directory |
| `/module-work` | Separate build workspace |
| `/output` | `running.config`, read-only collected `host-exports.json`, and artifacts |

The official package has no kernel-devel or complete `Module.symvers`. With this kernel's `CONFIG_MODVERSIONS=n`, `export_subset.py` checks every import against running-kernel `__ksymtab` names and exact-source EXPORT_SYMBOL / GPL / namespace declarations, producing a **required-symbol-only subset**.
Macro-generated `_dev_err` / `_dev_warn` exports are checked against both macro bodies and calls. The module's own `__this_module` is generated by MODPOST and is not treated as a kernel export.
Missing/conflicting provenance or unparseable namespace macros fail the build. No fabricated CRCs, ignored unknown symbols or `KBUILD_MODPOST_WARN` are used.
If MODVERSIONS is enabled later, use a matching kernel's official build export table; the subset method refuses to work.

Module BTF was skipped because a complete `vmlinux` was unavailable; the builder records that skip. Compilation and symbol-name checks cannot replace actual loading and ABI validation.
The module source includes the matching constraints; provenance checks are in `source.json` and the original patch is in project docs. The running kernel is unchanged.

Development checks (no real module commands or sysfs writes):

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s extras/thor-touch-driver -p 'test_*.py' -v
```

References: [Linux external modules](https://docs.kernel.org/kbuild/modules.html),
[driver binding](https://docs.kernel.org/driver-api/driver-model/binding.html), [Armada Issue #757](https://github.com/armada-os/armada/issues/757).
