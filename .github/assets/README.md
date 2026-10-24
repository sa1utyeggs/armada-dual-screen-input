English · [简体中文](README.zh-CN.md)

# Repository artwork

- `social-preview.svg` / `social-preview.png`: GitHub sharing card. Uses the current application icon from `assets/icons/armada-dual-screen-input.svg`; the PNG is rendered with `rsvg-convert`. No Valve artwork is included. Armada mark provenance is recorded in `THIRD_PARTY.md`.
- `interface-demo.mp4`: 46-second, 720p H.264 introduction rendered from the approved Remotion v10 composition on 2026-10-24. Combines existing dual-screen recordings (Chinese app interface, Steam and game footage) with bilingual captions and a 9-second illustrated positioning-touch ending. The cartoon-glove and apple artwork was generated with ImageGen; source artwork and prompts are retained in the external Remotion project. Recorded third-party interfaces and game artwork retain their respective rights; they are not covered by this repository's MIT license. Re-editing the footage is not new device or game-compatibility validation.
- `interface-keyboard-mouse-v10.gif`: keyboard-input and mouse-operation preview derived from 0.4–24.6 seconds of the full demo on 2026-10-25. The 24.2-second GIF is 896×504 at 10 fps, with 96 colors and continuous looping.
- `interface-gameplay-gesture-v10.gif`: Slay the Spire 2 gameplay and gesture preview derived from 28.6–46 seconds of the full demo on 2026-10-25. The 17.4-second GIF uses the same size, frame rate, palette limit and looping as the keyboard/mouse preview. It includes the complete 9-second ending without lower-left step explanations. The ending explains input behavior; it is not a recording of an application grabbing an apple. The contact hand keeps one extended-middle silhouette; curling the middle finger into the palm represents leaving the touch surface.
- `interface-demo-poster.png`: still poster derived from the full demo. Both README previews display as independent GIFs; the full MP4 is available through a separate raw-file download link.
- `keyboard-preview.png`: offscreen keyboard/trackpad rendering from 2026-10-20, with a fixed `nihao` pinyin example. Illustrates the input surface, rather than a live desktop session.
- `touch-preview.png`: offscreen direct-touch page rendering from 2026-10-21. Header statistics are placeholder values, not device measurements. Does not establish game compatibility or real multi-touch acceptance.

These repository presentation assets are excluded from the application bundle. Regenerate the social card after changing the application icon; retain source attribution.
