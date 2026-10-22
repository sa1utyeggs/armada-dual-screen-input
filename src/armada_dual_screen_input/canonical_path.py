"""Fresh strict path resolution without Python-level per-component syscalls."""
from __future__ import annotations

import ctypes as c
from functools import lru_cache
import os
from pathlib import Path
import sys


@lru_cache(maxsize=1)
def _native_api():
    # Cache function pointers only, never resolved paths, metadata or a prior
    # authorization result. POSIX realpath(NULL) owns a malloc-allocated result.
    if not sys.platform.startswith('linux'):
        return None
    try:
        api = c.CDLL(None, use_errno=True)
        api.realpath.argtypes = [c.c_char_p, c.c_void_p]
        api.realpath.restype = c.c_void_p
        api.free.argtypes = [c.c_void_p]
        api.free.restype = None
        return api
    except (OSError, AttributeError):
        return None


def canonical_path(path: Path) -> Path:
    api = _native_api()
    if api is None:
        return path.resolve(strict=True)
    encoded = os.fsencode(path)
    if b'\0' in encoded:
        raise ValueError('embedded null byte')
    result = api.realpath(encoded, None)
    if not result:
        error = c.get_errno()
        raise OSError(error, os.strerror(error), os.fspath(path))
    try:
        return Path(os.fsdecode(c.string_at(result)))
    finally:
        api.free(result)
