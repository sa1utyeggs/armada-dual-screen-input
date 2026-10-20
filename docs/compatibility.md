# 兼容范围与已知问题

| 项目 | 当前范围 |
| --- | --- |
| 实机 | AYN Thor，16GB / 512GB，Armada 安装在内部存储 |
| 已测试系统 | Armada `20261010.c3d178c`、Fedora 44 基础、Linux 7.2.6、aarch64 |
| 显示模式 | Steam Game Mode；使用官方 `armada-plasma-bottom` 会话 |
| Desktop Mode | 默认关闭；桌面图标可启动后台等待 Game Mode |
| 其他双屏设备 | 项目目标，但尚未实测，不承诺直接可用 |
| 实验触摸驱动 | 不属于应用安装内容；只在维护者当前 Thor 上测试 |

安装器默认检查 Armada、aarch64、Fedora 44 基础和 Thor 设备树。其他 Armada 双屏设备可在阅读限制后显式使用 `--allow-untested` 参与开发；该选项不会赋予 root 权限，也不会适配未知的屏幕尺寸或方向。

应用当前仍有 Thor 的屏幕尺寸、输出选择和设备监控假设。新机型应先收集显示会话/尺寸与输入路由，再新增适配及实机结果，不应通过改名称宣称通用。

- 定位触摸：第一指移动圆环，第二指确认一个上屏触点。应用会在切换目标时释放旧触点，等待焦点稳定及全部抬手后恢复。
- 游戏模式的部分触摸策略会把原生触摸转换为鼠标左键；不承诺所有游戏接收原生多点触摸。
- 已验证 Steam 右侧菜单关闭后的圆环自动恢复，用户确认移除正常切换的额外 1.5 秒等待后明显更快且操作正常。
- 《杀戮尖塔2》时间线出现过间歇重连提示，下一轮未复现，原因仍待定位，不能标为修复完成。
- Thor 原厂 FT5452 曾出现物理触点残留，独立候选模块通过一次 90 秒释放/拖动与回退测试。长期、同时落指、休眠恢复仍待验证；[Issue #757 的进展](https://github.com/armada-os/armada/issues/757#issuecomment-6284200266)。安装应用不代表已修复物理驱动。
- Steam 键盘联动依赖客户端内部接口；不可用时保留原生键盘，切页/收起/退出后恢复。Steam 更新可能需要重新验证。
- 中文字体使用系统 Pango/Noto CJK，未打包个人配置或字体缓存。

完整历史证据见源码仓库的 [定位触摸记录](https://github.com/sa1utyeggs/armada-dual-screen-input/blob/main/docs/position-touch.md)、[驱动研究](https://github.com/sa1utyeggs/armada-dual-screen-input/blob/main/docs/thor-ft5452-contact-lifecycle.md)和[历史汇总](https://github.com/sa1utyeggs/armada-dual-screen-input/blob/main/docs/history.md)。短时用户验收不等同于长期稳定性验证。
