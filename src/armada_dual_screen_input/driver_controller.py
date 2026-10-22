"""Settings-only asynchronous driver status and explicit confirmed actions."""
import json
import os
from pathlib import Path
import subprocess
import threading

from .i18n import LocalizedState, active_language, msg
from .touch_driver import probe
from .user_tasks import manager_environment


def launch(root, action):
    if action not in ('apply', 'revert'):
        raise ValueError('Unknown driver action')
    args = ['systemd-run', '--user', '--collect', '--quiet', '--unit=thor-panel-driver',
            '--property=Type=exec', '--expand-environment=no', '--wait']
    for key in ('XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_RUNTIME_DIR',
                'DBUS_SESSION_BUS_ADDRESS'):
        value = os.environ.get(key)
        if value and (key == 'DBUS_SESSION_BUS_ADDRESS' or Path(value).is_absolute()):
            args.append('--setenv='+key+'='+value)
    args += ['/usr/bin/python3', '-B', str(Path(root)/'tools/driver.py'), action,
             '--ui-language', active_language()]
    # The lower KDE session has a private D-Bus instance without systemd1.
    # Let the launcher find this user's real manager; preserve the lower bus
    # only in the worker's explicit --setenv for desktop notifications/auth.
    result = subprocess.run(args, capture_output=True, text=True, env=manager_environment())
    if result.returncode:
        raise RuntimeError('Cannot launch driver task')


class DriverController(LocalizedState):
    def __init__(self, root, *, dispatch, changed, inspect=probe, start=launch, background=None):
        self.root = Path(root)
        self.dispatch, self.changed, self.inspect, self.launch = dispatch, changed, inspect, start
        self.background = background or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self.info = {'component': False, 'compatible': False, 'active': False, 'kernel': ''}
        self.message = msg('driver.not_checked')
        self.phase = 'idle'
        self.confirming = None
        self._closed = False

    @property
    def busy(self):
        return self.phase in ('checking', 'starting')

    def can(self, action):
        return bool(self.phase == 'idle' and self.info['component'] and
                    ((action == 'apply' and self.info['compatible'] and not self.info['active'])
                     or (action == 'revert' and self.info['active'])))

    def refresh(self):
        if self.busy or self._closed:
            return
        self.cancel()
        self.phase, self.message = 'checking', msg('driver.checking')
        def work():
            try:
                info, error = self.inspect(), None
            except Exception:
                info, error = None, msg('driver.check_failed')
            def deliver():
                if not self._closed:
                    self.phase = 'error' if error else 'idle'
                    if info is not None:
                        self.info = info
                    self.message = (error or msg('driver.component_missing') if error or not self.info['component']
                                    else msg('driver.active') if self.info['active']
                                    else msg('driver.compatible') if self.info['compatible']
                                    else msg('driver.incompatible'))
                    self.changed()
                return False
            self.dispatch(deliver)
        self.background(work)
        self.changed()

    def request(self, action):
        if self.can(action):
            self.confirming = action

    def cancel(self):
        self.confirming = None

    def run(self):
        action = self.confirming
        if action is None or not self.can(action) or self._closed:
            return
        self.confirming = None
        self.phase, self.message = 'starting', msg('driver.starting')
        def work():
            try:
                self.launch(self.root, action); error = None
            except Exception:
                error = msg('driver.start_failed')
            def deliver():
                if not self._closed:
                    if error:
                        self.phase, self.message = 'error', error
                    self.changed()
                return False
            self.dispatch(deliver)
        self.background(work)
        self.changed()

    def close(self):
        self._closed = True
        self.cancel()
