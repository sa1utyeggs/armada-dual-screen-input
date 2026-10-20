# Third-party components

The project's own code is MIT licensed. This does not relicense these components:

| Component | License and source |
| --- | --- |
| Ratatoskr snapshot | MIT; [LICENSE](vendor/ratatoskr/LICENSE), [credits](vendor/ratatoskr/CREDITS.md), and [source/local changes](vendor/ratatoskr/UPSTREAM). Fixed upstream commit `24471899b5923b73f0ecb7ae67aba54ad7b6d73e`. |
| gtk-layer-shell runtime in aarch64 bundles | The Fedora package's LGPL and MIT license texts are copied unchanged into `runtime/usr/share/licenses/gtk-layer-shell/`. [Project](https://github.com/wmww/gtk-layer-shell), [matching Fedora source RPM](https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Everything/source/tree/Packages/g/gtk-layer-shell-0.10.0-1.fc44.src.rpm). The shared library is private to this application and remains replaceable. |
| Optional Thor driver experiment, repository only | GPL-2.0; [license](https://github.com/sa1utyeggs/armada-dual-screen-input/blob/main/extras/thor-touch-driver/LICENSE) and [source/provenance](https://github.com/sa1utyeggs/armada-dual-screen-input/blob/main/extras/thor-touch-driver/source.json). Excluded from application bundles and the installer. |

gtk-layer-shell is taken from an unmodified Fedora binary RPM with a pinned SHA-256. Package URL, checksum and selected files are recorded in `packaging/dependencies/gtk-layer-shell-aarch64.json`. Release bundles include its source-package reference and license texts. No system loader configuration is changed.

Steam-style controls are independently drawn; no Valve artwork is bundled.
