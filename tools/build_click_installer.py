#!/usr/bin/env python3
"""Generate a self-contained KDE launcher from a small, explicit source allowlist."""
import argparse
import base64
import io
from pathlib import Path
import zipfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))
from armada_dual_screen_input.ui_catalogs import EN_US, ZH_CN

NAME = 'Install-Armada-Dual-Screen-Input.desktop'
MODULES = ('tools/click_install.py', 'tools/release.py', 'tools/manage.py', 'tools/desktop_cache.py',
           'src/armada_dual_screen_input/i18n.py', 'src/armada_dual_screen_input/ui_catalogs.py',
           'src/armada_dual_screen_input/updates.py', 'src/armada_dual_screen_input/installer_release.py')


def launcher(root):
    root = Path(root)
    buffer = io.BytesIO()
    files = {'__main__.py': b'from click_install import main\nraise SystemExit(main())\n',
             'armada_dual_screen_input/__init__.py': b''}
    for name in MODULES:
        source = root / name
        if source.is_symlink() or not source.is_file():
            raise ValueError('Missing/unsafe installer source: ' + name)
        relative = name.removeprefix('tools/').removeprefix('src/')
        files[relative] = source.read_bytes()
    # Fixed timestamps/permissions; no checkout, settings, runtime or driver snapshot.
    files['LICENSE'] = (root / 'LICENSE').read_bytes()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    payload = base64.b64encode(buffer.getvalue()).decode('ascii')
    # A Python context manager keeps the embedded helper alive until GTK and the
    # installation worker exit, then removes it. No shell, curl pipeline or cwd.
    code = ("import base64,pathlib,runpy,tempfile\n"
            "with tempfile.TemporaryDirectory(prefix='ads-click-helper-') as directory:\n"
            " p=pathlib.Path(directory)/'installer.pyz'\n"
            f" p.write_bytes(base64.b64decode('{payload}'))\n"
            " runpy.run_path(str(p),run_name='__main__')\n")
    encoded = base64.b64encode(code.encode()).decode('ascii')
    command = f"import base64;exec(base64.b64decode('{encoded}'))"
    if len(command) > 120000:
        raise ValueError('Installer payload exceeds the portable command argument limit')
    return ('#!/usr/bin/env xdg-open\n[Desktop Entry]\nVersion=1.0\nType=Application\n'
            f"Name={EN_US['installer.desktop_name']}\nName[zh_CN]={ZH_CN['installer.desktop_name']}\n"
            f"Comment={EN_US['installer.desktop_comment']}\n"
            f"Comment[zh_CN]={ZH_CN['installer.desktop_comment']}\n"
            f'Exec=/usr/bin/python3 -I -B -c "{command}"\n'
            'Icon=system-software-install\nTerminal=false\nCategories=Utility;\nStartupNotify=false\n')


def build(root, output):
    target = Path(output) / NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(launcher(root), encoding='utf-8')
    target.chmod(0o755)
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent.parent / 'dist')
    args = parser.parse_args()
    print(build(Path(__file__).resolve().parent.parent, args.output))
