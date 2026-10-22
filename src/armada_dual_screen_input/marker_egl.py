"""An input-transparent XCB/EGL surface, scoped to one verified Gamescope.

EGL_EXT_platform_xcb requires a pointer to the XID, not an Xlib Window or
Display. An RGBA8/no-MSAA visual and empty input shape are mandatory. Setup
is checked before mapping. No root property, focus request or overlay slot
is modified. Full backbuffers are rendered; swap damage is only a hint to
the compositor, never permission to reuse undefined backbuffer contents.
"""
import ctypes as c
import os
from .gamescope_focus import Cookie, Iterator

def damage_values(rectangles, width, height):
    """Convert validated top-left scene damage to EGL bottom-left rectangles."""
    if len(rectangles) > 64:
        raise ValueError('Too many marker damage rectangles')
    values = []
    for rect in rectangles:
        if len(rect) != 4 or any((type(n) is not int for n in rect)):
            raise ValueError('Invalid marker damage')
        (x, y, w, h) = rect
        if w < 1 or h < 1 or x < 0 or (y < 0) or (x + w > width) or (y + h > height):
            raise ValueError('Marker damage exceeds canvas')
        values.extend((x, height - y - h, w, h))
    return values


EGL_EXTENSIONS = 0x3055
EGL_PLATFORM_XCB_EXT = 0x31dc
EGL_PLATFORM_XCB_SCREEN_EXT = 0x31de
EGL_NONE = 0x3038
EGL_SURFACE_TYPE = 0x3033
EGL_RENDERABLE_TYPE = 0x3040
EGL_RED_SIZE = 0x3024
EGL_GREEN_SIZE = 0x3023
EGL_BLUE_SIZE = 0x3022
EGL_ALPHA_SIZE = 0x3021
EGL_DEPTH_SIZE = 0x3025
EGL_STENCIL_SIZE = 0x3026
EGL_SAMPLE_BUFFERS = 0x3032
EGL_NATIVE_VISUAL_ID = 0x302e
EGL_SAMPLES = 0x3031
EGL_CONFIG_CAVEAT = 0x3027
EGL_OPENGL_ES_API = 0x30a0
EGL_CONTEXT_CLIENT_VERSION = 0x3098

class Surface:

    def __init__(self, focus, target):
        (self.focus, self.target) = (focus, target)
        self.egl = c.CDLL('libEGL.so.1')
        self.display = self.context = self.surface = None
        self.window = self.colormap = 0
        self.mapped = False
        self.swap_damage = None
        (p, i, u) = (c.c_void_p, c.c_int, c.c_uint)
        signatures = {
            'eglQueryString': (c.c_char_p, [p, i]),
            'eglGetError': (u, []),
            'eglGetProcAddress': (p, [c.c_char_p]),
            'eglInitialize': (u, [p, c.POINTER(i), c.POINTER(i)]),
            'eglChooseConfig': (u, [p, c.POINTER(i), c.POINTER(p), i, c.POINTER(i)]),
            'eglGetConfigAttrib': (u, [p, p, i, c.POINTER(i)]),
            'eglBindAPI': (u, [u]),
            'eglCreateContext': (p, [p, p, p, c.POINTER(i)]),
            'eglMakeCurrent': (u, [p, p, p, p]),
            'eglSwapInterval': (u, [p, i]),
            'eglSwapBuffers': (u, [p, p]),
            'eglDestroyContext': (u, [p, p]),
            'eglDestroySurface': (u, [p, p]),
            'eglTerminate': (u, [p]),
        }
        for (name, (result, args)) in signatures.items():
            f = getattr(self.egl, name)
            (f.restype, f.argtypes) = (result, args)
        api = focus.api
        signatures = {
            'xcb_generate_id': (u, [p]),
            'xcb_request_check': (p, [p, Cookie]),
            'xcb_create_colormap_checked': (Cookie, [p, c.c_uint8, u, u, u]),
            'xcb_create_window_checked': (Cookie, [p, c.c_uint8, u, u, c.c_int16, c.c_int16, c.c_uint16, c.c_uint16, c.c_uint16, c.c_uint16, u, u, p]),
            'xcb_change_property_checked': (Cookie, [p, c.c_uint8, u, u, u, c.c_uint8, u, p]),
            'xcb_map_window_checked': (Cookie, [p, u]),
            'xcb_destroy_window': (Cookie, [p, u]),
            'xcb_free_colormap': (Cookie, [p, u]),
            'xcb_flush': (i, [p]),
            'xcb_screen_allowed_depths_iterator': (Iterator, [p]),
            'xcb_depth_next': (None, [c.POINTER(Iterator)]),
            'xcb_depth_visuals_iterator': (Iterator, [p]),
            'xcb_visualtype_next': (None, [c.POINTER(Iterator)]),
            'xcb_poll_for_event': (p, [p]),
            'xcb_configure_window_checked': (Cookie, [p, u, c.c_uint16, p]),
        }
        for (name, (result, args)) in signatures.items():
            f = getattr(api, name)
            (f.restype, f.argtypes) = (result, args)
        try:
            self.setup()
        except Exception:
            self.close()
            raise

    def check(self, ok):
        if not ok:
            raise RuntimeError('EGL failure ' + hex(self.egl.eglGetError()))
        return ok

    def proc(self, name, result, args):
        address = self.egl.eglGetProcAddress(name.encode())
        if not address:
            raise RuntimeError('Missing EGL entry ' + name)
        return c.CFUNCTYPE(result, *args)(address)

    def checked(self, cookie):
        error = self.focus.api.xcb_request_check(self.focus.connection, cookie)
        if error:
            code = c.c_uint8.from_address(error + 1).value
            self.focus.libc.free(error)
            raise RuntimeError('Owned XCB request failed: ' + str(code))

    def depth(self, visual):
        api = self.focus.api
        screen = api.xcb_setup_roots_iterator(api.xcb_get_setup(self.focus.connection))
        while screen.rem:
            if c.c_uint32.from_address(screen.data).value == self.focus.root:
                depths = api.xcb_screen_allowed_depths_iterator(screen.data)
                while depths.rem:
                    visuals = api.xcb_depth_visuals_iterator(depths.data)
                    while visuals.rem:
                        if c.c_uint32.from_address(visuals.data).value == visual:
                            return c.c_uint8.from_address(depths.data).value
                        api.xcb_visualtype_next(c.byref(visuals))
                    api.xcb_depth_next(c.byref(depths))
            api.xcb_screen_next(c.byref(screen))
        return None

    def atom(self, name):
        raw = name.encode()
        f = self.focus
        reply = f._reply('xcb_intern_atom_reply', f.api.xcb_intern_atom(f.connection, False, len(raw), raw))
        try:
            return c.c_uint32.from_address(reply + 8).value
        finally:
            f.libc.free(reply)

    def property(self, name, values, kind=6):
        data = (c.c_uint32 * len(values))(*values)
        self.checked(self.focus.api.xcb_change_property_checked(self.focus.connection, 0, self.window, self.atom(name), kind, 32, len(values), data))

    def setup(self):
        # https://registry.khronos.org/EGL/extensions/EXT/EGL_EXT_platform_xcb.txt
        # https://registry.khronos.org/EGL/extensions/KHR/EGL_KHR_swap_buffers_with_damage.txt
        (p, i, u) = (c.c_void_p, c.c_int, c.c_uint)
        egl = self.egl
        f = self.focus
        api = f.api
        clients = (egl.eglQueryString(None, EGL_EXTENSIONS) or b'').split()
        if b'EGL_EXT_platform_xcb' not in clients:
            raise RuntimeError('EGL XCB platform unavailable')
        get_display = self.proc('eglGetPlatformDisplayEXT', p, [u, p, c.POINTER(i)])
        screen = int(self.target.surface_display.partition('.')[2] or 0)
        self.display = self.check(get_display(EGL_PLATFORM_XCB_EXT, f.connection, (i * 3)(EGL_PLATFORM_XCB_SCREEN_EXT, screen, EGL_NONE)))
        (major, minor) = (i(), i())
        self.check(egl.eglInitialize(self.display, c.byref(major), c.byref(minor)))
        self.extensions = (egl.eglQueryString(self.display, EGL_EXTENSIONS) or b'').split()
        attrs = (i * 19)(EGL_SURFACE_TYPE, 4, EGL_RENDERABLE_TYPE, 64, EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_DEPTH_SIZE, 0, EGL_STENCIL_SIZE, 0, EGL_SAMPLE_BUFFERS, 0, EGL_NONE)
        count = i()
        self.check(egl.eglChooseConfig(self.display, attrs, None, 0, c.byref(count)))
        if not 1 <= count.value <= 4096:
            raise RuntimeError('Invalid EGL config count')
        configs = (p * count.value)()
        self.check(egl.eglChooseConfig(self.display, attrs, configs, len(configs), c.byref(count)))
        if not 1 <= count.value <= len(configs):
            raise RuntimeError('EGL config count changed')
        config = None
        visual = 0
        for item in configs[:count.value]:
            vid = i()
            samples = i()
            caveat = i()
            self.check(egl.eglGetConfigAttrib(self.display, item, EGL_NATIVE_VISUAL_ID, c.byref(vid)))
            self.check(egl.eglGetConfigAttrib(self.display, item, EGL_SAMPLES, c.byref(samples)))
            self.check(egl.eglGetConfigAttrib(self.display, item, EGL_CONFIG_CAVEAT, c.byref(caveat)))
            if vid.value and self.depth(vid.value) == 32 and (samples.value == 0) and (caveat.value == EGL_NONE):
                (config, visual) = (item, vid.value)
                break
        if config is None:
            raise RuntimeError('No conformant alpha X11 EGL visual')
        self.colormap = api.xcb_generate_id(f.connection)
        self.checked(api.xcb_create_colormap_checked(f.connection, 0, self.colormap, f.root, visual))
        self.window = api.xcb_generate_id(f.connection)
        mask = 1 << 1 | 1 << 3 | 1 << 9 | 1 << 11 | 1 << 13
        values = (u * 5)(0, 0, 1, 1 << 15 | 1 << 17, self.colormap)
        self.checked(api.xcb_create_window_checked(f.connection, 32, self.window, f.root, self.target.x, self.target.y, self.target.width, self.target.height, 0, 1, visual, mask, values))
        shape = c.CDLL('libxcb-shape.so.0')
        shape.xcb_shape_rectangles_checked.restype = Cookie
        shape.xcb_shape_rectangles_checked.argtypes = [p, c.c_uint8, c.c_uint8, c.c_uint8, u, c.c_int16, c.c_int16, u, p]
        # ShapeSet=0, ShapeInput=2: zero rectangles make it click-through.
        self.checked(shape.xcb_shape_rectangles_checked(f.connection, 0, 2, 0, self.window, 0, 0, 0, None))
        for (name, value, kind) in self.target.properties():
            self.property(name, [value], kind)
        self.property('WM_HINTS', [1, 0, 1, 0, 0, 0, 0, 0, 0], 35)
        self.property('_NET_WM_PID', [os.getpid()])
        self.property('_NET_WM_WINDOW_TYPE', [self.atom('_NET_WM_WINDOW_TYPE_TOOLTIP')], 4)
        self.property('_NET_WM_STATE', [self.atom('_NET_WM_STATE_SKIP_TASKBAR'), self.atom('_NET_WM_STATE_SKIP_PAGER')], 4)
        self.flush()
        self.check(egl.eglBindAPI(EGL_OPENGL_ES_API))
        self.context = self.check(egl.eglCreateContext(self.display, config, None, (i * 3)(EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE)))
        create_surface = self.proc('eglCreatePlatformWindowSurfaceEXT', p, [p, p, p, c.POINTER(i)])
        xid = u(self.window)
        self.surface = self.check(create_surface(self.display, config, c.byref(xid), (i * 1)(EGL_NONE)))
        self.check(egl.eglMakeCurrent(self.display, self.surface, self.surface, self.context))
        self.check(egl.eglSwapInterval(self.display, 0))
        for (extension, symbol) in ((b'EGL_KHR_swap_buffers_with_damage', 'eglSwapBuffersWithDamageKHR'), (b'EGL_EXT_swap_buffers_with_damage', 'eglSwapBuffersWithDamageEXT')):
            if extension in self.extensions:
                self.swap_damage = self.proc(symbol, u, [p, p, c.POINTER(i), i])
                break

    def map(self):
        self.checked(self.focus.api.xcb_map_window_checked(self.focus.connection, self.window))
        self.flush()
        self.mapped = True

    def swap(self, rectangles):
        # Renderer clears/rebuilds every backbuffer. These are surface damage
        # hints only; no EGL buffer-age preservation is assumed.
        if not rectangles:
            return
        if self.swap_damage:
            data = damage_values(rectangles, self.target.width, self.target.height)
            array = (c.c_int * len(data))(*data)
            self.check(self.swap_damage(self.display, self.surface, array, len(rectangles)))
        else:
            self.check(self.egl.eglSwapBuffers(self.display, self.surface))

    def raise_window(self):
        value = c.c_uint32(0)
        self.checked(self.focus.api.xcb_configure_window_checked(self.focus.connection, self.window, 1 << 6, c.byref(value)))
        self.flush()

    def flush(self):
        self.focus.api.xcb_flush(self.focus.connection)

    def close(self):
        if self.display:
            self.egl.eglMakeCurrent(self.display, None, None, None)
            if self.surface:
                self.egl.eglDestroySurface(self.display, self.surface)
            if self.context:
                self.egl.eglDestroyContext(self.display, self.context)
            self.egl.eglTerminate(self.display)
        if self.window:
            self.focus.api.xcb_destroy_window(self.focus.connection, self.window)
        if self.colormap:
            self.focus.api.xcb_free_colormap(self.focus.connection, self.colormap)
        if self.window or self.colormap:
            self.flush()
        self.display = self.surface = self.context = None
        self.window = self.colormap = 0
