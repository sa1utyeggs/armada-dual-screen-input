"""Confirmed removal via a detached task; never uninstall on the GTK thread."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time

from .i18n import LocalizedState, active_language, decode_message, msg
from .updates import UpdateError, process_identity, state_path


def status_path():
    return state_path().with_name('uninstall.json')


def start_worker(root):
    command = ['systemd-run', '--user', '--collect', '--quiet', '--unit=thor-panel-uninstall',
               '--property=Type=exec', '--expand-environment=no']
    for key in ('XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_RUNTIME_DIR',
                'DBUS_SESSION_BUS_ADDRESS'):
        value = os.environ.get(key)
        if value and (key == 'DBUS_SESSION_BUS_ADDRESS' or Path(value).is_absolute()):
            command.append('--setenv=' + key + '=' + value)
    command += ['/usr/bin/python3', '-B', str(Path(root) / 'tools/uninstall.py'),
                '--ui-language', active_language()]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise UpdateError(msg('uninstall.start_failed'))


class UninstallController(LocalizedState):
    def __init__(self, root, *, dispatch, changed, launch=start_worker,
                 background=None, status_file=None):
        self.root = Path(root).resolve()
        data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
        self.managed = ((data / 'thor-panel/current').resolve() == self.root
                        and (data / 'thor-panel/install-state.json').is_file()
                        and (self.root / 'manifest.json').is_file()
                        and (self.root / 'tools/uninstall.py').is_file())
        self.dispatch, self.changed, self.launch = dispatch, changed, launch
        self.background = background or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self.status_file = status_file or status_path()
        self.phase, self.message = 'ready', msg('uninstall.ready')
        self.confirming = self._closed = False
        self._launch_time = None

    @property
    def busy(self):
        return self.phase in ('starting', 'uninstalling')

    def request(self):
        if not self._closed and self.managed and not self.busy and self.phase != 'success':
            self.confirming = True

    def cancel(self):
        self.confirming = False

    def run(self):
        if self._closed or not self.confirming or not self.managed or self.busy:
            return
        self.confirming = False
        self.phase, self.message = 'starting', msg('uninstall.starting')
        self._launch_time = time.time()
        def work():
            try:
                self.launch(self.root)
                error = None
            except Exception as exc:
                error = exc.args[0] if isinstance(exc, UpdateError) and exc.args else msg('uninstall.start_failed')
            def deliver():
                if not self._closed:
                    if error:
                        self.phase, self.message, self._launch_time = 'error', error, None
                    else:
                        self.refresh()
                    self.changed()
                return False
            self.dispatch(deliver)
        self.background(work)
        self.changed()

    def refresh(self):
        if self._closed or self._launch_time is None:
            return
        try:
            if self.status_file.stat().st_size > 8192 or self.status_file.stat().st_mtime < self._launch_time:
                raise ValueError('Stale or oversized uninstall status')
            data = json.loads(self.status_file.read_text())
            if (not isinstance(data, dict) or data.get('schema') != 1
                    or data.get('phase') not in ('uninstalling', 'success', 'error')
                    or not isinstance(data.get('message'), str)):
                raise ValueError('Invalid uninstall status')
            if data['phase'] == 'uninstalling' and (
                    type(data.get('pid')) is not int or data['pid'] <= 0
                    or not data.get('identity') or process_identity(data['pid']) != data['identity']):
                self.phase, self.message = 'error', msg('uninstall.interrupted')
            else:
                self.phase = data['phase']
                self.message = decode_message(data.get('message_i18n'), data['message'][:240])
            if not self.busy:
                self._launch_time = None
        except (OSError, ValueError, TypeError):
            if time.time() - self._launch_time > 20:
                self.phase, self.message, self._launch_time = 'error', msg('uninstall.start_failed'), None

    def close(self):
        self._closed = True
        self.confirming = False
