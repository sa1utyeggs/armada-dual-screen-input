"""Stable update discovery/downloads: no network, input devices or real services."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from armada_dual_screen_input.i18n import configure, active_language
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from armada_dual_screen_input.updates import (
    API, APP, REPO, HTTPSRedirects, UpdateError, latest_release, newer,
    parse_release, prepare_download,
)


def release_data(version='0.2.0'):
    tag = 'v' + version
    names = [f'{APP}-{version}-aarch64.tar.gz', 'SHA256SUMS']
    return {'tag_name': tag, 'prerelease': False, 'draft': False, 'assets': [
        {'name': name, 'browser_download_url': f'https://github.com/{REPO}/releases/download/{tag}/{name}',
         'digest': 'sha256:' + 'a' * 64, 'size': 123, 'state': 'uploaded'} for name in names]}


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        previous = active_language()
        configure("zh_CN")
        self.addCleanup(configure, previous)

    def test_only_newer_stable_releases_are_offered(self):
        for latest, current, expected in [('0.1.1', '0.1.0', True), ('0.1.0', '0.1.0', False),
                                         ('0.1.0', '0.1.0-preview.2', True), ('0.1.0', '0.2.0', False),
                                         ('0.10.0', '0.9.9', True), ('1.0.0+build.2', '1.0.0', False)]:
            with self.subTest(latest=latest, current=current):
                self.assertEqual(newer(latest, current), expected)
        with self.assertRaises(UpdateError):
            newer('0.1.0-preview.3', '0.1.0')

    def test_official_complete_assets_required(self):
        value = parse_release(release_data())
        self.assertEqual(value.version, '0.2.0')
        invalid = []
        for key in ('draft', 'prerelease'):
            data = release_data(); data[key] = True; invalid.append(data)
        data = release_data(); data['assets'] = None; invalid.append(data)
        data = release_data(); data['assets'].pop(); invalid.append(data)
        data = release_data(); data['assets'].append(data['assets'][0]); invalid.append(data)
        for key, value in [('browser_download_url', 'https://example.com/package'), ('size', 0),
                           ('size', 100 * 1024 * 1024), ('digest', None), ('state', 'new')]:
            data = release_data(); data['assets'][0][key] = value; invalid.append(data)
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(UpdateError):
                parse_release(data)

    def test_offline_errors_and_oversized_responses_are_actionable(self):
        with self.assertRaisesRegex(UpdateError, '网络'):
            latest_release(opener=Mock(side_effect=OSError('offline')))
        with self.assertRaises(UpdateError):
            latest_release(opener=lambda _: io.BytesIO(b'x' * (1024 * 1024 + 1)))
        opened = []
        def opener(url):
            opened.append(url)
            return io.BytesIO(json.dumps(release_data()).encode())
        self.assertEqual(latest_release(opener=opener).tag, 'v0.2.0')
        self.assertEqual(opened, [API])

    def test_rate_limits_and_other_http_failures_are_distinguished_without_retrying(self):
        for code, headers, message in (
                (403, {'X-RateLimit-Remaining': '0'}, '查询次数已达上限'),
                (429, {}, '查询次数已达上限'),
                (403, None, 'GitHub HTTP 403'),
                (502, {}, 'GitHub HTTP 502')):
            with self.subTest(code=code, headers=headers):
                error = HTTPError(API, code, 'fixture failure', headers, None)
                opener = Mock(side_effect=error)
                with self.assertRaisesRegex(UpdateError, message) as caught:
                    latest_release(opener=opener)
                self.assertIs(caught.exception.__cause__, error)
                opener.assert_called_once_with(API)

    def test_redirects_cannot_downgrade_or_leave_official_hosts(self):
        for url in ('http://github.com/asset', 'https://evil.example/file'):
            with self.assertRaises(UpdateError):
                HTTPSRedirects().redirect_request(None, None, 302, '', {}, url)


class DownloadTests(unittest.TestCase):
    def payload(self, members=None, *, bad_checksum=False):
        data = release_data()
        name = data['assets'][0]['name']
        prefix = name.removesuffix('.tar.gz')
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            for path, body, kind in members or [(prefix + '/VERSION', b'0.2.0\n', tarfile.REGTYPE)]:
                entry = tarfile.TarInfo(path); entry.type = kind; entry.size = len(body)
                if kind == tarfile.SYMTYPE:
                    entry.linkname = '/outside'
                archive.addfile(entry, io.BytesIO(body))
        binary = output.getvalue()
        sha = hashlib.sha256(binary).hexdigest()
        checksums = (('b' * 64 if bad_checksum else sha) + '  ' + name + '\n').encode()
        for asset, body in zip(data['assets'], (binary, checksums)):
            asset.update(digest='sha256:' + hashlib.sha256(body).hexdigest(), size=len(body))
        release = parse_release(data)
        bodies = {release.archive_url: binary, release.checksum_url: checksums}
        return release, bodies

    def test_verified_package_extracts_without_running_it(self):
        release, bodies = self.payload()
        with tempfile.TemporaryDirectory() as work:
            root = prepare_download(release, work, opener=lambda url: io.BytesIO(bodies[url]))
            self.assertEqual((root / 'VERSION').read_text(), '0.2.0\n')

    def test_bad_download_or_checksum_never_produces_installable_tree(self):
        for bad_checksum, tamper in [(True, False), (False, True)]:
            release, bodies = self.payload(bad_checksum=bad_checksum)
            if tamper:
                bodies[release.archive_url] += b'changed'
            with self.subTest(checksum=bad_checksum), tempfile.TemporaryDirectory() as work:
                with self.assertRaises(UpdateError):
                    prepare_download(release, work, opener=lambda url: io.BytesIO(bodies[url]))
                self.assertFalse((Path(work) / release.filename.removesuffix('.tar.gz')).exists())

    def test_unsafe_archive_entries_are_rejected_before_extraction(self):
        prefix = f'{APP}-0.2.0-aarch64'
        for members in [[('../outside', b'bad', tarfile.REGTYPE)],
                        [('/outside', b'bad', tarfile.REGTYPE)],
                        [(prefix + '/link', b'', tarfile.SYMTYPE)],
                        [(prefix + '/VERSION', b'a', tarfile.REGTYPE)] * 2,
                        [(prefix + '/a/../VERSION', b'a', tarfile.REGTYPE)]]:
            release, bodies = self.payload(members)
            with self.subTest(members=members), tempfile.TemporaryDirectory() as work:
                with self.assertRaises(UpdateError):
                    prepare_download(release, work, opener=lambda url: io.BytesIO(bodies[url]))
                self.assertFalse((Path(work) / prefix).exists())


if __name__ == '__main__':
    unittest.main()
