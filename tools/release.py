"""Build and verify offline application bundles. No installer/kernel actions."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

APP = 'armada-dual-screen-input'
ROOT_FILES = ('VERSION', 'README.md', 'README.en.md', 'CHANGELOG.md', 'LICENSE', 'THIRD_PARTY.md', 'install.sh', 'uninstall.sh')
TREES = ('src', 'vendor', 'assets', 'packaging')
TOOLS = ('manage.py', 'release.py', 'run.py', 'update.py', 'desktop_cache.py')
DOCS = ('installation.md', 'usage.md', 'compatibility.md', 'multilingual-keyboard.md')


class PackageError(RuntimeError):
    pass


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else hashlib.sha256(stream.read()).hexdigest()


def regular_files(root):
    for path in sorted(Path(root).rglob('*')):
        if '__pycache__' in path.parts or path.name in ('.DS_Store',) or path.name.endswith(('.pyc', '.pyo')):
            continue
        if path.is_symlink():
            raise PackageError('Symlink in bundle/source: ' + str(path))
        if path.is_file():
            yield path


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def version(root):
    value = (Path(root) / 'VERSION').read_text().strip()
    if not re.fullmatch(r'[0-9][A-Za-z0-9.+-]{0,63}', value):
        raise PackageError('Invalid VERSION')
    return value


def extract_runtime(rpm, spec, destination):
    if digest(rpm) != spec['sha256']:
        raise PackageError('Fedora runtime RPM checksum mismatch')
    with tempfile.TemporaryDirectory(prefix='ads-runtime-') as directory:
        work = Path(directory).resolve()
        selected = ['./' + item for item in spec['files']]
        if shutil.which('rpm2cpio') and shutil.which('cpio'):
            producer = subprocess.Popen(['rpm2cpio', str(rpm)], stdout=subprocess.PIPE)
            try:
                result = subprocess.run(['cpio', '-idm', '--quiet', '--no-absolute-filenames', *selected],
                                        stdin=producer.stdout, cwd=work, capture_output=True)
                producer.stdout.close()
                if result.returncode or producer.wait():
                    raise PackageError('Could not extract the verified Fedora runtime RPM')
            finally:
                if producer.poll() is None:
                    producer.terminate(); producer.wait()
        elif shutil.which('tar'):
            result = subprocess.run(['tar', '-xf', str(rpm), '-C', str(work), *selected], capture_output=True)
            if result.returncode:
                raise PackageError('Need rpm2cpio + cpio, or a libarchive tar capable of reading RPM')
        else:
            raise PackageError('Need rpm2cpio + cpio, or libarchive tar')
        for name in spec['files']:
            source = (work / name).resolve()
            if not source.is_relative_to(work) or not source.is_file():
                raise PackageError('Missing or unsafe runtime file: ' + name)
            target = Path(destination) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)  # Dereference only within the verified RPM.


def runtime_package(source, cache, *, supplied=None, offline=False):
    spec = json.loads((Path(source) / 'packaging/dependencies/gtk-layer-shell-aarch64.json').read_text())
    path = Path(supplied).resolve() if supplied else Path(cache) / spec['name']
    if not path.exists():
        if supplied or offline:
            raise PackageError('Runtime RPM unavailable; supply --runtime-rpm or allow its pinned Fedora download')
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='runtime-download.', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream, urllib.request.urlopen(spec['url'], timeout=45) as response:
                shutil.copyfileobj(response, stream)
            if digest(temporary) != spec['sha256']:
                raise PackageError('Downloaded runtime RPM checksum mismatch')
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    if digest(path) != spec['sha256']:
        raise PackageError('Runtime RPM checksum mismatch: ' + str(path))
    return path, spec


def prepare(source, destination, *, runtime_rpm=None, cache=None, offline=False):
    source, destination = Path(source).resolve(), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    names = [source / name for name in ROOT_FILES]
    names += [source / 'tools' / name for name in TOOLS]
    names += [source / 'docs' / name for name in DOCS]
    for directory in TREES:
        for path in regular_files(source / directory):
            if directory == 'src' and path.suffix not in ('.py', '.js'):
                continue
            if directory == 'vendor' and path.suffix != '.py' and path.name not in ('UPSTREAM', 'LICENSE', 'CREDITS.md'):
                continue
            if directory == 'assets' and path.suffix not in ('.svg', '.png'):
                continue
            if directory == 'packaging' and path.suffix not in ('.in', '.json'):
                continue
            names.append(path)
    for path in names:
        if path.is_symlink() or not path.is_file():
            raise PackageError('Missing/unsafe release source: ' + str(path))
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    rpm, spec = runtime_package(source, cache or source / '.cache', supplied=runtime_rpm, offline=offline)
    extract_runtime(rpm, spec, destination / 'runtime')
    try:
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, stderr=subprocess.DEVNULL, text=True).strip()
        dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=source, text=True).strip()
        revision += '-dirty' if dirty else ''
    except (OSError, subprocess.CalledProcessError):
        revision = 'source-snapshot'
    return seal(destination, revision=revision)


def seal(destination, *, revision='source-snapshot'):
    destination = Path(destination)
    files = {str(p.relative_to(destination)): digest(p) for p in regular_files(destination) if p != destination / 'manifest.json'}
    content = {'schema': 1, 'application': APP, 'version': version(destination), 'architecture': 'aarch64',
               'source_revision': revision, 'files': files}
    content['bundle_id'] = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:16]
    write_json(destination / 'manifest.json', content)
    verify(destination)
    return content


def verify(root):
    root = Path(root).resolve()
    manifest_path = root / 'manifest.json'
    if manifest_path.is_symlink():
        raise PackageError('Manifest must not be a symlink')
    data = json.loads(manifest_path.read_text())
    if (data.get('schema') != 1 or data.get('application') != APP
            or data.get('architecture') != 'aarch64'
            or not re.fullmatch(r'[0-9a-f]{16}', data.get('bundle_id', ''))
            or data.get('version') != version(root)):
        raise PackageError('Unsupported bundle manifest')
    files = data.get('files')
    if not isinstance(files, dict) or not 1 <= len(files) <= 4096:
        raise PackageError('Invalid manifest file list')
    for name, expected in files.items():
        path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or '\\' in name or not path.parts
                or not re.fullmatch(r'[A-Za-z0-9_./+-]+', name)
                or not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected)):
            raise PackageError('Unsafe manifest path or digest')
        target = root / name
        if target.is_symlink() or not target.resolve().is_relative_to(root) or not target.is_file() or digest(target) != expected:
            raise PackageError('Bundle checksum/path mismatch: ' + name)
    actual = {str(p.relative_to(root)) for p in regular_files(root)} - {'manifest.json'}
    if actual != set(files):
        raise PackageError('Unlisted or missing bundle files')
    unsigned = dict(data); unsigned.pop('bundle_id')
    if hashlib.sha256(json.dumps(unsigned, sort_keys=True).encode()).hexdigest()[:16] != data['bundle_id']:
        raise PackageError('Bundle manifest identity mismatch')
    return data


def archive(tree, target):
    tree, target = Path(tree), Path(target)
    with target.open('wb') as output, gzip.GzipFile(filename='', fileobj=output, mode='wb', mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode='w') as tar:
            for path in regular_files(tree):
                info = tar.gettarinfo(str(path), arcname=tree.name + '/' + str(path.relative_to(tree)))
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ''
                info.mode = 0o755 if path.suffix == '.sh' else 0o644
                with path.open('rb') as stream:
                    tar.addfile(info, stream)
