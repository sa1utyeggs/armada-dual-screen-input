"""Fixture-based tests: no services, real /proc reads, or device changes."""

import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from armada_dual_screen_input.session_detect import BOTTOM_DISPLAY, detect_target_session


class SessionDetectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        self.uid = os.getuid()
        self.bus = "unix:path=/tmp/example-session-bus"
        self.socket_paths = set()
        # The macOS execution sandbox prohibits even local AF_UNIX binds.
        # Emulate only the kernel-reported type for declared socket fixtures;
        # directory ownership, ordinary files, and missing paths remain real.
        original_stat = Path.stat

        def fixture_stat(path, *args, **kwargs):
            info = original_stat(path, *args, **kwargs)
            if path in self.socket_paths:
                values = list(info)
                values[0] = stat.S_IFSOCK | stat.S_IMODE(info.st_mode)
                return os.stat_result(values)
            return info

        patcher = patch.object(Path, "stat", fixture_stat)
        patcher.start()
        self.addCleanup(patcher.stop)

    def bind(self, name):
        path = self.runtime / name
        path.touch()
        self.socket_paths.add(path)

    def deny_environment(self, pid):
        denied_path = self.proc / str(pid) / "environ"
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            if path == denied_path:
                raise PermissionError(13, "Permission denied", str(path))
            return original_open(path, *args, **kwargs)

        patcher = patch.object(Path, "open", guarded_open)
        patcher.start()
        self.addCleanup(patcher.stop)

    def process(self, pid, name, *, display=None, args=(), parent=1, uid=None,
                bus=None, env=None, runtime=None):
        path = self.proc / str(pid)
        path.mkdir()
        uid = self.uid if uid is None else uid
        (path / "status").write_text(
            f"Name:\t{name}\nPPid:\t{parent}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n"
        )
        values = {
            "XDG_RUNTIME_DIR": str(runtime or self.runtime),
            "XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland",
            "DBUS_SESSION_BUS_ADDRESS": bus or self.bus,
        }
        if display:
            values["WAYLAND_DISPLAY"] = display
        values.update(env or {})
        (path / "environ").write_bytes(b"\0".join(
            f"{key}={value}".encode() for key, value in values.items()
        ) + b"\0")
        (path / "cmdline").write_bytes(b"\0".join(
            [name.encode(), *(arg.encode() for arg in args)]
        ) + b"\0")

    def detect(self, **kwargs):
        return detect_target_session(self.proc, self.runtime, self.uid, **kwargs)

    def desktop(self, display="wayland-0", *, kwin_pid=10, shell_pid=11):
        self.bind(display)
        # Real KWin can choose the socket after exec, so its original /proc
        # environment need not contain the name inherited by plasmashell.
        self.process(kwin_pid, "kwin_wayland")
        self.process(shell_pid, "plasmashell", display=display)

    def bottom(self, *, kwin_pid=20, shell_pid=21):
        self.bind(BOTTOM_DISPLAY)
        self.process(kwin_pid, "kwin_wayland",
                     args=("--x11-display", ":2", "--socket", BOTTOM_DISPLAY),
                     bus="unix:path=/tmp/bottom-bus",
                     env={"XDG_CONFIG_HOME": "/home/test/.config/armada/plasma/bottom"})
        if shell_pid is not None:
            self.process(shell_pid, "plasmashell", display=BOTTOM_DISPLAY,
                         bus="unix:path=/tmp/bottom-bus",
                         env={"XDG_CONFIG_HOME": "/home/test/.config"})

    def test_game_targets_kwin_not_direct_gamescope(self):
        self.bind("gamescope-secondary")
        self.bottom()
        result = self.detect()
        self.assertEqual(result.mode, "game")
        self.assertEqual(result.wayland_display, BOTTOM_DISPLAY)
        self.assertEqual(result.environment["QT_QPA_PLATFORM"], "wayland")
        self.assertEqual(result.environment["XDG_CONFIG_HOME"], "/home/test/.config")
        self.assertEqual(result.environment["DBUS_SESSION_BUS_ADDRESS"],
                         "unix:path=/tmp/bottom-bus")

    def test_game_only_ignores_desktop_without_bus_lookup(self):
        self.desktop()
        self.deny_environment(10)
        with patch("armada_dual_screen_input.session_detect.subprocess.run") as query:
            self.assertIsNone(self.detect(game_only=True))
            query.assert_not_called()

    def test_game_only_keeps_bottom_even_if_desktop_session_coexists(self):
        self.desktop()
        self.bottom()
        self.assertEqual(self.detect(game_only=True).mode, "game")

    def test_bottom_socket_without_shell_uses_kwin_bus(self):
        self.bottom(shell_pid=None)
        result = self.detect()
        self.assertEqual(result.mode, "game")
        self.assertNotIn("XDG_CONFIG_HOME", result.environment)

    def test_direct_bottom_gamescope_socket_is_not_a_plasma_session(self):
        self.bind("gamescope-secondary")
        self.process(20, "gamescope", display="gamescope-secondary")
        self.assertIsNone(self.detect())

    def test_stale_bottom_socket_is_not_enough(self):
        self.bind(BOTTOM_DISPLAY)
        self.assertIsNone(self.detect())

    def test_missing_bottom_socket_refuses_upper_screen_fallback(self):
        self.bind("gamescope-primary")
        self.process(20, "kwin_wayland", args=("--socket", BOTTOM_DISPLAY),
                     display="gamescope-primary")
        self.assertIsNone(self.detect())

    def test_regular_file_is_not_a_wayland_socket(self):
        (self.runtime / BOTTOM_DISPLAY).touch()
        self.process(20, "kwin_wayland", args=("--socket", BOTTOM_DISPLAY))
        self.assertIsNone(self.detect())

    def test_desktop_matches_shell_socket_and_kwin_bus(self):
        self.desktop()
        result = self.detect()
        self.assertEqual(result.mode, "desktop")
        self.assertEqual(result.wayland_display, "wayland-0")
        self.assertEqual(result.source_pids, (10, 11))

    def test_shell_without_matching_kwin_is_not_enough(self):
        self.bind("wayland-0")
        self.process(11, "plasmashell", display="wayland-0")
        self.assertIsNone(self.detect())

    def test_different_bus_does_not_match_unknown_kwin(self):
        self.bind("wayland-0")
        self.process(10, "kwin_wayland", bus="unix:path=/tmp/different")
        self.process(11, "plasmashell", display="wayland-0")
        self.assertIsNone(self.detect())

    def test_explicit_kwin_socket_can_match_without_shared_bus(self):
        self.bind("wayland-1")
        self.process(10, "kwin_wayland", args=("--socket=wayland-1",),
                     bus="unix:path=/tmp/different")
        self.process(11, "plasmashell", display="wayland-1")
        self.assertEqual(self.detect().wayland_display, "wayland-1")

    def test_nested_desktop_is_excluded(self):
        self.bind("armada-plasma-nested")
        self.process(10, "kwin_wayland", args=("--x11-display", ":0",
                     "--socket", "armada-plasma-nested"))
        self.process(11, "plasmashell", display="armada-plasma-nested")
        self.assertIsNone(self.detect())

    def test_same_named_process_from_another_uid_is_ignored(self):
        self.bind(BOTTOM_DISPLAY)
        self.process(20, "kwin_wayland", args=("--socket", BOTTOM_DISPLAY),
                     uid=self.uid + 1)
        self.assertIsNone(self.detect())

    def test_mismatched_runtime_is_ignored(self):
        self.bind(BOTTOM_DISPLAY)
        self.process(20, "kwin_wayland", args=("--socket", BOTTOM_DISPLAY),
                     runtime=self.root / "different-runtime")
        self.assertIsNone(self.detect())

    def test_mode_switch_with_both_sessions_is_ambiguous(self):
        self.desktop()
        self.bottom()
        self.assertIsNone(self.detect())

    def test_multiple_desktop_targets_are_ambiguous(self):
        self.desktop()
        self.bind("wayland-1")
        self.process(12, "plasmashell", display="wayland-1")
        self.assertIsNone(self.detect())

    def test_duplicate_bottom_compositors_are_ambiguous(self):
        self.bottom()
        self.process(22, "kwin_wayland", args=("--socket", BOTTOM_DISPLAY))
        self.assertIsNone(self.detect())

    def test_environment_contains_only_selected_values_and_no_x11_fallback(self):
        self.bind(BOTTOM_DISPLAY)
        self.process(20, "kwin_wayland", args=("--socket", BOTTOM_DISPLAY), env={
            "HOME": "/home/test", "LANG": "zh_CN.UTF-8", "TOKEN": "do-not-copy",
            "AWS_SECRET_ACCESS_KEY": "do-not-copy", "DISPLAY": ":0",
            "XAUTHORITY": "/tmp/do-not-copy", "LD_PRELOAD": "do-not-copy",
            "QT_QPA_PLATFORM": "xcb", "GAMESCOPE_WAYLAND_DISPLAY": "gamescope-0",
        })
        result = self.detect()
        self.assertEqual(result.environment["HOME"], "/home/test")
        self.assertEqual(result.environment["LANG"], "zh_CN.UTF-8")
        self.assertEqual(result.environment["QT_QPA_PLATFORM"], "wayland")
        for key in ("TOKEN", "AWS_SECRET_ACCESS_KEY", "DISPLAY", "XAUTHORITY",
                    "LD_PRELOAD", "GAMESCOPE_WAYLAND_DISPLAY"):
            self.assertNotIn(key, result.environment)

    def test_socket_path_outside_runtime_is_rejected(self):
        self.bind("wayland-0")
        self.process(10, "kwin_wayland")
        self.process(11, "plasmashell", display="/somewhere/wayland-0")
        self.assertIsNone(self.detect())

    def test_absolute_socket_path_inside_runtime_is_normalized(self):
        self.bind("wayland-0")
        self.process(10, "kwin_wayland")
        self.process(11, "plasmashell", display=str(self.runtime / "wayland-0"))
        self.assertEqual(self.detect().wayland_display, "wayland-0")

    def test_disappearing_or_malformed_proc_entry_does_not_crash(self):
        (self.proc / "123").mkdir()
        self.assertIsNone(self.detect())

    def test_other_users_runtime_is_rejected(self):
        self.bottom()
        self.assertIsNone(detect_target_session(self.proc, self.runtime, self.uid + 1))

    def test_protected_bottom_kwin_uses_direct_child_environment(self):
        # Mirrors the handheld: KWin environ is EACCES despite the same UID;
        # its direct plasmashell child publishes the real runtime and bus.
        self.bind(BOTTOM_DISPLAY)
        self.process(11740, "kwin_wayland", args=("--socket", BOTTOM_DISPLAY))
        self.process(11764, "plasmashell", parent=11740, display=BOTTOM_DISPLAY,
                     bus="unix:path=/tmp/actual-bottom-bus",
                     env={"HOME": "/home/test", "TOKEN": "never-copy"})
        self.deny_environment(11740)
        result = self.detect()
        self.assertEqual(result.mode, "game")
        self.assertEqual(result.source_pids, (11740, 11764))
        self.assertEqual(result.environment["DBUS_SESSION_BUS_ADDRESS"],
                         "unix:path=/tmp/actual-bottom-bus")
        self.assertEqual(result.environment["HOME"], "/home/test")
        self.assertNotIn("TOKEN", result.environment)

    def test_protected_desktop_kwin_uses_direct_child_environment(self):
        self.bind("wayland-0")
        self.process(10, "kwin_wayland", args=("--socket", "wayland-0"))
        self.process(11, "plasmashell", parent=10, display="wayland-0")
        self.deny_environment(10)
        result = self.detect()
        self.assertEqual(result.mode, "desktop")
        self.assertEqual(result.source_pids, (10, 11))

    def test_protected_desktop_kwin_can_use_child_chosen_socket(self):
        self.bind("wayland-0")
        self.process(10, "kwin_wayland")
        self.process(11, "plasmashell", parent=10, display="wayland-0")
        self.deny_environment(10)
        self.assertEqual(self.detect().mode, "desktop")

    def test_protected_kwin_without_direct_child_does_not_guess_runtime(self):
        self.bottom()
        self.deny_environment(20)
        # The helper's shell has parent=1, not the compositor.
        self.assertIsNone(self.detect())

    def test_protected_kwin_direct_child_wrong_socket_is_rejected(self):
        self.bind(BOTTOM_DISPLAY)
        self.bind("gamescope-primary")
        self.process(20, "kwin_wayland", args=("--socket", BOTTOM_DISPLAY))
        self.process(21, "plasmashell", parent=20, display="gamescope-primary")
        self.deny_environment(20)
        self.assertIsNone(self.detect())

    def test_protected_kwin_direct_child_wrong_runtime_is_rejected(self):
        self.bind(BOTTOM_DISPLAY)
        self.process(20, "kwin_wayland", args=("--socket", BOTTOM_DISPLAY))
        self.process(21, "plasmashell", parent=20, display=BOTTOM_DISPLAY,
                     runtime=self.root / "another-runtime")
        self.deny_environment(20)
        self.assertIsNone(self.detect())

    def test_protected_kwin_direct_child_other_uid_is_rejected(self):
        self.bind(BOTTOM_DISPLAY)
        self.process(20, "kwin_wayland", args=("--socket", BOTTOM_DISPLAY))
        self.process(21, "plasmashell", parent=20, display=BOTTOM_DISPLAY,
                     uid=self.uid + 1)
        self.deny_environment(20)
        self.assertIsNone(self.detect())

    def test_protected_shell_is_not_a_source_of_guessed_environment(self):
        self.desktop()
        self.deny_environment(11)
        self.assertIsNone(self.detect())

    def protected_systemd_desktop(self, *, shell_uid=None, kwin_uid=None,
                                  socket_name="wayland-0", bus=None):
        self.bind("wayland-0")
        self.bind("bus")
        self.process(45802, "kwin_wayland", parent=45772, uid=kwin_uid,
                     args=("--socket", socket_name))
        self.process(45941, "plasmashell", parent=1735, uid=shell_uid,
                     display="wayland-0",
                     bus=bus or f"unix:path={self.runtime}/bus")
        self.deny_environment(45802)

    @patch("armada_dual_screen_input.session_detect.subprocess.run")
    def test_protected_systemd_desktop_uses_verified_dbus_owner(self, run):
        self.protected_systemd_desktop()
        run.return_value = subprocess.CompletedProcess([], 0, "u 45802\n", "")
        result = self.detect()
        self.assertEqual(result.mode, "desktop")
        self.assertEqual(result.wayland_display, "wayland-0")
        self.assertEqual(result.source_pids, (45802, 45941))
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "/usr/bin/busctl")
        self.assertIn(f"--address=unix:path={self.runtime}/bus", argv)
        self.assertIn("GetConnectionUnixProcessID", argv)
        self.assertIn("--timeout=1s", argv)
        self.assertEqual(run.call_args.kwargs["timeout"], 1)
        self.assertNotIn("shell", run.call_args.kwargs)

    @patch("armada_dual_screen_input.session_detect.subprocess.run")
    def test_dbus_owner_different_pid_is_rejected(self, run):
        self.protected_systemd_desktop()
        run.return_value = subprocess.CompletedProcess([], 0, "u 12345\n", "")
        self.assertIsNone(self.detect())

    @patch("armada_dual_screen_input.session_detect.subprocess.run")
    def test_dbus_timeout_is_rejected(self, run):
        self.protected_systemd_desktop()
        run.side_effect = subprocess.TimeoutExpired("busctl", 1)
        self.assertIsNone(self.detect())

    @patch("armada_dual_screen_input.session_detect.subprocess.run")
    def test_missing_busctl_is_rejected(self, run):
        self.protected_systemd_desktop()
        run.side_effect = FileNotFoundError("busctl not installed")
        self.assertIsNone(self.detect())

    @patch("armada_dual_screen_input.session_detect.subprocess.run")
    def test_dbus_error_and_malformed_pid_are_rejected(self, run):
        self.protected_systemd_desktop()
        for code, output in ((1, "u 45802"), (0, "s 45802"), (0, "u 0"),
                             (0, "u 45802\nu 99999"), (0, "")):
            with self.subTest(code=code, output=output):
                run.return_value = subprocess.CompletedProcess([], code, output, "")
                self.assertIsNone(self.detect())

    @patch("armada_dual_screen_input.session_detect.subprocess.run")
    def test_dbus_pid_does_not_override_kwin_uid(self, run):
        self.protected_systemd_desktop(kwin_uid=self.uid + 1)
        run.return_value = subprocess.CompletedProcess([], 0, "u 45802\n", "")
        self.assertIsNone(self.detect())
        run.assert_not_called()

    @patch("armada_dual_screen_input.session_detect.subprocess.run")
    def test_dbus_pid_does_not_override_shell_uid(self, run):
        self.protected_systemd_desktop(shell_uid=self.uid + 1)
        run.return_value = subprocess.CompletedProcess([], 0, "u 45802\n", "")
        self.assertIsNone(self.detect())
        run.assert_not_called()

    @patch("armada_dual_screen_input.session_detect.subprocess.run")
    def test_dbus_cannot_override_mismatched_explicit_wayland_socket(self, run):
        self.protected_systemd_desktop(socket_name="another-wayland")
        self.bind("another-wayland")
        run.return_value = subprocess.CompletedProcess([], 0, "u 45802\n", "")
        self.assertIsNone(self.detect())
        run.assert_not_called()

    @patch("armada_dual_screen_input.session_detect.subprocess.run")
    def test_dbus_outside_user_runtime_is_rejected_without_connecting(self, run):
        self.protected_systemd_desktop(bus="unix:path=/tmp/unrelated-bus")
        self.assertIsNone(self.detect())
        run.assert_not_called()

    @patch("armada_dual_screen_input.session_detect.subprocess.run")
    def test_dbus_address_with_guid_is_supported(self, run):
        self.protected_systemd_desktop(
            bus=f"unix:path={self.runtime}/bus,guid={'a' * 32}")
        run.return_value = subprocess.CompletedProcess([], 0, "u 45802\n", "")
        self.assertEqual(self.detect().mode, "desktop")

    @patch("armada_dual_screen_input.session_detect.subprocess.run")
    def test_dbus_requires_real_same_user_bus_socket(self, run):
        self.protected_systemd_desktop()
        self.socket_paths.remove(self.runtime / "bus")
        self.assertIsNone(self.detect())
        run.assert_not_called()

    @patch("armada_dual_screen_input.session_detect.subprocess.run")
    def test_readable_kwin_and_direct_child_paths_do_not_query_dbus(self, run):
        self.desktop()
        self.assertEqual(self.detect().mode, "desktop")
        run.assert_not_called()

    @patch("armada_dual_screen_input.session_detect.subprocess.run")
    def test_protected_direct_child_path_does_not_query_dbus(self, run):
        self.bind("wayland-0")
        self.process(10, "kwin_wayland", args=("--socket", "wayland-0"))
        self.process(11, "plasmashell", parent=10, display="wayland-0")
        self.deny_environment(10)
        self.assertEqual(self.detect().mode, "desktop")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
