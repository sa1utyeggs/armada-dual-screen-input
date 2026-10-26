[English](../installation.md) · 简体中文

# 安装、升级与卸载

当前正式版本见 [Releases](https://github.com/sa1utyeggs/armada-dual-screen-input/releases/latest)，实机验证以 AYN Thor / Armada `20261010.c3d178c` / Linux 7.2.6 / Steam Game Mode 为准。
其他机型和系统版本见 [兼容范围](compatibility.md)。安装器以普通用户运行，**不要加 sudo**。

<a id="click-install"></a>

## 点击安装（推荐）

主页从仓库提供单个自包含的 `Install-Armada-Dual-Screen-Input.desktop` 文件，直接保存即可，无需解压或终端。即使新 Release 尚未附带该入口，也能安装最新稳定版应用包。已有发布标签和附件保持原样。

1. 在 **Armada 桌面模式**长按或右键[安装器链接](https://github.com/sa1utyeggs/armada-dual-screen-input/raw/refs/heads/main/Install-Armada-Dual-Screen-Input.desktop)，选择 **链接另存为**，保存 `Install-Armada-Dual-Screen-Input.desktop`。正常打开 GitHub Raw 链接可能显示文本，此时按准确文件名另存为即可。
2. 在 **Dolphin 文件管理器**打开下载目录。如果 Firefox 保存为 `Install-Armada-Dual-Screen-Input.desktop.download`，重命名为 `Install-Armada-Dual-Screen-Input.desktop`，只去掉最后的 `.download`。打开 `.desktop` 文件，按系统提示信任并允许运行。如果不允许执行，请在“属性 → 权限”勾选允许执行，再次打开。浏览器下载面板可能只显示文件，请使用文件管理器。
3. 窗口检查支持的设备并展示最新**稳定版 Release** 的版本。点击 **Install / 安装**，自动完成下载、校验、解压和安装，无需终端命令。窗口默认英文，可选择 **简体中文**；与键盘输入和应用语言配置独立。
4. 等待成功提示，关闭安装器，从桌面或应用菜单打开 **Virtual Keyboard & Mouse / 虚拟键鼠**，进入 Steam Game Mode 使用。

入口文件自带安装助手，不会从 `main` 下载并直接执行脚本。它跟随 GitHub 公开的 `releases/latest` 重定向，读取该标签的 HTTPS `SHA256SUMS` 并检查有大小上限的安装包响应头。这条路径不请求 REST API，因此不消耗共享的匿名 API 配额，也不需要 GitHub token。执行前，重新下载的校验文件必须与确认版本时的内容一致，安装包必须通过 SHA-256、安全路径、清单和所选版本检查。安装期间即使出现新的稳定版，也保持已确认标签，再以离线模式调用包内现有安装器。基础系统依赖与源码安装相同；浏览器登录不会为下载器提供认证。附件缺失、校验变化和网页下载失败都会停止安装，不自动重试，也不回退到开发构建。“重新检查”会重新检查设备与版本。下载文件和内嵌助手在正常退出时清理；忙碌期间请保持窗口打开。

窗口按显示器逻辑工作区留出装饰边界。已测 Thor 桌面的下屏在当前缩放下只有 `443×386`，安装器以 `419×322` 打开；内容可滚动，语言选择、安装与关闭按钮保持可见。这与应用的游戏模式面板尺寸独立。

Firefox 的保护性 `.download` 后缀在完整下载后仍可能保留，与未完成下载的 `.part` 不同。新 Release 也附带同一个入口和 `INSTALLER-SHA256SUMS`。应用的 `SHA256SUMS` 继续只列安装包，兼容旧版应用内更新。校验和只验证完整性，不代替发布者身份验证；请只从本项目下载。无法打开窗口时会尝试 KDE 错误弹窗；请检查系统 Python 3、PyGObject、GTK3 和桌面会话，或使用下面的离线安装方式。

全新安装不自动打开应用、不启用自启动；升级保留个人配置和已有自启动选择。入口仅调用本应用的用户级安装器，不安装或启用内核驱动。2026-10-26 用户已在 Thor 修正版窗口中完成安装，安装包校验、保留偏好和恢复原候选版均通过。初次浏览器下载使用临时局域网附件地址，修正版助手随后传入测试；干净用户下首次安装，以及尚未发布的 GitHub 附件按钮，仍需分别检查。[实机证据与边界](history.md#click-installer-20261026)

<a id="一键在线安装推荐"></a>

## 一键在线安装（开发构建）

在 Armada 桌面终端执行：

```bash
curl -fsSL https://raw.githubusercontent.com/sa1utyeggs/armada-dual-screen-input/main/get.sh | bash
```

也可以从 GitHub 下载项目根目录的 `get.sh`，然后执行 `bash get.sh`。
这一个脚本自动解析 `main` 当前提交，下载该提交的源码压缩包，检查源码路径和安装器，再执行现有安装流程。
不需要 Git、SSH 密钥、手动创建目录或解压；临时下载完成后会自动清理。
基础系统依赖与下面的源码安装相同，固定的 gtk-layer-shell 私有依赖仍从 Fedora 官方地址下载并校验 SHA-256。
整个过程以普通用户运行，**不要加 sudo**，不启用开机自启动，也不安装或加载实验驱动。

下载脚本后，可选用指定标签/提交，或只查看安装计划：

```bash
bash get.sh --ref v0.1.2
bash get.sh --dry-run
```

标签示例须替换成仓库中实际存在的标签。在线入口的 `--dry-run` 会下载到临时目录，但不安装、不修改服务；
本地 `install.sh --dry-run` 则连下载也不执行。在线升级时再次运行同一条命令，原配置与安装器管理规则保持不变。

匿名命令需要仓库和 `get.sh` 已公开且位于 `main`。
如果维护私有副本，可在环境中提供已有的只读 `GH_TOKEN` / `GITHUB_TOKEN`；下载器不会把它写入磁盘或传给应用安装进程，
跨主机重定向也不携带认证头。首次下载私有 `get.sh` 本身仍需已有的 GitHub 访问方式；该脚本不绕过仓库权限。
安装脚本下载失败或源码检查失败时会停止，不会尝试降低系统权限限制。

## 使用离线发布包

打开 [GitHub Releases](https://github.com/sa1utyeggs/armada-dual-screen-input/releases)，选择需要的版本，在 **Assets** 中下载：

- `armada-dual-screen-input-<版本>-aarch64.tar.gz`：带私有运行库的 ARM64 安装包。
- `SHA256SUMS`：同一 Release 的校验文件。

GitHub 自动生成的 **Source code (zip)** / **Source code (tar.gz)** 不包含打包后的运行库，不能当作上述离线安装包使用。
可以在另一台电脑下载这两个附件，再通过 LocalSend、USB 或其他方式传到掌机；安装时无需联网。

接收方拿到 `armada-dual-screen-input-0.1.2-aarch64.tar.gz` 和 `SHA256SUMS` 后，在 Armada 桌面终端执行：

```bash
sha256sum -c SHA256SUMS
tar -xzf armada-dual-screen-input-0.1.2-aarch64.tar.gz
cd armada-dual-screen-input-0.1.2-aarch64
bash install.sh
```

发布包自带本项目源码、Ratatoskr 快照、gtk-layer-shell 私有运行库和原许可证；安装期间无需下载这些内容。
校验和用于检查文件完整性，不代替可信下载来源。只使用项目维护者提供的包，勿混用不同版本的校验文件。

安装完成后，应用菜单和桌面出现 **虚拟键鼠**。默认不自动打开，也不启用登录自启动。
从桌面点击后，程序等待官方 Steam Game Mode 下屏会话就绪；Desktop Mode 不显示面板属于当前预期行为。

安装、升级、回退和卸载完成后，安装器会尝试刷新用户图标与应用菜单缓存，并向当前用户实际运行的 KDE 会话发送图标重载通知，
包括游戏模式下屏的独立会话。工具缺失、超时或刷新失败只作为 `desktop_refresh.warnings` 返回，不撤销已成功的操作。
移动主屏可能继续保留已经绘制的旧图像；这时下次退出并重新进入游戏模式会加载新图标。
安装器不会为刷新图标重启官方下屏、KWin 或 Steam，也不改变主屏收藏和图标位置。

## 从源码安装

有仓库访问权限时，克隆后执行：

```bash
git clone https://github.com/sa1utyeggs/armada-dual-screen-input.git
cd armada-dual-screen-input
bash install.sh
```

源码安装会从 Fedora 官方地址下载**固定版本、固定 SHA-256** 的 gtk-layer-shell RPM，只解出应用需要的库、typelib 和许可证，不执行 RPM 脚本、不写 `/usr`。
私有仓库需要先取得 GitHub 访问权限；本地离线发布包可直接交给其他人，不要求他们有仓库账号。

若没有网络，可事先准备指定 RPM，再运行：

```bash
bash install.sh --offline --runtime-rpm /路径/gtk-layer-shell-0.10.0-1.fc44.aarch64.rpm
```

源码安装解包需要 `rpm2cpio` 和 `cpio`，或支持 RPM 的 libarchive tar。离线发布包已经解包运行库，不需要这些工具。

## 安装前检查

```bash
bash install.sh --dry-run
python3 -B tools/manage.py doctor
```

`--dry-run` 只输出计划，不下载、不写文件、不修改服务。`doctor` 只检查依赖和权限，不创建输入设备。
源码尚未准备私有运行库时，doctor 可以报告 GtkLayerShell 缺失；完整安装阶段会在发布包/临时目录中准备该库后再次检查。

宿主仍需要 Python 3、PyGObject、Cairo、GTK3、PangoCairo、libevdev、libxcb 和 websocket-client，以及正常用户的 `/dev/uinput` 读写权限。
安装器会拒绝缺少这些基础依赖的环境；不会用临时 `dnf` overlay、修改系统输入权限、启动 root 服务或接管官方下屏服务来绕过。
请在 Armada 的普通桌面用户会话中运行，确保 `systemctl --user` 能连接。缺依赖时应更新/修复官方系统镜像，或向维护者提供 doctor 输出。
界面使用系统中文字体；如果出现方块，检查系统 Noto Sans CJK 字体，不要把个人字体缓存打进发布包。

## 管理

将 `~/.local/bin` 加入 PATH 的系统可直接使用下列命令；否则使用完整路径：

```bash
~/.local/bin/armada-dual-screen-input start
~/.local/bin/armada-dual-screen-input stop
~/.local/bin/armada-dual-screen-input status
~/.local/bin/armada-dual-screen-input doctor
```

右上角“关闭”按钮立即释放输入并停止本应用。收起后仍可展开，收起不等于退出。

## 升级与回退

在新版源码或发布包中再次运行 `bash install.sh`。
程序先验证整个发布包和依赖，再将版本复制到独立目录，切换 `current` 链接并更新用户入口。
配置和日志放在版本目录之外，不由安装器覆盖。升级前已在运行的面板会重启；原先未运行则保持停止。
安装器不更改已有的自启动选择；**全新安装不启用自启动**。

新安装器管理的旧版本会保留，可执行：

```bash
~/.local/bin/armada-dual-screen-input rollback
```

回退恢复应用版本及安装器管理的图标、入口和服务模板，不回退个人配置或内核；本地修改过的管理文件会拒绝覆盖。
首次从旧的平铺手工安装迁移时，没有可供上述命令切换的旧发布版本；
旧源文件仍留在原安装目录，入口文件的原内容备份在 `~/.local/share/thor-panel/backups/`。
升级的写入/服务重载失败会尝试恢复原入口和版本链接；如果用户服务本身不可用，应检查日志和备份，而不是重复运行 sudo。

## 卸载

可在 **Settings → General → Uninstall app**（设置 → 通用 → 卸载应用）中操作：先点“卸载应用”，核对删除/保留范围，再点右侧“确认卸载”。取消或切换设置页会撤销尚未提交的确认；有未保存设置或更新任务正在运行时禁止开始卸载。

卸载使用独立的普通用户任务 `thor-panel-uninstall`，不需要 sudo；它在面板自己的用户服务停止后继续完成清理。成功时面板关闭；失败时，若面板仍运行则显示错误，另尝试发送桌面通知。无通知服务时仍保留结果于 `~/.local/state/thor-panel/uninstall.json`（遵守 `XDG_STATE_HOME`），内含阶段、说明和遗留项。源码运行或旧手工安装不能通过此按钮删除，请使用下方命令核对处理。

此入口复用现有安装器，仅卸载本应用，保留个人配置、日志、备份及本地修改文件，不操作 Steam、Gamescope、官方下屏服务或游戏。

```bash
~/.local/bin/armada-dual-screen-input uninstall
```

也可以在源码/发布包目录执行 `bash uninstall.sh`。
卸载停止并移除本应用的用户服务、安装器管理的快捷方式、图标、启动命令和未被修改的发布版本。
被用户修改或不属于本应用的文件不会被强行删除，结果会列出遗留项；服务文件被改动时需先人工核对。
个人配置 `~/.config/thor-panel/`、日志 `~/.local/state/thor-panel/`、入口备份及旧手工安装文件保留。

2026-10-22 开发分支已通过 Thor 580 项 Python 检查及 Mac 15 项 JavaScript 检查；卸载测试使用临时用户目录和模拟服务，覆盖确认/取消、重复点击、更新互斥、任务失败重试、版本文件删除后继续记录结果及本地修改文件保留。尚未对 Thor 的真实安装执行卸载或桌面通知交互验收。

## 路径与更新兼容

| 内容 | 默认位置 |
| --- | --- |
| 版本目录 | `~/.local/share/thor-panel/releases/<版本>-<标识>/` |
| 当前/上一版本 | `~/.local/share/thor-panel/current`、`previous` |
| 安装记录 | `~/.local/share/thor-panel/install-state.json` |
| 用户服务 | `~/.config/systemd/user/thor-panel.service` |
| 应用/桌面入口 | `~/.local/share/applications/thor-panel.desktop`、桌面的 `虚拟键鼠.desktop` |
| 配置/日志 | `~/.config/thor-panel/`、`~/.local/state/thor-panel/` |

XDG 数据/配置目录按当前用户环境确定，兼容旧 `thor-panel` 服务名和配置名，避免同时启动两份面板。
文件位于用户持久目录，Armada 镜像更新后不会因为 `/usr` 被替换而丢失；这不代表未来 GTK、Steam 或 Gamescope API 一定兼容。
应用安装器不包含或启用实验性触摸驱动，驱动试验的内核匹配与回退另见上游 Issue #757。
