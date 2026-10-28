[English](../development.md) · 简体中文

# 开发与打包

## 目录边界

- `src/armada_dual_screen_input/` 是 Python 包，内部使用相对导入。会话发现、输入状态机与 GTK 显示分开，绘制线程不等待网络/X11 查询。
- `tests/` 只运行模拟或隔离检查，不启动面板，不向真实游戏发送输入。Linux GTK 集成检查在 Mac 上跳过。
- `tools/manage.py` 管理用户安装，`tools/release.py` 只准备/校验包，`tools/build_release.py` 只生成压缩包。
- `tools/run.py` 为源码与安装包提供同样的启动上下文；子进程使用明确的应用 `PYTHONPATH`，不依赖工作目录。
- `vendor/ratatoskr/` 保留固定快照、许可证、致谢和本地变更说明。修改这里时同步更新 `UPSTREAM`。
- `extras/thor-touch-driver/` 是独立 GPL 内核实验，不属于应用安装器或发布包。内核构建 / 试用不进入默认检查；可选图形管理桥接仅使用模拟权限和设备进行测试，不加载真实模块。

## 检查

```bash
python3 -B tools/run_tests.py
python3 -B tools/run_tests.py --with-node
```

第二个命令同时运行 15 项 Steam 键盘 JavaScript 检查，需要 Node.js。
Linux 全量 GTK 检查需要 PyGObject、Cairo、GTK3、GtkLayerShell 和 Noto CJK 字体；依赖齐全后可无显示器运行，测试会模拟窗口/输入对象。
Mac 的跳过项目不能记作 Linux 实机通过。涉及输入、焦点、窗口生命周期的修改还应在已保存游戏后进行交互验收。

仅检查当前会话/依赖，不创建输入设备：

```bash
python3 -B tools/run.py --probe
```

手动运行 UI 会创建本应用自己的虚拟输入设备：

```bash
python3 -B tools/run.py --run
```

默认只发现 Game Mode。不要在 CI、用户游戏运行时自动执行 `native_touch_probe.py` 或 `position_input_smoke.py`；这些开发工具只针对自己的测试窗口，需要显式安排。
开发工具的导入示例为 `PYTHONPATH=src python3 -B tools/position_input_smoke.py`，还需正确的 GTK 私有库/typelib 环境。

键盘时序检查使用真实 GLib 时钟，默认只离屏绘制并记录模拟设备，不创建窗口或输入设备：

```bash
python3 -B tools/keyboard_latency_bench.py --output /tmp/keyboard-timing.json
```

在已安排交互测试、Steam 首页空闲时，可显式运行自己的上屏输入窗口：

```bash
python3 -B tools/keyboard_latency_bench.py --run-own-window-test --output /tmp/keyboard-native.json
python3 -B tools/keyboard_ime_latency_bench.py --run-own-window-test --output /tmp/keyboard-ime.json
python3 -B tools/keyboard_window_latency_bench.py --run-own-window-test --output /tmp/keyboard-window.json
python3 -B tools/keyboard_window_latency_bench.py --run-own-window-test --defer-status-during-typing --output /tmp/keyboard-window-status.json
python3 -B tools/keyboard_window_latency_bench.py --run-own-window-test --defer-status-during-typing --short-taps --output /tmp/keyboard-feedback.json
```

这些交互工具必须逐个运行。前两个只使用固定测试文字，要求自己的上屏窗口保持焦点，失焦即停止；不向游戏或 Steam 搜索框发送输入，不保存个人文字、不改变输入设置。第三个短暂覆盖下屏，用模拟状态对比真实 Wayland 目标上的完整/局部绘制，不创建输入设备。检查包括每秒 5/10/15 次点按、长按字母/退格，以及拼音候选/空格提交。`passed` 代表内容/次序/释放正确或足量绘制完成，延迟数值供比较，不代表物理触摸到显示的全链路延迟，也不是长期无卡顿保证。详见 [测量边界与结果](keyboard-latency.md)。

`--short-taps` 另测 2/5/8/12/20/40ms 的短促点按，以及主线程同批收到按下/抬起的情形。统计自己的绘制回调是否选择了按下颜色；它不测物理显示器实际呈现，也不把“高亮未绘出”计作真实漏键。

## 构建离线包

```bash
python3 -B tools/build_release.py
```

构建器下载固定的 Fedora ARM64 gtk-layer-shell RPM，核对 SHA-256 后只解出五个清单文件。
可使用本地已下载 RPM 全离线构建：

```bash
python3 -B tools/build_release.py --offline --runtime-rpm /路径/gtk-layer-shell-0.10.0-1.fc44.aarch64.rpm
```

Mac 使用支持 RPM 的系统 libarchive tar；Linux 可用 `rpm2cpio` + `cpio`。输出在 `dist/`：

```text
armada-dual-screen-input-<VERSION>-aarch64.tar.gz
SHA256SUMS
Install-Armada-Dual-Screen-Input.desktop
INSTALLER-SHA256SUMS
```

包内 `manifest.json` 包含每个文件的 SHA-256、源版本标识和 bundle ID；有未提交修改时标识带 `-dirty`。
同一输入树和版本标识下，压缩包的顺序、权限、uid/gid、时间戳固定，构建可重复。
源码、模板、许可证和运行库进入白名单；测试、个人配置、日志、缓存、Git 历史和驱动实验不进入应用包。

点击入口只内嵌安装器、稳定版下载器、公开 Release 查询、验证与主机检查助手、双语文案和项目许可证。首次安装、应用内检查更新及独立更新任务共用官方网页重定向、稳定版标签严格验证、同标签 `SHA256SUMS` 及有大小上限的安装包响应头检查，不请求 REST API，也不回退到 REST。下载内容必须与已确认的校验文件字节和安装包 SHA-256 一致，随后通过安全解压和清单验证，才能安装。检查仍由手动触发、不自动重试；GitHub/CDN 网页仍可能限流。入口在临时 zip 中运行助手，下载用户确认的稳定版包，再通过 `--offline` 调用其现有安装器。独立的 `INSTALLER-SHA256SUMS` 保留应用 `SHA256SUMS` 的单条目格式，兼容旧版更新器。受版本控制的主页入口和 Release 入口必须包含生成器对应的源码与引导代码；不同 zlib 版本的压缩字节可能不同。修改任一内嵌助手后，重新生成主页文件：

```bash
python3 -B tools/build_click_installer.py --output .
```

检查会在源码目录之外运行内嵌入口的 `--help`，检查入口是否最新，并用假发布附件验证下载流程，不联网、不真实安装。Linux CI 使用 Xvfb 验证双语安装窗口布局，并继续运行原有文案和面板检查。在 Linux 桌面只预览安装器自己的窗口，不下载、不安装、不创建输入设备：

```bash
python3 -B tools/click_install.py --preview ready
```

浏览器下载行为、KDE 信任提示和 Thor 端到端安装仍需单独验收。

## 发布

1. 在 feature 分支完成检查和兼容性说明，提交并通过 PR 评审。
2. 更新 `VERSION`，同时将 `CHANGELOG.md` 与 `CHANGELOG.zh-CN.md` 内容归到对应版本的非空 `## <VERSION>` 标题下，合并到 `main`。版本使用 SemVer，例如 `0.1.0-preview.3`；`-preview.3`、`-rc.1` 等标记为 Pre-release，只有 `+build` 元数据的版本仍为正式版。
3. 在干净的 `main` 提交上创建并推送与 `VERSION` 完全对应的 tag。**推送 tag 就是发布动作**，只在已准备发布时执行：

   ```bash
   (
     set -eu
     git switch main
     git pull --ff-only
     test -z "$(git status --porcelain)"
     release_version=$(cat VERSION)
     git tag -a "v$release_version" -m "Release v$release_version"
     git push origin "v$release_version"
   )
   ```

4. 打开 Actions 的 **Build and release offline package**：该 tag 的完整 Linux/Python/JavaScript 检查通过后，CI 校验 tag 与 `VERSION` 一致、目标提交属于 `main`、中英文变更记录均存在且非空，再从该提交构建固定依赖的 aarch64 离线包并核对 SHA-256。发布 job 还会核对远端 tag 仍指向已构建提交。
5. CI 创建 Release 草稿，上传 `armada-dual-screen-input-<VERSION>-aarch64.tar.gz`、同次构建的 `SHA256SUMS`、`Install-Armada-Dual-Screen-Input.desktop` 和 `INSTALLER-SHA256SUMS`，最后发布；上传前核对两份校验文件。发布说明取自对应版本的两份 Changelog，英文在前、简体中文在后，附带点击安装与离线安装步骤；任一语言缺失会阻止发布；预览版不标为 Latest，其点击安装器仍选择最新稳定应用。只有发布 job 获得 `contents: write`，检查和构建只读，不需要配置个人访问令牌。
6. 在 AYN Thor 上验证全新安装、保留配置升级、版本回退和卸载，再扩大支持范围。隔离环境检查与实机验收分别记录。不要用 GitHub 自动生成的 Source code 压缩包替代安装包；仓库私有时，Release 也不能匿名下载。

保留 **Run workflow** 手动入口：只运行检查和构建，上传包含安装包、校验文件与发布说明的 Actions artifact，不发布 Release。涉及发布流程的 PR 也会构建验证，但不会发布。

检查、版本校验或构建失败时不创建 Release；上传失败时留在草稿。可在原 Actions run 中 **Re-run failed jobs** 继续上传并发布该草稿。已发布版本不会被重跑覆盖，应更新版本并推送新 tag；不要移动已发布 tag。

工作流不改变仓库可见性、不连接掌机、不安装应用或驱动。
不要向发布包加入个人运行库目录快照；所有二进制应来自固定依赖清单及可核对的来源。

参考：[GitHub 可复用工作流](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)、[GitHub CLI Release](https://cli.github.com/manual/gh_release_create)。
