"""Public installer discovery uses release links and never REST API requests."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from armada_dual_screen_input.installer_release import WEB, latest_install_release, open_release_url
from armada_dual_screen_input.updates import MAX_ARCHIVE, UpdateError, prepare_download
import test_updates as fixtures


class Response(io.BytesIO):
    def __init__(self, data=b'', *, url='', headers=None):
        super().__init__(data)
        self.url, self.headers = url, headers or {}

    def geturl(self):
        return self.url


class PublicInstallerReleaseTests(unittest.TestCase):
    def fixture(self, *, final=None, checksum=None, length=None):
        release, bodies = fixtures.DownloadTests().payload()
        calls = []
        def opener(url, *, method='GET'):
            calls.append((url, method))
            if url == WEB + '/releases/latest':
                return Response(url=final or WEB + '/releases/tag/' + release.tag)
            if url == release.checksum_url:
                return Response(bodies[url] if checksum is None else checksum)
            if url == release.archive_url and method == 'HEAD':
                return Response(headers={'Content-Length': str(release.archive_size) if length is None else length})
            raise AssertionError('Unexpected request: ' + url)
        return release, bodies, calls, opener

    def test_public_redirect_pins_version_and_download_checksums_without_api(self):
        expected, bodies, calls, opener = self.fixture()
        selected = latest_install_release(opener=opener)
        self.assertEqual(selected, expected)
        self.assertEqual(calls, [(WEB + '/releases/latest', 'GET'),
                                (expected.checksum_url, 'GET'), (expected.archive_url, 'HEAD')])
        self.assertTrue(all(url.startswith(WEB + '/') for url, _ in calls))
        with tempfile.TemporaryDirectory() as directory:
            bundle = prepare_download(selected, directory, opener=lambda url: io.BytesIO(bodies[url]))
            self.assertEqual((bundle / 'VERSION').read_text(), selected.version + '\n')

    def test_invalid_or_nonstable_redirect_stops_before_assets(self):
        for final in ('http://github.com/release', 'https://example.com/release',
                      WEB + '/releases/tag/v0.2.0-rc.1', WEB + '/releases/tag/main',
                      WEB + '/releases/tag/v0.2.0?other=1', WEB + '/releases/tag/v0.2.0#fragment',
                      'https://github.com/other/repo/releases/tag/v0.2.0', 'https://github.com/login'):
            with self.subTest(final=final):
                _, _, calls, opener = self.fixture(final=final)
                with self.assertRaises(UpdateError):
                    latest_install_release(opener=opener)
                self.assertEqual(len(calls), 1)

    def test_wrong_ambiguous_or_oversized_checksum_stops_before_package_headers(self):
        for checksum in (b'', b'bad checksum', b'\xff', b'x'*65537,
                         (b'a'*64 + b'  ../outside\n'), (b'a'*64 + b'  other.tar.gz\n'),
                         (b'a'*64 + b'  armada-dual-screen-input-0.2.0-aarch64.tar.gz\n')*2):
            with self.subTest(length=len(checksum)):
                _, _, calls, opener = self.fixture(checksum=checksum)
                with self.assertRaises(UpdateError):
                    latest_install_release(opener=opener)
                self.assertEqual(len(calls), 2)

    def test_invalid_or_oversized_archive_length_is_rejected(self):
        for length in ('', '0', '-1', 'not a size', str(MAX_ARCHIVE+1), '9999999999999999'):
            with self.subTest(length=length):
                _, _, _, opener = self.fixture(length=length)
                with self.assertRaises(UpdateError):
                    latest_install_release(opener=opener)

    def test_changed_asset_after_review_fails_before_extraction(self):
        _, bodies, _, opener = self.fixture()
        selected = latest_install_release(opener=opener)
        for url in (selected.archive_url, selected.checksum_url):
            changed = dict(bodies); changed[url] += b'changed'
            with self.subTest(url=url), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(UpdateError):
                    prepare_download(selected, directory, opener=lambda url: io.BytesIO(changed[url]))
                self.assertFalse((Path(directory)/selected.filename.removesuffix('.tar.gz')).exists())

    def test_web_errors_do_not_retry_or_switch_to_development_sources(self):
        for code in (403, 404, 429):
            opener = Mock(side_effect=HTTPError(WEB, code, 'fixture', {}, None))
            with self.subTest(code=code), self.assertRaises(UpdateError):
                latest_install_release(opener=opener)
            opener.assert_called_once_with(WEB + '/releases/latest')

    def test_public_requests_have_no_authentication_and_head_uses_head(self):
        requests = []
        opener = Mock(open=lambda request, **kw: requests.append(request) or Response())
        with patch('armada_dual_screen_input.installer_release.build_opener', return_value=opener):
            open_release_url(WEB + '/releases/latest', method='HEAD').close()
        self.assertEqual(requests[0].get_method(), 'HEAD')
        self.assertIsNone(requests[0].get_header('Authorization'))


if __name__ == '__main__':
    unittest.main()
