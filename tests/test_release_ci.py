"""Release tags and notes must describe the package actually being built."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

from release import PackageError
from release_ci import metadata


class ReleaseMetadataTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)

    def source(self, value, notes='- Tested change.'):
        (self.root / 'VERSION').write_text(value + '\n')
        (self.root / 'CHANGELOG.md').write_text(
            f'# Changelog\n\n## Unreleased\n\n- Future change.\n\n'
            f'## {value} · 2026-10-21\n\n{notes}\n\n## 0.0.1\n\n- Old change.\n')

    def test_stable_and_prerelease_tags_and_build_metadata(self):
        for value, prerelease in [('1.2.3', 'false'), ('0.1.0-preview.3', 'true'),
                                  ('1.2.3-rc.1+build.2', 'true'), ('1.2.3+build-2', 'false')]:
            with self.subTest(version=value):
                self.source(value)
                values, notes = metadata(self.root, 'v' + value)
                self.assertEqual(values, {'tag': 'v' + value, 'version': value, 'prerelease': prerelease})
                self.assertIn(f'armada-dual-screen-input-{value}-aarch64.tar.gz', notes)
                self.assertIn('SHA256SUMS', notes)

    def test_wrong_tag_fails_before_release(self):
        self.source('1.2.3')
        for tag in ('v1.2.4', '1.2.3', 'v1.2.3-rc.1'):
            with self.subTest(tag=tag), self.assertRaises(PackageError):
                metadata(self.root, tag)

    def test_manual_build_needs_no_tag(self):
        self.source('1.2.3')
        self.assertEqual(metadata(self.root)[0]['tag'], 'v1.2.3')

    def test_non_semantic_versions_are_rejected(self):
        for value in ('1.2', '01.2.3', '1.2.3-preview.01', '1.2.3-01', '1.2.3+', 'release'):
            with self.subTest(version=value):
                self.source(value)
                with self.assertRaises(PackageError):
                    metadata(self.root)

    def test_notes_include_only_exact_version_section(self):
        self.source('1.2.3')
        notes = metadata(self.root)[1]
        self.assertIn('Tested change.', notes)
        self.assertNotIn('Future change.', notes)
        self.assertNotIn('Old change.', notes)

    def test_missing_and_empty_changelog_sections_fail(self):
        self.source('1.2.3', notes='')
        with self.assertRaises(PackageError):
            metadata(self.root)
        (self.root / 'CHANGELOG.md').write_text('## 1.2.30\n\n- Different version.\n')
        with self.assertRaises(PackageError):
            metadata(self.root)


class ReleasePublishTests(unittest.TestCase):
    def test_real_publish_step_with_isolated_github_cli(self):
        # Exercise the actual workflow shell with fake API responses, never GitHub.
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/package.yml').read_text()
        script = textwrap.dedent(workflow.split('      - name: Publish verified release assets', 1)[1]
                                 .split('        run: |\n', 1)[1])
        gh = '''import json, os, sys
args = sys.argv[1:]
with open(os.environ['CALL_LOG'], 'a') as stream:
    stream.write(json.dumps(args) + '\\n')
if args[0] == 'api':
    if '/git/ref/' in args[1]:
        sha = 'b' * 40 if os.environ.get('MOVED') or os.environ.get('ANNOTATED') else 'a' * 40
        kind = 'tag' if os.environ.get('ANNOTATED') else 'commit'
        print(sha if args[-1] == '.object.sha' else kind)
    else:
        print(json.dumps({'object': {'sha': 'a' * 40, 'type': 'commit'}}))
elif args[:2] == ['release', 'view']:
    state = os.environ.get('DRAFT', 'missing')
    if state == 'missing': sys.exit(1)
    print(state)
elif args[:2] == ['release', 'upload'] and os.environ.get('FAIL_UPLOAD'):
    sys.exit(1)
'''
        checksum = '''import hashlib, pathlib
for line in pathlib.Path('SHA256SUMS').read_text().splitlines():
    expected, name = line.split()
    assert hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest() == expected
'''
        jq = '''import json, sys
print(json.load(sys.stdin)['object'][sys.argv[-1].rsplit('.', 1)[-1]])
'''
        cases = [('stable', {}, True), ('preview', {'PRERELEASE': 'true'}, True),
                 ('annotated', {'ANNOTATED': '1'}, True), ('draft retry', {'DRAFT': 'true'}, True),
                 ('published', {'DRAFT': 'false'}, False), ('moved', {'MOVED': '1'}, False),
                 ('upload failed', {'FAIL_UPLOAD': '1'}, False), ('tampered', {'TAMPERED': '1'}, False)]
        for label, options, success in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as work:
                root = Path(work)
                (root / 'bin').mkdir()
                (root / 'dist').mkdir()
                for name, code in [('gh', gh), ('sha256sum', checksum), ('jq', jq)]:
                    target = root / 'bin' / name
                    target.write_text('#!' + sys.executable + '\n' + code)
                    target.chmod(0o755)
                archive = root / 'dist/armada-dual-screen-input-1.2.3-aarch64.tar.gz'
                archive.write_bytes(b'fixture archive')
                expected = hashlib.sha256(archive.read_bytes()).hexdigest()
                (root / 'dist/SHA256SUMS').write_text(expected + '  ' + archive.name + '\n')
                (root / 'dist/release-notes.md').write_text('Fixture release notes')
                if options.get('TAMPERED'):
                    archive.write_bytes(b'tampered archive')
                env = dict(os.environ, PATH=str(root / 'bin') + os.pathsep + os.environ['PATH'],
                           CALL_LOG=str(root / 'calls'), GH_REPO='example/repo', GH_TOKEN='fixture',
                           RELEASE_TAG='v1.2.3', RELEASE_VERSION='1.2.3', PRERELEASE='false',
                           SOURCE_REVISION='a' * 40, RUNNER_TEMP=str(root), DRAFT='missing',
                           MOVED='', ANNOTATED='', FAIL_UPLOAD='')
                env.update(options)
                result = subprocess.run(['bash', '-c', script], cwd=root, env=env,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, success, result.stderr)
                calls = [json.loads(line) for line in (root / 'calls').read_text().splitlines()] if (root / 'calls').exists() else []
                verbs = [call[1] for call in calls if call[0] == 'release']
                if success:
                    self.assertEqual(verbs, ['view', 'upload', 'edit'] if options.get('DRAFT') == 'true'
                                     else ['view', 'create', 'upload', 'edit'])
                    publish = next(call for call in calls if call[:2] == ['release', 'edit'])
                    self.assertIn('--draft=false', publish)
                    self.assertIn('--latest=false' if options.get('PRERELEASE') == 'true' else '--latest=true', publish)
                else:
                    self.assertNotIn('edit', verbs)
                    if label in ('published', 'moved', 'tampered'):
                        self.assertNotIn('upload', verbs)


if __name__ == '__main__':
    unittest.main()
