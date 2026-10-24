[English](README.md) · 简体中文

# 仓库展示素材

- `social-preview.svg` / `social-preview.png`：GitHub 分享卡片，使用 `assets/icons/armada-dual-screen-input.svg` 中的当前应用图标；PNG 由 `rsvg-convert` 生成，不含 Valve 素材。Armada 标识来源记录在 `THIRD_PARTY.md`。
- `interface-demo.mp4`：2026-10-24 从已确认的 Remotion v10 合成导出的 46 秒、720p H.264 介绍视频。结合已有的双屏录制画面（中文应用界面、Steam 与游戏画面）、中英双语字幕和 9 秒的定位触屏原理动画。卡通手套和苹果素材由 ImageGen 生成，原始素材和提示词保留在外部 Remotion 工程中。录制的第三方界面与游戏美术保留各自权利，不适用本仓库的 MIT 许可证；重新剪辑不代表新增设备或游戏兼容性验证。
- `interface-demo-preview-v10.gif` / `interface-demo-poster.png`：从上述完整视频提取的动态片段集锦和静态封面。16 秒动图包含完整的 9 秒结尾，已去除左下角步骤说明。README 动图链接到完整 MP4；结尾用于说明输入行为，并非应用抓取苹果的实录。接触期间始终保持同一个中指伸直的手型；中指收回掌心表示离开触摸表面。
- `keyboard-preview.png`：2026-10-20 离屏渲染的键盘/触控板，使用固定 `nihao` 拼音示例；展示输入区域，并非实时桌面会话。
- `touch-preview.png`：2026-10-21 离屏渲染的直接触屏页。顶部状态为占位数值，非设备测量，不代表游戏兼容或真实多指验收通过。

这些仓库展示素材不包含在应用离线包中。修改应用图标后重新生成分享卡片，并保留来源署名。
