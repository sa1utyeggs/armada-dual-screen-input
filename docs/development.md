# 开发与打包

## 目录边界

- `src/armada_dual_screen_input/` 是 Python 包，内部使用相对导入。会话发现、输入状态机与 GTK 显示分开，绘制线程不等待网络/X11 查询。
- `tests/` 只运行模拟或隔离检查，不启动面板，不向真实游戏发送输入。Linux GTK 集成检查在 Mac 上跳过。
- `tools/manage.py` 管理用户安装，`tools/release.py` 只准备/校验包，`tools/build_release.py` 只生成压缩包。
- `tools/run.py` 为源码与安装包提供同样的启动上下文；子进程使用明确的应用 `PYTHONPATH`，不依赖工作目录。
- `vendor/ratatoskr/` 保留固定快照、许可证、致谢和本地变更说明。修改这里时同步更新 `UPSTREAM`。
- `extras/thor-touch-driver/` 是独立 GPL 实验，不在应用安装器、默认测试或发布包内。不要把驱动状态写成通用应用依赖。

## 检查

```bash
python3 -B tools/run_tests.py
python3 -B tools/run_tests.py --with-node
```

第二个命令同时运行 15 项 Steam 键盘 JavaScript 检查，需要 Node.js。
Linux 全量 GTK 检查需要 PyGObject、Cairo、GTK3 和 GtkLayerShell；依赖齐全后可无显示器运行，测试会模拟窗口/输入对象。
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
```

包内 `manifest.json` 包含每个文件的 SHA-256、源版本标识和 bundle ID；有未提交修改时标识带 `-dirty`。
同一输入树和版本标识下，压缩包的顺序、权限、uid/gid、时间戳固定，构建可重复。
源码、模板、许可证和运行库进入白名单；测试、个人配置、日志、缓存、Git 历史和驱动实验不进入应用包。

## 发布

1. 在 feature 分支完成检查和兼容性说明，提交并通过 PR 评审。
2. 更新 `VERSION` 与 `CHANGELOG.md`，从干净的指定提交构建，保留来源和校验记录。
3. 为该干净提交创建与 `VERSION` 对应的 `v<VERSION>` 标签；在 GitHub Releases 中选择该标签发布，将 tar.gz 和同次构建的 SHA256SUMS 一起上传到 Assets。`preview` 版本标记为 Pre-release。不要用 GitHub 自动生成的 Source code 压缩包替代安装包；仓库私有时，Release 也不能匿名下载。
4. 在 AYN Thor 上验证全新安装、保留配置升级、版本回退和卸载，再扩大支持范围。隔离环境检查与实机验收分别记录。

工作流仅测试或上传 Actions 构建产物，不会自动改变仓库可见性、创建公开 Release、连接掌机或安装驱动。
不要向发布包加入个人运行库目录快照；所有二进制应来自固定依赖清单及可核对的来源。
