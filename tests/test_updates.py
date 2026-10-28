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
from urllib.request import Request

from armada_dual_screen_input.updates import (
    APP, REPO, HTTPSRedirects, UpdateError, latest_release, newer,
    open_url, parse_release, prepare_download,
)


def release_data(version='0.2.0'):
    tag = 'v' + version
    names = [f'{APP}-{version}-aarch64.tar.gz', 'SHA256SUMS']
    return {'tag_name': tag, 'prerelease': False, 'draft': False, 'assets': [
        {'name': name, 'browser_download_url': f'https://github.com/{REPO}/releases/download/{tag}/{name}',
         'digest': 'sha256:' + 'a' * 64, 'size': 123, 'state': 'uploaded'} for name in names]}


WEB = 'https://github.com/' + REPO
API_URL = 'https://api.github.com/repos/' + REPO + '/releases/latest'


class PublicResponse(io.BytesIO):
    def __init__(self, data=b'', *, url='', headers=None):
        super().__init__(data)
        self.url, self.headers = url, headers or {}

    def geturl(self):
        return self.url


def public_release_fixture(*, final=None, checksum=None, fail_at=None, error=None):
    """The same offline public-discovery transport for UI and worker checks."""
    release, bodies = DownloadTests().payload()
    calls = []
    def opener(url, *, method='GET'):
        calls.append((url, method))
        if len(calls) == fail_at:
            raise error if error is not None else OSError('offline')
        if url == WEB + '/releases/latest' and method == 'GET':
            return PublicResponse(url=final if final is not None else WEB + '/releases/tag/' + release.tag)
        if url == release.checksum_url and method == 'GET':
            return PublicResponse(bodies[url] if checksum is None else checksum, url=url)
        if url == release.archive_url and method == 'HEAD':
            return PublicResponse(url=url, headers={'Content-Length': str(release.archive_size)})
        raise AssertionError('Unexpected public request: ' + str((url, method)))
    return release, bodies, calls, opener


def public_requests(release):
    return [(WEB + '/releases/latest', 'GET'), (release.checksum_url, 'GET'),
            (release.archive_url, 'HEAD')]


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
        for checksum in (b'x'*65537, b'\xff', b''):
            _, _, calls, opener = public_release_fixture(checksum=checksum)
            with self.subTest(checksum_size=len(checksum)), self.assertRaises(UpdateError):
                latest_release(opener=opener)
            self.assertEqual(len(calls), 2)

    def test_latest_uses_public_redirect_checksum_and_head_without_any_rest_request(self):
        expected, _, calls, opener = public_release_fixture()
        with patch('armada_dual_screen_input.updates.open_url',
                   side_effect=AssertionError('REST discovery forbidden')) as rest:
            self.assertEqual(latest_release(opener=opener), expected)
        self.assertEqual(calls, public_requests(expected))
        self.assertTrue(all(url.startswith(WEB + '/') for url, _ in calls))
        rest.assert_not_called()

    def test_old_json_only_responses_and_invalid_public_redirects_cannot_be_used(self):
        for response in (io.BytesIO(json.dumps(release_data()).encode()),
                         PublicResponse(json.dumps(release_data()).encode(), url=API_URL)):
            opener = Mock(return_value=response)
            with self.subTest(response=type(response).__name__), self.assertRaises(UpdateError):
                latest_release(opener=opener)
            opener.assert_called_once_with(WEB + '/releases/latest')
        for final in ('https://github.com/other/repo/releases/tag/v0.2.0',
                      WEB + '/releases/tag/v0.2.0-rc.1', WEB + '/releases/tag/v0.2.0?wrong=1'):
            _, _, calls, opener = public_release_fixture(final=final)
            with self.subTest(final=final), self.assertRaises(UpdateError):
                latest_release(opener=opener)
            self.assertEqual(calls, [(WEB + '/releases/latest', 'GET')])

    def test_each_public_lookup_failure_stops_without_retry_fallback_or_archive_get(self):
        for stage in (1, 2, 3):
            expected, _, calls, opener = public_release_fixture(fail_at=stage)
            with self.subTest(stage=stage), \
                    patch('armada_dual_screen_input.updates.open_url',
                          side_effect=AssertionError('REST fallback forbidden')) as rest:
                with self.assertRaisesRegex(UpdateError, '网络'):
                    latest_release(opener=opener)
            self.assertEqual(calls, public_requests(expected)[:stage])
            rest.assert_not_called()

    def test_rate_limits_and_other_http_failures_are_distinguished_without_retrying(self):
        for code, headers, message in (
                (403, {'X-RateLimit-Remaining': '0'}, '查询次数已达上限'),
                (429, {}, '查询次数已达上限'),
                (403, None, 'GitHub HTTP 403'),
                (502, {}, 'GitHub HTTP 502')):
            with self.subTest(code=code, headers=headers):
                error = HTTPError(WEB + '/releases/latest', code, 'fixture failure', headers, None)
                opener = Mock(side_effect=error)
                with self.assertRaisesRegex(UpdateError, message) as caught:
                    latest_release(opener=opener)
                self.assertIs(caught.exception.__cause__, error)
                opener.assert_called_once_with(WEB + '/releases/latest')

    def test_redirects_cannot_downgrade_or_leave_official_hosts(self):
        for url in ('http://github.com/asset', 'https://evil.example/file', API_URL):
            with self.assertRaises(UpdateError):
                HTTPSRedirects().redirect_request(Request(WEB + '/releases/latest', method='HEAD'),
                                                 None, 302, '', {}, url)

    def test_public_asset_redirects_preserve_head_and_get_across_both_cdn_hops(self):
        initial = WEB + '/releases/download/v0.2.0/' + APP + '-0.2.0-aarch64.tar.gz'
        destinations = ('https://release-assets.githubusercontent.com/asset?token=fixture',
                        'https://objects.githubusercontent.com/release-asset?token=fixture')
        for method in ('HEAD', 'GET'):
            for code in (301, 302, 303, 307, 308):
                with self.subTest(method=method, code=code):
                    request = Request(initial, method=method, headers={'Accept': '*/*'})
                    handler = HTTPSRedirects()
                    for destination in destinations:
                        redirected = handler.redirect_request(request, None, code, 'fixture', {}, destination)
                        self.assertIsInstance(redirected, Request)
                        self.assertEqual(redirected.full_url, destination)
                        self.assertEqual(redirected.get_method(), method)
                        self.assertEqual(request.get_method(), method)
                        request = redirected

    def test_public_asset_download_requests_do_not_use_json_or_authentication_headers(self):
        transport = Mock()
        transport.open.return_value = io.BytesIO()
        with patch('armada_dual_screen_input.updates.build_opener', return_value=transport):
            open_url(WEB + '/releases/download/v0.2.0/SHA256SUMS').close()
        request = transport.open.call_args.args[0]
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(request.get_header('Accept'), '*/*')
        self.assertIsNone(request.get_header('Authorization'))


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

    def test_public_descriptor_pins_both_downloads_before_extraction(self):
        _, bodies, _, opener = public_release_fixture()
        selected = latest_release(opener=opener)
        for url in (selected.archive_url, selected.checksum_url):
            changed = dict(bodies)
            changed[url] += b'changed after discovery'
            with self.subTest(url=url), tempfile.TemporaryDirectory() as work:
                with self.assertRaises(UpdateError):
                    prepare_download(selected, work, opener=lambda url: io.BytesIO(changed[url]))
                self.assertFalse((Path(work)/selected.filename.removesuffix('.tar.gz')).exists())

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
