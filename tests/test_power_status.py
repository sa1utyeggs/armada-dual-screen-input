"""Battery telemetry semantics, unavailable sensors and cache-only UI formatting."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import mock_open, patch

from armada_dual_screen_input.i18n import active_language, configure
from armada_dual_screen_input.power_status import battery_label


class BatteryLabelTests(unittest.TestCase):
    def setUp(self):
        previous = active_language()
        self.addCleanup(configure, previous)

    def test_signed_net_flow_in_both_languages_without_sensor_reads(self):
        with patch('builtins.open', side_effect=AssertionError('Painting must not read sensors')):
            for language, prefix in (('en_US', 'Bat.'), ('zh_CN', '电池')):
                configure(language)
                for watts, text in ((-4.95, '−5.0'), (12.3, '+12.3'), (0, '0.0'), (-0.01, '0.0')):
                    with self.subTest(language=language, watts=watts):
                        self.assertEqual(str(battery_label({'bat_cap': 96, 'bat_watts': watts})),
                                         f'{prefix} 96% {text}W')

    def test_missing_or_invalid_power_is_not_zero(self):
        configure('en_US')
        for watts in (None, '5.0', True, float('nan'), float('inf'), -float('inf')):
            with self.subTest(watts=watts):
                self.assertEqual(str(battery_label({'bat_cap': 80, 'bat_watts': watts})), 'Bat. 80% —W')
        self.assertEqual(str(battery_label({'bat_cap': 80})), 'Bat. 80% —W')


class BatterySamplerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1]/'vendor/ratatoskr/bin/system_stats.py'
        spec = importlib.util.spec_from_file_location('power_test_stats', source)
        cls.stats_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.stats_module)

    def sample(self, voltage, current):
        module = self.stats_module
        stats = module.HardwareStats.__new__(module.HardwareStats)
        stats._cpu_policies = stats._cpu_thermal = stats._gpu_thermal = []
        stats._prev_cpu_idle = stats._prev_cpu_total = 0
        values = {'voltage_now': voltage, 'current_now': current}
        def read(path, default=0):
            self.assertNotIn('power_now', path)
            return values.get(Path(path).name, default)
        with patch.object(module, '_read_int', side_effect=read), \
             patch.object(module, '_read_str', return_value='Discharging'), \
             patch.object(module.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='Volume: 0.50')), \
             patch('builtins.open', mock_open(read_data='')):
            return stats._sample()['bat_watts']

    def test_microvolt_microamp_conversion_preserves_sign_and_zero(self):
        self.assertEqual(self.sample(4_247_410, -1_166_410), -5.0)
        self.assertEqual(self.sample(4_000_000, 2_000_000), 8.0)
        self.assertEqual(self.sample(4_000_000, 0), 0.0)

    def test_missing_or_invalid_voltage_is_unavailable(self):
        for voltage, current in ((None, 0), (4_000_000, None), (0, -1_000_000), (-4000, 0)):
            with self.subTest(voltage=voltage, current=current):
                self.assertIsNone(self.sample(voltage, current))
