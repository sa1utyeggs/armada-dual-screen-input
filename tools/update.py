#!/usr/bin/env python3
"""Independent per-user update worker; survives a restart of thor-panel.service."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from armada_dual_screen_input.updates import (
    UpdateError, latest_release, newer, prepare_download, process_identity, state_path,
)
from release import PackageError, verify
from manage import Installer, Paths, atomic, host_check, runtime_check


def write_status(phase, message, *, tag='', path=None):
    value = {'schema': 1, 'phase': phase, 'message': message, 'tag': tag,
             'pid': os.getpid(), 'identity': process_identity(os.getpid())}
    atomic(path or state_path(), (json.dumps(value, ensure_ascii=False) + '\n').encode(), 0o600)


def perform(tag, *, fetch=latest_release, prepare=prepare_download, installer=None,
            paths=None, status=write_status, check_host=host_check, check_runtime=runtime_check):
    paths = paths or Paths.environment()
    installer = installer or Installer(paths)
    current = paths.root / 'current'
    if current.resolve() != ROOT or not paths.state.is_file():
        raise UpdateError('更新仅适用于安装器管理的应用')
    check_host()
    current_manifest = verify(ROOT)
    status('checking', '正在核对最新正式版本…', tag=tag)
    release = fetch()
    if release.tag != tag:
        raise UpdateError('最新版本已变化，请重新检查更新')
    if not newer(release.version, current_manifest['version']):
        status('success', '当前已是最新正式版', tag=tag)
        return
    with tempfile.TemporaryDirectory(prefix='thor-panel-update-') as directory:
        status('downloading', '正在下载并校验安装包…', tag=tag)
        bundle = prepare(release, Path(directory))
        manifest = verify(bundle)
        if (manifest['version'] != release.version
                or not re.fullmatch(r'[0-9a-f]{40}', manifest.get('source_revision', ''))):
            raise UpdateError('安装包版本或来源标识无效')
        if not all(value is True for value in check_runtime(bundle).values()):
            raise UpdateError('新版本依赖不满足，原版本未改变')
        status('installing', '正在安装，面板会短暂关闭并重新打开…', tag=tag)
        # A second updater or manual installer may have changed current during download.
        if current.resolve() != ROOT:
            raise UpdateError('应用版本已变化，请重新检查更新')
        result = installer.install(bundle)
        message = '已更新至 ' + tag + ('，面板已重新打开' if result['started'] else '，下次打开时生效')
        status('success', message, tag=tag)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-tag', required=True)
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise UpdateError('请使用普通用户更新，不要 sudo')
    paths = Paths.environment()
    if not paths.root.is_dir() or paths.root.is_symlink():
        raise UpdateError('未找到有效的用户安装')
    # Separate from the installer's transactional lock; covers download as well.
    lock_path = paths.root / 'update.lock'
    if lock_path.is_symlink():
        raise UpdateError('更新锁路径无效')
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            perform(args.expected_tag, paths=paths)
        except Exception as error:
            message = str(error) if isinstance(error, (UpdateError, PackageError)) else '更新失败，请检查网络或稍后重试'
            write_status('error', message, tag=args.expected_tag)
            raise SystemExit(1)


if __name__ == '__main__':
    main()
