# Armada Dual Screen Input（虚拟键鼠）

面向 ArmadaOS 双屏设备的副屏输入工具，提供虚拟键盘、触控板、设备监控和同屏镜像触摸。
项目以适配不同机型的屏幕尺寸、方向和输入设备为目标。

目前实机验证设备为 **AYN Thor**，已验证范围主要是 **Steam Game Mode**。
其他 ArmadaOS 双屏设备尚未验证，不能据此认为当前版本已经通用；设备识别、屏幕参数、触摸映射及硬件监控仍需逐机型确认。
Desktop Mode 支持仍为实验状态，默认关闭。

## 源码与版本管理

本项目以 Git 独立管理，项目名为 `armada-dual-screen-input`；GitHub 主仓库为
[`sa1utyeggs/armada-dual-screen-input`](https://github.com/sa1utyeggs/armada-dual-screen-input)，默认分支为 `main`，远端名为 `origin`。
原项目名为 `thor-virtual-input`。本地目录暂时保留 `thor-panel-prototype`，以兼容现有工作路径。
已有 `thor-panel` 安装目录、配置路径和用户服务名暂时保留，后续通过兼容迁移处理；更名不修改掌机运行配置。

`vendor/ratatoskr/` 是固定版本的第三方代码快照，来源、提交及本地修改记录见
[`UPSTREAM`](vendor/ratatoskr/UPSTREAM)，许可证和致谢保留在该目录内。
个人 GitHub 主仓库与 Ratatoskr 的代码来源分别记录，尚未把后者配置成 Git 远端。

仓库包含源码、测试、图标、桌面入口和用户服务模板。Python 缓存、设备运行库、个人配置、日志及备份由 `.gitignore` 排除。
进入源码目录后，在 Mac 上可执行 `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v`；依赖 Linux GTK 的集成检查会跳过，完整验证仍需 Thor 实机。
Steam 键盘抑制脚本另用 `node --test test_steam_keyboard_guard.js` 检查；测试使用模拟 Steam 对象，不连接或操作真实客户端。

同屏触摸已在功能分支整合到原面板，默认使用原生触摸；鼠标兼容模式另提供双指滚轮。
原触控板的双指滚动和灵敏度设置保留。独立预览仍供开发验证，不要与正式面板的镜像页同时运行。

## 同屏触摸开发进度

功能分支：`feature/mirrored-touch`，[草稿 PR #1](https://github.com/sa1utyeggs/armada-dual-screen-input/pull/1)。
2026-10-19 已接入 Gamescope PipeWire 画面、原生触屏与 EIS 鼠标兼容输入，并保留更新后的 main 深色样式和 Steam 键盘联动。
用户已在独立预览中确认 Steam 单指滑动 / 点按、《杀戮尖塔2》选牌 / 拖牌 / 菜单正常。
现在通过原“虚拟键鼠”入口进入第三个“同屏触摸”标签，不再需要另开预览；用户已确认集成版镜像、触摸和切回键鼠正常。
进入后等画面 / 目标就绪、焦点稳定且所有手指抬起，再自动启用；切换前台窗口或输入失效时释放旧触点，就绪后自动恢复。
手动“暂停触摸”或“释放触点”会保持暂停，点击“启用触摸”才恢复；切回键鼠 / 触控板、收起、隐藏或退出会释放输入并停止捕获。重新进入 / 展开时重新等待就绪后自动启用。
没有新增快捷方式或自启动项。
启动、实现约定及验收结果见[同屏触摸与双指滚轮](docs/mirrored-touch.md)，
私有依赖与持久部署见[镜像运行库](docs/mirror-runtime.md)。

在已登录的 ArmadaOS 图形用户环境中，可执行只读探测（不需要 sudo，不捕获画面或发送输入）：

```bash
python3 -B gamescope_probe.py --display gamescope-primary
```

`node_advertised` 仅表示服务器通告了节点，不代表画面或输入已可用。

## AYN Thor 实测环境与当前状态

设备：AYN Thor 16GB / 512GB，Armada OS `20261010.c3d178c`。

2026-10-15 已安装为独立 Linux 用户应用，默认只在 Steam Game Mode 的下屏显示。用户已确认键盘、触控板、上屏触摸和手柄可正常使用。按最新要求取消开机／登录自启动，改为桌面快捷方式手动打开；桌面模式显示仍暂不启用。

## 使用

2026-10-19 起，原面板采用 Steam 默认深色键盘风格：深灰实心键帽、蓝色按下与修饰键反馈、矢量编辑图标，以及统一的触控板、状态栏和收起条。样式由 `steam_style.py`、`steam_keys.py` 绘制；未复制 Valve 素材。按键排列、键鼠模式的键盘位置和大小保持不变。

- 默认“键鼠”：上方触控板，下方键盘，顶部用单行显示设备状态。
- 顶部提供“触控板”“键鼠”“同屏触摸”三种模式；状态栏只读。旧配置中的 `keyboard/settings` 在打开时兼容为 `split`（键鼠），最后选择的模式沿用原配置保存机制；镜像输入的启用状态不保存。键鼠模式的键盘位置和大小保持不变。
- **同屏触摸**：下屏显示上屏等比例画面，进入后就绪并抬手即自动启用。默认“原生触摸”沿用上屏应用设置，不转换双指滚轮。点“原生触摸”可切到“鼠标兼容”，此时单指为鼠标左键、双指为滚轮。输入方式切换后等待抬手并自动连接；手动暂停时切换仍保持暂停。“释放触点”会暂停；抬起无法撤销游戏已开始的动作。
- **关闭**：右上角红字按钮，立即释放虚拟按键／鼠标并退出面板；后台不会马上重新打开。
- **收起**：面板缩为窄条，让出官方下屏界面；点击窄条重新展开。
- **释放按键**：清除 Ctrl、Alt、Shift、Super 和鼠标键的保持状态。轻点修饰键可能使其保持到下一次输入；不确定当前状态时用此按钮复位。
- 面板不会因闲置自动叠加变暗遮罩；系统自身的亮度和休眠规则仍由 Armada 管理。
- 触控板轻点允许 350 毫秒内的小范围手指抖动；移动以离开落点的距离判定，不再累加原地抖动。移动加速按速度计算，减少触摸事件合并时的速度变化。
- 滚轮单独使用配置 `scroll_speed`（1～5）和 `scroll_scale`（大于 0、不超过 1；缺省为 1）。2026-10-19 在最低档仍偏快时，增加 `scroll_output.py`，在生成高精度与传统滚轮事件之前统一缩放并保留小数余量；当前掌机设置为 `scroll_speed=1`、`scroll_scale=0.25`。修改配置后需要重新打开面板，不改变指针、点击或系统滚轮设置。滚动手感待用户复测。
- Steam Game Mode 中，只在“键鼠”页可见、未收起时，临时抑制 Steam 原生键盘（含 Steam＋X）；触控板页、收起、隐藏或退出后恢复。`steam_keyboard_guard.py` 的后台线程使用现有本机 Steam CDP（127.0.0.1:8080）和系统已有的 `websocket-client`，不在 GTK 线程做网络请求，不修改 Steam 文件、首选项或自启动。`steam_keyboard_guard.js` 在 Steam 内设置 4 秒租约；面板被杀、UI 心跳停止或连接故障后独立过期，只恢复函数，不重放旧键盘请求。Steam 调试接口不可用或内部对象不匹配时，保持原生键盘可用。
- 游戏的专用整段文字输入请求在被抑制时按 Steam 的取消协议结束；下屏的真实按键不能代替这类 API 的文本提交回调。需要该对话框时先切到触控板页或收起下屏键盘。此联动适配 Steam 当前内部接口，客户端更新后需复核。显示拦截的已有项目参考：[BetterKeyboard](https://github.com/chenx-dust/BetterKeyboard/blob/01d52c6abd9cff20fa2b981a5b7f91a572eb6d02/src/utility/context.ts)；本实现不部署该插件的输入抓取功能。
- Ctrl＋P 等组合仍是标准键盘快捷键，可能打开上屏应用的打印窗口；可按 Esc 关闭。“释放按键”保留为独立按钮；右上角新增红色“关闭”，与收起分开。

**默认不自动启动。** 手动打开后，程序等待官方 Game Mode 下屏会话就绪才显示，不接管或关闭官方下屏服务。模式切换时回收旧窗口和虚拟输入；在桌面模式点快捷方式后，只等待进入 Game Mode，不在桌面显示面板。关闭后再次点击快捷方式即可重新打开。

掌机桌面快捷方式：`~/Desktop/虚拟键鼠.desktop`。应用列表入口：**虚拟键鼠**。点击不需要管理员密码，也不会重新启用自启动。

手动管理，不需要 sudo：

```bash
systemctl --user restart thor-panel.service
systemctl --user stop thor-panel.service
```

当前服务状态应为 `disabled`（手动打开时可同时为 `active`）。如以后需要管理自启动：

```bash
systemctl --user disable --now thor-panel.service
systemctl --user enable --now thor-panel.service
```

## 安装位置与排查

| 内容 | 路径 |
| --- | --- |
| 程序、上游来源及运行库 | `~/.local/share/thor-panel/` |
| 配置 | `~/.config/thor-panel/config.json` |
| 日志 | `~/.local/state/thor-panel/panel.log` |
| 独立用户服务 | `~/.config/systemd/user/thor-panel.service` |
| 应用入口 | `~/.local/share/applications/thor-panel.desktop` |
| 桌面快捷方式 | `~/Desktop/虚拟键鼠.desktop` |
| 键盘与鼠标图标 | `~/.local/share/icons/hicolor/scalable/apps/thor-virtual-input.svg` |

目录位于用户持久存储，没有使用重启后消失的系统 overlay。补充运行库仅供本应用加载，未修改宿主系统的动态链接器配置或全局环境。

```bash
python3 ~/.local/share/thor-panel/supervisor.py --probe
systemctl --user status thor-panel.service --no-pager
journalctl --user -u thor-panel.service -n 60 --no-pager
```

在桌面模式执行 probe，`session: null` 是当前仅支持 Game Mode 的预期结果。

## 已验证与限制

- 双指滚动后的残留触点恢复正在独立分支准备，尚未安装或实机复测；机制、验证范围和后续复测见[触点恢复说明](docs/trackpad-recovery.md)。
- 系统 GTK3、Cairo 与正常用户 `/dev/uinput` 权限可用；GUI 通过原生 GTK 运行。
- 原键鼠使用自己的 `/dev/uinput`；镜像原生触摸在页签就绪、目标稳定且所有手指抬起后按需建立临时触屏，暂停 / 离页即销毁。鼠标兼容使用 EIS。不读取 raw evdev，不独占物理触摸屏。
- Game Mode 连接官方底层 KWin 的 `armada-plasma-bottom`，不是直接连接 bottom Gamescope。真实唯一输出为 `X11-0`，逻辑尺寸 `689×600`。
- 官方 `armada-bottom-gamescope`、`armada-bottom-screen` 在面板运行时仍为 active。
- 首轮出现过 Steam 网页界面无响应。停止面板后仍未恢复；重建该 Steam 界面进程后恢复。随后仅为面板设置 `NO_AT_BRIDGE=1`，下一轮键盘、触摸和手柄测试通过。**尚不能确定首轮故障根因，不能将无障碍警告直接认定为根因。** 该隔离设置不修改系统辅助功能。
- 基础版本 63 项会话发现、输出选择和触摸状态测试在本地通过；此前 48 项测试在掌机 Linux 上通过。另增加并通过了 2 项关闭生命周期测试，覆盖关闭后停止后台、会话同时消失时也不会重开。通过桌面文件实际启动后确认服务 `active` 且自启动仍 `disabled`。旧版顶部 10 个控件曾通过离屏字体与边界检查。这些检查不等同于长期图形兼容验证。
- 2026-10-19 精简为 7 个顶部控件后，12 张原始／实际窗口尺寸预览无缺字；掌机 Linux 上 54 项布局、按键、触摸、滚轮与抑制检查通过。真实下屏回调检查确认：状态栏不切页，键鼠／触控板切换、收起、展开和关闭时抑制按预期启用或释放，保存的配置不变；该检查未向上屏发送文字，不代替实际游戏或长期触控体验验证。
- 同日加入第 3 个标签后，掌机 247 项 Python 检查与 Mac 的 15 项 Steam 键盘脚本检查通过。集成界面检查覆盖镜像首帧、初始暂停、无接触启用原生输入、收起停止、展开仍暂停、返回键鼠及退出，未向上屏发送触点。实际画面 1920×1080、窗口 689×542，中文缺字数为 0；配置文件未被检查脚本改写。原型的用户交互验收与本次生命周期检查分别记录，不据此认定长时间性能通过。
- 用户确认集成版镜像、触摸和切回键鼠正常后，按要求改为就绪并抬手后自动启用。掌机 256 项 Python 检查通过；无上屏触点的实机检查确认：按住时不连接，抬手约 0.41 秒后自动启用，手动暂停保持、恢复按钮正常，收起移除设备、展开自动启用，退出无残留触屏，个人配置字节不变。该检查不代替长时间游戏验证。
- 随后针对拖动偶发停住 / 跳动，修正过严的焦点比较：已经验证属于同一可见窗口的子控件切换不会销毁原生触摸连接，真实窗口、应用、尺寸、服务器、display、触屏策略变化或失焦仍会释放。掌机 260 项检查通过，用户复测拖动 / 点按 / 控件切换正常；诊断版修正前的一轮也正常，不能据此把该判断确定为所有卡顿的根因。中断日志仅记录状态、年龄、变化字段名和聚合发送数，不记录坐标或文字。
- 休眠恢复、长时间游戏、双屏模拟器接管下屏尚未验证。Desktop 支持保留为实验代码，默认关闭，不作为已完成能力。

## 实现与来源

复用 Ratatoskr 的 Cairo 键盘、手势与设备监控代码，改用 GTK 的窗口触摸事件，统一到单调时钟。中文按钮、监控页与收起条通过 PangoCairo 绘制，首选系统 Noto Sans CJK SC 并保留字体回退；已在掌机检查 16 个 UI 字符串无缺字、顶部标签无溢出。取消触摸、收起或退出进程时释放按键并停止惯性移动。GTK layer shell 指定输出且不获取键盘焦点。

2026-10-19 本地修补了 vendor 中的 `engine.py`：单指点击按最大落点偏移判定、350 毫秒点击窗口、超出 12 个逻辑像素后才开始移动、每次新触摸清除小数余量、按时间计算有上限的加速。`UPSTREAM` 已注明这些本地修改。新增 8 项无硬件指针回归测试，与原有输入隔离、会话和关闭生命周期测试一起运行；模拟检查不代替掌机手感验证。

同日用户确认不再自动变暗、轻点可以点击，但移动仍有卡顿。短时聚合诊断未见绘制线程持续阻塞；随后将 GDK 源事件间隔单独用于指针速度／加速／惯性计算，避免回调被批量投递时误判为高速移动。点击时长与接触存活仍使用单调时钟。新增 12 项源时间、回绕、重复事件与批量投递测试通过；这轮移动修复尚待用户实测，不将其记为完全解决。

随后用户反馈移动较顺畅，继续观察偶发停顿；又反馈多个应用中输入文字偶有卡顿。已发现原 `tap_key()` 在 GTK 触摸回调中同步等待 20 毫秒，改为本应用的 `KeyboardPulses` 定时释放；长按重复也改为同一事件循环的定时器，保留原 350／60 毫秒设置。快速同键连点用独立令牌防止旧释放干扰新按键，改变修饰键前先结束未完成脉冲，取消和关闭时清理所有定时源。掌机上 17 项无真实输入设备测试通过；输入体感是否改善仍待用户确认。未改动鼠标引擎、系统输入服务或自启动设置。

补充库为 Fedora 官方 `gtk-layer-shell-0.10.0-1.fc44.aarch64.rpm`，掌机 `rpmkeys --checksig` 结果为 `digests signatures OK`。

- RPM SHA256：`de2a27df40ae7cffd3b858f46f73744ec2f0b153a2870120f88cd0b40660fb92`
- [官方 RPM](https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Everything/aarch64/os/Packages/g/gtk-layer-shell-0.10.0-1.fc44.aarch64.rpm)
- [Fedora 源包](https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Everything/source/tree/Packages/g/gtk-layer-shell-0.10.0-1.fc44.src.rpm)
- 运行库许可证保留在 `runtime/usr/share/licenses/gtk-layer-shell/`。

其他来源：

- [Ratatoskr](https://github.com/venatrix-ritz/Ratatoskr)，固定提交 `24471899b5923b73f0ecb7ae67aba54ad7b6d73e`。`vendor/ratatoskr` 保留 MIT LICENSE 与 CREDITS，未部署其安装器、Decky 后端或服务切换管理器。
- [Armada Thor 设备配置](https://github.com/armada-os/armada/blob/c3d178c/system_files/usr/lib/armada/devices/ayn-thor.conf)
- [官方下屏会话](https://github.com/armada-os/armada/blob/c3d178c/system_files/usr/libexec/armada/armada-plasma-session)
- [官方下屏服务](https://github.com/armada-os/armada/blob/c3d178c/system_files/usr/lib/systemd/user/armada-bottom-screen.service)
- [GTK layer shell API](https://wmww.github.io/gtk-layer-shell/)
- [GDK 触摸事件](https://docs.gtk.org/gdk3/struct.EventTouch.html)
