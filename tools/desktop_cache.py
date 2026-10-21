"""Best-effort user icon/menu refresh; never replaces a shell or compositor."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


SESSION_KEYS = ('DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR', 'XDG_CACHE_HOME',
                'XDG_DATA_DIRS', 'XDG_CONFIG_DIRS', 'XDG_CURRENT_DESKTOP', 'LANG', 'LC_ALL', 'LC_MESSAGES')


def plasma_sessions(proc=Path('/proc'), uid=None):
    """Read only the same user's Plasma bus/locale, including private Game Mode buses."""
    uid = os.getuid() if uid is None else uid
    sessions = {}
    try:
        processes = proc.iterdir()
        for entry in processes:
            if not entry.name.isdecimal():
                continue
            try:
                if entry.stat().st_uid != uid or (entry / 'comm').read_text().strip() != 'plasmashell':
                    continue
                with (entry / 'environ').open('rb') as stream:
                    raw = stream.read(1024 * 1024)
                selected = {}
                for item in raw.split(b'\0'):
                    key, separator, value = item.partition(b'=')
                    if separator and key.decode(errors='replace') in SESSION_KEYS:
                        selected[key.decode()] = os.fsdecode(value)
                bus = selected.get('DBUS_SESSION_BUS_ADDRESS', '')
                if not bus.startswith('unix:') or len(bus) > 4096:
                    continue
                mobile = b'org.kde.plasma.mobileshell' in (entry / 'cmdline').read_bytes().split(b'\0')
                sessions[bus] = (selected, mobile or sessions.get(bus, ({}, False))[1])
            except (OSError, ValueError):
                continue  # A mode switch can remove the process during discovery.
    except OSError:
        pass
    return list(sessions.values())


def refresh_desktop(paths):
    """Return warnings instead of failing a completed installation/removal."""
    result = {'warnings': [], 'sessions_notified': 0, 'mobile_session_active': False}
    if sys.platform != 'linux':
        return result
    env = dict(os.environ, HOME=str(paths.home), XDG_DATA_HOME=str(paths.data),
               XDG_CONFIG_HOME=str(paths.config), QT_QPA_PLATFORM='offscreen')
    env.setdefault('XDG_CACHE_HOME', str(paths.home / '.cache'))

    def run(name, arguments, environment):
        executable = shutil.which(name)
        if not executable:
            result['warnings'].append(name + ' 不可用，桌面缓存将在后续会话重新加载')
            return False
        try:
            completed = subprocess.run([executable, *arguments], env=environment,
                                       capture_output=True, timeout=5)
            if completed.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
        result['warnings'].append(name + ' 刷新失败；已完成的安装或卸载不受影响')
        return False

    theme = paths.data / 'icons/hicolor'
    if theme.is_dir() and not theme.is_symlink():
        run('gtk-update-icon-cache', ['--force', '--ignore-theme-index', str(theme)], env)
        try:
            os.utime(theme, None)
        except OSError:
            result['warnings'].append('图标目录更新时间失败；已完成的操作不受影响')

    sessions = plasma_sessions()
    # Still rebuild disk caches when installed over SSH with no running desktop.
    targets = sessions or [({}, False)]
    for selected, mobile in targets[:4]:
        session_env = dict(env, **selected)
        run('kbuildsycoca6', ['--noincremental'], session_env)
        if selected and run('gdbus', ['emit', '--address', selected['DBUS_SESSION_BUS_ADDRESS'],
                                     '--object-path', '/KIconLoader', '--signal',
                                     'org.kde.KIconLoader.iconChanged', '0'], session_env):
            result['sessions_notified'] += 1
        result['mobile_session_active'] |= mobile
    if result['mobile_session_active']:
        result['note'] = '移动主屏可能保留旧图像；下次切回游戏模式时重新加载，不自动重启下屏会话'
    return result
