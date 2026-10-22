"""In-memory UI translation, separate from keyboard input and system settings.

Messages retain their stable identity until displayed. No filesystem, locale
mutation, GTK import, input change or subprocess is involved in translation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from string import Formatter

from .ui_catalogs import EN_US, ZH_CN

CATALOGS = {'en_US': EN_US, 'zh_CN': ZH_CN}
UI_LANGUAGES = {'auto': None, 'zh_CN': '简体中文', 'en_US': 'English'}
STEAM_LANGUAGE_HINT = 'ADS_STEAM_UI_LANGUAGE'
_language = 'en_US'


def read_ui_language(value):
    return value if isinstance(value, str) and value in UI_LANGUAGES else 'en_US'


def neutral_locale(environ):
    locale = next((environ.get(key) for key in ('LC_ALL', 'LC_MESSAGES', 'LANG')
                   if environ.get(key)), 'C')
    return locale.split('.', 1)[0].split('@', 1)[0].upper() in ('C', 'POSIX')


def resolve_language(value, environ=None):
    value = read_ui_language(value)
    if value != 'auto':
        return value
    env = os.environ if environ is None else environ
    locale = next((env.get(key) for key in ('LC_ALL', 'LC_MESSAGES', 'LANG') if env.get(key)), 'C')
    # Armada's Game Mode uses C.UTF-8 even with a translated Steam UI. The
    # launcher supplies a validated, startup-only hint without changing LANG.
    # LANGUAGE alone still does not override the untranslated C locale.
    if neutral_locale(env):
        hint = env.get(STEAM_LANGUAGE_HINT)
        return hint if hint in ('en_US', 'zh_CN') else 'en_US'
    choices = env.get('LANGUAGE', '').split(':') + [locale]
    for choice in choices:
        language = choice.replace('-', '_').split('_', 1)[0].split('.', 1)[0].lower()
        if language in ('zh', 'en'):
            return 'zh_CN' if language == 'zh' else 'en_US'
    return 'en_US'


def active_language():
    return _language


def configure(value, environ=None):
    global _language
    resolved = resolve_language(value, environ)
    changed = resolved != _language
    _language = resolved
    return changed


def tr(key, **values):
    template = CATALOGS[_language].get(key, EN_US.get(key, ZH_CN.get(key, key)))
    return template.format(**{name: str(value) if isinstance(value, Message) else value
                              for name, value in values.items()})


@dataclass(frozen=True)
class Message:
    key: str
    values: dict
    _rendered: dict = field(default_factory=dict, compare=False, repr=False)

    def __str__(self):
        language = active_language()
        if language not in self._rendered:
            self._rendered[language] = tr(self.key, **self.values)
        return self._rendered[language]


def msg(key, **values):
    if key not in EN_US:
        raise KeyError(key)
    return Message(key, values)


class LocalizedState:
    """Keep public .message a string while allowing live language changes."""
    @property
    def message(self):
        return str(self._message)

    @message.setter
    def message(self, value):
        self._message = value

    @property
    def message_key(self):
        return self._message.key if isinstance(self._message, Message) else None


def encode_message(value):
    """Optional status-file metadata; old readers still see the plain message."""
    if not isinstance(value, Message):
        return None
    return {'key': value.key, 'values': {
        key: encode_message(item) if isinstance(item, Message) else item
        for key, item in value.values.items()}}


def decode_message(data, fallback='', _depth=0):
    if _depth > 4 or not isinstance(data, dict) or set(data) != {'key', 'values'}:
        return fallback
    key, values = data['key'], data['values']
    if not isinstance(key, str) or key not in EN_US or not isinstance(values, dict):
        return fallback
    fields = {name for _, name, _, _ in Formatter().parse(EN_US[key]) if name is not None}
    if set(values) != fields:
        return fallback
    decoded = {}
    for name, value in values.items():
        if isinstance(value, dict):
            value = decode_message(value, None, _depth+1)
        if not (isinstance(value, (str, Message)) or type(value) in (int, float)):
            return fallback
        if isinstance(value, str) and len(value) > 240:
            return fallback
        decoded[name] = value
    return msg(key, **decoded)
