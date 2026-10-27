# SPDX-License-Identifier: GPL-2.0-only
from contextlib import nullcontext
import io
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
from types import SimpleNamespace
from unittest.mock import patch
import unittest

spec = importlib.util.spec_from_file_location('read_trial', Path(__file__).parent/'read-path-experiment/run_trial.py')
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class ReadTrialTests(unittest.TestCase):
    def test_only_fresh_bounded_contact_counts_can_start_or_continue_a_trial(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'input.json'
            for stamp,count,expected in ((10,2,2),(8,2,None),(11,2,None),(10,True,None),(10,6,None)):
                p.write_text(json.dumps(dict(at=stamp,contacts=count)))
                self.assertEqual(trial.input_count(p,10.5),expected)
            p.write_text('{broken')
            self.assertIsNone(trial.input_count(p,10.5))

    def test_failed_and_short_i2c_transfers_abort_instead_of_becoming_good_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'trace'
            for returned,expected in ((2,False),(1,True),(-110,True)):
                p.write_text(f'irq [000] 1.1: i2c_result: i2c-1 n=2 ret={returned}\n')
                self.assertEqual(trial.transfer_failed(p),expected)

    def test_transfer_monitor_keeps_every_line_across_large_appends_and_partial_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'trace';cursor={}
            p.write_bytes(b'prefix\n'+b'irq [000] 1.1: i2c_result: i2c-1 n=2 ret=-')
            self.assertFalse(trial.transfer_failed(p,cursor))
            with p.open('ab') as stream:stream.write(b'110\n'+b'other event\n'*10000)
            self.assertTrue(trial.transfer_failed(p,cursor))
            self.assertFalse(trial.transfer_failed(p,cursor))

    def test_secondary_recontacts_are_allowed_without_promoting_the_first_identity(self):
        for ids in ([1], [1,2], [1,3]):
            trial.require_primary(dict(contacts=len(ids),ids=ids),1)
        for state in (None,dict(contacts=1,ids=[2]),dict(contacts=3,ids=[1,2,3])):
            with self.assertRaises(RuntimeError):trial.require_primary(state,1)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'input.json'
            p.write_text(json.dumps(dict(at=10,contacts=2,ids=[1,2])))
            self.assertEqual(trial.input_count(p,10.5,with_ids=True)['ids'],[1,2])
            p.write_text(json.dumps(dict(at=10,contacts=2,ids=[1,1])))
            self.assertIsNone(trial.input_count(p,10.5,with_ids=True))

    def test_baseline_brackets_both_read_modes_and_no_other_modes_are_requested(self):
        self.assertEqual((trial.MODES[0],trial.MODES[-1]),(1,1))
        self.assertEqual(set(trial.MODES),{1,6,33})
        self.assertEqual(trial.MODES.count(6),2)
        self.assertEqual(trial.MODES.count(33),2)


    def test_bus_failure_restores_original_even_if_trace_shutdown_also_fails(self):
        for shutdown_fails in (False, True):
            with self.subTest(shutdown_fails=shutdown_fails), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);folder=root/'trial';folder.mkdir();parameter=root/'parameter'
                state=dict(phase='active',module_sha256='baseline')
                candidate=object();baseline=SimpleNamespace(verify=lambda _:None);applied=[]
                store=SimpleNamespace(lock=nullcontext,read=lambda:state)
                class System:
                    def driver(self,_): return 'armada_thor_ft5452'
                    def targets(self): return 'lower','upper'
                def apply(package):
                    applied.append(package)
                    if package is candidate:
                        state['module_sha256']='candidate';parameter.write_text('1')
                    else:
                        state['module_sha256']='baseline';parameter.unlink(missing_ok=True)
                controller=SimpleNamespace(apply=apply)
                control=SimpleNamespace(Linux=System,Store=lambda:store,Package=lambda _:baseline,
                    Controller=lambda *_:controller,DATA=root,MODULE='armada_thor_ft5452')
                def communicate(**_):
                    if shutdown_fails: raise subprocess.TimeoutExpired('fake capture',3)
                    return 'closed',''
                capture=SimpleNamespace(stdout=io.StringIO('{"ready":true}\n'),poll=lambda:None,
                    communicate=communicate,terminate=lambda:None,returncode=0)
                with patch.object(trial.os,'geteuid',return_value=0), patch.object(trial,'panel_running',return_value=False), \
                     patch.object(trial,'PARAMETER',parameter), patch.object(trial.subprocess,'Popen',return_value=capture), \
                     patch.object(trial.select,'select',return_value=([capture.stdout],[],[])), \
                     patch.object(trial.signal,'signal',return_value=0), patch.object(trial,'transfer_failed',return_value=True):
                    with self.assertRaises(RuntimeError):
                        trial.run(candidate,folder,180,6,dict(module_sha256='baseline'),control)
                self.assertEqual(applied,[candidate,baseline])
                self.assertFalse(parameter.exists())
                result=json.loads((folder/'status.json').read_text())
                self.assertEqual(result['phase'],'restored')
                self.assertIn('I2C transfer failed',result['trial_error'])
                self.assertEqual(result['cleanup_error'] is not None,shutdown_fails)


if __name__=='__main__': unittest.main()
