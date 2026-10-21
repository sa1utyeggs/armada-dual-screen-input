#!/usr/bin/env python3
"""Validate CI release metadata without creating a tag or contacting GitHub."""
import argparse
from pathlib import Path
import re
import subprocess

from release import APP, PackageError, version


def metadata(root, tag=None):
    root = Path(root)
    value = version(root)
    # Semantic versioning: a hyphen marks a prerelease, '+' is build metadata.
    identifier = r'(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)'
    semver = rf'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-{identifier}(?:\.{identifier})*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?'
    if not re.fullmatch(semver, value):
        raise PackageError('Release VERSION must be a semantic version')
    expected = 'v' + value
    if tag is not None and tag != expected:
        raise PackageError(f'Tag {tag!r} does not match VERSION ({expected})')
    changelog = (root / 'CHANGELOG.md').read_text()
    section = re.search(r'^## ' + re.escape(value) + r'(?:[ \t]+[^\n]*)?\n(.*?)(?=^## |\Z)',
                        changelog, re.MULTILINE | re.DOTALL)
    if section is None or not section[1].strip():
        raise PackageError('CHANGELOG.md needs a nonempty section for ' + value)
    prerelease = '-' in value.split('+', 1)[0]
    values = {'version': value, 'tag': expected, 'prerelease': str(prerelease).lower()}
    notes = section[1].strip() + '\n\n' + (
        f'安装包：`{APP}-{value}-aarch64.tar.gz`，校验文件：`SHA256SUMS`。\n'
        '下载两个附件后执行 `sha256sum -c SHA256SUMS`，再解压并运行 `bash install.sh`。\n'
        'GitHub 自动生成的 Source code 压缩包不能替代离线安装包。\n')
    return values, notes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag')
    parser.add_argument('--github-output', type=Path, required=True)
    parser.add_argument('--notes-file', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    values, notes = metadata(root, args.tag)
    values['revision'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    args.notes_file.parent.mkdir(parents=True, exist_ok=True)
    args.notes_file.write_text(notes)
    with args.github_output.open('a') as stream:
        stream.writelines(f'{key}={value}\n' for key, value in values.items())


if __name__ == '__main__':
    main()
