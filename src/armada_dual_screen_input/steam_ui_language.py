"""Read Steam's UI-language registry once, outside rendering/input callbacks.

No Steam commands, debugger calls, account selection, writes or locale changes.
Missing, malformed or unsupported values supply no hint (English fallback).
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat

from .i18n import STEAM_LANGUAGE_HINT, neutral_locale

MAX_BYTES = 65536
_TOKEN = re.compile(r'\s+|//[^\r\n]*|"(?:\\.|[^"\\])*"|[{}]|[^\s{}"]+')
_LANGUAGES = {'schinese': 'zh_CN', 'tchinese': 'zh_CN', 'english': 'en_US'}


def registry_language(text):
    """Parse bounded KeyValues; inspect only Steam's exact registry branches."""
    if len(text) > MAX_BYTES:
        return None
    tokens = []
    at = 0
    while at < len(text):
        match = _TOKEN.match(text, at)
        if match is None:
            return None
        token = match.group(); at = match.end()
        if token.isspace() or token.startswith('//'):
            continue
        structural = token in ('{', '}')
        if token.startswith('"'):
            token = re.sub(r'\\(["\\])', r'\1', token[1:-1])
        tokens.append((token, structural))
    if len(tokens) > 16384:
        return None
    paths = (
        ('registry', 'hkcu', 'software', 'valve', 'steam', 'language'),
        ('registry', 'hkcu', 'software', 'valve', 'steamsteamglobal', 'language'),
        ('registry', 'hklm', 'software', 'valve', 'steam', 'language'),
    )
    found = {}
    stack = []
    index = 0
    while index < len(tokens):
        (key, structural) = tokens[index]; index += 1
        if structural and key == '}':
            if not stack:
                return None
            stack.pop(); continue
        if structural or index == len(tokens):
            return None
        (value, structural) = tokens[index]; index += 1
        if structural and value == '{':
            stack.append(key.casefold())
            if len(stack) > 32:
                return None
        elif structural:
            return None
        else:
            path = (*stack, key.casefold())
            if path in paths:
                if path in found:
                    return None
                found[path] = value.strip().casefold()
    if stack:
        return None
    for path in paths:
        if path in found:
            return _LANGUAGES.get(found[path])
    return None


def read_steam_language(home):
    path = Path(home) / '.steam/registry.vdf'
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_CLOEXEC', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                return None
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return None
        return registry_language(data.decode('utf-8-sig'))
    except (OSError, UnicodeError, ValueError):
        return None


def add_steam_language_hint(environment, mode):
    """Copy environment; add only a fresh Game Mode / neutral-locale hint."""
    result = dict(environment)
    result.pop(STEAM_LANGUAGE_HINT, None)
    if mode == 'game' and neutral_locale(result):
        home = Path(result['HOME']) if result.get('HOME') else Path.home()
        if home.is_absolute():
            language = read_steam_language(home)
            if language in ('en_US', 'zh_CN'):
                result[STEAM_LANGUAGE_HINT] = language
    return result
