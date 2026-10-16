"""Small synthetic fixtures only. Never discover or open production scenarios."""
import copy
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "scenario_manifest", Path(__file__).resolve().parents[1] / "scripts" / "build_scenario_manifest.py")
manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manifest)


def synthetic_scene():
    return {
        "scenario_id": "Scenario_S1",
        "metadata": {"creation_time": "2025-11-18T12:00:00", "duration": 60, "time_step": 2,
                     "extra": {"generator_version": "synthetic-v1", "generator_seed": 7,
                               "source_dataset": "unit-test-fixture", "source_group_id": "synthetic-family",
                               "distribution_type": "dist1"}},
        "satellites": [{"id": "S1", "satellite_specs": {"max_data_storage_GB": 10},
                        "observation_capability": {"sensors": [{"sensor_id": "C1", "data_rate_Mbps": 0.1}]}}],
        "missions": [{"id": "M1", "priority": 2, "observation_requirement": {"duration_s": 4}}],
        "ground_stations": [{"id": "G1"}],
        "observation_windows": [{"satellite_id": "S1", "mission_id": "M1", "sensor_id": "C1",
                                 "time_windows": [segment(0, 10), segment(20, 30)]}],
        "communication_windows": [{"satellite_id": "S1", "ground_station_id": "G1", "time_windows": [
            {"start_time": "2025-11-18T12:00:40Z", "end_time": "2025-11-18T12:00:50Z"}]}],
    }


def segment(start, end):
    return {"start_time": f"2025-11-18T12:00:{start:02d}Z", "end_time": f"2025-11-18T12:00:{end:02d}Z",
            "orbit_number": 1, "agile_data": {key: [0, 1, 2, 3, 4] for key in ("pitch_angles", "yaw_angles", "roll_angles")},
            "non_agile_data": {"pitch_angle": 2, "yaw_angle": 2, "roll_angle": 2}}


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="eos-manifest-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "completed"
        self.archive.mkdir()
        self.out = self.root / "reports"
        self.scene = synthetic_scene()

    def write(self, scene=None, name="Scenario_test.json", directory=None):
        path = (directory or self.archive) / name
        path.write_text(json.dumps(self.scene if scene is None else scene), encoding="utf-8")
        return path

    def audit(self, scene=None):
        return manifest.audit_file(self.write(scene))

    def check_issue(self, result, check, level=None):
        self.assertTrue(any(i["check"] == check and (level is None or i["level"] == level)
                            for i in result["checks"]), result)

    def test_normal_scene(self):
        result = self.audit()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["record"]["time_step_s"], 2)
        self.assertEqual(result["record"]["communication_window_count"], 1)

    def test_sha_stability_and_complete_bytes(self):
        path = self.write()
        first, second = manifest.audit_file(path), manifest.audit_file(path)
        self.assertEqual(first["record"]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(first["record"]["registry_id"], second["record"]["registry_id"])

    def test_outer_and_inner_counts(self):
        self.scene["observation_windows"].append(copy.deepcopy(self.scene["observation_windows"][0]))
        row = self.audit()["record"]
        self.assertEqual((row["observation_entry_count"], row["observation_segment_count"]), (2, 4))

    def test_multiple_windows_one_mission_not_multiple_completions(self):
        row = self.audit()["record"]
        self.assertEqual(row["missions_with_windows"], 1)
        self.assertEqual(row["window_coverage_ratio"], 1)

    def test_same_internal_id_different_scale(self):
        self.write(name="a.json")
        self.scene["missions"].append({"id": "M2", "observation_requirement": {"duration_s": 4}})
        self.write(name="b.json")
        results = manifest.build_manifest([self.archive], self.out)["results"]
        self.assertEqual(len({r["record"]["registry_id"] for r in results}), 2)
        self.assertTrue(all(r["record"]["internal_scenario_id"] == "Scenario_S1" for r in results))
        self.check_issue(results[0], "internal_id_reuse", "WARN")

    def test_rename_does_not_change_registry_id(self):
        path = self.write(name="old_dist0.json")
        before = manifest.audit_file(path)["record"]
        renamed = path.with_name("renamed_dist1.json")
        path.rename(renamed)
        self.assertEqual(before["registry_id"], manifest.audit_file(renamed)["record"]["registry_id"])

    def test_missing_metadata_fails(self):
        del self.scene["metadata"]
        result = self.audit()
        self.assertEqual(result["status"], "FAIL")
        self.assertIsNone(result["record"]["registry_id"])

    def test_optional_missing_fields_warn_not_fail(self):
        for key in ("scenario_id", "observation_windows", "ground_stations", "communication_windows"):
            self.scene.pop(key)
        self.assertEqual(self.audit()["status"], "WARN")

    def test_invalid_json(self):
        path = self.archive / "broken.json"
        path.write_text('{"metadata":', encoding="utf-8")
        self.assertEqual(manifest.audit_file(path)["status"], "FAIL")

    def test_invalid_intervals(self):
        for end in ("2025-11-18T11:59:59Z", "2025-11-18T12:02:00Z", "bad"):
            with self.subTest(end=end):
                self.scene["observation_windows"][0]["time_windows"][0]["end_time"] = end
                self.check_issue(self.audit(), "window_time", "FAIL")

    def test_missing_satellite_reference(self):
        self.scene["observation_windows"][0]["satellite_id"] = "missing"
        self.check_issue(self.audit(), "reference", "FAIL")

    def test_missing_mission_reference(self):
        self.scene["observation_windows"][0]["mission_id"] = "missing"
        self.check_issue(self.audit(), "reference", "FAIL")

    def test_sensor_and_station_references(self):
        self.scene["observation_windows"][0]["sensor_id"] = "bad"
        self.scene["communication_windows"][0]["ground_station_id"] = "bad"
        result = self.audit()
        self.assertEqual(result["status"], "FAIL")
        self.assertGreaterEqual(sum(i["check"] == "reference" for i in result["checks"]), 2)

    def test_no_windows(self):
        self.scene["observation_windows"] = []
        row = self.audit()["record"]
        self.assertEqual(row["validation_status"], "WARN")
        self.assertEqual(row["missions_with_windows"], 0)

    def test_missing_attitude_fields(self):
        tw = self.scene["observation_windows"][0]["time_windows"][0]
        tw.pop("agile_data")
        tw.pop("non_agile_data")
        self.check_issue(self.audit(), "attitude_missing", "WARN")

    def test_partial_attitude(self):
        del self.scene["observation_windows"][0]["time_windows"][0]["agile_data"]["yaw_angles"]
        self.check_issue(self.audit(), "attitude_partial", "WARN")

    def test_inconsistent_angle_lengths(self):
        self.scene["observation_windows"][0]["time_windows"][0]["agile_data"]["yaw_angles"].pop()
        self.check_issue(self.audit(), "attitude_length", "FAIL")

    def test_nonfinite_values(self):
        for number in (float("nan"), float("inf"), "NaN", "1e999"):
            with self.subTest(number=number):
                self.scene["observation_windows"][0]["time_windows"][0]["agile_data"]["roll_angles"][2] = number
                self.assertEqual(self.audit()["status"], "FAIL")

    def test_readonly_input_and_no_mutation(self):
        path = self.write()
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        path.chmod(0o444)
        try:
            manifest.build_manifest([self.archive], self.out)
            self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
        finally:
            path.chmod(0o644)

    def test_output_isolation_and_csv_parity(self):
        self.write()
        report = manifest.build_manifest([self.archive], self.out)
        self.assertEqual({p.name for p in self.out.iterdir()}, set(manifest.REPORT_NAMES))
        rows = json.loads((self.out / "scenario_manifest.json").read_text(encoding="utf-8"))
        with (self.out / "scenario_manifest.csv").open(encoding="utf-8", newline="") as f:
            csv_rows = list(csv.DictReader(f))
        self.assertEqual(csv_rows[0], {k: "" if v is None else str(v) for k, v in rows[0].items()})
        self.assertEqual(report["registered_file_count"], 1)
        self.assertEqual(len(list(self.archive.iterdir())), 1)

    def test_output_equals_input_or_overlaps(self):
        self.write()
        for target in (self.archive, self.archive / "reports", self.root, self.archive / "Scenario_test.json"):
            with self.subTest(target=target), self.assertRaises(manifest.AuditError):
                manifest.build_manifest([self.archive], target)

    def test_detect_change_during_read(self):
        path = self.write()
        original = manifest.HashReader.read
        changed = False

        def read_and_change(reader, size=-1):
            nonlocal changed
            block = original(reader, size)
            if block and not changed:
                changed = True
                os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1000000000))
            return block

        with mock.patch.object(manifest.HashReader, "read", read_and_change):
            result = manifest.audit_file(path)
        self.assertEqual(result["status"], "FAIL")
        self.assertIsNone(result["record"]["registry_id"])

    def test_change_between_passes_even_if_same_size(self):
        path = self.write()
        original = manifest.read_pass
        calls = 0

        def changing(*args, **kwargs):
            nonlocal calls
            result = original(*args, **kwargs)
            calls += 1
            if calls == 1:
                path.write_bytes(path.read_bytes().replace(b'synthetic-v1', b'synthetic-v2'))
            return result

        with mock.patch.object(manifest, "read_pass", changing):
            self.assertEqual(manifest.audit_file(path)["status"], "FAIL")

    def test_duplicate_content(self):
        self.write(name="a.json")
        self.write(name="b.json")
        report = manifest.build_manifest([self.archive], self.out)
        self.assertEqual(report["unique_registry_count"], 1)
        self.assertEqual(report["registered_file_count"], 2)
        self.check_issue(report["results"][0], "duplicate_content", "WARN")

    def test_same_filename_different_content(self):
        other = self.root / "other_archive"
        other.mkdir()
        self.write()
        self.scene["missions"][0]["priority"] = 5
        self.write(directory=other)
        report = manifest.build_manifest([self.archive, other], self.out)
        self.assertEqual(report["unique_registry_count"], 2)
        self.check_issue(report["results"][0], "filename_conflict", "WARN")

    def test_explicit_registry_collision_fails_both(self):
        self.write(name="a.json")
        self.scene["missions"][0]["priority"] = 5
        self.write(name="b.json")
        with mock.patch.object(manifest, "registry_id", return_value="forced_collision"):
            report = manifest.build_manifest([self.archive], self.out)
        self.assertEqual(report["registered_file_count"], 0)
        self.assertTrue(all(r["status"] == "FAIL" for r in report["results"]))

    def test_existing_reports_never_overwritten(self):
        self.write()
        manifest.build_manifest([self.archive], self.out)
        before = (self.out / manifest.REPORT_NAMES[0]).read_bytes()
        with self.assertRaises(manifest.AuditError):
            manifest.build_manifest([self.archive], self.out)
        self.assertEqual(before, (self.out / manifest.REPORT_NAMES[0]).read_bytes())

    def test_duplicate_entity_ids_and_json_keys(self):
        for key in ("satellites", "missions", "ground_stations"):
            scene = synthetic_scene()
            scene[key].append(copy.deepcopy(scene[key][0]))
            self.check_issue(self.audit(scene), "duplicate_id", "FAIL")
        path = self.write()
        path.write_text('{"metadata": {}, "metadata": {}}', encoding="utf-8")
        self.assertEqual(manifest.audit_file(path)["status"], "FAIL")

    def test_malformed_structures(self):
        for key in ("satellites", "missions", "ground_stations", "observation_windows", "communication_windows"):
            scene = synthetic_scene()
            scene[key] = {"unexpected": "mapping"}
            self.check_issue(self.audit(scene), "schema", "FAIL")

    def test_numeric_and_duration_rules(self):
        for key, number in (("time_step", 0), ("duration", -1), ("duration", True)):
            scene = synthetic_scene()
            scene["metadata"][key] = number
            self.assertEqual(self.audit(scene)["status"], "FAIL")
        self.scene["missions"][0]["observation_requirement"]["duration_s"] = 20
        self.assertEqual(self.audit()["record"]["missions_with_windows"], 0)

    def test_endpoint_and_step_override(self):
        tw = self.scene["observation_windows"][0]["time_windows"][0]
        for array in tw["agile_data"].values():
            array.append(5)
        self.assertEqual(self.audit()["status"], "PASS")
        tw["time_step"] = 1
        self.check_issue(self.audit(), "sampling_length", "WARN")

    def test_timezone_matches_loader(self):
        self.scene["metadata"]["creation_time"] = "2025-11-18T20:00:00+08:00"
        self.assertEqual(self.audit()["status"], "PASS")

    def test_missing_provenance_is_not_invented(self):
        self.scene["metadata"]["extra"] = {}
        row = self.audit()["record"]
        for key in ("generator_seed", "generator_version", "source_dataset", "source_group_id"):
            self.assertIsNone(row[key])
        self.assertEqual(row["validation_status"], "WARN")

    def test_failed_file_only_in_validation_report(self):
        self.write(name="good.json")
        self.scene["metadata"]["duration"] = -1
        self.write(name="bad.json")
        report = manifest.build_manifest([self.archive], self.out)
        self.assertEqual(len(report["results"]), 2)
        self.assertEqual(report["registered_file_count"], 1)

    def test_protected_roots_rejected_before_discovery(self):
        # Mock protection roots to synthetic directories, never touch real input/output.
        with mock.patch.object(manifest, "PROJECT_ROOT", self.root):
            for name in ("input", "output"):
                protected = self.root / name
                protected.mkdir()
                with mock.patch.object(Path, "iterdir", side_effect=AssertionError("must not scan")):
                    with self.assertRaises(manifest.AuditError):
                        manifest.build_manifest([protected], self.out)
                    with self.assertRaises(manifest.AuditError):
                        manifest.build_manifest([self.archive], protected / "reports")

    def test_symlink_protected_directory_and_report(self):
        protected = self.root / "output"
        protected.mkdir()
        link = self.root / "alias"
        try:
            link.symlink_to(protected, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable on this host")
        with mock.patch.object(manifest, "PROJECT_ROOT", self.root):
            with self.assertRaises(manifest.AuditError):
                manifest.build_manifest([link], self.out)
            with self.assertRaises(manifest.AuditError):
                manifest.build_manifest([self.archive], link / "reports")

    def test_file_symlink_to_protected_path_not_opened(self):
        protected = self.root / "output"
        protected.mkdir()
        target = self.write(directory=protected)
        link = self.archive / "link.json"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable on this host")
        with mock.patch.object(manifest, "PROJECT_ROOT", self.root):
            result = manifest.audit_file(link)
        self.assertEqual(result["status"], "FAIL")
        self.assertIsNone(result["record"]["sha256"])

    def test_small_fallback_limit_without_large_fixture(self):
        path = self.write()
        with mock.patch.object(manifest, "SMALL_FILE_LIMIT", 128):
            self.assertEqual(manifest.audit_file(path, force_small=True)["status"], "FAIL")

    def test_stream_and_fallback_parity_arbitrary_key_order(self):
        if manifest.ijson is None:
            self.skipTest("ijson unavailable; bounded fallback tested separately")
        path = self.write(dict(reversed(list(self.scene.items()))))
        streamed = manifest.audit_file(path)
        fallback = manifest.audit_file(path, force_small=True)
        self.assertEqual(streamed["record"].pop("parser_mode"), "ijson-outer-item")
        self.assertEqual(fallback["record"].pop("parser_mode"), "stdlib-bounded")
        self.assertEqual(streamed, fallback)

    def test_trailing_json_rejected_both_parsers(self):
        path = self.write()
        with path.open("a", encoding="utf-8") as f:
            f.write("{}")
        for small in (False, True):
            self.assertEqual(manifest.audit_file(path, force_small=small)["status"], "FAIL")

    def test_io_failure_missing_file_and_nonregular(self):
        self.assertEqual(manifest.audit_file(self.archive / "absent.json")["status"], "FAIL")
        self.assertEqual(manifest.audit_file(self.archive)["status"], "FAIL")
        path = self.write()
        with mock.patch.object(Path, "open", side_effect=PermissionError("synthetic denied")):
            self.assertEqual(manifest.audit_file(path)["status"], "FAIL")

    def test_io_failure_mid_read(self):
        path = self.write()
        original = manifest.HashReader.read
        calls = 0

        def broken(reader, size=-1):
            nonlocal calls
            if size:
                calls += 1
                if calls > 1:
                    raise OSError("synthetic disk read failure")
            return original(reader, size)

        with mock.patch.object(manifest.HashReader, "read", broken):
            result = manifest.audit_file(path, force_small=True)
        self.assertEqual(result["status"], "FAIL")
        self.assertIsNone(result["record"]["sha256"])

    def test_unknown_numeric_overflow_and_malformed_attitude(self):
        self.scene["observation_windows"][0]["time_windows"][0]["agile_data"] = 42
        self.check_issue(self.audit(), "attitude_schema", "FAIL")
        path = self.write()
        path.write_text('{"unused_numeric_field": 1e999}', encoding="utf-8")
        self.assertEqual(manifest.audit_file(path, force_small=True)["status"], "FAIL")

    def test_legacy_angle_arrays_and_window_level_fallback(self):
        ow = self.scene["observation_windows"][0]
        ow["agile_data"] = {key: [0, 1, 2, 3, 4] for key in ("roll", "pitch", "yaw")}
        for tw in ow["time_windows"]:
            tw.pop("agile_data")
        self.check_issue(self.audit(), "legacy_attitude", "WARN")

    def test_invalid_internal_id_and_negative_resource(self):
        self.scene["scenario_id"] = ["invalid"]
        self.scene["satellites"][0]["satellite_specs"]["max_data_storage_GB"] = -1
        result = self.audit()
        self.check_issue(result, "identifier", "FAIL")
        self.check_issue(result, "numeric", "FAIL")

    def test_empty_directory_is_not_success(self):
        with self.assertRaises(manifest.AuditError):
            manifest.build_manifest([self.archive], self.out)
        self.assertFalse(self.out.exists())

    def test_cli_exit_status_and_required_arguments(self):
        import contextlib
        import io
        self.write()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(manifest.main(["--scenario-dir", str(self.archive), "--out-dir", str(self.out)]), 0)
        self.scene["metadata"]["duration"] = -1
        self.write()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(manifest.main(["--scenario-dir", str(self.archive), "--out-dir", str(self.root / "failed-reports")]), 1)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            manifest.main([])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
