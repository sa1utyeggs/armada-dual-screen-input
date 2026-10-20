"""Standalone downloader checks; no network or real installation is performed."""
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request


def bootstrap_module():
    shell = (Path(__file__).resolve().parents[1] / 'get.sh').read_text()
    code = shell.split("<<'ADS_PYTHON'\n", 1)[1].rsplit('\nADS_PYTHON', 1)[0]
    module = types.ModuleType('download_bootstrap')
    exec(compile(code, 'get.sh:python', 'exec'), module.__dict__)
    return module


b = bootstrap_module()


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)

    def snapshot(self, additions=()):
        archive = self.work / 'snapshot.tar.gz'
        with tarfile.open(archive, 'w:gz') as output:
            for name in sorted(b.REQUIRED):
                data = b'contents'
                member = tarfile.TarInfo('repo-hash/' + name); member.size = len(data)
                output.addfile(member, io.BytesIO(data))
            for name, kind, data in additions:
                member = tarfile.TarInfo(name); member.type = kind
                if kind == tarfile.REGTYPE:
                    member.size = len(data); output.addfile(member, io.BytesIO(data))
                else:
                    member.linkname = '../outside'; output.addfile(member)
        return archive

    def test_valid_snapshot_keeps_application_and_excludes_driver(self):
        source = b.extract_snapshot(self.snapshot([('repo-hash/extras/driver.ko', tarfile.REGTYPE, b'driver')]), self.work / 'source')
        self.assertTrue((source / 'install.sh').is_file())
        self.assertFalse((source / 'extras').exists())

    def test_unsafe_archive_is_rejected_before_writing_any_source(self):
        for name, kind in [('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE),
                           ('repo-hash/link', tarfile.SYMTYPE), ('repo-hash/hardlink', tarfile.LNKTYPE),
                           ('repo-hash/device', tarfile.CHRTYPE), ('repo-hash/../escape', tarfile.REGTYPE),
                           ('second-root/file', tarfile.REGTYPE), ('repo-hash/install.sh', tarfile.REGTYPE)]:
            with self.subTest(name=name):
                target = self.work / 'source'
                with self.assertRaises(b.DownloadError):
                    b.extract_snapshot(self.snapshot([(name, kind, b'bad')]), target)
                self.assertFalse(target.exists())

    def test_missing_installer_is_rejected(self):
        archive = self.work / 'old.tar.gz'
        with tarfile.open(archive, 'w:gz') as output:
            output.addfile(tarfile.TarInfo('repo/README.md'), io.BytesIO())
        with self.assertRaises(b.DownloadError):
            b.extract_snapshot(archive, self.work / 'source')

    def test_oversized_or_conflicting_archive_never_writes_source(self):
        archive = self.snapshot()
        with patch.object(b, 'EXPANDED_LIMIT', 1), self.assertRaises(b.DownloadError):
            b.extract_snapshot(archive, self.work / 'source')
        self.assertFalse((self.work / 'source').exists())
        archive = self.snapshot([('repo-hash/src/armada_dual_screen_input/__init__.py/child', tarfile.REGTYPE, b'bad')])
        with self.assertRaises(b.DownloadError): b.extract_snapshot(archive, self.work / 'source')
        self.assertFalse((self.work / 'source').exists())

    def test_redirect_strips_token_and_refuses_other_hosts_or_http(self):
        request = urllib.request.Request('https://api.github.com/source', headers={'Authorization': 'Bearer test-only'})
        redirect = b.GitHubRedirects().redirect_request(request, None, 302, 'Found', {}, 'https://codeload.github.com/source')
        self.assertIsNone(redirect.get_header('Authorization'))
        for target in ('https://example.com/file', 'http://api.github.com/file', 'https://user@api.github.com/file'):
            with self.assertRaises(b.DownloadError):
                b.GitHubRedirects().redirect_request(request, None, 302, 'Found', {}, target)

    def test_snapshot_resolves_and_downloads_same_commit_and_cleans_token(self):
        archive = self.snapshot()
        sha = 'a' * 40
        urls, roots, commands = [], [], []
        original_read = Path.read_text
        def download(url, target, **kwargs):
            urls.append(url); roots.append(Path(target).parent)
            Path(target).write_bytes(json.dumps({'sha': sha}).encode() if url.endswith('/main') else archive.read_bytes())
        def run(command, **kwargs):
            commands.append((command, kwargs))
            self.assertTrue(Path(command[1]).is_file())
            self.assertNotIn('GH_TOKEN', kwargs['env']); self.assertNotIn('GITHUB_TOKEN', kwargs['env'])
            return types.SimpleNamespace(returncode=0)
        with patch.object(b.sys, 'argv', ['get.sh', '--dry-run']), patch.object(b.sys, 'platform', 'linux'), \
             patch.object(b.os, 'geteuid', return_value=1000), patch.object(b.platform, 'machine', return_value='aarch64'), \
             patch.object(b.Path, 'read_text', autospec=True, side_effect=lambda path, *a, **kw:
                          'ID=armada\n' if str(path) == '/etc/os-release' else original_read(path, *a, **kw)), \
             patch.dict(b.os.environ, {'GH_TOKEN': 'test-only', 'GITHUB_TOKEN': 'test-only'}), \
             patch.object(b, 'download', side_effect=download), patch.object(b.subprocess, 'run', side_effect=run):
            self.assertEqual(b.main(), 0)
        self.assertEqual(len(commands), 1)
        self.assertEqual(urls[-1], 'https://api.github.com/repos/' + b.REPOSITORY + '/tarball/' + sha)
        self.assertIn('--dry-run', commands[0][0])
        self.assertTrue(all(not root.exists() for root in roots))

    def test_bad_revision_or_download_never_runs_installer(self):
        with patch.object(b, 'download') as download:
            for ref in ('../escape', 'main/../escape', '', 'bad ref'):
                with self.assertRaises(b.DownloadError): b.revision(ref, self.work, '')
            download.assert_not_called()

    def test_download_size_limit_and_authorization_header(self):
        requests = []
        opener = types.SimpleNamespace(open=lambda request, **kw: requests.append(request) or io.BytesIO(b'1234'))
        with patch.object(b.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(b.DownloadError):
                b.download('https://api.github.com/source', self.work / 'download', token='test-only', limit=3)
            self.assertEqual(requests[-1].get_header('Authorization'), 'Bearer test-only')
            b.download('https://codeload.github.com/source', self.work / 'download', token='test-only')
            self.assertIsNone(requests[-1].get_header('Authorization'))

    def test_http_failure_does_not_disclose_response_or_token(self):
        error = urllib.error.HTTPError('https://api.github.com/source?secret=test-only', 404, 'test-only', {}, None)
        opener = types.SimpleNamespace(open=lambda *a, **kw: (_ for _ in ()).throw(error))
        with patch.object(b.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(b.DownloadError) as result:
                b.download('https://api.github.com/source', self.work / 'download', token='test-only')
        self.assertNotIn('test-only', str(result.exception))
        self.assertFalse((self.work / 'download').exists())

    def test_pipe_wrapper_accepts_help_without_network_or_python_cwd(self):
        script = (Path(__file__).resolve().parents[1] / 'get.sh').read_text()
        result = subprocess.run(['bash', '-s', '--', '--help'], input=script, text=True, capture_output=True, cwd=self.work)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--ref', result.stdout)
