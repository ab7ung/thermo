"""Unit tests: parsers, sensor grouping, the Linux readers and the governor.

The Linux readers run against a fake /sys tree, so that path is covered on any
platform. The supervisor itself needs real processes and signals and lives in
tests/test_cli.sh.
"""
import importlib.machinery
import importlib.util
import pathlib
import shutil
import tempfile
import unittest

_path = pathlib.Path(__file__).resolve().parent.parent / "thermo"
_spec = importlib.util.spec_from_loader("thermo", importlib.machinery.SourceFileLoader("thermo", str(_path)))
t = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t)


class Parsers(unittest.TestCase):
    def test_ioreg_hundredths_of_a_degree(self):
        self.assertAlmostEqual(t.parse_ioreg('  "Temperature" = 3024\n'), 30.24)

    def test_ioreg_missing_or_absurd(self):
        self.assertIsNone(t.parse_ioreg("no sensor here"))
        self.assertIsNone(t.parse_ioreg('"Temperature" = 99999'))
        self.assertIsNone(t.parse_ioreg(None))

    def test_pmset_throttle(self):
        self.assertTrue(t.parse_pmset("CPU_Speed_Limit \t= 80"))
        self.assertTrue(t.parse_pmset("thermal warning level = 1"))
        self.assertFalse(t.parse_pmset("CPU_Speed_Limit = 100\nthermal warning level = 0"))
        self.assertFalse(t.parse_pmset(None))

    def test_sysfs_millidegrees(self):
        self.assertAlmostEqual(t.parse_millidegrees("52000\n"), 52.0)
        self.assertIsNone(t.parse_millidegrees("garbage"))
        self.assertIsNone(t.parse_millidegrees("0"))  # a zone reading zero is not a reading

    def test_powermetrics_takes_the_hottest_die(self):
        text = "CPU die temperature: 51.2 C\nGPU die temperature: 63.9 C\n"
        self.assertAlmostEqual(t.parse_powermetrics(text), 63.9)
        self.assertIsNone(t.parse_powermetrics("nothing"))

    def test_wmi_tenths_of_kelvin(self):
        self.assertAlmostEqual(t.parse_wmi("3131"), 40.0, places=1)
        self.assertIsNone(t.parse_wmi(""))


class SmcGrouping(unittest.TestCase):
    """SMC keys name their silicon: Tp* is CPU, Tg* GPU, TB* the battery."""

    READINGS = {"Tp01": 40.0, "Tp05": 30.0, "Tg0D": 45.0, "Tg0K": 41.0, "TB0T": 29.7, "TH0a": 32.8}

    def test_cpu_max_and_mean(self):
        self.assertEqual(t.group_sensors(self.READINGS)["cpu"], (40.0, 35.0))

    def test_gpu_max_and_mean(self):
        self.assertEqual(t.group_sensors(self.READINGS)["gpu"], (45.0, 43.0))

    def test_battery_is_chassis(self):
        self.assertAlmostEqual(t.group_sensors(self.READINGS)["chassis"][0], 29.7)

    def test_unrelated_keys_ignored(self):
        # TH0a is a drive sensor: it belongs to no group
        for group in t.group_sensors(self.READINGS).values():
            self.assertNotAlmostEqual(group[0], 32.8)

    def test_no_sensors_at_all(self):
        self.assertEqual(t.group_sensors({}), {"cpu": (None, None), "gpu": (None, None), "chassis": (None, None)})

    def test_absurd_readings_dropped(self):
        self.assertEqual(t.group_sensors({"Tp01": 0.0, "Tg0D": 999.0})["cpu"], (None, None))

    def test_parked_cores_ignored_while_live_ones_remain(self):
        # 2.1 °C is a power-gated core, not a temperature
        self.assertEqual(t.group_sensors({"Tp01": 44.0, "Tp05": 2.1})["cpu"], (44.0, 44.0))

    def test_all_cores_parked_falls_back_to_what_there_is(self):
        self.assertEqual(t.group_sensors({"Tp01": 2.1, "Tp05": 2.3})["cpu"], (2.3, 2.2))


class LinuxReaders(unittest.TestCase):
    """read_sysfs/read_fans against a fake /sys tree, so the Linux path runs anywhere."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.real_glob = t.glob.glob
        t.glob.glob = lambda pattern: self.real_glob(self.tmp + pattern)
        self.addCleanup(setattr, t.glob, "glob", self.real_glob)

    def write(self, relative, text):
        path = pathlib.Path(self.tmp) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_hottest_thermal_zone_wins(self):
        self.write("sys/class/thermal/thermal_zone0/temp", "41000\n")
        self.write("sys/class/thermal/thermal_zone1/temp", "58500\n")
        self.assertAlmostEqual(t.read_sysfs(), 58.5)

    def test_hwmon_inputs_counted_too(self):
        self.write("sys/class/hwmon/hwmon2/temp1_input", "72000\n")
        self.assertAlmostEqual(t.read_sysfs(), 72.0)

    def test_unreadable_and_absurd_zones_skipped(self):
        self.write("sys/class/thermal/thermal_zone0/temp", "not a number")
        self.write("sys/class/thermal/thermal_zone1/temp", "999000")
        self.write("sys/class/thermal/thermal_zone2/temp", "39000")
        self.assertAlmostEqual(t.read_sysfs(), 39.0)

    def test_no_zones_at_all(self):
        self.assertIsNone(t.read_sysfs())

    def test_fan_speeds_sorted_and_zeroes_dropped(self):
        self.write("sys/class/hwmon/hwmon0/fan1_input", "3200\n")
        self.write("sys/class/hwmon/hwmon0/fan2_input", "0\n")
        self.write("sys/class/hwmon/hwmon1/fan1_input", "1800\n")
        self.assertEqual(t.read_fans(), [1800, 3200])

    def test_no_fans(self):
        self.assertEqual(t.read_fans(), [])


class HotRule(unittest.TestCase):
    def reading(self, temp=50.0, throttled=False):
        return {"die": temp, "chassis": temp, "throttled": throttled}

    def test_at_threshold_is_hot(self):
        self.assertTrue(t.is_hot(self.reading(85.0), "die", 85.0))

    def test_below_threshold_is_not(self):
        self.assertFalse(t.is_hot(self.reading(84.9), "die", 85.0))

    def test_throttling_is_hot_at_any_temperature(self):
        self.assertTrue(t.is_hot(self.reading(20.0, throttled=True), "die", 85.0))

    def test_missing_reading_is_not_hot_on_its_own(self):
        # the governor decides what a lost sensor means; this rule only reads
        self.assertFalse(t.is_hot({"die": None, "throttled": False}, "die", 85.0))


class GovernorPolicy(unittest.TestCase):
    def gov(self, **kw):
        return t.Governor(pause=80, resume=70, **kw)

    def test_needs_two_hot_readings(self):
        g = self.gov()
        self.assertIsNone(g.step(85))
        self.assertEqual(g.step(85), "pause")

    def test_single_spike_does_not_freeze(self):
        g = self.gov()
        self.assertIsNone(g.step(85))
        self.assertIsNone(g.step(60))
        self.assertIsNone(g.step(85))

    def test_hysteresis_gap_holds_the_freeze(self):
        g = self.gov()
        g.step(85), g.step(85)
        self.assertIsNone(g.step(75))  # between resume and pause: stay frozen
        self.assertIsNone(g.step(75))
        self.assertTrue(g.frozen)

    def test_thaw_below_resume(self):
        g = self.gov()
        g.step(85), g.step(85)
        self.assertIsNone(g.step(69))
        self.assertEqual(g.step(69), "resume")
        self.assertFalse(g.frozen)

    def test_throttle_flag_freezes_at_once(self):
        # no streak: the OS is already throttling, that is not a prediction
        g = self.gov()
        self.assertEqual(g.step(30, throttled=True), "pause")

    def test_throttle_flag_blocks_thaw(self):
        g = self.gov()
        g.step(85), g.step(85)
        g.step(30, throttled=True)
        self.assertIsNone(g.step(30, throttled=True))
        self.assertTrue(g.frozen)

    def test_lost_sensor_fails_safe_after_three_misses(self):
        g = self.gov()
        self.assertIsNone(g.step(None))
        self.assertIsNone(g.step(None))
        self.assertEqual(g.step(None), "pause")  # third miss counts as hot, then streak

    def test_recovered_sensor_resets_the_miss_count(self):
        g = self.gov()
        g.step(None), g.step(None)
        g.step(60)
        self.assertIsNone(g.step(None))
        self.assertIsNone(g.step(None))


if __name__ == "__main__":
    unittest.main()
