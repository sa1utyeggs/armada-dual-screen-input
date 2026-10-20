"""No kernel, sysfs write, real module tool or privileged operation runs here."""
from copy import deepcopy
from contextlib import nullcontext
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import sys
import unittest
from unittest.mock import patch

import export_subset
import touchfix as t

HOST = dict(kernel_release='7.2.6', architecture='aarch64',
            kernel_notes_sha256='a' * 64, kernel_config_sha256='b' * 64,
            board_compatible=['ayn,thor'], modules_disabled=False)


class System:
    def __init__(self):
        self.host = deepcopy(HOST)
        self.drivers = {'1-0038': t.ORIGINAL, '4-0038': t.ORIGINAL}
        self.present = False
        self.events = []
        self.fail = None

    def profile(self): return self.host
    def module_info(self, path): return {'name': t.MODULE, 'vermagic': '7.2.6 SMP preempt mod_unload aarch64'}
    def targets(self): return '1-0038', '4-0038'
    def driver(self, device): return self.drivers[device]
    def inputs(self, device): return ((device, self.drivers[device]),) if self.drivers[device] else ()
    def loaded(self): return self.present

    def load(self, path):
        self.events.append(('load', str(path)))
        if self.fail == 'load': raise OSError('load failed')
        self.present = True
        if self.fail == 'upper-change': self.drivers['4-0038'] = 'unexpected'

    def unload(self, lower):
        self.events.append(('unload', lower))
        if self.fail == 'unload': raise OSError('busy')
        assert t.MODULE not in self.drivers.values()
        self.present = False

    def bind(self, driver, device, action):
        self.events.append((action, driver, device))
        assert device == '1-0038', 'Test tried to modify the upper screen'
        if self.fail == 'bind-new' and driver == t.MODULE and action == 'bind':
            raise OSError('probe failed')
        self.drivers[device] = driver if action == 'bind' else None

    def wait_input(self, driver, device):
        self.events.append(('ready', driver, device))
        if self.fail == 'wait-new' and driver == t.MODULE: raise OSError('no input')
        assert self.driver(device) == driver


class Store:
    def __init__(self): self.state = {}; self.saved = []
    def read(self): return deepcopy(self.state)
    def write(self, value): self.state = deepcopy(value)
    def lock(self): return nullcontext()
    def save(self, package):
        self.saved.append(package.manifest['sha256'])
        return Path('/trusted') / package.manifest['sha256'] / t.PAYLOAD


class DriverPackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        payload = bytearray(64); payload[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<HH', payload, 16, 1, 183)
        (self.root / t.PAYLOAD).write_bytes(payload)
        self.manifest = dict(schema=1, module=t.MODULE, payload=t.PAYLOAD,
            experimental=True, sha256=hashlib.sha256(payload).hexdigest(), host=deepcopy(HOST),
            vermagic='7.2.6 SMP preempt mod_unload aarch64')
        self.save_manifest()
        self.system, self.store = System(), Store()
        self.controller = t.Controller(self.system, self.store)
        self.addCleanup(patch.stopall)
        patch('subprocess.check_output', side_effect=AssertionError('No real tools in tests')).start()

    def save_manifest(self):
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))

    def package(self): return t.Package(self.root)

    def test_plan_verifies_without_device_or_store_mutations(self):
        self.assertEqual(self.package().verify(self.system), ('1-0038', '4-0038'))
        self.assertEqual(self.system.events, [])
        self.assertEqual(self.store.saved, [])

    def test_all_fingerprint_mismatches_are_rejected_before_actions(self):
        for key in ('kernel_release', 'architecture', 'kernel_notes_sha256', 'kernel_config_sha256'):
            with self.subTest(key=key):
                self.system.host = deepcopy(HOST); self.system.host[key] = 'different'
                with self.assertRaises(t.Refused): self.controller.apply(self.package())
                self.assertEqual(self.system.events, [])
                self.assertEqual(self.store.saved, [])

    def test_wrong_board_disabled_modules_and_changed_upper_are_rejected(self):
        for host, upper in ((dict(HOST, board_compatible=['other']), t.ORIGINAL),
                            (dict(HOST, modules_disabled=True), t.ORIGINAL),
                            (HOST, 'another-driver')):
            self.system.host = deepcopy(host); self.system.drivers['4-0038'] = upper
            with self.assertRaises(t.Refused): self.controller.apply(self.package())
            self.assertEqual(self.system.events, [])

    def test_checksum_wrong_architecture_and_payload_symlink_are_rejected(self):
        payload = self.root / t.PAYLOAD
        original = payload.read_bytes()
        payload.write_bytes(original + b'x')
        with self.assertRaises(t.Refused): self.package()
        bad = bytearray(original); struct.pack_into('<H', bad, 18, 62)
        payload.write_bytes(bad); self.manifest['sha256'] = t.sha(bad); self.save_manifest()
        with self.assertRaises(t.Refused): self.package()
        payload.unlink(); payload.symlink_to(self.root / 'unrelated')
        with self.assertRaises(t.Refused): self.package()

    def test_payload_path_and_module_identity_cannot_select_another_file(self):
        for key, value in (('payload', '../other.ko'), ('module', 'another'), ('experimental', False)):
            with self.subTest(key=key):
                original = self.manifest[key]; self.manifest[key] = value; self.save_manifest()
                with self.assertRaises(t.Refused): self.package()
                self.manifest[key] = original

    def test_malformed_metadata_is_rejected_without_tools(self):
        for key, value in (('host', None), ('sha256', {}), ('vermagic', '')):
            original = self.manifest[key]; self.manifest[key] = value; self.save_manifest()
            with self.assertRaises(t.Refused): self.package()
            self.manifest[key] = original

    def test_successful_takeover_and_revert_only_modify_lower(self):
        self.controller.apply(self.package())
        self.assertEqual(self.system.driver('1-0038'), t.MODULE)
        self.assertEqual(self.system.driver('4-0038'), t.ORIGINAL)
        self.assertEqual(self.store.state['phase'], 'active')
        self.controller.revert()
        self.assertEqual(self.system.driver('1-0038'), t.ORIGINAL)
        self.assertFalse(self.system.loaded())
        self.assertEqual(self.store.state['phase'], 'reverted')

    def test_probe_and_input_failures_restore_original_and_unload(self):
        for failure in ('load', 'bind-new', 'wait-new'):
            with self.subTest(failure=failure):
                self.system = System(); self.system.fail = failure
                c = t.Controller(self.system, self.store)
                with self.assertRaises(OSError): c.apply(self.package())
                self.assertEqual(self.system.driver('1-0038'), t.ORIGINAL)
                self.assertEqual(self.system.driver('4-0038'), t.ORIGINAL)
                self.assertFalse(self.system.loaded())
                self.assertEqual(self.store.state['phase'], 'reverted')

    def test_failed_unload_keeps_original_driver_and_records_recovery_needed(self):
        self.controller.apply(self.package()); self.system.fail = 'unload'
        with self.assertRaises(t.Refused): self.controller.apply(self.package())
        self.assertEqual(self.system.driver('1-0038'), t.ORIGINAL)
        self.assertEqual(self.store.state['phase'], 'recovery-needed')

    def test_upper_change_aborts_before_lower_detach_and_is_not_hidden(self):
        self.system.fail = 'upper-change'
        with self.assertRaises(t.Refused): self.controller.apply(self.package())
        self.assertFalse(any(event[0] == 'unbind' for event in self.system.events))
        self.assertEqual(self.store.state['phase'], 'recovery-needed')

    def test_unmanaged_same_name_module_is_never_unloaded(self):
        self.system.present = True
        with self.assertRaises(t.Refused): self.controller.apply(self.package())
        self.assertEqual(self.system.events, [])
        self.assertEqual(self.store.state, {})

    def test_update_returns_to_original_before_reloading_and_retains_previous_digest(self):
        self.controller.apply(self.package())
        before = self.manifest['sha256']; self.system.events.clear()
        payload = (self.root / t.PAYLOAD).read_bytes() + b'new'
        (self.root / t.PAYLOAD).write_bytes(payload)
        self.manifest['sha256'] = t.sha(payload); self.save_manifest()
        self.controller.apply(self.package())
        actions = [event[0] for event in self.system.events]
        self.assertLess(actions.index('unload'), actions.index('load'))
        self.assertEqual(self.store.state['previous_sha256'], before)

    def test_revert_recovers_a_detached_lower_device(self):
        self.system.drivers['1-0038'] = None
        self.controller.revert()
        self.assertEqual(self.system.driver('1-0038'), t.ORIGINAL)

    def test_interrupted_trial_reverts_before_returning(self):
        class FakeLinux(System):
            @staticmethod
            def admin(): pass
        with patch.object(t, 'Linux', FakeLinux), patch.object(t, 'Store', return_value=self.store), \
                patch.object(t, 'Controller', wraps=t.Controller) as controller, \
                patch.object(t.time, 'sleep', side_effect=KeyboardInterrupt), \
                patch.object(t.signal, 'signal'), patch.object(sys, 'stdout', io.StringIO()), \
                patch.object(sys, 'argv', ['touchfix', 'trial', str(self.root), '--experimental']):
            with self.assertRaises(KeyboardInterrupt): t.main()
            system = controller.call_args.args[0]
        self.assertEqual(system.driver('1-0038'), t.ORIGINAL)
        self.assertFalse(system.present)
        self.assertEqual(self.store.state['phase'], 'reverted')

    def test_failed_trial_preflight_does_not_revert_unmanaged_module(self):
        system = self.system; system.present = True
        fake = unittest.mock.Mock(return_value=system)
        with patch.object(t, 'Linux', fake), patch.object(t, 'Store', return_value=self.store), \
                patch.object(t.signal, 'signal'), patch.object(sys, 'stdout', io.StringIO()), \
                patch.object(sys, 'argv', ['touchfix', 'trial', str(self.root), '--experimental']):
            with self.assertRaises(t.Refused): t.main()
        self.assertTrue(system.present)
        self.assertEqual(system.events, [])


class ExportAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name)
        (self.source / 'drivers/base').mkdir(parents=True)
        (self.source / 'drivers/base/core.c').write_text('')

    def test_direct_exports_preserve_gpl_and_namespace(self):
        (self.source / 'test.c').write_text('EXPORT_SYMBOL(a); EXPORT_SYMBOL_NS_GPL(b, "EXAMPLE");')
        result = export_subset.collect(self.source, {'a', 'b'}, {'a', 'b'})
        self.assertEqual(result['a'], {'export': 'EXPORT_SYMBOL', 'namespace': ''})
        self.assertEqual(result['b'], {'export': 'EXPORT_SYMBOL_GPL', 'namespace': 'EXAMPLE'})

    def test_unexported_and_ambiguous_symbols_fail_closed(self):
        (self.source / 'test.c').write_text('EXPORT_SYMBOL(a); EXPORT_SYMBOL_GPL(a);')
        with self.assertRaises(ValueError): export_subset.collect(self.source, {'a'}, set())
        with self.assertRaises(ValueError): export_subset.collect(self.source, {'a'}, {'a'})
        with self.assertRaises(ValueError): export_subset.collect(self.source, {'missing'}, {'missing'})

    def test_printk_macro_needs_both_verified_body_and_invocation(self):
        core = self.source / 'drivers/base/core.c'
        core.write_text('#define define_dev_printk_level(func, kern_level) \\\nEXPORT_SYMBOL(func);\n\ndefine_dev_printk_level(_dev_err, KERN_ERR);')
        result = export_subset.collect(self.source, {'_dev_err'}, {'_dev_err'})
        self.assertEqual(result['_dev_err']['export'], 'EXPORT_SYMBOL')
        core.write_text('define_dev_printk_level(_dev_err, KERN_ERR);')
        with self.assertRaises(ValueError): export_subset.collect(self.source, {'_dev_err'}, {'_dev_err'})


if __name__ == '__main__':
    unittest.main()
