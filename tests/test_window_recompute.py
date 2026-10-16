"""Synthetic E2 contract tests; no legacy scenes, JVM, generators or resampling."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from core.models import AgileData, NonAgileData, TimeWindow, ObservationWindow, CommunicationWindow
from scripts import recompute_scenario_windows as tool


def fixture():
    return {
        "scenario_id": "Scenario_S1", "scenario_type": "mixed", "future_config": {"preserve": [1, None, "原值"]},
        "metadata": {"name": "frozen", "creation_time": "2025-11-18T20:00:00+08:00",
                     "duration": 120, "time_step": 10, "description": "unchanged", "extra": {"seed": 7}},
        "satellites": [{"id": "s1", "orbital_type": "LEO",
                        "orbital_params": {"semi_major_axis_km": 7000, "eccentricity": 0.001,
                            "inclination_deg": 98, "argument_of_perigee_deg": 10,
                            "right_ascension_of_ascending_node_deg": 20, "mean_anomaly_deg": 30,
                            "epoch": "18 Nov 2025 12:00:00.000", "future_orbit_field": "keep"},
                        "satellite_specs": {"max_data_storage_GB": 11, "max_power_W": 87, "future": 23},
                        "observation_capability": {"sensors": [{"sensor_id": "s1_sensor", "resolution": "high",
                            "sensor_mode": "sar", "field_of_view_deg": 17, "observation_swath_width_km": 24,
                            "data_rate_Mbps": 3, "power_consumption_W": 22, "min_elevation_angle_deg": 4,
                            "unknown_sensor_setting": {"a": 42}}]},
                        "maneuverability_capability": {"maneuverability_type": "agile", "slew_rate_deg_per_s": 0.5,
                            "max_pitch_angle_deg": 23, "max_yaw_angle_deg": 24, "max_roll_angle_deg": 25,
                            "stabilization_time_s": 13},
                        "communication_capability": {"antennas": [{"antenna_id": "a1", "data_rate_Mbps": 7}]}}],
        "missions": [{"id": name, "target_location": {"latitude": 20 + i, "longitude": 100 + i, "altitude_km": 0.1},
                      "priority": 9 - i, "observation_requirement": {"duration_s": 10, "future_requirement": i},
                      "future_task_setting": [name]} for i, name in enumerate(("m1", "m2"))],
        "observation_windows": [{"old": "replaced, not shifted"}],
        "communication_windows": [{"old": "replaced"}],
    }


def fake_calculator(**kwargs):
    if kwargs["ensure_each_mission_has_window"] is not False or kwargs["mission_info"] is not None:
        raise AssertionError("resampling must be impossible")
    start = kwargs["start_time"]
    def window(offset):
        return TimeWindow(start + timedelta(seconds=offset), start + timedelta(seconds=offset + 20),
                          AgileData([1, 2], [3, 4], [5, 6]), NonAgileData(2, 4, 6), 1)
    obs = [ObservationWindow("s1", "s1_sensor", "m1", [window(0), window(40)])]
    comm = [CommunicationWindow("s1", "g1", [TimeWindow(start, start + timedelta(seconds=20), orbit_number=1)])] \
        if kwargs["ground_stations"] else []
    return obs, comm, kwargs["missions"]


class RecomputeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="epoch-e2-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "legacy" / "frozen.json"
        self.target = self.root / "fixed" / "s1_epoch_fixed_v1.json"
        self.source.parent.mkdir()
        self.scene = fixture()
        self.write_source()
        self.original = self.source.read_bytes()

    def write_source(self):
        self.source.write_text(json.dumps(self.scene, ensure_ascii=False, indent=2), encoding="utf-8")

    def run_tool(self, **kwargs):
        return tool.recompute_file(self.source, self.target, calculator=fake_calculator, **kwargs)

    def read_result(self):
        return json.loads(self.target.read_bytes())

    def assert_no_publication(self):
        self.assertFalse(self.target.exists())
        self.assertFalse(tool.sidecar_path(self.target).exists())
        self.assertEqual(list(self.root.rglob(".epoch-*.tmp")), [])

    def test_static_fields_including_unknown_fields_identical(self):
        self.run_tool()
        self.assertEqual(tool.static_data(self.scene), tool.static_data(self.read_result()))
        self.assertEqual(self.read_result()["satellites"][0]["orbital_params"]["epoch"], "18 Nov 2025 12:00:00.000")

    def test_sensor_resources_coordinates_priority_duration_preserved(self):
        self.run_tool()
        result = self.read_result()
        self.assertEqual(result["satellites"], self.scene["satellites"])
        self.assertEqual(result["missions"], self.scene["missions"])

    def test_zero_window_task_preserved_and_denominator_correct(self):
        evidence = self.run_tool()
        self.assertEqual([m["id"] for m in self.read_result()["missions"]], ["m1", "m2"])
        self.assertEqual(evidence["structure_validation"]["mission_count"], 2)
        self.assertEqual(evidence["structure_validation"]["missions_with_windows"], 1)

    def test_multiple_windows_and_attitudes_replaced(self):
        self.run_tool()
        windows = self.read_result()["observation_windows"][0]["time_windows"]
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0]["agile_data"]["pitch_angles"], [1, 2])
        self.assertEqual(windows[0]["non_agile_data"]["roll_angle"], 6)
        self.assertEqual(windows[0]["orbit_number"], 1)

    def test_missing_ground_stations_no_fabricated_communication(self):
        evidence = self.run_tool()
        self.assertEqual(self.read_result()["communication_windows"], [])
        self.assertNotIn("ground_stations", self.read_result())
        self.assertEqual(evidence["ground_station_status"], "no_ground_station_configured")

    def test_ground_stations_preserved_communication_recomputed(self):
        self.scene["ground_stations"] = [{"id": "g1", "location": {"latitude": 35, "longitude": 110, "altitude_km": 1},
                                          "future_station_setting": {"frequency": 8}}]
        self.write_source()
        evidence = self.run_tool()
        self.assertEqual(self.read_result()["ground_stations"], self.scene["ground_stations"])
        self.assertEqual(len(self.read_result()["communication_windows"]), 1)
        self.assertEqual(evidence["ground_station_status"], "configured")

    def test_projection_preserves_configs_no_defaults(self):
        def inspect(**kwargs):
            sat = kwargs["satellites"][0]
            self.assertEqual(sat.maneuverability_capability.max_yaw_angle, 24)
            self.assertEqual(sat.observation_capability.sensors[0].field_of_view_deg, 17)
            self.assertEqual(sat.satellite_specs.max_power_W, 87)
            self.assertEqual(kwargs["step_seconds"], 10)
            self.assertEqual(kwargs["start_time"].hour, 12)
            return fake_calculator(**kwargs)
        tool.recompute_file(self.source, self.target, calculator=inspect)

    def test_no_resampling_or_generator_import(self):
        with patch("utils.visibility.generate_random_coordinates", side_effect=AssertionError("resampling")):
            self.run_tool()
        import sys
        self.assertNotIn("main_generate", sys.modules)

    def test_invalid_epoch_fails_before_calculator(self):
        self.scene["satellites"][0]["orbital_params"]["epoch"] = "bad-date"
        self.write_source()
        with self.assertRaisesRegex(ValueError, "satellite_id='s1'"):
            tool.recompute_file(self.source, self.target, calculator=lambda **kwargs: self.fail("calculator called"))
        self.assert_no_publication()

    def test_readonly_input_byte_and_metadata_unchanged(self):
        self.source.chmod(0o444)
        before = self.source.stat()
        try:
            self.run_tool()
            self.assertEqual(self.source.read_bytes(), self.original)
            after = self.source.stat()
            self.assertEqual((before.st_mtime_ns, before.st_size, before.st_mode),
                             (after.st_mtime_ns, after.st_size, after.st_mode))
        finally:
            self.source.chmod(0o644)

    def test_output_cannot_equal_input(self):
        with self.assertRaisesRegex(ValueError, "different from input"):
            tool.recompute_file(self.source, self.source, calculator=fake_calculator)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_existing_output_never_overwritten(self):
        self.target.parent.mkdir()
        self.target.write_bytes(b"existing")
        with self.assertRaises(ValueError):
            self.run_tool()
        self.assertEqual(self.target.read_bytes(), b"existing")

    def test_existing_sidecar_never_overwritten(self):
        sidecar = tool.sidecar_path(self.target)
        sidecar.parent.mkdir(parents=True)
        sidecar.write_bytes(b"existing evidence")
        with self.assertRaisesRegex(ValueError, "provenance output already exists"):
            self.run_tool()
        self.assertFalse(self.target.exists())
        self.assertEqual(sidecar.read_bytes(), b"existing evidence")

    def test_calculation_exception_no_publication(self):
        def fail(**kwargs):
            raise RuntimeError("interrupted calculation")
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            tool.recompute_file(self.source, self.target, calculator=fail)
        self.assert_no_publication()

    def test_second_publish_failure_rolls_back_owned_scene(self):
        original_publish = tool._publish_no_replace
        def fail_evidence(temporary, target):
            if target == tool.sidecar_path(self.target):
                raise OSError("evidence failure")
            original_publish(temporary, target)
        with patch.object(tool, "_publish_no_replace", side_effect=fail_evidence), self.assertRaises(OSError):
            self.run_tool()
        self.assert_no_publication()

    def test_atomic_no_replace_race_preserves_competing_file(self):
        original_publish = tool._publish_no_replace
        def race(temporary, target):
            if target == self.target:
                target.write_bytes(b"competing producer")
            original_publish(temporary, target)
        with patch.object(tool, "_publish_no_replace", side_effect=race), self.assertRaises(FileExistsError):
            self.run_tool()
        self.assertEqual(self.target.read_bytes(), b"competing producer")
        self.assertFalse(tool.sidecar_path(self.target).exists())

    def test_hashes_and_source_provenance_computed_from_bytes(self):
        evidence = self.run_tool()
        self.assertEqual(evidence["parent_scenario_sha256"], hashlib.sha256(self.original).hexdigest())
        self.assertEqual(evidence["scenario_sha256"], hashlib.sha256(self.target.read_bytes()).hexdigest())
        self.assertEqual(evidence["static_data_sha256"], evidence["legacy_static_sha256"])
        self.assertEqual(evidence["static_data_sha256"], tool.digest(tool.static_data(self.scene)))
        self.assertEqual(evidence["source_scenario_id"], "Scenario_S1")
        self.assertNotEqual(evidence["registry_id"], "Scenario_S1")
        self.assertEqual(evidence["source_files_sha256"]["utils/time_parsing.py"], tool.file_sha256(tool.ROOT / "utils/time_parsing.py"))
        self.assertEqual(json.loads(tool.sidecar_path(self.target).read_bytes()), evidence)

    def test_completion_is_not_physics_or_scheduling_acceptance(self):
        evidence = self.run_tool()
        self.assertEqual(evidence["scenario_physics_version"], "epoch_fixed_v1")
        self.assertEqual(evidence["epoch_parser_version"], "epoch_parser_v1")
        self.assertEqual(evidence["completion_status"], "complete")
        self.assertEqual(evidence["publication_status"], "candidate_only")
        self.assertFalse(evidence["formal_release_eligible"])
        self.assertEqual(evidence["physical_validation"]["status"], "NOT_RUN")
        self.assertEqual(evidence["scheduling_validation"]["status"], "NOT_RUN")
        self.assertIsNone(evidence["propagation_version"])
        self.assertEqual(evidence["calculator_kind"], "injected_test_calculator")

    def test_deterministic_candidate_bytes_and_static_hash(self):
        first = self.run_tool()
        first_bytes = self.target.read_bytes()
        other = self.root / "fixed2" / "another_epoch_fixed_v1.json"
        second = tool.recompute_file(self.source, other, calculator=fake_calculator)
        self.assertEqual(first_bytes, other.read_bytes())
        for key in ("scenario_sha256", "static_data_sha256", "parent_scenario_sha256"):
            self.assertEqual(first[key], second[key])

    def test_custom_sensor_is_rejected_without_renaming(self):
        self.scene["satellites"][0]["observation_capability"]["sensors"][0]["sensor_id"] = "custom_sensor"
        self.write_source()
        with self.assertRaisesRegex(ValueError, "unsupported custom/multiple sensors"):
            self.run_tool()
        self.assert_no_publication()

    def test_multi_sensor_is_rejected_before_calculation(self):
        sensors = self.scene["satellites"][0]["observation_capability"]["sensors"]
        sensors.append(dict(sensors[0], sensor_id="another_sensor"))
        self.write_source()
        with self.assertRaisesRegex(ValueError, "public API proposal required"):
            self.run_tool()
        self.assert_no_publication()

    def test_calculator_static_mutation_fails_with_field_diff(self):
        def mutate(**kwargs):
            kwargs["missions"][0].target_location.latitude = -25
            return fake_calculator(**kwargs)
        with self.assertRaisesRegex(ValueError, "target_location.latitude"):
            tool.recompute_file(self.source, self.target, calculator=mutate)
        self.assert_no_publication()
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_calculator_replaced_missions_rejected(self):
        def remove(**kwargs):
            obs, comm, missions = fake_calculator(**kwargs)
            return obs, comm, missions[:1]
        with self.assertRaisesRegex(ValueError, "replaced missions"):
            tool.recompute_file(self.source, self.target, calculator=remove)
        self.assert_no_publication()

    def test_static_diff_function_includes_unknown_fields(self):
        changed = deepcopy(self.scene)
        changed["future_config"]["preserve"][2] = "changed"
        with self.assertRaisesRegex(ValueError, r"future_config.preserve\[2\]"):
            tool.assert_same(tool.static_data(self.scene), tool.static_data(changed), "static")

    def test_invalid_recomputed_reference_rejected(self):
        def invalid(**kwargs):
            obs, comm, missions = fake_calculator(**kwargs)
            obs[0].sensor_id = "fabricated_sensor"
            return obs, comm, missions
        with self.assertRaisesRegex(ValueError, "unknown sensor"):
            tool.recompute_file(self.source, self.target, calculator=invalid)
        self.assert_no_publication()

    def test_communication_without_station_rejected(self):
        def invalid(**kwargs):
            obs, comm, missions = fake_calculator(**kwargs)
            return obs, [CommunicationWindow("s1", "missing", [])], missions
        with self.assertRaisesRegex(ValueError, "without ground stations"):
            tool.recompute_file(self.source, self.target, calculator=invalid)
        self.assert_no_publication()

    def test_source_changed_during_calculation_rejected(self):
        def changed(**kwargs):
            self.source.write_bytes(self.original + b"\n")
            return fake_calculator(**kwargs)
        with self.assertRaisesRegex(ValueError, "source changed"):
            tool.recompute_file(self.source, self.target, calculator=changed)
        self.assert_no_publication()

    def test_frozen_sha_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "frozen input hash"):
            self.run_tool(expected_source_sha256="0" * 64)
        self.assert_no_publication()

    def test_size_limit(self):
        with self.assertRaisesRegex(ValueError, "memory safety limit"):
            self.run_tool(max_input_bytes=2)
        self.assert_no_publication()

    def test_unknown_scanning_override_rejected(self):
        self.scene["metadata"]["extra"]["visibility_settings"] = {"new_physics": 1}
        self.write_source()
        with self.assertRaisesRegex(ValueError, "unsupported metadata.extra.visibility_settings"):
            self.run_tool()

    def test_existing_scanning_settings_forwarded(self):
        self.scene["metadata"]["extra"]["visibility_settings"] = {"min_elevation_deg": 7, "coarse_step_min": 30}
        self.write_source()
        def inspect(**kwargs):
            self.assertEqual(kwargs["min_elevation_deg"], 7)
            self.assertEqual(kwargs["coarse_step_min"], 30)
            return fake_calculator(**kwargs)
        tool.recompute_file(self.source, self.target, calculator=inspect)

    def test_missing_required_orbit_field_rejected_without_defaults(self):
        del self.scene["satellites"][0]["orbital_params"]["mean_anomaly_deg"]
        self.write_source()
        with self.assertRaises((KeyError, AttributeError)):
            self.run_tool()
        self.assert_no_publication()

    def test_duplicate_json_keys_rejected(self):
        self.source.write_text('{"scenario_id":"a","scenario_id":"b"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            self.run_tool()
        self.assert_no_publication()

    def test_protected_paths_rejected_before_open(self):
        for name in ("input", "output", "experiments/scenarios", ".git"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "protected path"):
                tool.recompute_file(self.source, tool.ROOT / name / "new_epoch_fixed_v1.json", calculator=fake_calculator)

    def test_independent_output_directory_required(self):
        with self.assertRaisesRegex(ValueError, "independent output directory"):
            tool.recompute_file(self.source, self.source.parent / "new_epoch_fixed_v1.json", calculator=fake_calculator)

    def test_output_name_must_distinguish_physics(self):
        with self.assertRaisesRegex(ValueError, "output name"):
            tool.recompute_file(self.source, self.target.with_name("plain.json"), calculator=fake_calculator)

    def test_missing_attitudes_rejected(self):
        def invalid(**kwargs):
            obs, comm, missions = fake_calculator(**kwargs)
            obs[0].time_window[0].agile_data = None
            return obs, comm, missions
        with self.assertRaisesRegex(ValueError, "must include agile"):
            tool.recompute_file(self.source, self.target, calculator=invalid)
        self.assert_no_publication()

    def test_missing_orbit_number_rejected(self):
        def invalid(**kwargs):
            obs, comm, missions = fake_calculator(**kwargs)
            obs[0].time_window[0].orbit_number = None
            return obs, comm, missions
        with self.assertRaisesRegex(ValueError, "orbit_number"):
            tool.recompute_file(self.source, self.target, calculator=invalid)
        self.assert_no_publication()

    def test_out_of_range_coordinates_rejected(self):
        self.scene["missions"][0]["target_location"]["latitude"] = 95
        self.write_source()
        with self.assertRaisesRegex(ValueError, "out of range"):
            self.run_tool()
        self.assert_no_publication()

    def test_broken_output_symlink_rejected(self):
        self.target.parent.mkdir()
        self.target.symlink_to(self.root / "nonexistent.json")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.run_tool()
        self.assertTrue(self.target.is_symlink())
        self.assertFalse((self.root / "nonexistent.json").exists())

    def test_completion_timestamp_created_after_scenario_hash_verification(self):
        stage = tool._stage
        def inspect(path, payload):
            if path == tool.sidecar_path(self.target):
                self.assertTrue(self.target.is_file())
                evidence = json.loads(payload)
                self.assertEqual(evidence["scenario_sha256"], tool.file_sha256(self.target))
                self.assertIn("completed_at", evidence)
            return stage(path, payload)
        with patch.object(tool, "_stage", side_effect=inspect):
            self.run_tool()

    def test_sidecar_staging_failure_removes_published_candidate(self):
        stage = tool._stage
        def fail(path, payload):
            if path == tool.sidecar_path(self.target):
                raise OSError("sidecar staging failed")
            return stage(path, payload)
        with patch.object(tool, "_stage", side_effect=fail), self.assertRaises(OSError):
            self.run_tool()
        self.assert_no_publication()

    def test_uncommitted_tool_does_not_claim_base_commit_as_tool_version(self):
        from subprocess import CompletedProcess
        base = "a" * 40
        with patch.object(tool.subprocess, "check_output", return_value=base):
            # Untracked or modified production sources cannot claim HEAD.
            for return_codes in ([1], [0, 1]):
                with self.subTest(return_codes=return_codes), patch.object(tool.subprocess, "run", side_effect=[
                        CompletedProcess([], code) for code in return_codes]):
                    info = tool.build_info()
                    self.assertEqual(info["base_git_sha"], base)
                    self.assertIsNone(info["recompute_tool_git_sha"])
                    self.assertEqual(info["code_identity_kind"], "working_tree_files_plus_base_commit")


@unittest.skipUnless(os.environ.get("EOS_RUN_OREKIT_TESTS") == "1", "opt-in: EOS_RUN_OREKIT_TESTS=1")
class OrekitEpochIntegrationTests(unittest.TestCase):
    def test_equivalent_epochs_pv_windows_attitudes_and_small_bundle(self):
        """One synthetic orbit, two fixed targets, 600 s; never open real scenes."""
        from utils import visibility as visibility
        from utils.time_parsing import parse_orbit_epoch
        # Stage the existing identical data in Linux temp storage. Java's tiny
        # ZIP reads through WSL DrvFS are slow; no download/environment install.
        data_directory = tempfile.TemporaryDirectory(prefix="epoch-orekit-data-")
        self.addCleanup(data_directory.cleanup)
        data_zip = Path(data_directory.name) / "orekit-data.zip"
        shutil.copyfile(tool.ROOT / "utils" / "orekit-data.zip", data_zip)
        self.assertEqual(tool.file_sha256(data_zip), tool.file_sha256(tool.ROOT / "utils" / "orekit-data.zip"))
        visibility.ensure_orekit(str(data_zip))
        from orekit_jpype.pyhelpers import datetime_to_absolutedate
        from org.orekit.propagation.analytical import KeplerianPropagator
        from org.orekit.orbits import KeplerianOrbit
        from java.lang import System

        scene = fixture()
        scene["metadata"].update(duration=600, time_step=10)
        op = scene["satellites"][0]["orbital_params"]
        op.update(semi_major_axis_km=7000, eccentricity=0.001, inclination_deg=28,
                  argument_of_perigee_deg=0, right_ascension_of_ascending_node_deg=0, mean_anomaly_deg=0)
        for axis in ("yaw", "pitch", "roll"):
            scene["satellites"][0]["maneuverability_capability"][f"max_{axis}_angle_deg"] = 180
        for mission, lat, lon in zip(scene["missions"], (5, 8), (125, 135)):
            mission["target_location"].update(latitude=lat, longitude=lon, altitude_km=0)
        formats = ("18 Nov 2025 12:00:00.000", "2025-11-18T12:00:00Z", "2025-11-18T20:00:00+08:00")
        ctx = visibility._CONTEXT
        results, pv_results = [], []
        for value in formats:
            op["epoch"] = value
            epoch = parse_orbit_epoch(value)
            orbit = visibility._build_keplerian_orbit(ctx, 7000000, 0.001, 28, 0, 0, 0, epoch)
            propagator = KeplerianPropagator(orbit)
            states = {}
            for frame_name, frame in (("EME2000", ctx.inertial), ("ITRF/IERS2010/simpleEOP", ctx.itrf)):
                for seconds in (0, 300, 600):
                    date = datetime_to_absolutedate(epoch + timedelta(seconds=seconds))
                    pv = propagator.propagate(date).getPVCoordinates(frame)
                    def vector(v):
                        return [float(v.getX()), float(v.getY()), float(v.getZ())]
                    states[(frame_name, seconds)] = (vector(pv.getPosition()), vector(pv.getVelocity()))
            pv_results.append(states)
            result, _ = tool.recompute_data(scene, data_path=str(data_zip))
            results.append({key: result[key] for key in tool.DYNAMIC_FIELDS})
        position_error = max(math.dist(pv_results[0][key][0], other[key][0])
                             for other in pv_results[1:] for key in pv_results[0])
        velocity_error = max(math.dist(pv_results[0][key][1], other[key][1])
                             for other in pv_results[1:] for key in pv_results[0])
        self.assertLessEqual(position_error, 1e-6)
        self.assertLessEqual(velocity_error, 1e-9)
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])
        windows = [tw for ow in results[0]["observation_windows"] for tw in ow["time_windows"]]
        samples = sum(len(tw["agile_data"]["pitch_angles"]) for tw in windows)
        self.assertGreater(len(windows), 0, "avoid vacuous window equivalence")
        self.assertGreater(samples, 0, "avoid vacuous attitude equivalence")
        # Exercise the real E2 adapter, hashes and no-overwrite publication too.
        with tempfile.TemporaryDirectory(prefix="epoch-orekit-test-") as directory:
            source = Path(directory) / "legacy" / "synthetic.json"
            target = Path(directory) / "candidate" / "synthetic_epoch_fixed_v1.json"
            source.parent.mkdir()
            op["epoch"] = formats[0]
            source.write_bytes(tool.canonical_bytes(scene))
            source_sha = tool.file_sha256(source)
            evidence = tool.recompute_file(source, target, expected_source_sha256=source_sha,
                                           data_path=str(data_zip))
            self.assertEqual(tool.file_sha256(source), source_sha)
            self.assertEqual(evidence["scenario_sha256"], tool.file_sha256(target))
            self.assertEqual(evidence["static_data_sha256"], evidence["legacy_static_sha256"])
            self.assertEqual(evidence["calculator_kind"], "orekit")
            self.assertIsNotNone(evidence["propagation_version"])
            report = {"status": "PASS", "scope": "equivalent epoch formats and synthetic E2 bundle only",
                      "test_source": "tests/test_window_recompute.py::OrekitEpochIntegrationTests",
                      "python": tool.sys.version.split()[0], "orekit_jpype": importlib.metadata.version("orekit_jpype"),
                      "orekit_java": (str(KeplerianOrbit.class_.getPackage().getImplementationVersion())
                                      if KeplerianOrbit.class_.getPackage().getImplementationVersion() else None),
                      "java": str(System.getProperty("java.version")),
                      "utc_start": "2025-11-18T12:00:00+00:00", "duration_s": 600, "fine_step_s": 10,
                      "coarse_step_s": 60, "min_elevation_deg": 5, "attitude_limits_deg": 180,
                      "frames": ["EME2000", "ITRF / IERS 2010 / simpleEOP=True", "WGS84"],
                      "pv_offsets_s": [0, 300, 600], "formats": list(formats),
                      "fixed_targets_lat_lon": [[5, 125], [8, 135]],
                      "position_tolerance_m": 1e-6, "velocity_tolerance_m_s": 1e-9,
                      "window_tolerance_s": 0, "attitude_tolerance_deg": 0,
                      "max_position_error_m": position_error, "max_velocity_error_m_s": velocity_error,
                      "max_window_error_s": 0, "max_attitude_error_deg": 0,
                      "observation_segments": len(windows), "attitude_samples": samples,
                      "source_sha256": source_sha, "candidate_sha256": evidence["scenario_sha256"],
                      "static_sha256": evidence["static_data_sha256"],
                      "orekit_data_sha256": evidence["orekit_data_sha256"],
                      "completed_at": tool.datetime.now(tool.timezone.utc).isoformat(),
                      "full_E3_E4_acceptance": "NOT_RUN"}
            print("OREKIT_EPOCH_EVIDENCE=" + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    unittest.main()
