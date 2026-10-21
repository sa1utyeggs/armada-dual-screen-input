"""Official stable release discovery and bounded, verified package downloads."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import time
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPO = 'sa1utyeggs/armada-dual-screen-input'
API = 'https://api.github.com/repos/' + REPO + '/releases/latest'
APP = 'armada-dual-screen-input'
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
STABLE = r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\+[0-9A-Za-z.-]+)?'


class UpdateError(Exception):
    pass


class HTTPSRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urlsplit(newurl)
        if url.scheme != 'https' or url.hostname not in (
                'github.com', 'api.github.com', 'release-assets.githubusercontent.com',
                'objects.githubusercontent.com'):
            raise UpdateError('下载被重定向到非官方地址')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url):
    return build_opener(HTTPSRedirects()).open(Request(url, headers={
        'User-Agent': APP + '-updater', 'Accept': 'application/vnd.github+json',
    }), timeout=15)


def limited_read(response, limit):
    data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError('更新响应超过大小限制')
    return data


def newer(latest, current):
    match = re.fullmatch(STABLE, latest)
    old = re.match(r'^(\d+)\.(\d+)\.(\d+)(?:[-+]|$)', current)
    if not match or not old:
        raise UpdateError('无法比较版本号')
    new_key, old_key = tuple(map(int, match.groups())), tuple(map(int, old.groups()))
    return new_key > old_key or (new_key == old_key and '-' in current.split('+', 1)[0])


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    archive_url: str
    checksum_url: str
    archive_sha: str
    checksum_sha: str
    archive_size: int
    checksum_size: int

    @property
    def filename(self):
        return f'{APP}-{self.version}-aarch64.tar.gz'


def parse_release(data):
    tag = data.get('tag_name', '') if isinstance(data, dict) else ''
    if (not isinstance(tag, str) or not 2 <= len(tag) <= 65
            or not tag.startswith('v') or not re.fullmatch(STABLE, tag[1:])
            or data.get('draft') is not False or data.get('prerelease') is not False):
        raise UpdateError('未找到有效的正式版本')
    version = tag[1:]
    filename = f'{APP}-{version}-aarch64.tar.gz'
    assets = data.get('assets', [])
    if not isinstance(assets, list):
        raise UpdateError('发布附件列表无效')
    selected = []
    for name, limit in ((filename, MAX_ARCHIVE), ('SHA256SUMS', 65536)):
        matches = [a for a in assets if isinstance(a, dict) and a.get('name') == name]
        if len(matches) != 1:
            raise UpdateError('该版本缺少完整安装包或校验文件')
        asset = matches[0]
        if not isinstance(asset.get('browser_download_url'), str):
            raise UpdateError('发布附件的地址无效')
        url = urlsplit(asset['browser_download_url'])
        digest = asset.get('digest', '')
        size = asset.get('size')
        if (url.scheme != 'https' or url.netloc != 'github.com' or url.query or url.fragment
                or unquote(url.path) != f'/{REPO}/releases/download/{tag}/{name}'
                or asset.get('state') != 'uploaded'
                or type(size) is not int or not 0 < size <= limit
                or not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest)):
            raise UpdateError('发布附件的地址、大小或校验信息无效')
        selected.append((asset['browser_download_url'], digest[7:], size))
    return Release(version, tag, selected[0][0], selected[1][0], selected[0][1], selected[1][1],
                   selected[0][2], selected[1][2])


def latest_release(*, opener=open_url):
    try:
        with opener(API) as response:
            return parse_release(json.loads(limited_read(response, 1024 * 1024)))
    except UpdateError:
        raise
    except Exception as error:
        raise UpdateError('检查更新失败，请检查网络后重试') from error


def download(url, target, size, expected, *, opener=open_url):
    digest = hashlib.sha256()
    received = 0
    deadline = time.monotonic() + 180
    with opener(url) as response, Path(target).open('xb') as output:
        while True:
            block = response.read(128 * 1024)
            if time.monotonic() > deadline:
                raise UpdateError('下载超时，请稍后重试')
            if not block:
                break
            received += len(block)
            if received > size:
                raise UpdateError('下载大小与发布信息不一致')
            digest.update(block)
            output.write(block)
    if received != size or digest.hexdigest() != expected:
        raise UpdateError('下载文件校验失败，原版本未改变')


def prepare_download(release, work, *, opener=open_url):
    """Download/extract only. The caller verifies the manifest before installing."""
    work = Path(work)
    archive, checksum = work / release.filename, work / 'SHA256SUMS'
    download(release.checksum_url, checksum, release.checksum_size, release.checksum_sha, opener=opener)
    download(release.archive_url, archive, release.archive_size, release.archive_sha, opener=opener)
    lines = checksum.read_text().strip().splitlines()
    if len(lines) != 1 or lines[0].split() != [release.archive_sha, release.filename]:
        raise UpdateError('SHA256SUMS 与安装包不匹配')
    prefix = release.filename.removesuffix('.tar.gz')
    with tarfile.open(archive) as reader:
        members = []
        names = set()
        total = 0
        for member in reader:
            members.append(member)
            if len(members) > 4097:
                raise UpdateError('安装包文件数量无效')
            path = PurePosixPath(member.name)
            total += member.size
            if (not member.isfile() or path.is_absolute() or '..' in path.parts
                    or not path.parts or path.parts[0] != prefix or len(path.parts) < 2
                    or str(path) != member.name or member.name in names
                    or member.size < 0 or total > MAX_EXPANDED):
                raise UpdateError('安装包包含不安全的路径或文件')
            names.add(member.name)
        if not members:
            raise UpdateError('安装包为空')
        for member in members:
            target = work / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with reader.extractfile(member) as source, target.open('xb') as destination:
                shutil.copyfileobj(source, destination)
            target.chmod(0o755 if target.suffix == '.sh' else 0o644)
    return work / prefix


def state_path():
    import os
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'thor-panel/update.json'


def process_identity(pid):
    try:
        return (Path('/proc/sys/kernel/random/boot_id').read_text().strip() + ':' +
                (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()[19])
    except (OSError, IndexError):
        return None
