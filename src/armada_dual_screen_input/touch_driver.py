"""Unprivileged client for a separately installed, root-owned driver component."""
import json
import os
from pathlib import Path
import stat
import subprocess

COMPONENT = Path('/var/lib/armada-touch-fix-ui')
BRIDGE = COMPONENT / 'gui_bridge.py'


def bridge_available(root=COMPONENT):
    try:
        for path, directory in ((root.parent.parent, True), (root.parent, True), (root, True),
                                (root/'gui_bridge.py', False)):
            info = path.lstat()
            if info.st_uid != 0 or info.st_mode & 0o022:
                return False
            if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
                return False
        return True
    except OSError:
        return False


def probe(*, runner=subprocess.run):
    if not bridge_available():
        return {'schema': 1, 'component': False, 'compatible': False, 'active': False,
                'kernel': os.uname().release, 'autoload': False}
    result = runner(['/usr/bin/python3', '-I', '-B', str(BRIDGE), 'status'],
                    capture_output=True, text=True, timeout=8)
    if result.returncode or len(result.stdout) > 16384:
        raise ValueError('Driver component status unavailable')
    data = json.loads(result.stdout)
    if (not isinstance(data, dict) or data.get('schema') != 1 or
            any(type(data.get(key)) is not bool for key in ('component', 'compatible', 'active')) or
            not isinstance(data.get('kernel'), str) or len(data['kernel']) > 100):
        raise ValueError('Invalid driver status')
    return data


def authenticated_action(action, *, runner=subprocess.run):
    if action not in ('apply', 'revert') or not bridge_available():
        raise ValueError('Optional driver component is missing or unsafe')
    # No shell, caller-controlled script/module path, sudoers or polkit rule.
    result = runner(['/usr/bin/pkexec', '/usr/bin/python3', '-I', '-B', str(BRIDGE), action],
                    capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Administrator authentication canceled or driver operation failed')
    data = json.loads(result.stdout)
    if (not isinstance(data, dict) or data.get('schema') != 1 or 'error' in data
            or data.get('component') is not True or data.get('active') is not (action == 'apply')):
        raise RuntimeError('Driver operation returned no valid result')
    return data
