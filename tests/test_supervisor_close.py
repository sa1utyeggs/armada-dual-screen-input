"""Closing must remain effective even when the graphics session changes."""
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from armada_dual_screen_input import supervisor
class CompletedChild:
    def __init__(self):
        self.returncode = None
        self.terminations = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminations += 1
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode


class SupervisorCloseTests(unittest.TestCase):
    def exercise_close(self, session_disappears):
        child = CompletedChild()
        target = SimpleNamespace(mode="game")
        sleeps = 0

        def gui_closes(_):
            nonlocal sleeps
            sleeps += 1
            if sleeps > 1:
                self.fail("Supervisor kept running after Close")
            child.returncode = 0

        targets = [target, None if session_disappears else target]
        keys = ["same-game-session", None if session_disappears else "same-game-session"]
        with tempfile.TemporaryDirectory() as runtime, \
             patch.object(supervisor.sys, "platform", "linux"), \
             patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime}), \
             patch.object(supervisor.signal, "signal"), \
             patch.object(supervisor, "detect_target_session", side_effect=targets), \
             patch.object(supervisor, "target_key", side_effect=keys), \
             patch.object(supervisor, "child_environment", return_value={}), \
             patch.object(supervisor.subprocess, "Popen", return_value=child) as launch, \
             patch.object(supervisor.time, "sleep", side_effect=gui_closes):
            self.assertEqual(supervisor.run(), 0)
            launch.assert_called_once()
        self.assertEqual(child.terminations, 0)

    def test_close_stops_supervisor(self):
        self.exercise_close(session_disappears=False)

    def test_close_is_not_lost_when_session_disappears_simultaneously(self):
        self.exercise_close(session_disappears=True)


if __name__ == "__main__":
    unittest.main()
