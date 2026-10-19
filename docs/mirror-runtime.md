# 同屏触摸原型运行库

已验证环境：Fedora 44 / ArmadaOS `20261010.c3d178c`，aarch64。
这是开发依赖说明，不是通用安装器，不修改 bootc 系统镜像或启用服务。
宿主需要 Python GI / Cairo、GTK3、GStreamer 的 appsink / videoconvert / videoscale / videorate、
PipeWire、libei、libxcb 和 Wayland client。Mac 可运行纯逻辑测试。

## 私有 PipeWire 插件

本轮系统已有 PipeWire 1.6.9，缺少 GStreamer `pipewiresrc`，使用同版本官方 RPM，只解包到私有目录。

| 项目 | 锁定值 |
| --- | --- |
| 包 | `pipewire-gstreamer-1.6.9-1.fc44.aarch64.rpm` |
| SHA256 | `b08ba5e6579adfd4846da5327d978e7bc28a57e25b781dfeef2a41141528d1ad` |
| 插件 | `usr/lib64/gstreamer-1.0/libgstpipewire.so` |
| RPM 许可证声明 | MIT |
| 实机签名检查 | `rpmkeys --checksig` 为 `digests signatures OK` |

[官方 RPM](https://dl.fedoraproject.org/pub/fedora/linux/updates/44/Everything/aarch64/Packages/p/pipewire-gstreamer-1.6.9-1.fc44.aarch64.rpm)。
下载后同时检查整包 SHA256 和 Fedora 签名；不要绕过摘要检查。
用 `rpm2cpio` / `cpio -idm --no-absolute-filenames` 解包到新建私有 runtime。
分包不含许可证文件，打包时保留对应版本 PipeWire 的 `COPYING` 与 `LICENSE`；
本轮宿主相同版本文件在 `/usr/share/licenses/pipewire/`。

启动器只为子进程设置 `GST_PLUGIN_PATH=<runtime>/usr/lib64/gstreamer-1.0`，
在 runtime 旁创建独立 registry 缓存，不改全局环境和系统插件目录。
系统更新后需重新核对 PipeWire / GStreamer 版本与 ABI，不能把 Fedora 44 二进制直接用于其他系统。

## GTK layer-shell

可显式传入原面板已验证的私有库：

```bash
--gtk-runtime-root "$HOME/.local/share/thor-panel/runtime"
```

仅对子进程设置 `LD_LIBRARY_PATH`、`GI_TYPELIB_PATH`，不修改原面板。
原 layer-shell 包、摘要和来源见 [README](../README.md)。没有原面板时需独立准备库、typelib 和许可证。

## 开发检查

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v
python3 -B gamescope_probe.py --display gamescope-primary
python3 -B mirror_launch.py --x-display :0 \
  --runtime-root /path/to/private/runtime \
  --gtk-runtime-root /path/to/gtk/runtime
```

探测不取帧或发送输入。预览取帧但默认暂停触摸；上屏控制 display 需先核实。
`--quit-after 7` 是有限时长检查；`--proof /path/to/preview.png` 显式保存布局截图。
截图可能含用户内容，留在本地且不提交 Git。`--fps 30` / `--fps 60` 只影响这个预览进程。

真实按钮 / 滚轮检查使用自己的上屏测试窗口：

```bash
python3 -B mirror_input_smoke.py --x-display :0 --steam-ui-parent
```

只允许 Steam 首页前台、没有游戏或覆盖层时短暂附加；只给测试程序自己的窗口写属性，
不改 Steam 库或全局焦点控制。测试窗口未获得焦点时退出并报告 `input_sent: false`。

使用“关闭预览”退出。开发诊断可给自己的预览 PID 发送 SIGUSR1 输出线程栈；
不记录触摸坐标、按键内容或图像，日志不提交 Git。
清理只删除自行创建的开发目录、runtime、缓存与日志，不删除已安装的 `thor-panel`。
