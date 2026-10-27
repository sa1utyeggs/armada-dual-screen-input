[English](README.md) · 简体中文

# Thor 下屏驱动独立模块（实验）

2026-10-20。只用于 AYN Thor 下屏 FT5452 的可选驱动试验，不是通用双屏应用的默认依赖。
应用本身不会导入、加载或安装本目录的代码；原桌面入口与自启动设置保持不变。

## 当前验证

- 完成针对 Armada `20261010.c3d178c` / Linux `7.2.6` / AArch64 的模块编译。
- 剥离调试信息后的模块为 39,648 字节，`vermagic` 为 `7.2.6 SMP preempt mod_unload aarch64`。
- 69 个未定义导入符号全部与运行内核导出名及对应源码的导出声明核对；MODPOST、最终链接通过。
- 18 项工具与符号核对测试通过，覆盖版本拒绝、仅操作下屏、加载 / probe / 输入失败回退、更新顺序与中断试验回退。
- 掌机 `status`、`plan` 匹配后，实测模块加载、仅下屏重新绑定和输入设备重建成功；上屏保留原厂驱动及原输入设备。
- 前两轮因面板不可见而中断，均通过 Ctrl+C 恢复原厂驱动并卸载模块；不计作触摸效果验证。关闭占据下屏的 LocalSend 后，用户确认面板可见。
- 第三轮完成 90 秒限时测试，用户确认“每次都能立即变蓝，拖动正常”：保持第一指时，第二指抬起能够释放定位触摸。只读触点记录包含双指、单指与零接触切换，测试末尾多次返回零接触及 `BTN_TOUCH=false`。
- 90 秒到期后工具正常退出，复查上下屏均为 `edt_ft5x06`、候选模块已卸载。内核 / 启动文件未替换，面板仍为按需启动；root 管理目录保留试验包及状态。
- **这是一次短时验证；两指同时落下、长期游戏、休眠恢复与不同系统构建尚未完成专项验证。** 不能将这次结果扩大为所有触摸问题已解决。
- 随后用户授权延长测试，已通过 `apply` 再次启用同一候选模块，并重新打开虚拟键鼠。复查下屏由候选模块接管，上屏仍为原厂驱动及原输入设备。此次没有 90 秒自动回退；手动 `revert` 或重启恢复原厂驱动，没有配置开机加载。长期测试结果待用户反馈。

## 方法

使用 Linux 7.2.6 加 Armada 现有补丁及 [DROP_UNUSED 候选](../../docs/patches/0030-input-edt-ft5x06-thor-bottom-drop-unused.patch) 的驱动源码，
编译为名称独立的 `armada_thor_ft5452` 模块。只保留 FT5452 的 OF / I2C 匹配表，probe 还要求：

- 整机兼容 `ayn,thor`；
- 控制器兼容 `focaltech,ft5452`，I2C 地址 `0x38`；
- 设备树标签为 `bottom_touchscreen`。

保留 Armada 的输入设备命名、读取方式、IRQ、供电和 PM 逻辑，以及候选的完整触点帧同步。
设备树、上屏驱动与启动镜像均不替换。原作者及补丁来源保留在源码与 `source.json` 中；驱动许可证见 [LICENSE](LICENSE)。

运行时先注册新驱动，再解绑下屏原驱动，将同一个物理下屏绑定到新驱动。上屏始终由原驱动管理。
工具按设备树匹配唯一目标，不把 `/dev/input/event5` 或 `1-0038` 当作通用固定地址。
切换会重建下屏 input 设备；是否被当前 Gamescope / KWin 正确重新接收，必须实测。

## 包与兼容性

候选包包含 `manifest.json`、`armada_thor_ft5452.ko`、`touchfix.py`、许可证与模块源码 / 构建记录。
模块及清单只在显式操作后复制到 root 管理的 `/var/lib/armada-touch-fix/packages/<SHA256>/`，旧包保留。
工具不会下载网络代码；正式发布的可信下载与图形更新入口尚未实现。

每次启用都核对架构、内核 release、运行配置 SHA-256、`/sys/kernel/notes` SHA-256、模块名、vermagic 和文件校验和。
因此同名 `7.2.6` 的其他构建也会被拒绝。系统更新后继续使用官方更新源；不匹配时保持原厂驱动，等待相应的新包。
此机制不提供跨内核 ABI 保证，也不使用强制加载、版本检查绕过或签名检查绕过。

目前包只支持以下内核指纹：

```text
kernel notes: 868b1eab0643a777197361333300dea114aabf6ae65549c4750b11e8a0f18775
kernel config: 3cae56750274cbd5b90a788335389dfbd38ad9fcb526505593ee878dc208a04f
```

## 操作入口

<a id="settings-controls"></a>

### 可选设置入口

当前应用源码提供 **设置 → 试验性功能**。应用仍以普通用户运行，普通安装器 / 应用包仍不包含内核模块和这些实验脚本。先单独取得可信、精确匹配内核的模块包，再从本仓库显式准备 root 管理的可选图形组件：

```bash
sudo python3 extras/thor-touch-driver/install_gui.py /path/to/module-package
python3 -I -B /var/lib/armada-touch-fix-ui/gui_bridge.py status
```

准备时校验模块包与运行内核，保存到原有 root 管理的模块仓库，并只安装 `/var/lib/armada-touch-fix-ui/` 中的元数据和控制代码。**不会更换当前驱动**，不增加服务 / polkit / sudoers 规则、不配置开机加载、不替换启动文件。普通应用更新或卸载保留这个独立 root 组件。

设置页仅在打开或手动刷新时读取状态。指纹匹配后，“启用修复（到重启）”和“恢复原厂驱动”均需要二次确认及系统管理员认证。未保存的输入设置、正在进行的更新 / 卸载会阻止操作。独立的普通用户任务与应用更新共用操作锁，先关闭本面板释放虚拟输入，经 `pkexec` 调用固定的 root 管理入口；取消或普通失败后也重新打开面板。入口不接受 GUI 提供的模块 / 脚本路径，再次校验固定包，并只重新绑定下屏。root 命令等待有上限；内核卡死或 panic 仍需要重启。

切换前请保存并退出游戏。状态检查与真实触摸验收分开，操作成功不代表所有手势、长期使用或休眠恢复均已验证。设置页外没有后台轮询，默认不开机加载。系统更新导致指纹不同会拒绝启用；已有模块生效时仍可恢复原厂。终端回退入口：

```bash
sudo python3 -I -B /var/lib/armada-touch-fix-ui/gui_bridge.py revert
```

最近一次任务结果保留在 `~/.local/state/thor-panel/driver.json`，并尝试发送桌面通知；重新打开驱动页查看实际状态。准备和操作均不修改个人输入偏好、游戏、Steam 或官方显示服务。

在候选包目录中查看状态及只读计划，不需要 sudo：

```bash
python3 -B touchfix.py status
python3 -B touchfix.py plan .
```

首次只在已保存并退出游戏、掌机保持唤醒且 SSH 可用时进行前台限时试验：

```bash
sudo python3 -B touchfix.py trial . --experimental --seconds 90
```

工具正常运行时，90 秒后恢复原厂驱动；Ctrl+C、SIGTERM 或 SIGHUP 也进入回退。
试验进程持有操作锁，不要从另一终端与它同时更新 / 回退。不要关闭 SSH 窗口代替正常结束。
试验前停止本应用以释放虚拟输入，切换成功后再打开面板；不需要改动官方上下屏服务。

确认真实试验通过后，可显式启用至下次重启，或用同一入口更新兼容的新包：

```bash
sudo python3 -B touchfix.py apply . --experimental
sudo python3 -B touchfix.py revert --experimental
```

更新先将下屏交回原厂驱动并卸载旧模块，再加载新模块；普通加载、probe 或输入创建失败时尝试恢复原厂驱动。
`state.json` 先记录 pending，再进行设备操作，失败不会被标记为 active。无法恢复时明确记录 `recovery-needed`。
这些是用户态恢复机制，**内核卡死或 panic 时无法执行回退**；此时需要手动重启。

没有安装开机加载规则、udev 规则、systemd 服务、sudoers 规则，也不改内核 / DTB / initramfs / ABL / `KERNEL`。
正常重启会重新使用原启动内核及原厂驱动。外置模块仍在内核地址空间运行，限定设备匹配不能隔离内核崩溃；
加载后也可能留下 out-of-tree taint 标记，直到重启。首次试验不应在未保存的游戏中进行。

## 离线构建与符号来源

使用匹配的 ARM64 GCC 16.2.1 环境和本机配置，在独立工作区解包已校验的 Linux 7.2.6，应用 Armada 192 份补丁及候选，共 193 份。
`build-offline.sh` 只执行 `modules_prepare` 和这个外置模块的编译，不续跑此前停止的整内核构建，不安装产物。
需要准备下列只读输入与独立输出路径，脚本可通过同名环境变量重定向：

| 路径 | 内容 |
| --- | --- |
| `/kernel-cache` | 已校验的 `linux-7.2.6.tar.xz` |
| `/kernel-recipe` | Armada c3d178c 内核配方，加本候选的 series |
| `/module-source` | 本目录 |
| `/module-work` | 独立构建工作区 |
| `/output` | `running.config`、只读采集的 `host-exports.json` 及生成产物 |

官方包没有 kernel-devel 或完整 `Module.symvers`。本机 `CONFIG_MODVERSIONS=n`，故 `export_subset.py` 将每个导入名与
运行内核 `__ksymtab` 名称和准确源码的 EXPORT_SYMBOL / GPL / namespace 声明逐项核对，生成**仅含所需符号的子集**。
`_dev_err` / `_dev_warn` 的宏生成导出单独核对宏体和调用；模块自己的 `__this_module` 由 MODPOST 生成，不当作内核导出。
找不到、来源冲突或 namespace 宏无法解析时构建失败；没有伪造 CRC、忽略未知符号或启用 `KBUILD_MODPOST_WARN`。
若未来开启 MODVERSIONS，必须改用匹配内核的正式构建导出表，当前子集方法拒绝工作。

未生成模块 BTF，因为没有完整 `vmlinux`；构建器记录了该跳过信息。编译与符号名称核对不能替代真实加载和 ABI 验证。
改成模块后的源码包含匹配约束，来源校验见 `source.json`，原补丁见项目 docs；运行内核仍保持不变。

开发检查（不会执行真实模块命令或写 sysfs）：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s extras/thor-touch-driver -p 'test_*.py' -v
```

参考：[Linux 外置模块](https://docs.kernel.org/kbuild/modules.html)、
[驱动绑定](https://docs.kernel.org/driver-api/driver-model/binding.html)、[Armada Issue #757](https://github.com/armada-os/armada/issues/757)。

游戏模式下屏 KDE 使用独立 D-Bus 会话。驱动任务启动器需连接实际用户服务管理器，不能继承下屏私有总线；仅将它转交独立任务用于桌面通知 / 认证。若提示任务启动失败，且没有 `thor-panel-driver` 单元或 `driver.json`，说明尚未尝试切换驱动。

## 被动读帧诊断

`trace_reads.py` 是独立实验诊断工具，不进入应用包。它在确认的 Thor 下屏 FT5452 上，通过自己的临时 tracefs 实例记录现有 regmap 读取、I2C 写入／读取请求、实际返回数据及事务结果，不发起总线事务或输入，不更改驱动、模块、开机设置或全局追踪配置。操作 tracefs 需要 root；默认采集 180 秒，最长 600 秒，流数据上限 32 MiB。正常退出／信号结束会禁用并移除私有实例。追踪本身会增加开销，因此记录的是插桩后的耗时。记录数据载荷会增加体积；针对特定交叉动作宜短采集 10–20 秒，不能假定默认时长一定容纳得下。

先安排好自有诊断窗口中的受控手动测试，再运行：

```bash
sudo python3 -I -B extras/thor-touch-driver/trace_reads.py collect --seconds 180 --output /tmp/thor-read-trace.txt
python3 -B extras/thor-touch-driver/trace_reads.py decode /tmp/thor-read-trace.txt > /tmp/thor-read-frames.json
```

输出路径必须尚不存在。`--done /path/to/marker` 可在测试窗口关闭时结束采集。解码器保留不完整／非顺序读取、触点事件标记／ID／坐标及失败事务；默认完整帧长度为 33 个寄存器，与该 FT5452 驱动的五触点布局一致。数据包自洽本身不能证明物理静止，也不能排除跨帧采集；没有能区分原因的实验时，不应把寄存器变化直接认定为手部移动、传感器串扰或读取路径缺陷。

新增的 `messages` 列表独立于 regmap 帧，保留 I2C 写入／返回消息的序号、地址、标志、声明长度和数据字节。载荷缺失、格式错误或截短时，`payload_complete` 为 `false`。没有这些事件的历史采集保持空列表，不能根据 regmap 数据推定缺失的返回字节。把差异归因到控制器之前，应先对照寄存器指针写入、实际返回值和独立解码结果。主机完整事务成功，不代表控制器保证锁存了同一次传感器扫描。本工具不切换工厂模式、不读取电容矩阵，也不验证通用 EDT 调参寄存器对 FT5452 是否适用。
