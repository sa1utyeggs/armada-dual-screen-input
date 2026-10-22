"""Read-only, bounded discovery of a selected Gamescope's capture interfaces.

No frames are captured and no input is sent. The Gamescope PipeWire protocol
is private and version-specific; an advertised node is not proof of usable
capture. Native calls run in a child process so an unresponsive compositor
cannot block the caller indefinitely.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys


def _validate_runtime(runtime: Path) -> Path:
    """Resolve and validate the directory afresh for this operation."""
    runtime = runtime.resolve(strict=True)
    info = runtime.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('runtime directory must belong to the current user')
    return runtime


def _display_path(runtime: Path, name: str) -> Path:
    """Resolve one endpoint inside an already-validated canonical directory."""
    if not name or name in ('.', '..') or '/' in name or '\0' in name:
        raise ValueError('an explicit display socket basename is required')
    path = (runtime / name).resolve(strict=True)
    if path.parent != runtime:
        raise ValueError('display must be a same-user socket inside the runtime directory')
    return path


def _socket_info(path: Path) -> os.stat_result:
    """Validate fresh metadata; callers must not reuse it for a later check."""
    info = path.stat()
    if info.st_uid != os.getuid() or not stat.S_ISSOCK(info.st_mode):
        raise ValueError('display must be a same-user socket inside the runtime directory')
    return info


def validate_display(runtime: Path, name: str) -> Path:
    runtime = _validate_runtime(runtime)
    path = _display_path(runtime, name)
    _socket_info(path)
    return path


def _native_query(path: Path) -> dict:
    import ctypes as c
    import ctypes.util

    class Interface(c.Structure):
        pass

    class Message(c.Structure):
        _fields_ = [('name', c.c_char_p), ('signature', c.c_char_p),
                    ('types', c.POINTER(c.POINTER(Interface)))]

    Interface._fields_ = [('name', c.c_char_p), ('version', c.c_int),
                          ('method_count', c.c_int), ('methods', c.POINTER(Message)),
                          ('event_count', c.c_int), ('events', c.POINTER(Message))]
    library = ctypes.util.find_library('wayland-client')
    if library is None:
        raise RuntimeError('libwayland-client is unavailable')
    lib = c.CDLL(library, use_errno=True)
    lib.wl_display_connect.argtypes = [c.c_char_p]
    lib.wl_display_connect.restype = c.c_void_p
    lib.wl_display_disconnect.argtypes = [c.c_void_p]
    lib.wl_display_roundtrip.argtypes = [c.c_void_p]
    lib.wl_display_roundtrip.restype = c.c_int
    lib.wl_proxy_marshal_constructor_versioned.argtypes = [
        c.c_void_p, c.c_uint32, c.POINTER(Interface), c.c_uint32]
    lib.wl_proxy_marshal_constructor_versioned.restype = c.c_void_p
    lib.wl_proxy_add_listener.argtypes = [c.c_void_p, c.POINTER(c.c_void_p), c.c_void_p]
    lib.wl_proxy_add_listener.restype = c.c_int

    display = lib.wl_display_connect(os.fsencode(path))
    if not display:
        raise RuntimeError('could not connect to the selected Wayland display')
    interfaces = []
    nodes = []
    global_cb = c.CFUNCTYPE(None, c.c_void_p, c.c_void_p, c.c_uint32,
                           c.c_char_p, c.c_uint32)
    remove_cb = c.CFUNCTYPE(None, c.c_void_p, c.c_void_p, c.c_uint32)
    node_cb = c.CFUNCTYPE(None, c.c_void_p, c.c_void_p, c.c_uint32)

    @global_cb
    def on_global(data, proxy, name, interface, version):
        interfaces.append((name, interface.decode('ascii', errors='replace'), version))

    @remove_cb
    def on_remove(data, proxy, name):
        interfaces[:] = [item for item in interfaces if item[0] != name]

    @node_cb
    def on_node(data, proxy, node_id):
        nodes.append(node_id)

    registry_listener = (c.c_void_p * 2)(c.cast(on_global, c.c_void_p),
                                        c.cast(on_remove, c.c_void_p))
    node_listener = (c.c_void_p * 1)(c.cast(on_node, c.c_void_p))
    # Keep message tables and callbacks alive through all native dispatches.
    methods = (Message * 1)(Message(b'destroy', b'', None))
    events = (Message * 1)(Message(b'stream_node', b'u', None))
    pipewire_interface = Interface(b'gamescope_pipewire', 1, 1, methods, 1, events)
    try:
        registry_interface = Interface.in_dll(lib, 'wl_registry_interface')
        registry = lib.wl_proxy_marshal_constructor_versioned(
            display, 1, c.byref(registry_interface), 1, None)
        if not registry or lib.wl_proxy_add_listener(registry, registry_listener, None) != 0:
            raise RuntimeError('could not register a Wayland registry listener')
        if lib.wl_display_roundtrip(display) < 0:
            raise RuntimeError('Wayland registry roundtrip failed')
        matches = [item for item in interfaces if item[1] == 'gamescope_pipewire']
        if len(matches) == 1:
            name, _, version = matches[0]
            proxy = lib.wl_proxy_marshal_constructor_versioned(
                registry, 0, c.byref(pipewire_interface), 1,
                c.c_uint32(name), c.c_char_p(b'gamescope_pipewire'), c.c_uint32(1), None)
            if not proxy or lib.wl_proxy_add_listener(proxy, node_listener, None) != 0:
                raise RuntimeError('could not register the PipeWire node listener')
            if lib.wl_display_roundtrip(display) < 0:
                raise RuntimeError('PipeWire node roundtrip failed')
        valid_nodes = [node for node in nodes if node != 0xffffffff]
        return {
            'status': 'node_advertised' if valid_nodes else 'no_capture_node',
            'interfaces': sorted({item[1] for item in interfaces}),
            'pipewire_node_id': valid_nodes[-1] if valid_nodes else None,
            'capture_tested': False,
            'input_tested': False,
        }
    finally:
        lib.wl_display_disconnect(display)


def probe_display(runtime: Path, name: str, *, timeout: float = 3.0) -> dict:
    if not sys.platform.startswith('linux'):
        return {'status': 'unsupported_platform'}
    if not 0 < timeout <= 30:
        raise ValueError('probe timeout must be between zero and 30 seconds')
    try:
        validate_display(runtime, name)
    except (OSError, ValueError) as error:
        return {'status': 'invalid_display', 'error': str(error)}
    try:
        result = subprocess.run(
            [sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--worker',
             '--runtime-dir', str(runtime), '--display', name],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        if result.returncode != 0:
            return {'status': 'probe_failed', 'returncode': result.returncode}
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise ValueError('probe result is not an object')
        return value
    except subprocess.TimeoutExpired:
        return {'status': 'timeout'}
    except (OSError, ValueError):
        return {'status': 'probe_failed'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--display', required=True, help='explicit target socket, e.g. gamescope-primary')
    parser.add_argument('--runtime-dir', type=Path,
                        default=Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')))
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        try:
            result = _native_query(validate_display(args.runtime_dir, args.display))
        except (OSError, ValueError, RuntimeError):
            return 1
    else:
        result = probe_display(args.runtime_dir, args.display)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
