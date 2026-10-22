"""Driver UI safety: fake privilege, modules, services and temporary files only."""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import hashlib
from contextlib import nullcontext
import unittest
from unittest.mock import Mock, patch

from armada_dual_screen_input import touch_driver as client
from armada_dual_screen_input.driver_controller import DriverController, launch
from armada_dual_screen_input.input_settings import SettingsDraft, SETTINGS_PAGES

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('driver_root_bridge_tests',
    ROOT/'extras/thor-touch-driver/gui_bridge.py')
bridge = importlib.util.module_from_spec(spec); spec.loader.exec_module(bridge)
spec = importlib.util.spec_from_file_location('driver_worker_tests', ROOT/'tools/driver.py')
worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)


class DriverClientTests(unittest.TestCase):
    def test_missing_component_never_starts_a_command(self):
        runner = Mock()
        with patch.object(client, 'bridge_available', return_value=False):
            info = client.probe(runner=runner)
        self.assertFalse(info['component']); runner.assert_not_called()

    def test_status_runs_fixed_isolated_python_without_privilege(self):
        info = dict(schema=1, component=True, compatible=True, active=True, kernel='7.2.6')
        runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(info)))
        with patch.object(client, 'bridge_available', return_value=True):
            self.assertEqual(client.probe(runner=runner), info)
        args = runner.call_args.args[0]
        self.assertEqual(args, ['/usr/bin/python3', '-I', '-B', str(client.BRIDGE), 'status'])

    def test_bad_status_and_authentication_cancellation_fail_closed(self):
        with patch.object(client, 'bridge_available', return_value=True):
            for data in ({'schema': 1}, {'schema': 2}, []):
                with self.assertRaises(ValueError):
                    client.probe(runner=lambda *a,**k: SimpleNamespace(returncode=0, stdout=json.dumps(data)))
            with self.assertRaises(RuntimeError):
                client.authenticated_action('apply', runner=lambda *a,**k: SimpleNamespace(returncode=126,stdout=''))

    def test_only_fixed_actions_and_root_owned_helper_are_accepted(self):
        runner = Mock(return_value=SimpleNamespace(returncode=0,
            stdout='{"schema":1,"component":true,"active":true}'))
        with patch.object(client, 'bridge_available', return_value=True):
            client.authenticated_action('apply', runner=runner)
            args = runner.call_args.args[0]
            self.assertEqual(args, ['/usr/bin/pkexec','/usr/bin/python3','-I','-B',str(client.BRIDGE),'apply'])
            for action in ('status','apply /tmp/module.ko','install','../apply'):
                with self.assertRaises(ValueError):client.authenticated_action(action,runner=runner)
        with patch.object(client, 'bridge_available', return_value=False):
            with self.assertRaises(ValueError):client.authenticated_action('apply',runner=runner)

    def test_user_writable_or_symlink_component_is_not_executed(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)/'component';p.mkdir();(p/'gui_bridge.py').write_text('not executable')
            p.chmod(0o777)
            self.assertFalse(client.bridge_available(p))
            link=Path(temp)/'alias';link.symlink_to(p,target_is_directory=True)
            self.assertFalse(client.bridge_available(link))


class DriverControllerTests(unittest.TestCase):
    def controller(self, **kwargs):
        c=DriverController(ROOT,dispatch=lambda cb:cb(),changed=lambda:None,
            background=lambda fn:fn(),**kwargs)
        c.info=dict(component=True,compatible=True,active=False,kernel='7.2.6')
        return c

    def test_no_probe_or_driver_change_happens_at_construction(self):
        inspect=Mock();start=Mock();self.controller(inspect=inspect,start=start)
        inspect.assert_not_called();start.assert_not_called()

    def test_launcher_uses_user_manager_not_lower_private_bus(self):
        private_bus='unix:path=/tmp/lower-private-bus'
        with patch.dict(os.environ,{'DBUS_SESSION_BUS_ADDRESS':private_bus}), \
             patch('armada_dual_screen_input.driver_controller.subprocess.run') as run:
            run.return_value.returncode=0
            launch(ROOT,'revert')
        args=run.call_args.args[0]
        self.assertIn('--user',args)
        self.assertIn('--setenv=DBUS_SESSION_BUS_ADDRESS='+private_bus,args)
        self.assertNotIn('DBUS_SESSION_BUS_ADDRESS',run.call_args.kwargs['env'])
        self.assertEqual(args[-4:-2],[str(ROOT/'tools/driver.py'),'revert'])
        self.assertIn('--unit=thor-panel-driver',args)

    def test_explicit_confirmation_and_duplicate_click_protection(self):
        start=Mock();c=self.controller(start=start)
        c.run();start.assert_not_called()
        c.request('apply');self.assertEqual(c.confirming,'apply')
        c.run();c.run();c.request('apply');c.run()
        start.assert_called_once_with(ROOT,'apply')
        self.assertTrue(c.busy)

    def test_incompatible_enable_is_blocked_but_restore_remains_available(self):
        c=self.controller(start=Mock());c.info.update(compatible=False,active=True)
        c.request('apply');self.assertIsNone(c.confirming)
        c.request('revert');self.assertEqual(c.confirming,'revert')
        c.cancel();self.assertIsNone(c.confirming)
        c.close();c.run();c.launch.assert_not_called()

    def test_probe_failure_and_late_result_after_close(self):
        c=self.controller(inspect=Mock(side_effect=OSError));c.refresh()
        self.assertEqual(c.phase,'error')
        self.assertFalse(c.can('apply'))
        tasks=[];c.background=tasks.append;c.refresh();c.close();tasks.pop()()
        self.assertEqual(c.phase,'checking')

    def test_driver_page_has_no_settings_defaults_or_save_side_effects(self):
        self.assertEqual(len(SETTINGS_PAGES),5)
        self.assertNotIn('updates',SETTINGS_PAGES)
        d=SettingsDraft({});d.section='driver'
        self.assertEqual(d.rows(),[])
        self.assertEqual(d.hit(100,790),('driver_left',None))
        self.assertEqual(d.hit(900,790),('driver_right',None))
        self.assertEqual(d.hit(100,880),('driver_refresh',None))
        self.assertEqual(d.hit(1100,1020),(None,None))
        self.assertFalse(d.dirty)


class RootDriverBridgeTests(unittest.TestCase):
    def profile(self):
        return dict(kernel_release='7.2.6',architecture='aarch64',kernel_notes_sha256='n',
                    kernel_config_sha256='c',board_compatible=['ayn,thor'],modules_disabled=False)

    def test_read_only_status_checks_full_fingerprints_and_upper_driver(self):
        profile=self.profile();meta={'host':{k:profile[k] for k in (
            'kernel_release','architecture','kernel_notes_sha256','kernel_config_sha256')}}
        s=SimpleNamespace(profile=lambda:profile,targets=lambda:('lower','upper'),
                          driver=lambda node:'edt_ft5x06')
        self.assertTrue(bridge.status(meta,s)['compatible'])
        profile['kernel_notes_sha256']='different-build'
        self.assertFalse(bridge.status(meta,s)['compatible'])
        profile['kernel_notes_sha256']='n';s.driver=lambda _: 'unexpected'
        self.assertFalse(bridge.status(meta,s)['compatible'])

    def test_failed_package_verification_prevents_store_or_controller_mutations(self):
        control=SimpleNamespace(Linux=SimpleNamespace(admin=Mock()),
            Package=Mock(return_value=SimpleNamespace(manifest={'sha256':'a'*64},
                                                      verify=Mock(side_effect=ValueError('mismatch')))),
            Store=Mock(),Controller=Mock())
        with self.assertRaises(ValueError):
            bridge.perform('apply',{'module_sha256':'a'*64},control,system=object())
        control.Store.assert_not_called();control.Controller.assert_not_called()

    def test_root_component_rejects_unsafe_ownership_and_type(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'file';p.write_text('x');p.chmod(0o666)
            with self.assertRaises(ValueError):bridge.secure(p)
            symlink=Path(temp)/'link';symlink.symlink_to(p)
            with self.assertRaises(ValueError):bridge.secure(symlink)

    def test_root_component_verifies_code_before_importing_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); files={'gui_bridge.py':b'# trusted bridge\n','touchfix.py':b'VALUE = 7\n'}
            for n,data in files.items():(root/n).write_bytes(data)
            profile=self.profile()
            metadata={'schema':1,'component':'armada-thor-touch-fix-ui','module_sha256':'a'*64,
                'host':{k:profile[k] for k in ('kernel_release','architecture','kernel_notes_sha256','kernel_config_sha256')},
                'files':{n:hashlib.sha256(data).hexdigest() for n,data in files.items()}}
            (root/'component.json').write_text(json.dumps(metadata))
            with patch.object(bridge,'secure'):
                actual,control=bridge.load_component(root)
                self.assertEqual(control.VALUE,7)
                (root/'touchfix.py').write_text('raise AssertionError("must not execute")')
                with self.assertRaisesRegex(ValueError,'checksum'):bridge.load_component(root)

    def test_already_active_module_is_not_rebound(self):
        profile=self.profile(); sha='a'*64
        meta={'host':{k:profile[k] for k in ('kernel_release','architecture','kernel_notes_sha256','kernel_config_sha256')},
              'module_sha256':sha}
        system=SimpleNamespace(profile=lambda:profile,targets=lambda:('lower','upper'),loaded=lambda:True,
            driver=lambda p:'armada_thor_ft5452' if p=='lower' else 'edt_ft5x06')
        store=SimpleNamespace(lock=lambda:nullcontext(),read=lambda:{'module_sha256':sha})
        controller=Mock();control=SimpleNamespace(Linux=SimpleNamespace(admin=Mock()),MODULE='armada_thor_ft5452',
            Package=Mock(return_value=SimpleNamespace(manifest={'sha256':sha},verify=Mock())),
            Store=lambda:store,Controller=Mock(return_value=controller))
        self.assertTrue(bridge.perform('apply',meta,control,system)['active'])
        controller.apply.assert_not_called()
        profile['kernel_notes_sha256']='changed'
        control.Package.reset_mock()
        bridge.perform('revert',meta,control,system)
        controller.revert.assert_called_once();control.Package.assert_not_called()


class DriverWorkerTests(unittest.TestCase):
    def exercise(self, fail):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'current').symlink_to(worker.ROOT,target_is_directory=True)
            paths=SimpleNamespace(root=root);calls=[];statuses=[]
            def service(args,**kwargs):
                calls.append(args);return SimpleNamespace(returncode=0)
            operate=Mock(side_effect=RuntimeError('authentication canceled') if fail else None,
                         return_value={'active':True})
            with patch.object(worker,'verify'),patch.object(worker.os,'geteuid',return_value=1000):
                if fail:
                    with self.assertRaises(RuntimeError):
                        worker.perform('apply',paths=paths,service=service,operate=operate,
                                       status=lambda *v:statuses.append(v))
                else:
                    worker.perform('apply',paths=paths,service=service,operate=operate,
                                   status=lambda *v:statuses.append(v))
            self.assertEqual(calls,[['is-active','--quiet','thor-panel.service'],
                ['stop','thor-panel.service'],['start','thor-panel.service']])
            self.assertEqual(statuses[-1][0],'error' if fail else 'success')

    def test_auth_cancel_restores_only_the_panel(self):self.exercise(True)
    def test_success_restores_only_the_panel(self):self.exercise(False)


if __name__=='__main__':unittest.main()
