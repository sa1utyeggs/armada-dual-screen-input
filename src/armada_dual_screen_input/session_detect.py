"""Read-only discovery of an Armada Plasma session suitable for a lower-screen app.

Discovery never starts a compositor, changes a service, or guesses a Wayland name.
Game Mode must have KWin's ``armada-plasma-bottom`` socket, not just the direct
``gamescope-secondary`` socket. Desktop Mode must have an identifiable Plasma
shell and a matching KWin. Ambiguous or stale sessions return None.

This proves that a same-user compositor and its socket exist; it does not prove
that the compositor currently owns the lower DRM panel or that input focus is
correct. In particular a dual-screen emulator may temporarily hold the lease.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Mapping


BOTTOM_DISPLAY = "armada-plasma-bottom"
# Do not retain arbitrary /proc environment variables, tokens, or command lines.
_ENV_KEYS = frozenset({
    "HOME", "USER", "LOGNAME", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE",
    "LC_MESSAGES", "TZ", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
    "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_CONFIG_DIRS", "XDG_DATA_DIRS",
    "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE", "XDG_SESSION_DESKTOP",
    "DESKTOP_SESSION", "DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY",
    "QT_QPA_PLATFORMTHEME", "QT_QUICK_CONTROLS_STYLE", "QT_QUICK_CONTROLS_MOBILE",
    "PLASMA_PLATFORM", "KDE_FULL_SESSION", "KDE_SESSION_VERSION",
})


@dataclass(frozen=True)
class SessionTarget:
    mode: str  # "game" or "desktop"
    runtime_dir: Path
    wayland_display: str
    environment: Mapping[str, str]
    source_pids: tuple[int, ...]


@dataclass(frozen=True)
class _Process:
    pid: int
    parent_pid: int
    name: str
    environment: Mapping[str, str]
    socket_name: str | None
    nested_x11: bool
    environment_readable: bool


def _read_environment(path: Path) -> dict[str, str]:
    selected: dict[str, str] = {}
    with path.open("rb") as stream:
        raw = stream.read(1024 * 1024)
    for entry in raw.split(b"\0"):
        key, separator, value = entry.partition(b"=")
        if not separator:
            continue
        try:
            key_text = key.decode("ascii")
            if key_text in _ENV_KEYS:
                selected[key_text] = value.decode("utf-8", errors="surrogateescape")
        except UnicodeError:
            continue
    return selected


def _read_processes(proc_root: Path, uid: int) -> list[_Process]:
    processes: list[_Process] = []
    try:
        entries = sorted(proc_root.iterdir(), key=lambda item: item.name)
    except OSError:
        return processes
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        try:
            status = {}
            with (entry / "status").open() as stream:
                for line in stream:
                    key, separator, value = line.partition(":")
                    if separator and key in {"Name", "Uid", "PPid"}:
                        status[key] = value.strip()
                    # Most /proc entries are unrelated to Plasma. Do not
                    # parse their remaining status lines; relevant processes
                    # still require fresh UID and parent metadata below.
                    if ("Name" in status and status["Name"] not in
                            {"kwin_wayland", "plasmashell"}) or len(status) == 3:
                        break
            if status.get("Name") not in {"kwin_wayland", "plasmashell"}:
                continue
            if int(status["Uid"].split()[1]) != uid:
                continue
            name = status["Name"]
            if name not in {"kwin_wayland", "plasmashell"}:
                continue
            environment_readable = True
            try:
                environment = _read_environment(entry / "environ")
            except PermissionError:
                # KWin can be non-dumpable even for the graphical user. Its
                # status/cmdline remain useful, but runtime and GUI environment
                # must then be corroborated by its direct Plasma child below.
                if name != "kwin_wayland":
                    continue
                environment = {}
                environment_readable = False
            socket_name = None
            nested_x11 = False
            if name == "kwin_wayland":
                # Only keep the options required to identify the compositor.
                args = (entry / "cmdline").read_bytes().split(b"\0")
                for index, argument in enumerate(args):
                    if argument == b"--socket" and index + 1 < len(args):
                        socket_name = os.fsdecode(args[index + 1])
                    elif argument.startswith(b"--socket="):
                        socket_name = os.fsdecode(argument.partition(b"=")[2])
                    elif argument == b"--x11-display" or argument.startswith(b"--x11-display="):
                        nested_x11 = True
            processes.append(_Process(
                pid=int(entry.name), parent_pid=int(status["PPid"]), name=name,
                environment=environment, socket_name=socket_name,
                nested_x11=nested_x11,
                environment_readable=environment_readable,
            ))
        except (OSError, ValueError, KeyError, IndexError):
            # Processes can disappear or become unreadable during a mode switch.
            continue
    return processes


def _display_name(value: str | None, runtime: Path) -> str | None:
    if not value or "\0" in value:
        return None
    path = Path(value)
    if path.is_absolute():
        if path.parent != runtime:
            return None
        value = path.name
    if value in {".", ".."} or "/" in value:
        return None
    return value


def _socket_exists(runtime: Path, name: str, uid: int) -> bool:
    try:
        info = (runtime / name).stat()
        return stat.S_ISSOCK(info.st_mode) and info.st_uid == uid
    except OSError:
        return False


def _same_runtime(process: _Process, runtime: Path) -> bool:
    return process.environment.get("XDG_RUNTIME_DIR") == str(runtime)


def _direct_shell_confirms_runtime(shell: _Process, kwin: _Process, runtime: Path) -> bool:
    if shell.parent_pid != kwin.pid or not _same_runtime(shell, runtime):
        return False
    env = shell.environment
    if env.get("XDG_SESSION_TYPE") != "wayland" or "KDE" not in env.get("XDG_CURRENT_DESKTOP", "").upper().split(":"):
        return False
    display = _display_name(env.get("WAYLAND_DISPLAY"), runtime)
    if not display:
        return False
    if kwin.socket_name:
        return _display_name(kwin.socket_name, runtime) == display
    # A normal desktop KWin may choose its socket after exec. Its direct child
    # can identify that socket; a bottom/nested KWin must explicitly name it.
    return not kwin.nested_x11 and _desktop_display(shell, runtime) is not None


def _dbus_kwin_owner(bus: str, runtime: Path, uid: int) -> int | None:
    # This fallback is for the ordinary Desktop session's user bus only. Do not
    # connect to network/abstract/arbitrary private buses from process metadata.
    match = re.fullmatch(r"unix:path=([^,;]+)(?:,guid=[0-9a-fA-F]{32})?", bus)
    if not match or Path(match.group(1)) != runtime / "bus":
        return None
    if not _socket_exists(runtime, "bus", uid):
        return None
    try:
        result = subprocess.run(
            ["/usr/bin/busctl", f"--address={bus}", "--timeout=1s", "call",
             "org.freedesktop.DBus", "/org/freedesktop/DBus",
             "org.freedesktop.DBus", "GetConnectionUnixProcessID", "s",
             "org.kde.KWin"],
            capture_output=True, text=True, timeout=1, check=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    owner = re.fullmatch(r"u ([1-9][0-9]*)\s*", result.stdout)
    return int(owner.group(1)) if owner else None


def _desktop_display(process: _Process, runtime: Path) -> str | None:
    env = process.environment
    desktops = env.get("XDG_CURRENT_DESKTOP", "").upper().split(":")
    if env.get("XDG_SESSION_TYPE") != "wayland" or "KDE" not in desktops:
        return None
    name = _display_name(env.get("WAYLAND_DISPLAY"), runtime)
    if not name or name.startswith(("gamescope", "armada-plasma-")):
        return None
    return name


def _matching_kwin(shell: _Process, kwin: _Process, display: str, runtime: Path) -> bool:
    if kwin.nested_x11 or (kwin.socket_name or "").startswith("armada-plasma-"):
        return False
    explicit = _display_name(kwin.socket_name, runtime)
    if explicit:
        return explicit == display
    inherited = _display_name(kwin.environment.get("WAYLAND_DISPLAY"), runtime)
    if inherited:
        return inherited == display
    if shell.parent_pid == kwin.pid:
        return True
    # Plasma may be spawned by systemd rather than directly by KWin. Armada's
    # nested sessions have a separate dbus-run-session, so a matching nonempty
    # session bus is useful corroboration, never a substitute for socket checks.
    bus = shell.environment.get("DBUS_SESSION_BUS_ADDRESS")
    return bool(bus and bus == kwin.environment.get("DBUS_SESSION_BUS_ADDRESS"))


def _target(mode: str, runtime: Path, name: str, source: _Process,
            pids: tuple[int, ...], *, kwin_only: bool = False) -> SessionTarget:
    environment = dict(source.environment)
    if kwin_only:
        # Armada gives KWin a private config directory but its child GUI apps
        # the normal one. Do not accidentally inherit KWin's private directory.
        environment.pop("XDG_CONFIG_HOME", None)
    environment.update({
        "XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": name,
        "QT_QPA_PLATFORM": "wayland", "XDG_SESSION_TYPE": "wayland",
    })
    return SessionTarget(mode, runtime, name, environment, tuple(sorted(set(pids))))


def detect_target_session(
    proc_root: str | Path = "/proc",
    runtime_dir: str | Path | None = None,
    expected_uid: int | None = None,
    *, game_only: bool = False,
) -> SessionTarget | None:
    """Find one explicit usable Plasma target; return None if unavailable/ambiguous.

    Run as the graphical user. An administrative caller must explicitly supply
    that user's UID/runtime; this module never assumes that UID is 1000. No
    caller environment is copied into the result. PATH and application-specific
    settings belong to the launcher, not to session discovery.
    """
    uid = os.getuid() if expected_uid is None else expected_uid
    if uid < 0:
        return None
    runtime = Path(runtime_dir) if runtime_dir is not None else Path(f"/run/user/{uid}")
    if not runtime.is_absolute():
        return None
    try:
        info = runtime.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid:
            return None
    except OSError:
        return None

    processes = _read_processes(Path(proc_root), uid)
    shells = [p for p in processes if p.name == "plasmashell" and _same_runtime(p, runtime)]
    kwins = []
    # At most one query per bus in this detection pass. Readable environments
    # and direct children never incur a DBus subprocess or its timeout.
    bus_owners: dict[str, int | None] = {}
    for kwin in (p for p in processes if p.name == "kwin_wayland"):
        if game_only and _display_name(kwin.socket_name, runtime) != BOTTOM_DISPLAY:
            continue
        if _same_runtime(kwin, runtime):
            kwins.append(kwin)
            continue
        if kwin.environment_readable:
            continue
        if any(_direct_shell_confirms_runtime(shell, kwin, runtime) for shell in shells):
            kwins.append(kwin)
            continue
        # systemd can parent plasmashell, making PPid insufficient. A protected
        # KWin must explicitly name the exact same live same-user socket before
        # the shell's DBus owner identity may corroborate the relationship.
        explicit = _display_name(kwin.socket_name, runtime)
        if not explicit or kwin.nested_x11 or not _socket_exists(runtime, explicit, uid):
            continue
        for shell in shells:
            if _desktop_display(shell, runtime) != explicit:
                continue
            bus = shell.environment.get("DBUS_SESSION_BUS_ADDRESS", "")
            if bus not in bus_owners:
                bus_owners[bus] = _dbus_kwin_owner(bus, runtime, uid)
            if bus_owners[bus] == kwin.pid:
                kwins.append(kwin)
                break
    targets: dict[tuple[str, str], SessionTarget] = {}

    for kwin in kwins:
        name = _display_name(kwin.socket_name, runtime)
        if name != BOTTOM_DISPLAY or not _socket_exists(runtime, name, uid):
            continue
        matching_shells = [
            shell for shell in shells
            if _display_name(shell.environment.get("WAYLAND_DISPLAY"), runtime) == name
            and (
                _direct_shell_confirms_runtime(shell, kwin, runtime)
                or (kwin.environment_readable
                    and bool(shell.environment.get("DBUS_SESSION_BUS_ADDRESS"))
                    and shell.environment.get("DBUS_SESSION_BUS_ADDRESS")
                    == kwin.environment.get("DBUS_SESSION_BUS_ADDRESS"))
            )
        ]
        # A single compositor per name is expected. Multiple PID claims may
        # indicate a restart race; refuse the target instead of choosing one.
        key = ("game", name)
        if key in targets:
            return None
        source = matching_shells[0] if matching_shells else kwin
        targets[key] = _target("game", runtime, name, source,
                               (kwin.pid, *(p.pid for p in matching_shells)),
                               kwin_only=not matching_shells)

    for shell in (() if game_only else shells):
        name = _desktop_display(shell, runtime)
        if not name or not _socket_exists(runtime, name, uid):
            continue
        matching = [kwin for kwin in kwins if _matching_kwin(shell, kwin, name, runtime)]
        if len(matching) != 1:
            continue
        key = ("desktop", name)
        previous = targets.get(key)
        pids = (shell.pid, matching[0].pid, *(previous.source_pids if previous else ()))
        targets[key] = _target("desktop", runtime, name, shell, pids)

    return next(iter(targets.values())) if len(targets) == 1 else None
