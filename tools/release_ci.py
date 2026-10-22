#!/usr/bin/env python3
"""Validate CI release metadata without creating a tag or contacting GitHub."""
import argparse
from pathlib import Path
import re
import subprocess

from release import APP, PackageError, version


REPOSITORY = 'https://github.com/sa1utyeggs/armada-dual-screen-input'


def changelog_section(root, filename, value):
    try:
        changelog = (Path(root) / filename).read_text(encoding='utf-8')
    except OSError as exc:
        raise PackageError(filename + ' is required for bilingual release notes') from exc
    sections = re.findall(r'^## ' + re.escape(value) + r'(?:[ \t]+[^\n]*)?\n(.*?)(?=^## |\Z)',
                          changelog, re.MULTILINE | re.DOTALL)
    if len(sections) != 1 or not sections[0].strip():
        raise PackageError(filename + ' needs exactly one nonempty section for ' + value)
    return sections[0].strip()


def release_notes(root, value, *, ref=None):
    """Read both editions; never publish a silently untranslated release."""
    ref = ref or 'v' + value
    blocks = []
    for filename, heading in (('CHANGELOG.md', 'English'), ('CHANGELOG.zh-CN.md', '简体中文')):
        section = changelog_section(root, filename, value)
        # Release pages resolve relative links differently from repository files.
        section = re.sub(r'(\]\()((?:docs/)[^\s)]+)(\))',
                         lambda m: m[1] + REPOSITORY + '/blob/' + ref + '/' + m[2] + m[3], section)
        if heading == 'English':
            footer = (f'Package: `{APP}-{value}-aarch64.tar.gz`; checksums: `SHA256SUMS`.\n'
                      'Download both assets, run `sha256sum -c SHA256SUMS`, extract the archive, '
                      'then run `bash install.sh` as your regular user.\n'
                      "GitHub-generated Source code archives do not replace the offline installer bundle.")
        else:
            footer = (f'安装包：`{APP}-{value}-aarch64.tar.gz`，校验文件：`SHA256SUMS`。\n'
                      '下载两个附件后执行 `sha256sum -c SHA256SUMS`，再解压并以普通用户运行 `bash install.sh`。\n'
                      'GitHub 自动生成的 Source code 压缩包不能替代离线安装包。')
        blocks.append('## ' + heading + '\n\n' + section + '\n\n' + footer)
    return '\n\n---\n\n'.join(blocks) + '\n'


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
    prerelease = '-' in value.split('+', 1)[0]
    values = {'version': value, 'tag': expected, 'prerelease': str(prerelease).lower()}
    return values, release_notes(root, value)


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
