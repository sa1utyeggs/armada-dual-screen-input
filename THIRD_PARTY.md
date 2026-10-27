English · [简体中文](THIRD_PARTY.zh-CN.md)

# Third-party components

The project's own code is MIT licensed. This does not relicense these components:

| Component | License and source |
| --- | --- |
| Ratatoskr snapshot | MIT; [LICENSE](vendor/ratatoskr/LICENSE), [credits](vendor/ratatoskr/CREDITS.md), and [source/local changes](vendor/ratatoskr/UPSTREAM). Fixed upstream commit `24471899b5923b73f0ecb7ae67aba54ad7b6d73e`. |
| gtk-layer-shell runtime in aarch64 bundles | The Fedora package's LGPL and MIT license texts are copied unchanged into `runtime/usr/share/licenses/gtk-layer-shell/`. [Project](https://github.com/wmww/gtk-layer-shell), [matching Fedora source RPM](https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Everything/source/tree/Packages/g/gtk-layer-shell-0.10.0-1.fc44.src.rpm). The shared library is private to this application and remains replaceable. |
| Optional system libxkbcommon and xkeyboard-config | System keyboard mapping API/data, not bundled. [libxkbcommon license](https://github.com/xkbcommon/libxkbcommon/blob/master/LICENSE). No global keyboard layout is changed. |
| Optional system libpinyin and dictionary | GPL-3.0-or-later; [source/license](https://github.com/libpinyin/libpinyin). Not bundled or downloaded by the installer. Loaded only in the separate, optional `keyboard_worker.py` process. The panel exchanges transient text/candidate data over private anonymous pipes; the project's MIT license does not relicense libpinyin or its dictionaries. |
| Optional Thor driver experiment, repository only | GPL-2.0; [license](https://github.com/sa1utyeggs/armada-dual-screen-input/blob/main/extras/thor-touch-driver/LICENSE) and [source/provenance](https://github.com/sa1utyeggs/armada-dual-screen-input/blob/main/extras/thor-touch-driver/source.json). Excluded from application bundles and the installer. |

gtk-layer-shell is taken from an unmodified Fedora binary RPM with a pinned SHA-256. Package URL, checksum and selected files are recorded in `packaging/dependencies/gtk-layer-shell-aarch64.json`. Release bundles include its source-package reference and license texts. No system loader configuration is changed.

Steam-style controls are independently drawn; no Valve artwork is bundled.

The application icon adapts the Armada sail mark from
[armada-os/armada](https://github.com/armada-os/armada/blob/86d29b9ba1c660fcfbc43d80d9def02765c41082/.github/assets/armada-mark-white.svg).
The Armada name and mark retain their original ownership; the project MIT license
does not relicense that mark. The surrounding icon and input symbols are drawn for this application.

## Project-generated glove marker artwork

The optional positioning marker uses [aiming A](assets/markers/glove/idle.png) and [held F](assets/markers/glove/pressed.png). The artwork was generated and revised with the built-in ImageGen tool from the project's generated introduction-video glove illustration, then visually selected by the user on 2026-10-26. It was not extracted from the recorded Steam or game footage. The two production PNGs share a logical hotspot and are prepared on 64-pixel transparent canvases; pose changes do not change input coordinates.

Source artwork, generation/edit prompts and comparison previews are retained as local design evidence under `outputs/glove-v7/`. Those high-resolution sources and discarded drafts are excluded from application bundles; only the four runtime marker PNGs for the glove and pixel hand are included alongside the application icons. The introduction-video asset provenance remains in [.github/assets/README.md](.github/assets/README.md). This artwork record does not replace the licenses or ownership of any third-party component listed above.

## Pixel hand and procedural reticle

The pixel-hand positioning style uses `assets/markers/pixel_hand/idle.png` and `assets/markers/pixel_hand/pressed.png`, on 64-pixel transparent canvases. These two-state assets were generated with the built-in ImageGen tool from the user's approved second concept image, then prepared for the application's marker path. They are a pixel hand, not the discarded cat-paw concept. The source PNG, generation prompts, normalization records and comparison evidence remain local under `outputs/pixel-hand-v1/`; discarded alternatives are excluded from bundles.

The sci-fi reticle is defined as programmatic Cairo geometry in [the marker appearance implementation](src/armada_dual_screen_input/marker_appearance.py), with a fixed center hotspot on a 64-pixel canvas. Its two states are rasterized through the same prepared sprite path as the other styles. No downloaded artwork or AI-generated raster asset is used for the reticle, and no reticle PNG is added to the package.


The Game Mode text adapter implements only the version-1 subset of Valve's
[private Gamescope input-method protocol](https://github.com/ValveSoftware/gamescope/blob/master/protocol/gamescope-input-method.xml).
It is not a stable cross-compositor Wayland API. No Valve source or protocol XML
is bundled; unknown protocol versions and unavailable routes fail closed.
