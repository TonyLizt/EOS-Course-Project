"""Pure Python epoch tests: importing the parser must never start a JVM."""
import ast
from datetime import datetime, timedelta, timezone
import locale
from pathlib import Path
import unittest
from unittest.mock import patch

from utils.time_parsing import parse_orbit_epoch


class EpochParsingTests(unittest.TestCase):
    expected = datetime(2025, 11, 18, 12, tzinfo=timezone.utc)

    def test_english_month(self):
        self.assertEqual(parse_orbit_epoch("18 Nov 2025 12:00:00.000"), self.expected)

    def test_all_english_months(self):
        for index, month in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1):
            self.assertEqual(parse_orbit_epoch(f"01 {month} 2025 00:00:00").month, index)

    def test_iso(self):
        self.assertEqual(parse_orbit_epoch("2025-11-18T12:00:00+00:00"), self.expected)

    def test_z(self):
        self.assertEqual(parse_orbit_epoch("2025-11-18T12:00:00Z"), self.expected)

    def test_positive_offset(self):
        self.assertEqual(parse_orbit_epoch("2025-11-18T20:00:00+08:00"), self.expected)

    def test_negative_offset(self):
        self.assertEqual(parse_orbit_epoch("2025-11-18T07:00:00-05:00"), self.expected)

    def test_naive_string_means_utc(self):
        self.assertEqual(parse_orbit_epoch("2025-11-18 12:00:00"), self.expected)

    def test_datetime_naive(self):
        self.assertEqual(parse_orbit_epoch(self.expected.replace(tzinfo=None)), self.expected)

    def test_datetime_aware(self):
        self.assertEqual(parse_orbit_epoch(self.expected.astimezone(timezone(timedelta(hours=8)))), self.expected)

    def test_fractional_seconds(self):
        for value in ("18 Nov 2025 12:00:00.123456", "2025-11-18T12:00:00.123456Z"):
            self.assertEqual(parse_orbit_epoch(value).microsecond, 123456)

    def test_leap_day(self):
        self.assertEqual(parse_orbit_epoch("29 Feb 2024 00:00:00").day, 29)

    def test_invalid_dates(self):
        for value in ("29 Feb 2025 00:00:00", "2025-13-01", "2025-11-18T25:00:00"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_orbit_epoch(value)

    def test_empty(self):
        for value in ("", "   "):
            with self.assertRaises(ValueError):
                parse_orbit_epoch(value)

    def test_unsupported_month(self):
        with self.assertRaisesRegex(ValueError, "unsupported English month"):
            parse_orbit_epoch("18 Xxx 2025 12:00:00")

    def test_invalid_types_and_numbers(self):
        for value in (None, True, False, [], {}, float("nan"), float("inf"), float("-inf"), 10**1000):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                parse_orbit_epoch(value)

    def test_error_context(self):
        with self.assertRaises(ValueError) as caught:
            parse_orbit_epoch("bad-date", satellite_id="sat-42", field_name="orbit.epoch")
        for token in ("sat-42", "orbit.epoch", "bad-date", "Invalid"):
            self.assertIn(token, str(caught.exception))

    def test_no_wall_clock_dependency(self):
        class ClockForbidden(datetime):
            @classmethod
            def now(cls, *args, **kwargs):
                raise AssertionError("wall clock accessed")
        with patch("utils.time_parsing.datetime", ClockForbidden):
            for _ in range(3):
                self.assertEqual(parse_orbit_epoch("18 Nov 2025 12:00:00.000"), self.expected)
                with self.assertRaises(ValueError):
                    parse_orbit_epoch("broken")

    def test_no_locale_dependency(self):
        before = locale.setlocale(locale.LC_TIME)
        with patch("locale.setlocale", side_effect=AssertionError("locale accessed")), \
             patch("locale.nl_langinfo", side_effect=AssertionError("locale accessed"), create=True):
            self.assertEqual(parse_orbit_epoch("18 Nov 2025 12:00:00.000"), self.expected)
        self.assertEqual(locale.setlocale(locale.LC_TIME), before)

    def test_legacy_formats(self):
        for value in ("2025-11-18 12:00:00", "2025/11/18 12:00:00",
                      "2025-11-18T12:00:00", "2025/11/18T12:00:00"):
            self.assertEqual(parse_orbit_epoch(value), self.expected)

    def test_numeric_unix_seconds(self):
        self.assertEqual(parse_orbit_epoch(self.expected.timestamp()), self.expected)
        self.assertEqual(parse_orbit_epoch(0), datetime(1970, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(parse_orbit_epoch(0.25).microsecond, 250000)

    def test_equivalent_formats(self):
        values = ["18 Nov 2025 12:00:00.000", "2025-11-18T12:00:00Z", "2025-11-18T20:00:00+08:00"]
        self.assertEqual(len({parse_orbit_epoch(v) for v in values}), 1)

    def test_visibility_entry_point_without_jvm(self):
        from utils.visibility import _parse_epoch, _extract_orbit_params
        from types import SimpleNamespace
        sat = SimpleNamespace(id="s", orbital_params=SimpleNamespace(
            semi_major_axis=7000, eccentricity=0, inclination=0,
            right_ascension_of_ascending_node=0, argument_of_perigee=0, mean_anomaly=0,
            initial_representation_Epoch="18 Nov 2025 12:00:00.000"))
        with patch("utils.visibility.ensure_orekit", side_effect=AssertionError("JVM started")):
            self.assertEqual(_extract_orbit_params(sat)["epoch_dt"], self.expected)
            with self.assertRaisesRegex(ValueError, "satellite_id='s'"):
                _parse_epoch("bad", satellite_id="s")

    def test_generator_prevalidation_before_pool_without_importing_generator(self):
        # main_generate has output-directory side effects at import: inspect its AST only.
        source = Path(__file__).resolve().parents[1] / "main_generate.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_all_scenarios")
        calls = [n for n in ast.walk(function) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        self.assertLess(next(n.lineno for n in calls if n.func.id == "parse_orbit_epoch"),
                        next(n.lineno for n in calls if n.func.id == "ProcessPoolExecutor"))


if __name__ == "__main__":
    unittest.main()
