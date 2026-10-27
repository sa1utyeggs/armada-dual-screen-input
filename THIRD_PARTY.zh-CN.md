[English](THIRD_PARTY.md) · 简体中文

# 第三方组件

本项目自己的代码采用 MIT；这不会重新许可以下组件：

| 组件 | 许可证与来源 |
| --- | --- |
| Ratatoskr 固定快照 | MIT；见 [LICENSE](vendor/ratatoskr/LICENSE)、[致谢](vendor/ratatoskr/CREDITS.md)和[来源/本地修改](vendor/ratatoskr/UPSTREAM)。固定提交 `24471899b5923b73f0ecb7ae67aba54ad7b6d73e`。 |
| aarch64 离线包内 gtk-layer-shell 运行库 | Fedora 包中的 LGPL、MIT 许可证原文保留在 `runtime/usr/share/licenses/gtk-layer-shell/`。[项目](https://github.com/wmww/gtk-layer-shell)、[对应 Fedora 源 RPM](https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Everything/source/tree/Packages/g/gtk-layer-shell-0.10.0-1.fc44.src.rpm)。共享库仅供本应用使用，仍可替换。 |
| 可选系统 libxkbcommon 与 xkeyboard-config | 系统键盘映射 API/数据，不随包分发。[libxkbcommon 许可证](https://github.com/xkbcommon/libxkbcommon/blob/master/LICENSE)。不修改全局键盘布局。 |
| 可选系统 libpinyin 与词库 | GPL-3.0-or-later；见[源码/许可证](https://github.com/libpinyin/libpinyin)。安装器不打包或下载，仅由可选的独立 `keyboard_worker.py` 进程加载。面板通过私有匿名管道交换临时文字/候选；项目 MIT 不重新许可 libpinyin 或词库。 |
| 可选 Thor 驱动实验，仅仓库提供 | GPL-2.0；见[许可证](https://github.com/sa1utyeggs/armada-dual-screen-input/blob/main/extras/thor-touch-driver/LICENSE)及[源码/来源](https://github.com/sa1utyeggs/armada-dual-screen-input/blob/main/extras/thor-touch-driver/source.json)。应用包与安装器排除此实验。 |

gtk-layer-shell 来自未经修改、固定 SHA-256 的 Fedora 二进制 RPM。`packaging/dependencies/gtk-layer-shell-aarch64.json` 记录包 URL、校验和及选取文件。离线包包含源包引用和许可证原文，不修改系统动态链接器配置。

Steam 风格控件由本项目独立绘制，不包含 Valve 美术素材。

应用图标改编自 [armada-os/armada 的船帆标识](https://github.com/armada-os/armada/blob/86d29b9ba1c660fcfbc43d80d9def02765c41082/.github/assets/armada-mark-white.svg)。Armada 名称与标识保留原权属，项目 MIT 不重新许可该标识；其余图标及输入符号为本应用绘制。

## 本项目生成的手套指示器素材

可选的定位指示器使用[定位态 A](assets/markers/glove/idle.png)与[按住态 F](assets/markers/glove/pressed.png)。素材由内置 ImageGen 工具基于项目介绍视频中生成的手套插画制作并修改，用户于 2026-10-26 确认视觉造型；并非从 Steam 或游戏实录中提取。两张正式 PNG 使用 64 像素透明画布，共用逻辑热点；姿态切换不改变输入坐标。

源图、生成／修改提示词及对比预览作为本地设计证据保留在 `outputs/glove-v7/`。高分辨率源图与弃用草稿不进入应用包，包内只加入手套和像素手的四张运行用指示器 PNG 及应用图标。介绍视频素材的来源说明仍见 [.github/assets/README.md](.github/assets/README.md)。这份美术来源记录不替代前述第三方组件各自的许可证或权属。

## 像素手与程序化准星

像素手定位样式使用 `assets/markers/pixel_hand/idle.png` 和 `assets/markers/pixel_hand/pressed.png`，采用 64 像素透明画布。这组两态素材由内置 ImageGen 工具依据用户认可的第二张概念图生成，再整理为应用指示器所需格式；它是像素手，并非已弃用的猫爪方案。源 PNG、生成提示词、归一化记录与对比证据保留在本地 `outputs/pixel-hand-v1/`，弃用方案不进入应用包。

科幻准星由[指示器样式实现](src/armada_dual_screen_input/marker_appearance.py)中的程序化 Cairo 几何定义，采用 64 像素画布及固定中心热点，两种状态通过与其他样式相同的预生成精灵路径栅格化。准星不使用下载素材或 AI 生成的位图，也不向安装包添加准星 PNG。

Game Mode 文字适配器仅实现 Valve [私有 Gamescope 输入法协议](https://github.com/ValveSoftware/gamescope/blob/master/protocol/gamescope-input-method.xml)的版本 1 子集。它不是稳定的跨合成器 Wayland API。不包含 Valve 源码或协议 XML；未知协议版本或不可用路由会拒绝发送。
