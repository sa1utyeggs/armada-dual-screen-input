# 原生触摸路由验证

历史验证日期：2026-10-19；接入状态更新：2026-10-20。范围：AYN Thor、ArmadaOS `20261010.c3d178c`、Steam Game Mode。

## 结论

**已验证临时虚拟触摸屏能将真正的触摸事件送到上屏专用测试窗口，下屏没有收到这些事件。**
后续已接入独立镜像界面，用户确认 Steam 单指滑动 / 点按，以及《杀戮尖塔2》选牌 / 拖牌 / 菜单正常。
原生模式按用户要求不模拟双指滚轮、不设置双指判定延迟，直接传递最多两个独立触点。
上述内容为初次路由验证的历史结果。2026-10-20 已按用户要求移除镜像功能，原生路由仍供[定位触摸](position-touch.md)使用；没有改动 Steam 设置、物理触屏、udev 规则、官方下屏服务和自启动规则。

## 为什么可以这样路由

当前上屏 Gamescope 通过 libinput 读取输入设备；其参数包含
`--ignore-touch-device bottom_touchscreen`、`--force-orientation right` 和 `--default-touch-mode 4`。
路由测试及 Steam 界面中 `STEAM_TOUCH_CLICK_MODE=4`，对应触摸透传。
《杀戮尖塔2》中观测为 1（触摸映射为左键），沿用这个游戏已有的策略，不写入或覆盖该属性。
因此应用收到的事件可能是原生触摸，也可能经 Gamescope 转成鼠标，与直接触摸物理上屏相同。

Armada 的 DRM lease 补丁将匹配物理下屏名称的触摸经 lease socket 转交下屏。
下屏 Gamescope 没有直接打开 `/dev/input/event*`；新建且不匹配物理下屏名称的触摸屏可进入上屏路径。
该结论来自此版本源码、设备描述符检查和实际输入测试，不推定其他机型或更新后的路由相同。

## 隔离检查与实测

依赖：系统 `libevdev-1.13.7-1.fc44.aarch64`，通过 ctypes 调用；无需安装 Python evdev。
Gamescope 包：`terra-gamescope-3.16.31^1-1.100601.fc44.armada.aarch64`。

1. 用 libevdev 创建名为 `Armada native touch probe <pid>` 的临时 Type B 多点触摸设备。
   声明 `INPUT_PROP_DIRECT`、两个槽、触点追踪 ID、绝对坐标及 `BTN_TOUCH`，不声明鼠标左键。
2. 先不发送任何接触事件。udev 将其分类为 `ID_INPUT_TOUCHSCREEN=1`；描述符检查只有上屏 Gamescope 打开它。
   关闭后设备节点消失。
3. 打开程序自己的上屏全屏测试窗口，以及只计数、不转发输入的下屏观察窗口。
   每次发送前检查：上屏仍是本程序窗口、触摸模式仍为透传、设备仍只由同一 Gamescope 打开。
4. 发送一组单指移动和一组双指接触。结果如下：

| 检查 | 实测 |
| --- | --- |
| 上屏原生触摸源 | GDK `touchscreen` |
| 按下 / 移动 / 抬起 | 3 / 4 / 3 |
| 同时接触数 | 2 |
| 目标坐标匹配 | 通过，误差不超过 3 个窗口像素 |
| 下屏按下 / 移动 / 抬起 / 取消 | 0 / 0 / 0 / 0 |
| 退出后虚拟设备 | 已移除 |

测试坐标只作用于本程序自己的窗口；未向 Steam 页面或游戏发送触点。
XWayland / GTK 内部可能另有触摸到指针的兼容事件；本次原生触摸结论依据实际收到的 TOUCH 序列，
不能只凭鼠标位置变化作判断。

### 坐标的重要区别

第一次按物理屏的 `right` 旋转逆变换发送时，触摸路由成功，但坐标不匹配。
实际收到的是未旋转的虚拟设备坐标，说明该虚拟设备没有继承物理屏的输出关联旋转。
改为 `normal`、直接使用上屏逻辑归一化坐标后通过。

示例：逻辑目标 `(0.25, 0.30)`、`(0.75, 0.70)` 在 1920×1080 测试窗口中实际落点为
`(480, 323)`、`(1439, 755)`。不能将 Thor 物理屏方向直接复用为虚拟设备方向。

## 开发检查入口

`native_touch.py`：无 I/O 的接触编码，以及探测 / 定位触摸共用的 libevdev 临时设备。
`native_touch_probe.py`：有时间上限的双窗口路由检查。
`test_native_touch.py`：编码、双指槽、释放、路由检查失败和写入失败清理测试。
`native_input.py`：定位触摸使用的原生发送后端及后台路由检查。
`gamescope_target.py`、`touch_intent.py`：独立的目标身份检查与输入意图，不依赖捕获源。

本轮 9 项原生触摸单元测试在 Mac 和 Thor 通过；Thor 连同此前镜像相关测试共 85 项通过。
实机 GUI 路由验证单独执行，不能用单元测试结果替代。
后续接入直接触摸后，Mac / Thor 的镜像和原生相关测试各 104 项通过。
早期接入后端的专用窗口检查还通过了“触点保持时关闭”，正常抬起并移除设备。
最终直接触摸版本在游戏中实测后退出，确认捕获停止、进程退出、无残留虚拟触屏。

在已确认 Steam 首页、无游戏运行的开发环境执行：

```bash
PYTHONPATH=src python3 -B tools/native_touch_probe.py --x-display :0 --rotation normal \
  --gtk-runtime-root "$HOME/.local/share/thor-panel/runtime" \
  --report /tmp/native-touch-route.json
```

测试会短暂显示自有窗口，结束后自动关闭。运行时不要触摸设备，以免污染下屏观察计数。
报告中的坐标属于专用测试窗口内的生成触点，不记录文字、游戏画面、IP 或凭据。
不需要 sudo；探测不打开或读取物理 evdev，不独占触摸屏。

## 当前接入与待验证

- 当前日常入口为原面板的“定位触摸”：第一指相对定位，第二指确认，最多向上屏保持一个原生触点；不传输画面。
- 目标稳定并抬手后按需创建临时触屏；暂停、离页、收起或关闭时释放并销毁。沿用原手动入口，不新增自启动。
- 镜像页、独立预览、镜像专用鼠标后端和相应捕获运行库设置已移除。旧版本测试结果保留为路由来源，不代表这些功能仍受支持。
- **异常释放当前表现为抬起，不是真正的 touch cancel**；可能提交已经开始的应用动作。其他游戏、休眠与长期共存仍需验证。
- 下屏漏落指 / 漏抬指仍作为独立问题追踪，见 [ArmadaOS Issue #757](https://github.com/armada-os/armada/issues/757)。

## 参考

- [Linux uinput](https://docs.kernel.org/input/uinput.html)
- [Linux 多点触摸 Type B 协议](https://docs.kernel.org/input/multi-touch-protocol.html)
- [libevdev uinput](https://www.freedesktop.org/software/libevdev/doc/latest/group__uinput.html)
- [Armada DRM lease 触摸转发补丁](https://github.com/armada-os/armada/blob/c3d178c/packages/gamescope/patches/0013-feat-drm-run-a-compositor-from-the-leased-output.patch)
- [Armada 下屏触摸隔离补丁](https://github.com/armada-os/armada/blob/c3d178c/packages/gamescope/patches/0014-wlserver-always-swallow-ignored-touch-device.patch)
- [当前定位触摸](position-touch.md)
