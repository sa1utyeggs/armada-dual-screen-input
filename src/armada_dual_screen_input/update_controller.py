"""Non-blocking settings model; network and process startup run off the GTK loop."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time

from .updates import UpdateError, latest_release, newer, process_identity, state_path

BUSY = {'checking', 'starting', 'downloading', 'installing'}


def after(seconds, callback):
    timer = threading.Timer(seconds, callback)
    timer.daemon = True
    timer.start()
    return timer


def start_worker(root, tag):
    command = ['systemd-run', '--user', '--collect', '--quiet', '--unit=thor-panel-update',
               '--property=Type=exec', '--expand-environment=no']
    for key in ('XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_RUNTIME_DIR'):
        value = os.environ.get(key)
        if value and Path(value).is_absolute():
            command.append('--setenv=' + key + '=' + value)
    command += ['/usr/bin/python3', '-B', str(Path(root) / 'tools/update.py'), '--expected-tag', tag]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise UpdateError('无法启动更新任务，请稍后重试')


class UpdateController:
    def __init__(self, root, *, dispatch, changed, fetch=latest_release, launch=start_worker,
                 background=None, status_file=None, deadline=after):
        self.root = Path(root).resolve()
        self.current = (self.root / 'VERSION').read_text().strip()
        data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
        self.managed = ((data / 'thor-panel/current').resolve() == self.root
                        and (data / 'thor-panel/install-state.json').is_file()
                        and (self.root / 'manifest.json').is_file()
                        and (self.root / 'tools/update.py').is_file())
        self.dispatch, self.changed = dispatch, changed
        self.fetch, self.launch = fetch, launch
        self.background = background or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self.status_file = status_file or state_path()
        self.phase, self.message = 'ready', '点击检查最新正式版'
        self.latest, self.confirming = None, False
        self._closed, self._request = False, 0
        self._launch_time = None
        self._checking = False
        self._deadline, self.deadline = None, deadline

    def _clear_deadline(self):
        if self._deadline:
            self._deadline.cancel()
            self._deadline = None

    @property
    def busy(self):
        return self.phase in BUSY

    @property
    def available(self):
        return (self.managed and self.latest is not None and self.phase in {'available', 'error'}
                and newer(self.latest.version, self.current))

    def _async(self, operation, complete):
        self._request += 1
        request = self._request
        def work():
            try:
                value, error = operation(), None
            except Exception as exc:
                value, error = None, str(exc) if isinstance(exc, UpdateError) else '操作失败，请检查网络后重试'
            def deliver():
                if not self._closed and request == self._request:
                    complete(value, error)
                    self.changed()
                return False
            self.dispatch(deliver)
        self.background(work)

    def check(self):
        if self._closed or self.busy:
            return
        self.phase, self.message = 'checking', '正在检查最新正式版…'
        self._checking = True
        self.latest, self.confirming = None, False
        def complete(release, error):
            self._clear_deadline()
            self._checking = False
            if error:
                self.phase, self.message = 'error', error
                return
            self.latest = release
            try:
                has_update = newer(release.version, self.current)
            except UpdateError:
                self.latest = None
                self.phase, self.message = 'error', '无法比较当前版本，请使用安装包升级'
                return
            if has_update:
                self.phase, self.message = 'available', '发现新版本 ' + release.tag
            else:
                self.phase, self.message = 'current', '当前已是最新正式版'
        self._async(self.fetch, complete)
        request = self._request
        def expired():
            def deliver():
                if not self._closed and request == self._request and self._checking:
                    self._deadline = None
                    self._request += 1
                    self._checking = False
                    self.phase, self.message = 'error', '检查更新超时，请检查网络后重试'
                    self.changed()
                return False
            self.dispatch(deliver)
        if self._checking:
            self._deadline = self.deadline(45, expired)
        self.changed()

    def install(self):
        if self._closed or not self.available:
            return
        tag = self.latest.tag
        self.confirming = False
        self.phase, self.message = 'starting', '正在启动独立更新任务…'
        self._launch_time = time.time()
        def complete(_, error):
            if error:
                self.phase, self.message = 'error', error
                self._launch_time = None
            else:
                self.refresh()
        self._async(lambda: self.launch(self.root, tag), complete)
        self.changed()

    def refresh(self):
        if self._closed or self._checking:
            return
        try:
            if self.status_file.stat().st_size > 8192:
                raise ValueError('Invalid status size')
            data = json.loads(self.status_file.read_text())
            if (not isinstance(data, dict) or data.get('schema') != 1
                    or data.get('phase') not in {'checking', 'downloading', 'installing', 'success', 'error'}):
                raise ValueError('Invalid status')
            if self._launch_time and self.status_file.stat().st_mtime < self._launch_time:
                raise FileNotFoundError
            phase, message = data['phase'], data.get('message', '')
            if not isinstance(message, str):
                raise ValueError('Invalid message')
            if phase == 'success' and self._launch_time is None and data.get('tag') != 'v' + self.current:
                return
            if phase in BUSY:
                pid = data.get('pid')
                if type(pid) is not int or pid <= 0 or not data.get('identity') or process_identity(pid) != data['identity']:
                    phase, message = 'error', '上次更新已中断，请重新检查后重试'
            if self.phase == 'available' and self._launch_time is None and phase not in BUSY:
                return
            self.phase, self.message = phase, message[:240]
            if phase not in BUSY:
                self._launch_time = None
        except (OSError, ValueError, TypeError):
            if self._launch_time and time.time() - self._launch_time > 15:
                self.phase, self.message = 'error', '更新任务未能启动，请重试'
                self._launch_time = None

    def close(self):
        self._clear_deadline()
        self._closed = True
        self._request += 1
