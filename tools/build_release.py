#!/usr/bin/env python3
"""Create a checksum-verified offline aarch64 bundle; no device deployment."""
import argparse
from pathlib import Path
import tempfile

from release import APP, archive, digest, prepare, version
from build_click_installer import build

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=root / 'dist')
parser.add_argument('--runtime-rpm', type=Path)
parser.add_argument('--offline', action='store_true')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
name = f'{APP}-{version(root)}-aarch64'
with tempfile.TemporaryDirectory(prefix='ads-release-') as work:
    tree = Path(work) / name
    prepare(root, tree, runtime_rpm=args.runtime_rpm, cache=root / '.cache', offline=args.offline)
    target = args.output / (name + '.tar.gz')
    archive(tree, target)
(args.output / 'SHA256SUMS').write_text(digest(target) + '  ' + target.name + '\n')
launcher = build(root, args.output)
# Keep the app checksum single-entry: already installed updaters require it.
(args.output / 'INSTALLER-SHA256SUMS').write_text(digest(launcher) + '  ' + launcher.name + '\n')
print(target)
print(launcher)
