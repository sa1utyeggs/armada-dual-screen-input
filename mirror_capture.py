"""Latest-frame-only PipeWire capture, independent of the GTK input thread."""
from __future__ import annotations

from dataclasses import dataclass
import math
import threading
import time
from pathlib import Path

from gamescope_probe import probe_display, validate_display


@dataclass(frozen=True)
class CapturedFrame:
    sequence: int
    width: int
    height: int
    stride: int
    data: bytearray  # BGRx: Cairo FORMAT_RGB24 on little-endian Linux
    received_at: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.received_at):
            raise ValueError('frame receive time must be finite')
        if not (0 < self.width <= 8192 and 0 < self.height <= 8192):
            raise ValueError('invalid frame dimensions')
        if self.stride < self.width * 4 or self.stride * self.height > 128 * 1024 * 1024:
            raise ValueError('invalid or oversized frame stride')
        if len(self.data) < self.stride * self.height:
            raise ValueError('incomplete frame data')

    def fresh(self, now: float, max_age: float = 0.35) -> bool:
        return math.isfinite(now) and 0 <= now - self.received_at <= max_age


class FrameStore:
    """One immutable frame reference, never a backlog of outdated images."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: CapturedFrame | None = None

    def publish(self, frame: CapturedFrame) -> bool:
        with self._lock:
            if self._frame is not None and frame.sequence <= self._frame.sequence:
                return False
            self._frame = frame
            return True

    def latest(self) -> CapturedFrame | None:
        with self._lock:
            return self._frame

    def clear(self) -> None:
        with self._lock:
            self._frame = None


def pipeline_description(node_id: int, fps: int) -> str:
    if type(node_id) is not int or not 0 < node_id < 0xffffffff:
        raise ValueError('an advertised PipeWire node ID is required')
    if type(fps) is not int or not 1 <= fps <= 120:
        raise ValueError('invalid preview frame rate')
    return (
        f'pipewiresrc name=source path={node_id} do-timestamp=true on-disconnect=error '
        'use-bufferpool=false max-buffers=4 '
        '! queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 leaky=downstream '
        f'! videorate drop-only=true ! video/x-raw,framerate={fps}/1 '
        '! videoconvert ! video/x-raw,format=BGRx '
        '! appsink name=frames max-buffers=1 drop=true sync=false wait-on-eos=false'
    )


class MirrorCapture:
    def __init__(self, node_id: int, *, fps: int = 60) -> None:
        self.description = pipeline_description(node_id, fps)
        self.node_id, self.fps = node_id, fps
        self.source_size: tuple[int, int] | None = None
        self.frames = FrameStore()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.status = 'stopped'
        self.error: str | None = None
        self.checked_at = 0.0

    def healthy(self, now: float) -> bool:
        return self.status == 'running' and 0 <= now - self.checked_at <= 0.3

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError('capture instances cannot be restarted')
        self.status = 'starting'
        self._thread = threading.Thread(target=self._run, name='mirror-capture', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()  # Never wait for a graphics pipeline on the GTK thread.

    def wait(self, timeout: float = 2.0) -> bool:
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            return not self._thread.is_alive()
        return True

    def _run(self) -> None:
        pipeline = None
        try:
            import gi
            gi.require_version('Gst', '1.0')
            gi.require_version('GstVideo', '1.0')
            from gi.repository import Gst, GstVideo
            Gst.init(None)
            if Gst.ElementFactory.find('pipewiresrc') is None:
                raise RuntimeError('PipeWire GStreamer plugin is unavailable')
            # Keep one native-size stream for its entire lifetime. Reconnecting
            # or renegotiating a scaled stream caused missing first frames and
            # buffer removal with the tested PipeWire/GStreamer versions.
            # A static source may wait for its next commit; don't fail after 2s.
            pipeline = Gst.parse_launch(self.description)
            sink = pipeline.get_by_name('frames')
            if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError('capture pipeline failed to start')
            sequence = 0
            while not self._stop.is_set():
                sample = sink.emit('try-pull-sample', 100 * Gst.MSECOND)
                message = pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS)
                if message is not None:
                    if message.type == Gst.MessageType.ERROR:
                        error, _ = message.parse_error()
                        raise RuntimeError(str(error))
                    raise RuntimeError('capture stream ended')
                self.checked_at = time.monotonic()
                if sample is None:
                    continue
                info = GstVideo.VideoInfo.new_from_caps(sample.get_caps())
                if self.source_size is None:
                    self.source_size = (info.width, info.height)
                elif (info.width, info.height) != self.source_size:
                    raise RuntimeError('capture source size changed; reopen the preview')
                stride, offset = info.stride[0], info.offset[0]
                size = stride * info.height
                if not (0 < info.width <= 8192 and 0 < info.height <= 8192
                        and stride >= info.width * 4 and 0 < size <= 128 * 1024 * 1024):
                    raise RuntimeError('unsupported capture layout')
                buffer = sample.get_buffer()
                if buffer.get_size() < offset + size:
                    raise RuntimeError('incomplete capture buffer')
                ok, mapped = buffer.map(Gst.MapFlags.READ)
                if not ok:
                    raise RuntimeError('capture buffer cannot be mapped')
                try:
                    pixels = bytearray(mapped.data[offset:offset + size])
                finally:
                    buffer.unmap(mapped)
                sequence += 1
                received_at = time.monotonic()
                self.frames.publish(CapturedFrame(sequence, info.width, info.height, stride,
                                                  pixels, received_at))
                self.status = 'running'
        except Exception as error:
            self.error = str(error)
            self.status = 'error'
        finally:
            if pipeline is not None:
                pipeline.set_state(Gst.State.NULL)
            if self._stop.is_set():
                self.status = 'stopped'


class SourceMonitor:
    """Bounded compositor/node heartbeat for Gamescope's damage-driven stream.

Static images do not generate new buffers. A retained frame may be used only
while the capture worker, source identity and compositor query all remain live.
This cannot prove that an otherwise responsive producer has no internal bug;
the prototype still requires end-to-end game and suspend/resume validation.
"""

    def __init__(self, runtime: Path, display: str, node_id: int) -> None:
        self.runtime, self.display, self.node_id = runtime, display, node_id
        path = validate_display(runtime, display)
        info = path.stat()
        self.identity = (path, info.st_dev, info.st_ino)
        self.confirmed_at = 0.0
        self.valid = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name='capture-source', daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _same_source(self) -> bool:
        try:
            path = validate_display(self.runtime, self.display)
            info = path.stat()
            return self.identity == (path, info.st_dev, info.st_ino)
        except (OSError, ValueError):
            return False

    def current(self, now: float) -> bool:
        return (not self._stop.is_set() and self.valid
                and 0 <= now - self.confirmed_at <= 2 and self._same_source())

    def _run(self) -> None:
        while not self._stop.is_set():
            result = probe_display(self.runtime, self.display, timeout=0.8)
            self.valid = (self._same_source() and result.get('status') == 'node_advertised'
                          and result.get('pipewire_node_id') == self.node_id)
            if self.valid:
                self.confirmed_at = time.monotonic()
            self._stop.wait(0.8)
        self.valid = False

    def stop(self) -> None:
        self.valid = False
        self._stop.set()

    def wait(self) -> None:
        self._thread.join(timeout=1.2)
