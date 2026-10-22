"""GPU atlas rendering with the same premultiplied Cairo ring pixels.

Atlas allocation/upload is startup-only. Each frame clears the complete
backbuffer and draws at most ten tiny quads. No glFinish/readback occurs in
the application render loop. Shader coordinates match Cairo device pixels.
"""
import ctypes as c
from .marker_paint import _ring_sprite, _PHASES, _SPRITE_SIZE, _SPRITE_ORIGIN

VERTEX = b"""#version 150
uniform vec2 canvas;
uniform vec4 tile;
out vec2 uv;
void main() {
    vec2 unit = vec2((gl_VertexID == 1 || gl_VertexID == 3) ? 1.0 : 0.0,
                     gl_VertexID >= 2 ? 1.0 : 0.0);
    vec2 pos = tile.xy + unit * SPRITE_SIZE;
    gl_Position = vec4(pos.x / canvas.x * 2.0 - 1.0,
                       1.0 - pos.y / canvas.y * 2.0, 0.0, 1.0);
    uv = (tile.zw + unit * SPRITE_SIZE) / ATLAS_SIZE;
}""".replace(b'SPRITE_SIZE', str(float(_SPRITE_SIZE)).encode()).replace(
    b'ATLAS_SIZE', str(float(_PHASES*_SPRITE_SIZE)).encode())
FRAGMENT = b"""#version 150
uniform sampler2D atlas;
in vec2 uv;
out vec4 color;
void main() { color = texture(atlas, uv); }
"""

def rgba_pixels(data):
    """Cairo ARGB32 is native-endian premultiplied; GL expects RGBA bytes."""
    import sys
    data = bytearray(data)
    if sys.byteorder == 'little':
        (data[0::4], data[2::4]) = (data[2::4], data[0::4])
    else:
        (data[0::4], data[1::4], data[2::4], data[3::4]) = (data[1::4], data[2::4], data[3::4], data[0::4])
    return data


GL_VERSION = 0x1f02
GL_RENDERER = 0x1f01
GL_VERTEX_SHADER = 0x8b31
GL_FRAGMENT_SHADER = 0x8b30
GL_COMPILE_STATUS = 0x8b81
GL_LINK_STATUS = 0x8b82
GL_TEXTURE_2D = 0xde1
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_TEXTURE_WRAP_S = 0x2802
GL_TEXTURE_WRAP_T = 0x2803
GL_NEAREST = 0x2600
GL_CLAMP_TO_EDGE = 0x812f
GL_RGBA8 = 0x8058
GL_RGBA = 0x1908
GL_UNSIGNED_BYTE = 0x1401
GL_SCISSOR_TEST = 0xc11
GL_DEPTH_TEST = 0xb71
GL_STENCIL_TEST = 0xb90
GL_DITHER = 0xbd0
GL_COLOR_BUFFER_BIT = 0x4000
GL_BLEND = 0xbe2
GL_ONE_MINUS_SRC_ALPHA = 0x303
GL_TEXTURE0 = 0x84c0

class GL:

    def __init__(self):
        self.api = c.CDLL('libepoxy.so.0')
        (u, i, f, p) = (c.c_uint, c.c_int, c.c_float, c.c_void_p)
        signatures = {
            'GetString': (c.c_char_p, [u]),
            'GetError': (u, []),
            'Viewport': (None, [i, i, i, i]),
            'CreateShader': (u, [u]),
            'ShaderSource': (None, [u, i, c.POINTER(c.c_char_p), c.POINTER(i)]),
            'CompileShader': (None, [u]),
            'GetShaderiv': (None, [u, u, c.POINTER(i)]),
            'GetShaderInfoLog': (None, [u, i, c.POINTER(i), p]),
            'DeleteShader': (None, [u]),
            'CreateProgram': (u, []),
            'AttachShader': (None, [u, u]),
            'LinkProgram': (None, [u]),
            'GetProgramiv': (None, [u, u, c.POINTER(i)]),
            'GetProgramInfoLog': (None, [u, i, c.POINTER(i), p]),
            'DeleteProgram': (None, [u]),
            'UseProgram': (None, [u]),
            'GetUniformLocation': (i, [u, c.c_char_p]),
            'Uniform2f': (None, [i, f, f]),
            'Uniform4f': (None, [i, f, f, f, f]),
            'Uniform1i': (None, [i, i]),
            'GenVertexArrays': (None, [i, c.POINTER(u)]),
            'BindVertexArray': (None, [u]),
            'DeleteVertexArrays': (None, [i, c.POINTER(u)]),
            'DrawArrays': (None, [u, i, i]),
            'GenTextures': (None, [i, c.POINTER(u)]),
            'BindTexture': (None, [u, u]),
            'DeleteTextures': (None, [i, c.POINTER(u)]),
            'ActiveTexture': (None, [u]),
            'TexParameteri': (None, [u, u, i]),
            'TexImage2D': (None, [u, i, i, i, i, i, u, u, p]),
            'ClearColor': (None, [f, f, f, f]),
            'Clear': (None, [u]),
            'Enable': (None, [u]),
            'Disable': (None, [u]),
            'BlendFunc': (None, [u, u]),
        }
        for (name, (result, args)) in signatures.items():
            address = c.c_void_p.in_dll(self.api, 'epoxy_gl' + name).value
            if not address:
                raise RuntimeError('Missing GL entry ' + name)
            setattr(self, name, c.CFUNCTYPE(result, *args)(address))

class Renderer:

    def __init__(self, canvas, colors):
        self.gl = gl = GL()
        self.canvas = canvas
        self.program = 0
        self.vao = c.c_uint()
        self.textures = []
        self.info = {k: gl.GetString(v).decode(errors='replace') for (k, v) in (('version', GL_VERSION), ('renderer', GL_RENDERER))}
        if any(name in self.info['renderer'].lower() for name in ('llvmpipe', 'softpipe', 'swrast')):
            raise RuntimeError('Native marker requires a hardware renderer')
        shaders = []
        try:
            for (source, kind) in ((VERTEX, GL_VERTEX_SHADER), (FRAGMENT, GL_FRAGMENT_SHADER)):
                if 'OpenGL ES' in self.info['version']:
                    source = source.replace(b'#version 150', b'#version 300 es\nprecision highp float;')
                shader = gl.CreateShader(kind)
                shaders.append(shader)
                text = c.c_char_p(source)
                gl.ShaderSource(shader, 1, c.byref(text), None)
                gl.CompileShader(shader)
                status = c.c_int()
                gl.GetShaderiv(shader, GL_COMPILE_STATUS, c.byref(status))
                if not status.value:
                    log = c.create_string_buffer(4096)
                    gl.GetShaderInfoLog(shader, 4096, None, log)
                    raise RuntimeError('GL shader failed: ' + log.value.decode(errors='replace'))
            self.program = gl.CreateProgram()
            for shader in shaders:
                gl.AttachShader(self.program, shader)
            gl.LinkProgram(self.program)
            status = c.c_int()
            gl.GetProgramiv(self.program, GL_LINK_STATUS, c.byref(status))
            if not status.value:
                log = c.create_string_buffer(4096)
                gl.GetProgramInfoLog(self.program, 4096, None, log)
                raise RuntimeError('GL link failed: ' + log.value.decode(errors='replace'))
            self.canvas_location = gl.GetUniformLocation(self.program, b'canvas')
            self.tile_location = gl.GetUniformLocation(self.program, b'tile')
            self.atlas_location = gl.GetUniformLocation(self.program, b'atlas')
            if min(self.canvas_location, self.tile_location, self.atlas_location) < 0:
                raise RuntimeError('Missing sprite uniforms')
            gl.GenVertexArrays(1, c.byref(self.vao))
            for rgba in (colors.idle_rgba, colors.pressed_rgba):
                self.textures.append(self.make_atlas(rgba))
            self.check()
        except Exception:
            self.close()
            raise
        finally:
            for shader in shaders:
                gl.DeleteShader(shader)

    def check(self):
        error = self.gl.GetError()
        if error:
            raise RuntimeError('GL error ' + hex(error))

    def make_atlas(self, rgba):
        import cairo
        size = _PHASES * _SPRITE_SIZE
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        cr = cairo.Context(surface)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        for y in range(_PHASES):
            for x in range(_PHASES):
                cr.set_source_surface(_ring_sprite(rgba, x, y), x * _SPRITE_SIZE, y * _SPRITE_SIZE)
                cr.rectangle(x * _SPRITE_SIZE, y * _SPRITE_SIZE, _SPRITE_SIZE, _SPRITE_SIZE)
                cr.fill()
        surface.flush()
        data = rgba_pixels(surface.get_data())
        memory = (c.c_ubyte * len(data)).from_buffer(data)
        texture = c.c_uint()
        gl = self.gl
        gl.GenTextures(1, c.byref(texture))
        gl.BindTexture(GL_TEXTURE_2D, texture.value)
        for (key, value) in ((GL_TEXTURE_MIN_FILTER, GL_NEAREST), (GL_TEXTURE_MAG_FILTER, GL_NEAREST), (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE), (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)):
            gl.TexParameteri(GL_TEXTURE_2D, key, value)
        gl.TexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, size, size, 0, GL_RGBA, GL_UNSIGNED_BYTE, memory)
        return texture

    def draw(self, rings):
        # Full clear avoids stale pixels regardless of buffer age. Uploaded
        # Cairo pixels are premultiplied, so use ONE/ONE_MINUS_SRC_ALPHA.
        gl = self.gl
        (w, h) = self.canvas
        gl.Viewport(0, 0, w, h)
        gl.Disable(GL_SCISSOR_TEST)
        gl.Disable(GL_DEPTH_TEST)
        gl.Disable(GL_STENCIL_TEST)
        gl.Disable(GL_DITHER)
        gl.ClearColor(0, 0, 0, 0)
        gl.Clear(GL_COLOR_BUFFER_BIT)
        gl.Enable(GL_BLEND)
        gl.BlendFunc(1, GL_ONE_MINUS_SRC_ALPHA)
        gl.UseProgram(self.program)
        gl.BindVertexArray(self.vao.value)
        gl.ActiveTexture(GL_TEXTURE0)
        gl.Uniform1i(self.atlas_location, 0)
        gl.Uniform2f(self.canvas_location, w, h)
        bound = None
        for (u, v, pressed) in rings:
            (qx, qy) = (round(u * (w - 1) * _PHASES), round(v * (h - 1) * _PHASES))
            texture = self.textures[int(pressed)].value
            if texture != bound:
                gl.BindTexture(GL_TEXTURE_2D, texture)
                bound = texture
            gl.Uniform4f(self.tile_location, qx // _PHASES - _SPRITE_ORIGIN, qy // _PHASES - _SPRITE_ORIGIN, qx % _PHASES * _SPRITE_SIZE, qy % _PHASES * _SPRITE_SIZE)
            gl.DrawArrays(5, 0, 4)
        gl.BindVertexArray(0)
        gl.UseProgram(0)

    def close(self):
        for texture in self.textures:
            self.gl.DeleteTextures(1, c.byref(texture))
        self.textures = []
        if self.vao.value:
            self.gl.DeleteVertexArrays(1, c.byref(self.vao))
            self.vao.value = 0
        if self.program:
            self.gl.DeleteProgram(self.program)
            self.program = 0
