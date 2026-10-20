# Armada Dual Screen Input · 虚拟键鼠

ArmadaOS 双屏掌机的副屏键盘、触控板和定位触摸应用。看上屏，在下屏操作；定位触摸不需要镜像或持续传输画面。

目前为预览版，**实机验证设备是 AYN Thor，主要支持 Steam Game Mode**。Desktop Mode 默认关闭，其他机型仍需适配和验证。

## 安装

在 **Armada 桌面终端**执行这一条命令即可自动下载、准备依赖并安装，不需要 Git、SSH 密钥或手工解包：

```bash
curl -fsSL https://raw.githubusercontent.com/sa1utyeggs/armada-dual-screen-input/main/get.sh | bash
```

也可以从 GitHub 下载 [`get.sh`](get.sh)，在下载目录执行 `bash get.sh`。
安装使用普通用户，**不要 sudo**。默认添加“虚拟键鼠”应用和桌面入口，**不自动启动、不启用开机自启动**。

离线安装包在 [GitHub Releases](https://github.com/sa1utyeggs/armada-dual-screen-input/releases) 中按版本发布。
选择版本，在 **Assets** 中同时下载 `armada-dual-screen-input-<版本>-aarch64.tar.gz` 和 `SHA256SUMS`，再传到掌机。
该安装包包含私有运行库；GitHub 自动生成的 **Source code** 压缩包只是源码，不能代替离线安装包。
以下以 `v0.1.0-preview.1` 为例：

```bash
sha256sum -c SHA256SUMS
tar -xzf armada-dual-screen-input-0.1.0-preview.1-aarch64.tar.gz
cd armada-dual-screen-input-0.1.0-preview.1-aarch64
bash install.sh
```

也可克隆源码后运行 `bash install.sh`；源码入口会校验并准备固定的 Fedora gtk-layer-shell 私有依赖。

[完整安装、升级、回退与卸载](docs/installation.md) · [兼容范围](docs/compatibility.md) · [使用说明](docs/usage.md)

## 功能

- **键鼠**：下屏虚拟键盘和触控板，中文界面、Steam 风格控件；闲置不叠加变暗遮罩。
- **触控板**：单指移动/轻点、双指滚轮，支持独立滚动缩放。
- **定位触摸**：第一指移动上屏圆环；第二指确认触摸，保持第二指并移动第一指可拖动。
- **手动管理**：关闭会释放输入并退出；收起可以再次展开，官方下屏服务继续运行。

```bash
~/.local/bin/armada-dual-screen-input start
~/.local/bin/armada-dual-screen-input stop
~/.local/bin/armada-dual-screen-input doctor
~/.local/bin/armada-dual-screen-input rollback
~/.local/bin/armada-dual-screen-input uninstall
```

更新时在新包中再次运行 `bash install.sh`，配置和日志保留。安装器只管理本应用用户目录及用户服务，不安装实验内核驱动。

## 项目结构

```text
src/armada_dual_screen_input/  应用、输入状态机、会话与覆盖层
tests/                       Python / JavaScript 回归检查
tools/                       安装管理、离线打包、开发验证入口
packaging/                   服务/桌面模板与固定依赖清单
assets/icons/                应用图标
vendor/ratatoskr/             固定第三方快照与来源说明
docs/                        安装、使用、兼容性与实测记录
extras/thor-touch-driver/    独立实验；不进入应用发布包
```

源码重构保留旧 `thor-panel` 配置和服务名，避免与旧安装并行启动。用户数据不进入仓库或发布包。

## 开发与发布

```bash
python3 -B tools/run_tests.py --with-node
python3 -B tools/build_release.py
```

构建器只打包白名单源码和校验过的 Fedora 运行库，生成 aarch64 `.tar.gz`、文件清单和 `SHA256SUMS`。
它不会连接掌机、安装应用或生成/加载驱动。Mac 可以构建包并运行纯逻辑测试；Linux GTK 检查仍需 Linux 环境。

[开发流程](https://github.com/sa1utyeggs/armada-dual-screen-input/blob/main/docs/development.md) · [第三方来源](THIRD_PARTY.md) · [变更记录](CHANGELOG.md)

## 当前验证边界

已有 Thor 用户交互验收包括键鼠基础操作、定位触摸与拖动、右侧 Steam 菜单后的圆环自动恢复，以及正常切换恢复速度优化。
《杀戮尖塔2》时间线的间歇重连仍待定位，长期、休眠恢复和其他机型的稳定性尚未完成验证。
Thor 的物理触点残留另见 [Armada Issue #757](https://github.com/armada-os/armada/issues/757#issuecomment-6284200266)；安装本应用不等于修复该驱动问题。
历史测试数量和当时的限制保留在 [历史记录](https://github.com/sa1utyeggs/armada-dual-screen-input/blob/main/docs/history.md)、[定位触摸记录](https://github.com/sa1utyeggs/armada-dual-screen-input/blob/main/docs/position-touch.md)中，不代表当前所有环境都已验证。

## 许可证

本项目代码使用 [MIT](LICENSE)。Ratatoskr、gtk-layer-shell 和仓库内的实验驱动保留各自的许可证，见 [THIRD_PARTY.md](THIRD_PARTY.md)。
