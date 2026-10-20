#!/usr/bin/env bash
# Standalone GitHub downloader. Works from a downloaded file or curl | bash.
set -euo pipefail
command -v python3 >/dev/null 2>&1 || { echo '需要 Python 3；请在 Armada 桌面终端运行。' >&2; exit 1; }
python3 -B - "$@" <<'ADS_PYTHON'
"""Download one GitHub snapshot, then use its per-user installer."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = 'sa1utyeggs/armada-dual-screen-input'
ALLOWED_HOSTS = {'api.github.com', 'codeload.github.com'}
ARCHIVE_LIMIT = 32 * 1024 * 1024
EXPANDED_LIMIT = 128 * 1024 * 1024
REQUIRED = {'VERSION', 'install.sh', 'tools/manage.py', 'tools/release.py',
            'src/armada_dual_screen_input/__init__.py', 'vendor/ratatoskr/LICENSE',
            'packaging/dependencies/gtk-layer-shell-aarch64.json'}


class DownloadError(RuntimeError):
    pass


def checked_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise DownloadError('拒绝非 GitHub HTTPS 下载地址。')
    return parsed


class GitHubRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destination = checked_url(newurl)
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        if result is not None and destination.hostname != urllib.parse.urlsplit(req.full_url).hostname:
            result.remove_header('Authorization')
        return result


def download(url, target, *, token='', limit=ARCHIVE_LIMIT):
    parsed = checked_url(url)
    headers = {'User-Agent': 'armada-dual-screen-input-installer',
               'Accept': 'application/vnd.github+json'}
    if token and parsed.hostname == 'api.github.com':
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(GitHubRedirects())
    try:
        with opener.open(request, timeout=60) as response, Path(target).open('wb') as output:
            size = 0
            while chunk := response.read(128 * 1024):
                size += len(chunk)
                if size > limit:
                    raise DownloadError('GitHub 下载超出预期大小，已停止。')
                output.write(chunk)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise DownloadError('GitHub 返回 404：仓库尚未公开、引用不存在，或没有访问权限。') from None
        raise DownloadError('GitHub 下载失败（HTTP %s）；请稍后重试。' % error.code) from None
    except urllib.error.URLError:
        raise DownloadError('无法连接 GitHub；请检查网络后重试。') from None


def revision(ref, directory, token):
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,199}', ref)
            or any(part in ('', '.', '..') for part in ref.split('/'))):
        raise DownloadError('无效的 GitHub 分支、标签或提交。')
    metadata = directory / 'commit.json'
    download('https://api.github.com/repos/' + REPOSITORY + '/commits/'
             + urllib.parse.quote(ref, safe=''), metadata, token=token, limit=1024 * 1024)
    sha = json.loads(metadata.read_text()).get('sha', '')
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise DownloadError('GitHub 未返回有效提交，已停止。')
    return sha


def extract_snapshot(archive, destination):
    """Validate every member before writing; never extract links or driver extras."""
    with tarfile.open(archive, 'r:gz') as source:
        roots, names, planned, total = set(), set(), [], 0
        for count, member in enumerate(source, 1):
            if count > 8192:
                raise DownloadError('源码压缩包文件数异常。')
            path = PurePosixPath(member.name)
            if (path.is_absolute() or not path.parts or '..' in path.parts
                    or '\\' in member.name or any(ord(ch) < 32 for ch in member.name)
                    or not (member.isdir() or member.isfile())):
                raise DownloadError('源码压缩包包含不安全路径或特殊文件。')
            normalized = str(path)
            if normalized in names:
                raise DownloadError('源码压缩包包含重复路径。')
            names.add(normalized); roots.add(path.parts[0])
            if member.isfile():
                total += member.size
                if member.size < 0 or total > EXPANDED_LIMIT:
                    raise DownloadError('源码解包大小异常。')
                relative = PurePosixPath(*path.parts[1:])
                # The driver prototype, GitHub automation and development helpers
                # are not needed by an application installation.
                if (len(path.parts) > 1 and (relative.parts[0] in ('src', 'vendor', 'assets', 'packaging', 'docs')
                        or str(relative) in ('VERSION', 'README.md', 'CHANGELOG.md', 'LICENSE', 'THIRD_PARTY.md', 'install.sh', 'uninstall.sh')
                        or str(relative) in ('tools/manage.py', 'tools/release.py', 'tools/run.py'))):
                    planned.append((member, relative))
        if len(roots) != 1 or not REQUIRED.issubset({str(path) for _, path in planned}):
            raise DownloadError('下载的源码缺少安装器；请确认所选分支已经包含新版安装流程。')
        files = {path for _, path in planned}
        if any(parent in files for path in files for parent in path.parents):
            raise DownloadError('源码压缩包包含冲突路径。')
        # No filesystem writes happen until the complete archive has passed.
        for member, relative in planned:
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as data, target.open('wb') as output:
                shutil.copyfileobj(data, output)
    return destination


def main():
    parser = argparse.ArgumentParser(description='从 GitHub 自动下载并安装虚拟键鼠；无需 Git/SSH/sudo。')
    parser.add_argument('--ref', default='main', help='GitHub 分支、标签或提交（默认 main）')
    parser.add_argument('--dry-run', action='store_true', help='下载临时源码并显示安装计划，不安装')
    parser.add_argument('--no-desktop', action='store_true')
    parser.add_argument('--allow-untested', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'linux' or os.geteuid() == 0 or platform.machine() != 'aarch64':
        raise DownloadError('请在 ArmadaOS ARM64 的普通桌面用户终端执行，不要加 sudo。')
    release = Path('/etc/os-release').read_text()
    if not re.search(r'^ID=[\"\']?armada[\"\']?$', release, re.MULTILINE):
        raise DownloadError('此安装入口适用于 ArmadaOS。')
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN') or ''
    with tempfile.TemporaryDirectory(prefix='ads-download-') as directory:
        work = Path(directory)
        sha = revision(args.ref, work, token)
        print('正在下载虚拟键鼠（提交 %s）……' % sha[:12], flush=True)
        archive = work / 'source.tar.gz'
        download('https://api.github.com/repos/' + REPOSITORY + '/tarball/' + sha, archive, token=token)
        source = extract_snapshot(archive, work / 'source')
        options = [flag for flag, enabled in (('--dry-run', args.dry_run), ('--no-desktop', args.no_desktop),
                                              ('--allow-untested', args.allow_untested)) if enabled]
        env = dict(os.environ)
        env.pop('GH_TOKEN', None); env.pop('GITHUB_TOKEN', None)
        result = subprocess.run(['bash', str(source / 'install.sh'), *options], cwd=source, env=env)
        if result.returncode:
            return result.returncode
    if not args.dry_run:
        print('安装完成。请从桌面或应用菜单打开“虚拟键鼠”；默认不开机自启。')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (DownloadError, OSError, ValueError, tarfile.TarError):
        error = sys.exc_info()[1]
        # Do not dump a response body, signed download URL, or authentication header.
        print('虚拟键鼠安装失败：' + (str(error) if isinstance(error, DownloadError) else '下载或源码检查失败，请重试。'), file=sys.stderr)
        raise SystemExit(1)
ADS_PYTHON
