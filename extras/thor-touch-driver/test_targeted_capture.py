# SPDX-License-Identifier: GPL-2.0-only
import importlib.util
import json
import os
from pathlib import Path
import string
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch
import unittest

ROOT = Path(__file__).parent/'targeted-capture'


def load(name):
    spec = importlib.util.spec_from_file_location('targeted_'+name, ROOT/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = load('capture_core')
catalog = load('ui_catalogs')
launcher = load('launch_capture')


class TargetedCaptureTests(unittest.TestCase):
    def test_late_first_request_receives_the_full_independent_active_budget(self):
        clock = core.LifetimeBudget(100)
        self.assertIsNone(clock.timeout_reason(699.9))
        self.assertTrue(clock.start_active(699.95, observed_at=699.9))
        self.assertEqual(clock.metadata()['active_deadline'], 749.95)
        self.assertIsNone(clock.timeout_reason(749.9))
        self.assertEqual(clock.timeout_reason(749.95), 'active_timeout')

    def test_no_first_request_still_times_out_and_a_late_contact_is_rejected(self):
        clock = core.LifetimeBudget(0)
        self.assertEqual(clock.timeout_reason(600), 'waiting_timeout')
        self.assertFalse(clock.start_active(600.1, observed_at=600.01))
        self.assertIsNone(clock.active_started)
        self.assertEqual(clock.metadata()['wait_seconds'], 600)
        self.assertEqual(clock.metadata()['active_window_seconds'], 50)

    def test_active_budget_cannot_be_extended_by_repeated_requests(self):
        clock = core.LifetimeBudget(0)
        self.assertTrue(clock.start_active(590))
        self.assertTrue(clock.start_active(639))
        self.assertEqual(clock.active_started, 590)
        self.assertEqual(clock.timeout_reason(640), 'active_timeout')
        with self.assertRaises(ValueError):
            core.LifetimeBudget(0, wait_seconds=601)

    def test_new_tracking_id_retains_unchanged_axis_and_snapshots_do_not_mutate(self):
        state = core.SlotState({0: dict(id=-1, x=300, y=240)})
        state.feed(3, 0x39, 7)
        first = state.feed(0, 0, 0)
        self.assertEqual(first, {0: dict(id=7, x=300, y=240)})
        state.feed(3, 0x39, -1)
        self.assertEqual(state.feed(0, 0, 0), {})
        state.feed(3, 0x39, 8)
        state.feed(3, 0x35, 304)
        self.assertEqual(state.feed(0, 0, 0), {0: dict(id=8, x=304, y=240)})
        self.assertEqual(first, {0: dict(id=7, x=300, y=240)})

    def test_slot_selection_and_syn_dropped_are_not_silently_repaired(self):
        state = core.SlotState({0: dict(id=1, x=1, y=2), 1: dict(id=-1, x=3, y=4)})
        state.feed(3, 0x2f, 1)
        state.feed(3, 0x39, 2)
        self.assertEqual(state.feed(0, 0, 0)[1], dict(id=2, x=3, y=4))
        with self.assertRaisesRegex(RuntimeError, 'SYN_DROPPED'):
            state.feed(0, 3, 0)

    def test_protocol_waits_for_trace_and_gates_the_baseline_before_scan(self):
        trial = core.Protocol(trace_required=True)
        trial.step(0, [11])
        self.assertEqual(trial.phase, 'trace')
        trial.step(2, [11], trace_ready=True)
        self.assertEqual(trial.phase, 'baseline')
        self.assertEqual(trial.remaining(2), 3)
        trial.step(5, [11])
        self.assertEqual(trial.phase, 'add')
        trial.step(6, [11, 12])
        self.assertEqual(trial.phase, 'scan')
        trial.step(10, [11])  # Secondary may lift and return.
        trial.step(11, [11, 13])
        self.assertEqual(trial.secondary_ids, {12, 13})
        trial.step(16, [11, 13])
        self.assertEqual(trial.phase, 'lift')
        trial.step(17, [13])
        trial.step(18, [])
        self.assertEqual(trial.phase, 'done')

    def test_primary_loss_extra_contacts_and_premature_second_do_not_promote_roles(self):
        for now, ids, reason in ((1, [2], 'primary_lifted'),
                                 (1, [1, 2, 3], 'extra_contacts'),
                                 (1, [1, 2], 'second_too_early')):
            trial = core.Protocol()
            trial.step(0, [1])
            trial.step(now, ids)
            self.assertEqual((trial.phase, trial.reason, trial.primary), ('invalid', reason, 1))

    def test_lift_timeout_also_applies_after_primary_lifts_before_secondary(self):
        trial = core.Protocol()
        trial.phase, trial.phase_at, trial.primary = 'lift', 0, 1
        trial.step(16, [2])
        self.assertEqual((trial.phase, trial.reason), ('invalid', 'lift_timeout'))

    def start_post_hold(self):
        trial = core.Protocol(post_hold_seconds=3)
        trial.step(0, [1])
        trial.step(3, [1])
        trial.step(4, [1, 2])
        trial.step(14, [1, 2])
        return trial

    def test_post_hold_keeps_capture_active_until_secondary_lift_and_three_second_baseline(self):
        trial = self.start_post_hold()
        self.assertEqual(trial.phase, 'release_second')
        self.assertFalse(trial.capture_should_stop)
        trial.step(15, [1])
        self.assertEqual(trial.phase, 'postbaseline')
        self.assertEqual(trial.remaining(15), 3)
        self.assertFalse(trial.capture_should_stop)
        trial.step(17.9, [1])
        self.assertEqual(trial.phase, 'postbaseline')
        trial.step(18, [1])
        self.assertEqual(trial.phase, 'lift')
        self.assertTrue(trial.capture_should_stop)
        trial.step(19, [])
        self.assertEqual(trial.phase, 'done')

    def test_post_hold_primary_loss_cannot_promote_the_secondary(self):
        for phase in ('release_second', 'postbaseline'):
            with self.subTest(phase=phase):
                trial = self.start_post_hold()
                if phase == 'postbaseline':
                    trial.step(15, [1])
                trial.step(16, [2])
                self.assertEqual((trial.phase, trial.reason, trial.primary), ('invalid', 'primary_lifted', 1))
                self.assertTrue(trial.capture_should_stop)

    def test_secondary_return_invalidates_final_baseline(self):
        trial = self.start_post_hold()
        trial.step(15, [1])
        trial.step(16, [1, 3])
        self.assertEqual((trial.phase, trial.reason), ('invalid', 'second_returned'))
        self.assertTrue(trial.capture_should_stop)

    def test_secondary_release_wait_and_optional_duration_remain_bounded(self):
        trial = self.start_post_hold()
        trial.step(24.1, [1, 2])
        self.assertEqual((trial.phase, trial.reason), ('invalid', 'secondary_lift_timeout'))
        with self.assertRaises(ValueError):
            core.Protocol(post_hold_seconds=10)

    def stationary_control(self, second=(950, 600), continuous=False):
        trial = core.Protocol(scan_mode='stationary', post_hold_seconds=3, continuous_secondary=continuous)
        trial.step(0, [1])
        trial.step(3, [1])
        trial.step(4, [1, 2], positions={1: (260, 540), 2: second})
        return trial

    def test_stationary_points_gate_three_holds_then_final_baseline_without_early_marker(self):
        trial = self.stationary_control()
        self.assertEqual((trial.phase, trial.point_index), ('goto_point', 0))
        self.assertFalse(trial.capture_should_stop)
        positions = {1: (260, 540), 2: (950, 300)}
        trial.step(5, [1, 2], positions=positions)
        self.assertEqual(trial.phase, 'hold_point')
        self.assertEqual(trial.remaining(5), 3)
        self.assertEqual(positions, {1: (260, 540), 2: (950, 300)})
        trial.step(8.001, [1, 2], positions=positions)
        self.assertEqual((trial.phase, trial.point_index), ('goto_point', 1))
        trial.step(8.1, [1, 2], positions={2: (950, 900)})
        trial.step(11.101, [1, 2], positions={2: (950, 900)})
        self.assertEqual((trial.phase, trial.point_index), ('goto_point', 2))
        trial.step(11.2, [1, 2], positions={2: (950, 300)})
        trial.step(14.201, [1, 2], positions={2: (950, 300)})
        self.assertEqual(trial.phase, 'release_second')
        self.assertFalse(trial.capture_should_stop)
        trial.step(15, [1])
        self.assertEqual(trial.phase, 'postbaseline')
        trial.step(18, [1])
        self.assertEqual(trial.phase, 'lift')
        self.assertTrue(trial.capture_should_stop)

    def test_stationary_departure_resets_hold_timer_without_extending_stage_deadline(self):
        trial = self.stationary_control(second=(950, 300))
        self.assertEqual(trial.phase, 'hold_point')
        trial.step(5, [1, 2], positions={2: (950, 500)})
        self.assertEqual(trial.phase, 'goto_point')
        self.assertIsNone(trial.hold_since)
        trial.step(6, [1, 2], positions={2: (950, 300)})
        trial.step(8.9, [1, 2], positions={2: (950, 300)})
        self.assertEqual(trial.point_index, 0)
        trial.step(9.001, [1, 2], positions={2: (950, 300)})
        self.assertEqual(trial.point_index, 1)
        late = self.stationary_control()
        late.step(7, [1, 2], positions={2: (950, 300)})
        late.step(8, [1, 2], positions={2: (950, 500)})
        late.step(9, [1, 2], positions={2: (950, 300)})
        late.step(10.01, [1, 2], positions={2: (950, 500)})
        self.assertEqual((late.phase, late.reason), ('invalid', 'position_timeout'))

    def test_stationary_primary_loss_or_extra_contact_never_promotes_the_second(self):
        for ids, reason in (([2], 'primary_lifted'), ([1, 2, 3], 'extra_contacts')):
            for position in ((950, 300), (950, 600)):
                with self.subTest(ids=ids, position=position):
                    trial = self.stationary_control(second=position)
                    trial.step(5, ids, positions={2: position})
                    self.assertEqual((trial.phase, trial.reason, trial.primary), ('invalid', reason, 1))

    def test_stationary_radius_is_only_a_protocol_gate_and_secondary_recontact_resets_it(self):
        trial = self.stationary_control(second=(1030, 300))
        self.assertEqual(trial.phase, 'hold_point')
        trial.step(5, [1], positions={1: (260, 540)})
        self.assertEqual(trial.phase, 'goto_point')
        trial.step(6, [1, 3], positions={3: (1030.1, 300)})
        self.assertEqual(trial.phase, 'goto_point')
        trial.step(7, [1, 3], positions={3: (950, 300)})
        self.assertEqual(trial.phase, 'hold_point')
        self.assertEqual(trial.hold_since, 7)
        self.assertEqual(trial.secondary_ids, {2, 3})

    def test_stationary_mode_requires_bounded_post_control_and_rejects_unknown_modes(self):
        for values in (dict(scan_mode='stationary'), dict(scan_mode='unknown')):
            with self.assertRaises(ValueError):
                core.Protocol(**values)

    def test_stationary_arrival_after_three_point_two_seconds_gets_the_full_three_second_hold(self):
        trial = self.stationary_control()
        trial.step(7.2, [1, 2], positions={2: (950, 300)})
        self.assertEqual(trial.phase, 'hold_point')
        trial.step(10.199, [1, 2], positions={2: (950, 300)})
        self.assertEqual((trial.phase, trial.point_index), ('hold_point', 0))
        trial.step(10.201, [1, 2], positions={2: (950, 300)})
        self.assertEqual((trial.phase, trial.point_index), ('goto_point', 1))

    def test_stationary_late_arrival_before_six_seconds_can_finish_before_nine(self):
        trial = self.stationary_control()
        trial.step(9.9, [1, 2], positions={2: (950, 300)})
        trial.step(12.899, [1, 2], positions={2: (950, 300)})
        self.assertEqual(trial.phase, 'hold_point')
        trial.step(12.901, [1, 2], positions={2: (950, 300)})
        self.assertEqual((trial.phase, trial.point_index), ('goto_point', 1))
        overrun = self.stationary_control()
        overrun.step(9.9, [1, 2], positions={2: (950, 300)})
        overrun.step(13.01, [1, 2], positions={2: (950, 300)})
        self.assertEqual((overrun.phase, overrun.reason), ('invalid', 'position_timeout'))

    def test_stationary_missing_arrival_or_departure_after_travel_deadline_cannot_restart_it(self):
        missing = self.stationary_control()
        missing.step(10.01, [1, 2], positions={2: (950, 600)})
        self.assertEqual((missing.phase, missing.reason), ('invalid', 'position_timeout'))
        departed = self.stationary_control()
        departed.step(9, [1, 2], positions={2: (950, 300)})
        departed.step(10.1, [1, 2], positions={2: (950, 600)})
        self.assertEqual((departed.phase, departed.reason), ('invalid', 'position_timeout'))

    def test_continuous_secondary_guard_rejects_lift_or_replacement_until_release_prompt(self):
        for ids in ([1], [1, 3]):
            for point in ((950, 300), (950, 600)):
                with self.subTest(ids=ids, point=point):
                    trial = self.stationary_control(second=point, continuous=True)
                    self.assertEqual(trial.fixed_secondary, 2)
                    trial.step(5, ids, positions={3: point})
                    self.assertEqual((trial.phase, trial.reason), ('invalid', 'secondary_changed'))
        trial = self.stationary_control(second=(950, 300), continuous=True)
        trial.step(7.001, [1, 2], positions={2: (950, 300)})
        trial.step(7.1, [1, 2], positions={2: (950, 900)})
        trial.step(10.101, [1, 2], positions={2: (950, 900)})
        trial.step(10.2, [1, 2], positions={2: (950, 300)})
        trial.step(13.201, [1, 2], positions={2: (950, 300)})
        self.assertEqual(trial.phase, 'release_second')
        trial.step(14, [1])
        self.assertEqual(trial.phase, 'postbaseline')
        with self.assertRaises(ValueError):
            core.Protocol(continuous_secondary=True)

    def test_bilingual_catalog_has_identical_keys_and_named_placeholders(self):
        english, chinese = catalog.CATALOGS['en'], catalog.CATALOGS['zh-CN']
        self.assertEqual(set(english), set(chinese))
        formatter = string.Formatter()
        for key in english:
            placeholders = lambda text: {name for _, name, _, _ in formatter.parse(text) if name}
            self.assertEqual(placeholders(english[key]), placeholders(chinese[key]), key)
        self.assertEqual(catalog.text('run', 'invalid', target='A'), 'Target A')


class TargetedLauncherTests(unittest.TestCase):
    def run_fake(self, script, action=None, request=True, request_delay=.03, action_delay=0):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            finished = threading.Event()
            operator_uid = os.getuid() or 65534
            if os.getuid() == 0:
                os.chown(folder, operator_uid, -1)

            def marker(name):
                path = folder/name
                path.touch()
                if os.getuid() == 0:
                    os.chown(path, operator_uid, -1)

            def user_markers():
                if not request:
                    return
                time.sleep(request_delay)
                marker('capture-request')
                if action:
                    deadline = time.monotonic()+2
                    while not finished.is_set() and time.monotonic() < deadline:
                        if (folder/'trace-ready').exists():
                            time.sleep(action_delay)
                            if action == 'signal':
                                launcher.signal.getsignal(launcher.signal.SIGTERM)(None, None)
                            else:
                                marker(action)
                            return
                        time.sleep(.01)

            def factory(output, seconds):
                return subprocess.Popen([sys.executable, '-u', '-c', script, str(output)],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        start_new_session=True)

            worker = threading.Thread(target=user_markers)
            worker.start()
            try:
                with patch.object(launcher.os, 'geteuid', return_value=0), \
                     patch.dict(launcher.os.environ, {'SUDO_UID': str(operator_uid)}):
                    result = launcher.run(folder, wait_seconds=.2, capture_seconds=.4,
                                          startup_seconds=.2, capture_factory=factory)
            finally:
                finished.set()
                worker.join(timeout=1)
            files = {p.name: p.read_text() for p in folder.iterdir() if p.is_file()}
            owners = {p.name: p.stat().st_uid for p in folder.iterdir() if p.is_file()}
            return result, files, owners

    def test_ready_requires_success_and_normal_exit_requires_window_completion(self):
        script = ('import json,pathlib,sys,time\n'
                  'folder=pathlib.Path(sys.argv[1])\n'
                  'print(json.dumps(dict(ready=True)),flush=True)\n'
                  'while not (folder/"capture.done").exists():time.sleep(.01)\n'
                  'print(json.dumps(dict(closed=True,instance_removed=True)),flush=True)\n')
        result, files, owners = self.run_fake(script, action='capture.done')
        self.assertEqual(result['outcome'], 'completed')
        self.assertEqual(result['returncode'], 0)
        self.assertFalse(result['terminated'])
        self.assertIn('trace-ready', files)
        self.assertNotIn('trace-failed', files)
        self.assertEqual(json.loads(files['trace-result.json']), result)
        self.assertTrue(all(uid == (os.getuid() or 65534) for uid in owners.values()))

    def test_wait_timeout_does_not_launch_a_collector_or_claim_ready(self):
        result, files, _ = self.run_fake('raise SystemExit("must not launch")', request=False)
        self.assertEqual(result['outcome'], 'failed')
        self.assertIsNone(result['returncode'])
        self.assertIn('trace-failed', files)
        self.assertNotIn('trace-ready', files)
        self.assertIn('waiting for the first-contact', result['error'])

    def test_late_request_does_not_spend_the_collectors_active_capture_budget(self):
        script = ('import json,pathlib,sys,time\n'
                  'folder=pathlib.Path(sys.argv[1])\n'
                  'print(json.dumps(dict(ready=True)),flush=True)\n'
                  'while not (folder/"capture.done").exists():time.sleep(.01)\n'
                  'print(json.dumps(dict(closed=True,instance_removed=True)),flush=True)\n')
        result, files, _ = self.run_fake(script, action='capture.done', request_delay=.15, action_delay=.15)
        self.assertEqual(result['outcome'], 'completed')
        self.assertGreater(result['elapsed'], result['budgets']['wait_seconds'])
        self.assertGreaterEqual(result['request_wait_elapsed'], .14)
        self.assertEqual(result['budgets']['capture_seconds'], .4)
        self.assertNotIn('trace-failed', files)

    def test_collector_failure_and_early_success_invalidate_the_window(self):
        cases = [
            ('import sys\nprint("{\\"ready\\":false}",flush=True)\nsys.exit(1)', False),
            ('print("{\\"ready\\":true}",flush=True)\n'
             'print("{\\"closed\\":true,\\"instance_removed\\":true}",flush=True)', True),
            ('print("{\\"ready\\":true}",flush=True)\n'
             'print("{\\"closed\\":true,\\"instance_removed\\":false}",flush=True)', True),
        ]
        for script, ready in cases:
            with self.subTest(script=script):
                result, files, _ = self.run_fake(script)
                self.assertEqual(result['outcome'], 'failed')
                self.assertEqual('trace-ready' in files, ready)
                self.assertIn('trace-failed', files)

    def test_cancel_after_ready_terminates_only_the_private_child(self):
        script = 'import time\nprint("{\\"ready\\":true}",flush=True)\ntime.sleep(10)'
        for action in ('cancel', 'signal'):
            with self.subTest(action=action):
                result, files, _ = self.run_fake(script, action=action)
                self.assertEqual(result['outcome'], 'failed')
                self.assertTrue(result['terminated'])
                self.assertIsNotNone(result['returncode'])
                self.assertLess(result['elapsed'], 2)
                self.assertIn('trace-failed', files)

    def test_old_markers_and_symlink_directories_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root/'real'
            folder.mkdir()
            launcher.validate_folder(folder, os.getuid())
            (folder/'trace-ready').touch()
            with self.assertRaisesRegex(ValueError, 'old marker'):
                launcher.validate_folder(folder, os.getuid())
            alias = root/'alias'
            alias.symlink_to(folder, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                launcher.validate_folder(alias, os.getuid())


if __name__ == '__main__':
    unittest.main()
