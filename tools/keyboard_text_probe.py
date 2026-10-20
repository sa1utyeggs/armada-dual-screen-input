#!/usr/bin/env python3
"""Opt-in Unicode commit check in this helper's own upper GTK text field.

Requires idle Steam UI. It never injects into Steam, a game, or another app.
No root/window-focus property, clipboard or system configuration is changed.
"""
from __future__ import annotations

import argparse
import ctypes as c
import json
import os
import time

from armada_dual_screen_input.gamescope_focus import Cookie, UpperFocus
from armada_dual_screen_input.gamescope_text import GamescopeText
from armada_dual_screen_input.pinyin_engine import PinyinEngine
from armada_dual_screen_input.keyboard_languages import KeyboardLanguages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-own-window-test", action="store_true", required=True)
    parser.parse_args()
    focus = UpperFocus(":0")
    initial = focus.snapshot()
    if initial.app_id != 769 or initial.graphics_app_id != 769:
        focus.close()
        raise SystemExit("Idle Steam UI required; no window opened or input sent")
    os.environ.update(GDK_BACKEND="x11", DISPLAY=":0", NO_AT_BRIDGE="1")
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("GdkX11", "3.0")
    from gi.repository import GLib, Gtk, GdkX11

    window = Gtk.Window(title="Armada keyboard Unicode check — automatic close")
    window.set_decorated(False)
    window.fullscreen()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
    box.set_border_width(100)
    box.pack_start(Gtk.Label(label="多语言键盘接口测试 · 数秒后自动关闭"), False, False, 0)
    entry = Gtk.Entry()
    box.pack_start(entry, False, False, 0)
    window.add(box)
    window.realize()
    xid = GdkX11.X11Window.get_xid(window.get_window())
    focus.api.xcb_change_property_checked.restype = Cookie
    focus.api.xcb_change_property_checked.argtypes = [c.c_void_p, c.c_uint8, c.c_uint32,
                                                    c.c_uint32, c.c_uint32, c.c_uint8,
                                                    c.c_uint32, c.c_void_p]
    focus.api.xcb_request_check.restype = c.c_void_p
    focus.api.xcb_request_check.argtypes = [c.c_void_p, Cookie]
    for name, value, kind in (("STEAM_GAME", 769, 6), ("WM_TRANSIENT_FOR", initial.window, 33)):
        encoded = name.encode()
        reply = focus._reply("xcb_intern_atom_reply", focus.api.xcb_intern_atom(
            focus.connection, False, len(encoded), encoded))
        atom = c.c_uint32.from_address(reply + 8).value
        focus.libc.free(reply)
        data = c.c_uint32(value)
        cookie = focus.api.xcb_change_property_checked(focus.connection, 0, xid,
                                                       atom, kind, 32, 1, c.byref(data))
        error = focus.api.xcb_request_check(focus.connection, cookie)
        if error:
            focus.libc.free(error)
            raise RuntimeError("Could not set up this helper's own window")
    engine = PinyinEngine()
    candidates = engine.lookup("nihao")
    word, rest = engine.choose(0)
    engine.close()
    assert word == "你好" and rest == ""
    transport = GamescopeText("/run/user/" + str(os.getuid()))
    languages = None
    loop = GLib.MainLoop()
    result = {"passed": False, "input_sent": False, "system_pinyin": candidates[0] == "你好"}
    state = {"phase": "focus", "start": time.monotonic(), "at": 0.}

    def step():
        nonlocal languages
        now = time.monotonic()
        try:
            if now - state["start"] > 9:
                raise RuntimeError("Own text field did not become ready")
            current = focus.snapshot()
            if current.window != xid or not current.input_in_surface:
                if state["phase"] == "focus":
                    return True
                raise RuntimeError("Helper lost focus; no further input sent")
            if state["phase"] == "focus":
                transport.commit(word, current)
                result["input_sent"] = True
                state.update(phase="first", at=now)
            elif state["phase"] == "first" and now - state["at"] > .5:
                if entry.get_text() != "你好":
                    raise RuntimeError("Unicode text did not reach the helper's own text field")
                transport.commit(" 世界 @é", current)
                state.update(phase="second", at=now)
            elif state["phase"] == "second" and now - state["at"] > .5:
                if entry.get_text() != "你好 世界 @é":
                    raise RuntimeError("Direct Unicode commit mismatch")
                result["direct_unicode"] = True
                transport.close()
                entry.set_text("")
                languages = KeyboardLanguages(
                    "zh_CN", mode="game", runtime="/run/user/" + str(os.getuid()),
                    changed=lambda: None, dispatch=GLib.idle_add,
                    forward_key=lambda code: None,
                )
                languages.sync(True)
                state.update(phase="worker", at=now)
            elif state["phase"] == "worker" and languages.ready:
                for code in (49, 23, 35, 30, 24):  # nihao
                    languages.key(code)
                state.update(phase="compose", at=now)
            elif state["phase"] == "compose" and languages.preedit == "nihao":
                if not languages.candidates or languages.candidates[0] != "你好":
                    raise RuntimeError("Persistent worker candidate mismatch")
                if entry.get_text():
                    raise RuntimeError("Raw pinyin leaked into the target")
                languages.choose(0)
                state.update(phase="choose", at=now)
            elif state["phase"] == "choose" and entry.get_text() == "你好":
                for code in (31, 35, 23, 36, 23, 18):  # shijie
                    languages.key(code)
                languages.key(57)  # Space queued immediately after the letters.
                state.update(phase="ordered-space", at=now)
            elif state["phase"] == "ordered-space" and entry.get_text() == "你好世界":
                result.update(persistent_worker=True, ordered_space=True, no_raw_pinyin=True)
                languages.key(49)
                languages.sync(False)
                state.update(phase="cancel", at=now)
            elif state["phase"] == "cancel" and now - state["at"] > .3:
                result.update(passed=entry.get_text() == "你好世界",
                              own_window_only=True, canceled_on_hide=not languages.ready)
                loop.quit()
                return False
        except Exception as error:
            result["error"] = str(error)
            loop.quit()
            return False
        return True

    window.show_all()
    entry.grab_focus()
    GLib.timeout_add(40, step)
    try:
        loop.run()
    finally:
        if languages:
            languages.close()
        transport.close()
        window.destroy()
        focus.close()
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
