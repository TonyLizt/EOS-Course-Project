"""R1-02 synthetic artifacts only; never discover or open real scenarios."""
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from eos_system.scenario_artifacts import (
    SCHEMA_VERSION, STATIC_HASH_VERSION, file_sha256, inspect_scenario,
    load_index, resolve_location, verify_index,
)


class ArtifactIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r1-artifact-unit-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw.json"
        self.raw.write_text('{"S1":["LEO"]}', encoding="utf-8")
        self.scene = {"scenario_id": "Scenario_S1", "metadata": {"duration": 86400},
                      "satellites": [{"id": "S1"}], "missions": [{"id": "M1"}],
                      "unknown_static": {"x": 1}, "observation_windows": []}
        self.parent_path = self.root / "legacy.json"
        self.parent_path.write_text(json.dumps(self.scene), encoding="utf-8")
        child_scene = deepcopy(self.scene)
        child_scene["observation_windows"] = [{"proof": "derived"}]
        self.child_path = self.root / "candidate.json"
        self.child_path.write_text(json.dumps(child_scene), encoding="utf-8")

        def row(path, typ):
            info = inspect_scenario(path)
            return dict(info, id=info["registry_id"], artifact_type=typ,
                        location={"kind": "repo_relative", "path": path.name},
                        filename=path.name, static_hash_version=STATIC_HASH_VERSION,
                        lineage_group_id=None, evidence_refs=[])
        self.parent = row(self.parent_path, "legacy")
        self.child = row(self.child_path, "candidate")
        self.child.update(parent_scenario_sha256=self.parent["sha256"], publication_status="candidate_only",
                          formal_release_eligible=False, sidecar_ref="sidecar", producer_identity={"source_files_sha256": {}},
                          continuous_exposure={"status": "INCONCLUSIVE", "reason": "NO_CONTINUITY_CERTIFICATE"})
        side = {k: self.child[k] for k in ("registry_id", "parent_scenario_sha256", "static_data_sha256", "publication_status", "formal_release_eligible")}
        side.update(scenario_sha256=self.child["sha256"], completion_status="complete", source_files_sha256={}, legacy_static_sha256=self.child["static_data_sha256"])
        self.side_path = self.root / "sidecar.json"
        self.side_path.write_text(json.dumps(side), encoding="utf-8")
        self.index = {"schema_version": SCHEMA_VERSION, "raw_inputs": [{"id": "raw", "artifact_type": "raw_satellites", "location": {"kind": "repo_relative", "path": "raw.json"}, "sha256": file_sha256(self.raw), "size_bytes": self.raw.stat().st_size}],
                      "scenario_artifacts": [self.parent, self.child],
                      "frozen_candidate_sha256": [self.child["sha256"]],
                      "evidence": [{"id": "sidecar", "artifact_type": "evidence", "role": "producer_sidecar", "location": {"kind": "repo_relative", "path": "sidecar.json"}, "sha256": file_sha256(self.side_path), "size_bytes": self.side_path.stat().st_size}],
                      "lineage_edges": [{"child_id": self.child["id"], "parent_id": self.parent["id"], "relationship": "recomputed_from", "evidence_level": "DECLARED_CORROBORATED"}]}
        self.child["evidence_refs"] = ["sidecar"]

    def verify(self, index=None, roots=None):
        return verify_index(self.index if index is None else index, repo_root=self.root, evidence_roots=roots)

    def codes(self, report):
        return {c["code"] for c in report["checks"]}

    def edit_sidecar(self, **updates):
        obj = load_index(self.side_path)
        obj.update(updates)
        self.side_path.write_text(json.dumps(obj), encoding="utf-8")
        self.index["evidence"][0].update(sha256=file_sha256(self.side_path), size_bytes=self.side_path.stat().st_size)

    def test_happy_identity_checks_are_scoped_and_missing_reports_warn(self):
        result = self.verify()
        self.assertEqual(result["status"], "WARN")
        self.assertTrue({"FILE_IDENTITY", "SCENARIO_IDENTITY", "SIDECAR_BINDING", "PARENT_STATIC_LINK", "EVIDENCE_ROLE_MISSING"} <= self.codes(result))

    def test_raw_only_verified_bytes_can_pass(self):
        self.index.update(scenario_artifacts=[], frozen_candidate_sha256=[], evidence=[], lineage_edges=[])
        self.assertEqual(self.verify()["status"], "PASS")

    def test_missing_local_root_is_missing_evidence(self):
        self.index["raw_inputs"][0]["location"] = {"kind": "local_evidence", "root": "local", "path": "raw.json"}
        self.assertIn("FILE_UNAVAILABLE", self.codes(self.verify()))
        self.assertEqual(self.verify()["status"], "WARN")
        self.assertIn("FILE_IDENTITY", self.codes(self.verify(roots={"local": self.root})))

    def test_same_name_different_content_fails(self):
        self.raw.write_text('{"S2":["LEO"]}', encoding="utf-8")
        self.assertIn("FILE_IDENTITY_MISMATCH", self.codes(self.verify()))
        self.assertEqual(self.verify()["status"], "FAIL")

    def test_missing_original_file_is_warn_not_verified(self):
        self.side_path.unlink()
        result = self.verify()
        self.assertEqual(result["status"], "WARN")
        self.assertNotIn("SIDECAR_BINDING", self.codes(result))

    def test_bad_sha_is_invalid(self):
        self.parent["sha256"] = "abcd"
        self.assertEqual(self.verify()["status"], "FAIL")

    def test_bad_registry_id_even_when_sha_matches(self):
        self.child["registry_id"] = self.parent["registry_id"]
        self.assertEqual(self.verify()["status"], "FAIL")

    def test_missing_reference_target_is_invalid(self):
        self.child["evidence_refs"].append("unindexed")
        self.assertEqual(self.verify()["status"], "FAIL")

    def test_parent_sha_contradiction_fails_despite_equal_static(self):
        self.child["parent_scenario_sha256"] = "a" * 64
        self.edit_sidecar(parent_scenario_sha256="a" * 64)
        result = self.verify()
        self.assertIn("PARENT_IDENTITY_MISMATCH", self.codes(result))
        self.assertEqual(result["status"], "FAIL")

    def test_wrong_sidecar_result(self):
        self.edit_sidecar(scenario_sha256=self.parent["sha256"])
        self.assertIn("SIDECAR_BINDING_MISMATCH", self.codes(self.verify()))

    def test_sidecar_source_map_must_match(self):
        self.edit_sidecar(source_files_sha256={"tool.py": "f" * 64})
        self.assertIn("PRODUCER_IDENTITY_MISMATCH", self.codes(self.verify()))

    def test_source_static_changes_affect_static_hash(self):
        before = inspect_scenario(self.parent_path)
        self.scene["unknown_static"]["x"] = 2
        self.parent_path.write_text(json.dumps(self.scene), encoding="utf-8")
        self.assertNotEqual(before["static_data_sha256"], inspect_scenario(self.parent_path)["static_data_sha256"])

    def test_different_windows_keep_static_without_proving_origin(self):
        self.assertEqual(self.child["static_data_sha256"], self.parent["static_data_sha256"])
        self.assertNotEqual(self.child["sha256"], self.parent["sha256"])
        self.index["lineage_edges"] = []
        self.assertEqual(self.verify()["status"], "FAIL")

    def test_raw_hypothesis_stays_unverified(self):
        self.index["lineage_edges"].append({"child_id": self.parent["id"], "parent_id": "raw", "relationship": "raw_input_hypothesis", "evidence_level": "FILENAME_ONLY"})
        self.assertIn("RAW_ORIGIN_NOT_VERIFIED", self.codes(self.verify()))
        self.index["lineage_edges"][-1]["evidence_level"] = "DECLARED_CORROBORATED"
        self.assertEqual(self.verify()["status"], "FAIL")

    def test_uncertified_ml_lineage_is_not_accepted(self):
        self.child["lineage_group_id"] = "invented-family"
        self.assertEqual(self.verify()["status"], "FAIL")

    def test_frozen_cohort_rejects_added_old_candidate(self):
        self.index["frozen_candidate_sha256"] = [self.parent["sha256"]]
        self.assertEqual(self.verify()["status"], "FAIL")

    def test_candidate_cannot_be_released_or_certified(self):
        for field, value in (("publication_status", "released"), ("formal_release_eligible", True), ("continuous_exposure", {"status": "PASS"})):
            with self.subTest(field=field):
                index = deepcopy(self.index)
                index["scenario_artifacts"][1][field] = value
                self.assertEqual(self.verify(index)["status"], "FAIL")

    def test_e3_subject_sha_checked_independently_from_filename(self):
        report = self.root / "acceptance_summary.json"
        report.write_text(json.dumps({"candidate_sha256": self.parent["sha256"]}), encoding="utf-8")
        self.index["evidence"].append({"id": "summary", "artifact_type": "evidence", "role": "e3_summary", "location": {"kind": "repo_relative", "path": report.name}, "sha256": file_sha256(report), "size_bytes": report.stat().st_size, "subject_binding": {"field": "candidate_sha256", "scenario_sha256": self.child["sha256"]}})
        self.child["evidence_refs"].append("summary")
        self.assertIn("E3_SUBJECT_MISMATCH", self.codes(self.verify()))

    def test_path_traversal_absolute_and_windows_paths_rejected(self):
        for value in ("../x", "/etc/passwd", "C:/x", "folder\\x", "a/../x", "./raw.json", "a//x"):
            with self.subTest(path=value), self.assertRaises(ValueError):
                resolve_location({"kind": "repo_relative", "path": value}, self.root, {})

    def test_list_evidence_subject_selector_is_exact_and_unambiguous(self):
        p = self.root / 'summary.json'
        data = [{'case': 'current', 'scenario_sha256': self.child['sha256']}]
        p.write_text(json.dumps(data), encoding='utf-8')
        node = {'id': 'list-summary', 'artifact_type': 'evidence', 'role': 'continuous_exposure_summary',
                'location': {'kind': 'repo_relative', 'path': p.name}, 'sha256': file_sha256(p), 'size_bytes': p.stat().st_size,
                'subject_bindings': [{'selector': {'case': 'current'}, 'field': 'scenario_sha256', 'scenario_sha256': self.child['sha256']}]}
        self.index['evidence'].append(node)
        self.assertNotEqual(self.verify()['status'], 'FAIL')
        data.append(deepcopy(data[0]))
        p.write_text(json.dumps(data), encoding='utf-8')
        node.update(sha256=file_sha256(p), size_bytes=p.stat().st_size)
        self.assertEqual(self.verify()['status'], 'FAIL')

    def test_symlink_rejected_even_if_it_points_inside_root(self):
        link = self.root / "alias.json"
        try:
            link.symlink_to(self.raw)
        except OSError:
            self.skipTest("host does not permit symlinks")
        with self.assertRaises(ValueError):
            resolve_location({"kind": "repo_relative", "path": link.name}, self.root, {})

    def test_duplicate_id_and_duplicate_json_keys_fail(self):
        self.index["raw_inputs"].append(deepcopy(self.index["raw_inputs"][0]))
        self.assertEqual(self.verify()["status"], "FAIL")
        p = self.root / "duplicate.json"
        p.write_text('{"sha256":"a","sha256":"b"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            load_index(p)

    def test_invalid_identity_types_do_not_crash(self):
        index = deepcopy(self.index)
        index["lineage_edges"][0]["parent_id"] = []
        self.assertEqual(self.verify(index)["status"], "FAIL")
        self.assertEqual(self.verify({})["status"], "FAIL")

    def test_validation_preserves_index_and_all_source_bytes(self):
        old_index = deepcopy(self.index)
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.iterdir()}
        self.verify()
        self.assertEqual(self.index, old_index)
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.iterdir()})

    def test_cli_exit_and_stdout_only(self):
        from scripts.verify_scenario_artifacts import main
        path = self.root / "index.json"
        path.write_text(json.dumps(self.index), encoding="utf-8")
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--index", str(path), "--repo-root", str(self.root)]), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "WARN")
        self.raw.write_text('{}', encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--index", str(path), "--repo-root", str(self.root)]), 1)
            self.assertEqual(main(["--index", str(self.root / "missing.json")]), 2)


if __name__ == "__main__":
    unittest.main()
