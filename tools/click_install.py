#!/usr/bin/env python3
"""Graphical stable-release installer, also embedded in the download launcher.

Imports are read-only. Network and installation run only after explicit actions;
--preview renders this installer's own window without either operation.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading

# Source checkout entry point; the downloadable zip supplies its own modules.
SOURCE = Path(__file__).resolve().parent.parent / 'src'
if SOURCE.is_dir():
    sys.path.insert(0, str(SOURCE))

from armada_dual_screen_input.i18n import LocalizedState, UI_LANGUAGES, active_language, configure, msg, tr
from armada_dual_screen_input.updates import UpdateError, prepare_download
from armada_dual_screen_input.installer_release import latest_install_release
from manage import host_check
from release import PackageError, verify


def install_release(release, *, status, prepare=prepare_download, check=verify,
                    run=subprocess.run, check_host=host_check):
    """Install the exact release reviewed by the user; never follow main/latest again."""
    check_host()
    with tempfile.TemporaryDirectory(prefix='ads-click-download-') as directory:
        status('installer.downloading')
        bundle = prepare(release, Path(directory))
        status('installer.verifying')
        manifest = check(bundle)
        if (manifest['version'] != release.version
                or not re.fullmatch(r'[0-9a-f]{40}', manifest.get('source_revision', ''))):
            raise UpdateError(msg('worker.manifest'))
        env = dict(os.environ)
        for name in ('GH_TOKEN', 'GITHUB_TOKEN', 'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUSERBASE'):
            env.pop(name, None)
        status('installer.installing')
        result = run(['/usr/bin/python3', '-E', '-s', '-B', str(bundle / 'tools/manage.py'),
                      'install', '--offline'], cwd=bundle, env=env, capture_output=True, text=True)
        if result.returncode:
            raise PackageError((result.stderr or result.stdout)[-6000:].strip())
        return json.loads(result.stdout)


class InstallSession(LocalizedState):
    """UI-independent state; a retry always rechecks the host and stable metadata."""
    def __init__(self, *, changed=lambda: None, fetch=latest_install_release,
                 install=install_release, check_host=host_check):
        self.changed, self.fetch, self.install, self.check_host = changed, fetch, install, check_host
        self.phase, self.release, self.details = 'idle', None, ''
        self.message = msg('installer.checking')

    @property
    def busy(self):
        return self.phase in ('checking', 'installing')

    def update(self, key):
        self.message = msg(key)
        self.changed()

    def start(self, action, *, launch=lambda job: threading.Thread(target=job, daemon=False).start()):
        if self.busy:
            return False
        if action == 'install':
            if self.phase != 'ready' or self.release is None:
                return False
            self.phase = 'installing'
            job = self._install
        elif action == 'check':
            self.phase, self.release = 'checking', None
            job = self._check
        else:
            return False
        self.details = ''
        self.update('installer.checking' if action == 'check' else 'installer.downloading')
        launch(lambda: self._guard(job))
        return True

    def _guard(self, job):
        try:
            job()
        except Exception as error:
            self.phase = 'error'
            # Keep translated identities until paint, including after a language switch.
            self.details = error.args[0] if isinstance(error, UpdateError) and error.args else str(error)[-6000:]
            self.message = msg('installer.failed')
        self.changed()

    def _check(self):
        self.check_host()
        self.release = self.fetch()
        self.phase = 'ready'
        self.message = msg('installer.ready', tag=self.release.tag)

    def _install(self):
        result = self.install(self.release, status=self.update)
        self.phase = 'success'
        self.message = msg('installer.success', tag=self.release.tag)
        refresh = result.get('desktop_refresh', {})
        if refresh.get('warnings') or refresh.get('mobile_session_active'):
            self.message = msg('installer.success_refresh', tag=self.release.tag)


def window_size(display, available_size=None):
    """Use logical work areas: the Thor lower screen can be only 443×386."""
    if available_size is None:
        areas = [display.get_monitor(i).get_workarea() for i in range(display.get_n_monitors())]
        available_size = (min(a.width for a in areas), min(a.height for a in areas)) if areas else (564, 504)
    width, height = available_size
    return max(280, min(540, width - 24)), max(220, min(440, height - 64))


def create_window(session, Gtk, GLib, *, preview=False, offscreen=False, available_size=None):
    """Scroll content on small screens while keeping language/actions visible."""
    base = Gtk.OffscreenWindow if offscreen else Gtk.Window

    class InstallerWindow(base):
        def __init__(self):
            super().__init__()
            self.initial_size = window_size(self.get_display(), available_size)
            self.set_default_size(*self.initial_size)
            if offscreen:
                self.set_size_request(*self.initial_size)
            self.set_border_width(12)
            self.connect('delete-event', lambda *_: session.busy and not preview)
            self.connect('destroy', lambda *_: Gtk.main_quit() if Gtk.main_level() else None)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            self.add(box)
            self.body_scroll = Gtk.ScrolledWindow()
            self.body_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self.body_scroll.set_propagate_natural_width(False)
            self.body_scroll.set_propagate_natural_height(False)
            box.pack_start(self.body_scroll, True, True, 0)
            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            self.body_scroll.add(body)
            self.title_label = Gtk.Label(xalign=0)
            self.scope = Gtk.Label(xalign=0)
            self.status = Gtk.Label(xalign=0)
            for label in (self.title_label, self.status, self.scope):
                label.set_line_wrap(True)
                label.set_max_width_chars(54)
                label.set_selectable(True)
                body.pack_start(label, False, False, 0)
            self.languages = Gtk.ComboBoxText()
            for language in ('en_US', 'zh_CN'):
                self.languages.append(language, UI_LANGUAGES[language])
            self.languages.set_active_id(active_language())
            self.languages.connect('changed', self.language_changed)
            self.progress = Gtk.Spinner()
            body.pack_start(self.progress, False, False, 0)
            self.detail_scroll = Gtk.ScrolledWindow()
            self.detail_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            self.detail_scroll.set_min_content_height(90)
            self.detail_view = Gtk.TextView(editable=False, cursor_visible=False)
            self.detail_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            self.detail_scroll.add(self.detail_view)
            body.pack_start(self.detail_scroll, False, False, 0)
            buttons = Gtk.Box(spacing=8)
            buttons.pack_start(self.languages, True, True, 0)
            self.close_button = Gtk.Button()
            self.action = Gtk.Button()
            for button in (self.close_button, self.action):
                button.set_size_request(-1, 44)
            self.close_button.connect('clicked', lambda *_: self.destroy() if preview or not session.busy else None)
            self.action.connect('clicked', lambda *_: session.start(
                'install' if session.phase == 'ready' else 'check') if not preview else None)
            buttons.pack_end(self.action, False, False, 0)
            buttons.pack_end(self.close_button, False, False, 0)
            box.pack_end(buttons, False, False, 0)
            self.show_all()
            self.refresh()

        def language_changed(self, combo):
            configure(combo.get_active_id())
            self.refresh()

        def refresh(self):
            self.set_title(tr('installer.title'))
            self.title_label.set_text(tr('installer.title'))
            self.scope.set_text(tr('installer.scope'))
            self.status.set_text(session.message)
            self.languages.set_tooltip_text(tr('settings.ui_language'))
            self.close_button.set_label(tr('common.close'))
            self.close_button.set_sensitive(preview or not session.busy)
            self.action.set_label(tr('installer.install' if session.phase == 'ready' else 'installer.retry'))
            self.action.set_sensitive(session.phase in ('ready', 'error') and not preview)
            self.action.set_visible(session.phase != 'success')
            self.progress.start() if session.busy else self.progress.stop()
            self.progress.set_visible(session.busy)
            self.detail_view.get_buffer().set_text(str(session.details))
            self.detail_scroll.set_visible(bool(session.details))
            return False

    window = InstallerWindow()
    session.changed = lambda: GLib.idle_add(window.refresh)
    return window


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', choices=('ready', 'downloading', 'success', 'error'),
                        help='Show an inert installer window; no downloads or installation')
    args = parser.parse_args()
    configure('en_US')
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk, GLib
        initialized, _ = Gtk.init_check(None)
        if not initialized:
            raise RuntimeError('No graphical display')
    except (ImportError, ValueError, RuntimeError):
        message = tr('installer.no_gui')
        dialog = shutil.which('kdialog')
        if dialog:
            subprocess.run([dialog, '--error', message], check=False)
        print(message, file=sys.stderr)
        return 1
    session = InstallSession()
    if args.preview:
        from types import SimpleNamespace
        session.release = SimpleNamespace(tag='v0.0.0')
        session.phase = 'installing' if args.preview == 'downloading' else args.preview
        key = {'ready': 'installer.ready', 'downloading': 'installer.downloading',
               'success': 'installer.success', 'error': 'installer.failed'}[args.preview]
        session.message = msg(key, **({'tag': 'v0.0.0'} if args.preview in ('ready', 'success') else {}))
        if args.preview == 'error':
            session.details = msg('update.network')
    window = create_window(session, Gtk, GLib, preview=bool(args.preview))
    if not args.preview:
        session.start('check')
    Gtk.main()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
