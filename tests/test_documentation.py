"""Keep navigation, bilingual evidence and release docs maintainable offline."""
from collections import Counter
from html import unescape
import re
from pathlib import Path
import unicodedata
import unittest
from urllib.parse import unquote, urlsplit

from release import DOCS, ROOT_FILES

ROOT = Path(__file__).resolve().parents[1]
GUIDES = sorted((ROOT / 'docs').glob('*.md'))
PAIRS = [(ROOT / 'README.md', ROOT / 'README.zh-CN.md'),
         (ROOT / 'CHANGELOG.md', ROOT / 'CHANGELOG.zh-CN.md'),
         (ROOT / 'THIRD_PARTY.md', ROOT / 'THIRD_PARTY.zh-CN.md'),
         (ROOT / '.github/assets/README.md', ROOT / '.github/assets/README.zh-CN.md'),
         (ROOT / 'extras/thor-touch-driver/README.md', ROOT / 'extras/thor-touch-driver/README.zh-CN.md')]
PAIRS += [(path, path.parent / 'zh-CN' / path.name) for path in GUIDES]


def prose(text):
    return re.sub(r'^\s*```.*?^\s*```\s*$', '', text, flags=re.M | re.S)


def anchors(text):
    result = set(re.findall(r'<a\s+id="([^"]+)"', text))
    counts = Counter()
    for heading in re.findall(r'^#{1,6} (.+)$', prose(text), re.M):
        heading = re.sub(r'[`*]', '', heading).lower()
        slug = ''.join(c for c in heading if c in '-_ ' or unicodedata.category(c)[0] in 'LN').replace(' ', '-')
        number = counts[slug]
        counts[slug] += 1
        result.add(slug + ('-' + str(number) if number else ''))
    return result


def local_links(text):
    text = prose(text)
    return re.findall(r'\]\(([^\s)]+)\)', text) + re.findall(r'(?:href|src)="([^"]+)"', text)


def broken_links(path):
    failures = []
    for link in local_links(path.read_text()):
        url = urlsplit(unescape(link))
        if url.scheme or url.netloc or url.path.startswith('/'):
            continue
        target = (path.parent / unquote(url.path)).resolve() if url.path else path
        if not target.is_file():
            failures.append(link + ': missing file')
        elif url.fragment and target.suffix == '.md' and unquote(url.fragment) not in anchors(target.read_text()):
            failures.append(link + ': missing anchor')
    return failures


def commands(text):
    blocks = re.findall(r'^\s*```[^\n]*\n(.*?)^\s*```', text, re.M | re.S)
    # Human-readable comments may be translated; executable/example payloads may not.
    return ['\n'.join(line for line in block.strip().splitlines() if not line.lstrip().startswith('#'))
            for block in blocks]


def table_numbers(text):
    return [[sorted(re.findall(r'\d+(?:[.,]\d+)*', cell)) for cell in line.split('|')]
            for line in text.splitlines() if line.startswith('|')]


class DocumentationTests(unittest.TestCase):
    def test_every_first_party_guide_has_reciprocal_language_links(self):
        import os
        for english, chinese in PAIRS:
            with self.subTest(guide=str(english.relative_to(ROOT))):
                self.assertTrue(chinese.is_file())
                en, zh = english.read_text(), chinese.read_text()
                self.assertIn(Path(os.path.relpath(chinese, english.parent)).as_posix(), local_links(en))
                self.assertIn(Path(os.path.relpath(english, chinese.parent)).as_posix(), local_links(zh))
                self.assertIn('English', en[:250])
                self.assertIn('简体中文', zh[:250])

    def test_default_readme_is_english_and_old_entry_is_a_forwarder(self):
        self.assertIn('## Quick start', (ROOT / 'README.md').read_text())
        old = (ROOT / 'README.en.md').read_text()
        self.assertIn('[English](README.md)', old)
        self.assertIn('[简体中文](README.zh-CN.md)', old)

    def test_all_first_party_local_links_and_fragments_resolve(self):
        failures = []
        for path in [p for pair in PAIRS for p in pair] + [ROOT / 'README.en.md']:
            failures += [str(path.relative_to(ROOT)) + ': ' + item for item in broken_links(path)]
        self.assertEqual(failures, [])

    def test_guide_commands_and_measurement_tables_match(self):
        for english, chinese in PAIRS:
            if english.name != 'README.md' or english.parent == ROOT:
                continue
            if english.parent.name in ('assets', 'thor-touch-driver'):
                with self.subTest(guide=english):
                    self.assertEqual(commands(english.read_text()), commands(chinese.read_text()))
        for english in GUIDES:
            if english.name == 'README.md':
                continue
            chinese = english.parent / 'zh-CN' / english.name
            with self.subTest(guide=english.name):
                self.assertEqual(commands(english.read_text()), commands(chinese.read_text()))
                self.assertEqual(table_numbers(english.read_text()), table_numbers(chinese.read_text()))

    def test_changelog_version_order_and_nonempty_sections_match(self):
        from release_ci import changelog_section
        en = (ROOT / 'CHANGELOG.md').read_text()
        zh = (ROOT / 'CHANGELOG.zh-CN.md').read_text()
        versions = re.findall(r'^## (\S+)', en, re.M)
        self.assertEqual(versions, re.findall(r'^## (\S+)', zh, re.M))
        for version in versions:
            for filename in ('CHANGELOG.md', 'CHANGELOG.zh-CN.md'):
                self.assertTrue(changelog_section(ROOT, filename, version))

    def test_both_editions_are_in_offline_package_allowlist(self):
        for name in ('README.md', 'README.zh-CN.md', 'README.en.md', 'CHANGELOG.md',
                     'CHANGELOG.zh-CN.md', 'THIRD_PARTY.md', 'THIRD_PARTY.zh-CN.md'):
            self.assertIn(name, ROOT_FILES)
        for path in GUIDES:
            self.assertIn(path.name, DOCS)
            self.assertIn('zh-CN/' + path.name, DOCS)

    def test_link_check_detects_stale_anchors(self):
        self.assertIn('a-heading', anchors('# A heading\n'))
        self.assertNotIn('old-heading', anchors('# A heading\n'))
        self.assertIn('旧链接', anchors('<a id="旧链接"></a>\n# New heading\n'))
