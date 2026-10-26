English · [简体中文](zh-CN/installation.md)

<a id="安装升级与卸载"></a>

# Installation, upgrades and removal

See [Releases](https://github.com/sa1utyeggs/armada-dual-screen-input/releases/latest) for the current stable version. Device validation refers to AYN Thor / Armada `20261010.c3d178c` / Linux 7.2.6 / Steam Game Mode. See [compatibility](compatibility.md) for other devices and systems. Run the installer as your regular user, **without sudo**.

<a id="click-install"></a>

## Click installation (recommended)

The homepage provides one self-contained `Install-Armada-Dual-Screen-Input.desktop` file from the repository. Save that file directly; no extraction or terminal is needed. It installs the latest stable app bundle, even before a new Release includes the launcher as an attachment. Older published tags and assets are unchanged.

1. In **Armada Desktop Mode**, right-click (or press and hold) the [installer link](https://github.com/sa1utyeggs/armada-dual-screen-input/raw/refs/heads/main/Install-Armada-Dual-Screen-Input.desktop), choose **Save Link As** and save `Install-Armada-Dual-Screen-Input.desktop`. GitHub Raw may display the file as text when opened normally; save it with this exact filename in that case.
2. Open Downloads in **Dolphin**. If Firefox saved `Install-Armada-Dual-Screen-Input.desktop.download`, rename it to `Install-Armada-Dual-Screen-Input.desktop` by removing only the final `.download`. Open the `.desktop` file and confirm the system's trust/run prompt. If execution is disabled, open Properties → Permissions, allow execution, and open it again. Browser download panels may only show the file; use the file manager.
3. The window checks the supported device and displays the latest **stable Release** version. Select **Install**. Downloads, checksum verification, extraction and installation are automatic; no terminal commands are needed. Select **简体中文** for Chinese; the window defaults to English independently of keyboard input and app preferences.
4. Wait for the success message, close the installer and open **Virtual Keyboard & Mouse / 虚拟键鼠** from the desktop or application menu. Enter Steam Game Mode to use the panel.

The launcher embeds the installer helper; it does not fetch and execute a script from `main`. It follows GitHub's public `releases/latest` redirect, reads that tag's HTTPS `SHA256SUMS` and checks bounded package headers. This path makes no REST API requests, so it does not consume the shared anonymous API quota or need a GitHub token. Before execution, the downloaded checksum file must still match the reviewed bytes, and the package must match its SHA-256, safe paths, manifest and selected version. The selected tag stays fixed even if another stable release appears during installation. It then invokes the existing package installer in offline mode. Base dependencies match source installation; a browser login does not authenticate its downloads. Missing files, changed checksums and web download failures stop installation, with no automatic retries or development-build fallback. **Check again** rechecks the device and release. Downloads and the embedded helper are temporary and are removed on normal exit. Keep the window open while it is busy.

The window uses logical monitor work areas and leaves room for decorations. On the tested Thor desktop, the lower screen is only `443×386` at its current scaling; the installer starts at `419×322`. Content scrolls while the language selector, Install and Close buttons stay visible. This is separate from the app's Game Mode panel geometry.

Firefox's protective `.download` suffix can remain after a complete download; it differs from an unfinished `.part` file. New Releases also include the same launcher and `INSTALLER-SHA256SUMS`. The app's `SHA256SUMS` remains single-entry for older in-app updaters. Checksums verify integrity, not publisher identity; download only from this project. If the window cannot open, a KDE error dialog is attempted; check system Python 3, PyGObject, GTK3 and the desktop session, or use the offline instructions below.

Fresh installation does not open the app or enable autostart; upgrades preserve preferences and the existing autostart choice. Only this app's per-user installer is invoked. No kernel driver is installed or enabled. On 2026-10-26 the user completed installation through the revised window on Thor; package verification, unchanged preferences and restoration of the original candidate passed. The initial browser download used a temporary LAN attachment URL, and the revised helpers were transferred for testing. A clean first install and the unpublished GitHub attachment button remain separate checks. [Device evidence and limits](history.md#click-installer-20261026)

<a id="一键在线安装推荐"></a>
<a id="one-command-online-installation-recommended"></a>

## One-command online installation (development build)

Run in an Armada desktop terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/sa1utyeggs/armada-dual-screen-input/main/get.sh | bash
```

You can also download the repository's root `get.sh` and run `bash get.sh`. It resolves the current `main` commit, downloads that commit's source archive, validates source paths and the installer, then runs the existing installation process. Git, SSH keys, manual directory creation and extraction are unnecessary. Temporary downloads are cleaned up automatically. Base dependencies match source installation below; the pinned private gtk-layer-shell dependency is still downloaded from official Fedora and SHA-256 verified. The process runs as a regular user, **without sudo**, and enables neither autostart nor an experimental driver.

After downloading the script, optionally select a tag/commit or inspect the plan:

```bash
bash get.sh --ref v0.1.2
bash get.sh --dry-run
```

Replace the tag example with an existing repository tag. Online `--dry-run` downloads into a temporary directory but performs no installation or service changes; local `install.sh --dry-run` does not even download. Rerun the same online command to upgrade while preserving configuration and installer ownership rules.

Anonymous use requires a public repository with `get.sh` on `main`. For a private fork, an existing read-only `GH_TOKEN` / `GITHUB_TOKEN` may be provided in the environment. The downloader neither writes it to disk nor passes it to the app installer; authentication headers are not forwarded across hosts. Obtaining the private `get.sh` itself still requires existing GitHub access. The script does not bypass repository permissions. Download/source-validation failures stop the process without weakening system permission restrictions.

<a id="使用离线发布包"></a>

## Offline release bundle

Open [GitHub Releases](https://github.com/sa1utyeggs/armada-dual-screen-input/releases), choose a version and download both **Assets**:

- `armada-dual-screen-input-<VERSION>-aarch64.tar.gz`: ARM64 installer bundle including its private runtime.
- `SHA256SUMS`: the checksum file from the same release.

GitHub's generated **Source code (zip)** / **Source code (tar.gz)** omit the packaged runtime and are not substitutes. Download both assets on another computer and transfer them with LocalSend, USB or another method; installation requires no network.

For the example `armada-dual-screen-input-0.1.2-aarch64.tar.gz` and its `SHA256SUMS`, run in an Armada desktop terminal:

```bash
sha256sum -c SHA256SUMS
tar -xzf armada-dual-screen-input-0.1.2-aarch64.tar.gz
cd armada-dual-screen-input-0.1.2-aarch64
bash install.sh
```

The bundle includes app sources, the Ratatoskr snapshot, private gtk-layer-shell runtime and original licenses; these need no installation-time download. Checksums establish integrity, not a trusted origin. Use maintainer-provided packages and never mix a package with another version's checksum file.

Installation adds **Virtual Keyboard & Mouse / 虚拟键鼠** to the desktop and application menu; older releases use the Chinese name. It neither opens automatically nor enables login autostart. The shortcut waits for the official Steam Game Mode lower session. No panel in Desktop Mode is currently expected.

After install, upgrade, rollback or removal, the installer attempts to refresh user icon/application-menu caches and notify this user's running KDE sessions, including the separate Game Mode lower-screen session. Missing tools, timeouts or failures are returned as `desktop_refresh.warnings` without undoing a successful operation. The mobile home screen may retain an already drawn image until the next exit/re-entry to Game Mode. The installer restarts neither the official lower session, KWin nor Steam for icon refresh, and preserves home favorites and icon positions.

<a id="从源码安装"></a>

## Install from source

With repository access, clone and run:

```bash
git clone https://github.com/sa1utyeggs/armada-dual-screen-input.git
cd armada-dual-screen-input
bash install.sh
```

Source installation downloads an official Fedora gtk-layer-shell RPM pinned by **version and SHA-256**, extracting only required libraries, typelib and licenses. It runs no RPM scripts and writes nothing to `/usr`. A private repository needs GitHub access; an offline bundle can be given to someone without a repository account.

Without network access, prepare the pinned RPM first:

```bash
bash install.sh --offline --runtime-rpm /路径/gtk-layer-shell-0.10.0-1.fc44.aarch64.rpm
```

Source extraction needs `rpm2cpio` + `cpio`, or libarchive tar with RPM support. Offline bundles already contain the extracted runtime and need neither tool.

<a id="安装前检查"></a>

## Pre-install checks

```bash
bash install.sh --dry-run
python3 -B tools/manage.py doctor
```

`--dry-run` prints a plan without downloading, writing files or changing services. `doctor` checks dependencies/permissions without creating input devices. Before source runtime preparation it may report missing GtkLayerShell; full installation checks again after preparing the library in a bundle/temporary directory.

The host still needs Python 3, PyGObject, Cairo, GTK3, PangoCairo, libevdev, libxcb, websocket-client and normal-user read/write access to `/dev/uinput`. The installer refuses missing base dependencies. It does not work around them through a transient `dnf` overlay, input-permission changes, root services or takeover of the official lower session. Use Armada's normal desktop user session with a working `systemctl --user`. Update/repair the official system image for missing dependencies, or provide `doctor` output to the maintainer. The UI uses system Chinese fonts; if squares appear, inspect Noto Sans CJK rather than packaging a personal font cache.

<a id="管理"></a>

## Management

If `~/.local/bin` is on PATH you may use the command name directly; otherwise use these full paths:

```bash
~/.local/bin/armada-dual-screen-input start
~/.local/bin/armada-dual-screen-input stop
~/.local/bin/armada-dual-screen-input status
~/.local/bin/armada-dual-screen-input doctor
```

The upper-right Close button releases input and stops this app. Hide collapses the panel so it can be expanded again; it does not exit.

<a id="升级与回退"></a>

## Upgrade and rollback

Run `bash install.sh` again in the new source/bundle. The installer verifies the complete bundle and dependencies, copies it to a separate version directory, switches `current` and updates user entry points. Configuration and logs live outside releases and are not overwritten. An active panel restarts; an inactive panel stays stopped. Existing autostart choice is preserved; **fresh installs do not enable autostart**.

Previous installer-managed versions are retained:

```bash
~/.local/bin/armada-dual-screen-input rollback
```

Rollback restores the app version and managed icon, entry and service templates, not personal configuration or the kernel. Locally modified managed files are not overwritten. A first migration from the old flat manual layout has no previous release for this rollback command: old source files remain in the original directory, and entry-file backups are under `~/.local/share/thor-panel/backups/`. Upgrade write/service-reload failures attempt to restore entries and version links. If the user service itself is unavailable, inspect logs/backups instead of repeatedly using sudo.

<a id="卸载"></a>

## Uninstall

Open **Settings → General → Uninstall app**: select Uninstall app, review what is removed/kept, then select Confirm uninstall on the right. Cancel or another settings page clears an unsubmitted confirmation. Unsaved settings or an active update block removal.

A separate regular-user task, `thor-panel-uninstall`, needs no sudo and continues after the panel's own service stops. Success closes the panel. On failure, a running panel displays an error and a desktop notification is attempted. Without a notification service, the durable record remains at `~/.local/state/thor-panel/uninstall.json` (respecting `XDG_STATE_HOME`), including phase, message and leftovers. Source runs and old manual installs cannot be removed by this button; inspect/use the command below.

The action reuses the existing installer. It removes only this app and keeps personal configuration, logs, backups and local modifications. It does not manage Steam, Gamescope, the official lower-screen service or games.

```bash
~/.local/bin/armada-dual-screen-input uninstall
```

Alternatively run `bash uninstall.sh` from the source/bundle directory. Removal stops/deletes this app's user service, managed shortcuts, icon, command and unmodified releases. Modified or unowned files are not forcibly deleted; the result lists leftovers. A modified service file needs manual inspection first. Personal configuration under `~/.config/thor-panel/`, logs under `~/.local/state/thor-panel/`, entry backups and old manual-install files remain.

On 2026-10-22 the development branch passed 580 Python checks on Thor and 15 JavaScript checks on Mac. Removal tests used temporary user directories and fake services, covering confirmation/cancel, duplicate taps, update exclusion, retry, recording results after deleting release files, and preservation of local modifications. Actual Thor removal and interactive desktop notification acceptance have not been performed.

<a id="路径与更新兼容"></a>

## Paths and system-update compatibility

| Item | Default path |
| --- | --- |
| Releases | `~/.local/share/thor-panel/releases/<VERSION>-<ID>/` |
| Current/previous | `~/.local/share/thor-panel/current`, `previous` |
| Installation state | `~/.local/share/thor-panel/install-state.json` |
| User service | `~/.config/systemd/user/thor-panel.service` |
| App/desktop entries | `~/.local/share/applications/thor-panel.desktop`, desktop `虚拟键鼠.desktop` |
| Configuration/logs | `~/.config/thor-panel/`, `~/.local/state/thor-panel/` |

XDG paths follow the current user's environment. Existing `thor-panel` service/configuration identities are retained to avoid duplicate panels. Files live in persistent user directories, so replacement of `/usr` by an Armada image update does not remove them. Future GTK, Steam or Gamescope API compatibility is not guaranteed. The installer includes/enables no experimental touch driver; kernel matching and rollback are documented separately in upstream Issue #757.
