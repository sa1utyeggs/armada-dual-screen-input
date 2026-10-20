"""Read characters from the system XKB keymap; never change a system layout."""
from __future__ import annotations

import ctypes as c
import ctypes.util


class XkbUnavailable(RuntimeError):
    pass


class _Names(c.Structure):
    _fields_ = [(key, c.c_char_p) for key in
                ("rules", "model", "layout", "variant", "options")]


class XkbLayout:
    """A private keymap/state, independent of the physical keyboard's layout."""
    def __init__(self, layout="us", variant=""):
        library = ctypes.util.find_library("xkbcommon")
        if not library:
            raise XkbUnavailable("System libxkbcommon is unavailable")
        self.lib = c.CDLL(library)
        self.context = self.keymap = self.state = None
        signatures = {
            "xkb_context_new": ([c.c_int], c.c_void_p),
            "xkb_context_unref": ([c.c_void_p], None),
            "xkb_keymap_new_from_names": ([c.c_void_p, c.POINTER(_Names), c.c_int], c.c_void_p),
            "xkb_keymap_unref": ([c.c_void_p], None),
            "xkb_keymap_mod_get_index": ([c.c_void_p, c.c_char_p], c.c_uint32),
            "xkb_state_new": ([c.c_void_p], c.c_void_p),
            "xkb_state_unref": ([c.c_void_p], None),
            "xkb_state_update_mask": ([c.c_void_p] + [c.c_uint32] * 6, c.c_uint32),
            "xkb_state_key_get_utf8": ([c.c_void_p, c.c_uint32, c.c_char_p, c.c_size_t], c.c_int),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.lib, name)
            function.argtypes, function.restype = args, result
        try:
            self.context = self.lib.xkb_context_new(0)
            if not self.context:
                raise XkbUnavailable("Could not create an XKB context")
            names = _Names(b"evdev", b"pc105", layout.encode("ascii"),
                           variant.encode("ascii"), b"")
            self.keymap = self.lib.xkb_keymap_new_from_names(self.context, c.byref(names), 0)
            if not self.keymap:
                raise XkbUnavailable("System XKB layout data is unavailable")
            self.state = self.lib.xkb_state_new(self.keymap)
            if not self.state:
                raise XkbUnavailable("Could not create an XKB state")
            self.modifiers = {}
            for name in ("Shift", "Lock", "Mod5"):
                index = self.lib.xkb_keymap_mod_get_index(self.keymap, name.encode())
                self.modifiers[name] = (1 << index) if index < 32 else 0
        except Exception:
            self.close()
            raise

    def character(self, code, *, shift=False, caps=False, altgr=False):
        if not self.state or not isinstance(code, int) or not 0 <= code <= 767:
            return ""
        mask = (self.modifiers["Shift"] if shift else 0) | (self.modifiers["Mod5"] if altgr else 0)
        self.lib.xkb_state_update_mask(self.state, mask, 0,
                                       self.modifiers["Lock"] if caps else 0, 0, 0, 0)
        output = c.create_string_buffer(64)
        length = self.lib.xkb_state_key_get_utf8(self.state, code + 8, output, len(output))
        return output.value.decode("utf-8") if 0 < length < len(output) else ""

    def close(self):
        for attr, name in (("state", "xkb_state_unref"), ("keymap", "xkb_keymap_unref"),
                           ("context", "xkb_context_unref")):
            pointer = getattr(self, attr, None)
            if pointer:
                getattr(self.lib, name)(pointer)
                setattr(self, attr, None)
