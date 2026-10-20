# Thor 下屏驱动独立模块（实验）

2026-10-20。只用于 AYN Thor 下屏 FT5452 的可选驱动试验，不是通用双屏应用的默认依赖。
应用本身不会导入、加载或安装本目录的代码；原桌面入口与自启动设置保持不变。

## 当前验证

- 完成针对 Armada `20261010.c3d178c` / Linux `7.2.6` / AArch64 的模块编译。
- 剥离调试信息后的模块为 39,648 字节，`vermagic` 为 `7.2.6 SMP preempt mod_unload aarch64`。
- 69 个未定义导入符号全部与运行内核导出名及对应源码的导出声明核对；MODPOST、最终链接通过。
- 18 项工具与符号核对测试通过，覆盖版本拒绝、仅操作下屏、加载 / probe / 输入失败回退、更新顺序与中断试验回退。
- 掌机仅运行过 `status`、`plan`，返回匹配；当时上下屏均由原厂 `edt_ft5x06` 驱动，模块未加载，没有创建持久工具状态。
- **真实加载、下屏热插拔进入 Gamescope、触点修复效果和休眠恢复尚未验证。** 不将编译成功称作修复完成。

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
