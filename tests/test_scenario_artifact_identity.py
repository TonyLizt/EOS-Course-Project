"""Byte identity regressions; Git writes are confined to disposable repositories."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from eos_system.scenario_artifacts import SCHEMA_VERSION, load_index, verify_index


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/registry/scenario_artifacts.v1.json"
CORE = "eos_system/scenario_artifacts.py"
SNAPSHOT = "docs/phase2/evidence/r1_02/d0d9325/database_current_v03.crlf.snapshot.md"
ORIGINAL = "docs/phase2/database_current_v03.md"
BASELINE = "d0d9325759f078ef13f41cc9eee74c5e7733758a"
HISTORICAL_SHA = "4b30f69358c610308e23817b35821a79879a18fbfb2388d21202427621408285"


class ArtifactEvidenceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.index = load_index(INDEX)
        self.historical = next(n for n in self.index["evidence"] if n["id"] == "database-current")

    def test_core_source_is_indexed_lf_bytes(self):
        data = (ROOT / CORE).read_bytes()
        self.assertNotIn(b"\r", data)
        identity = next(n for n in self.index["evidence"] if n["id"] == "r1-02-checker-source")
        self.assertEqual(hashlib.sha256(data).hexdigest(), identity["sha256"])
        self.assertEqual(len(data), identity["size_bytes"])
        self.assertEqual(identity["sha256"], self.index["review_tool_identity"]["sha256"])

    def test_historical_snapshot_has_pinned_identity_and_version(self):
        node = self.historical
        self.assertEqual(node["location"], {"kind": "repo_relative", "path": SNAPSHOT,
                                           "original_path": ORIGINAL, "normalized_path": SNAPSHOT})
        self.assertEqual(node["historical_source"]["git_commit"], BASELINE)
        self.assertEqual(node["historical_source"]["path"], ORIGINAL)
        self.assertEqual(node["historical_source"]["checkout_eol"], "CRLF")
        self.assertEqual(node["evidence_scope"], "historical_baseline_document_not_current_database_schema")
        data = (ROOT / SNAPSHOT).read_bytes()
        self.assertEqual(node["sha256"], HISTORICAL_SHA)
        self.assertEqual(node["size_bytes"], 6091)
        self.assertEqual(hashlib.sha256(data).hexdigest(), HISTORICAL_SHA)
        self.assertEqual(len(data), 6091)
        lf = data.replace(b"\r\n", b"\n")
        self.assertEqual(len(lf), node["historical_source"]["git_blob_size_bytes"])
        self.assertEqual(hashlib.sha256(lf).hexdigest(), node["historical_source"]["git_blob_sha256"])
        self.assertEqual(lf.replace(b"\n", b"\r\n"), data)

    def git(self, root, *args, data=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.run(["git", "-C", str(root), *args], input=data, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout

    def test_git_store_and_checkout_preserve_bytes_with_both_autocrlf_modes(self):
        # Exercise actual clean/smudge conversion without staging or committing.
        # Both Windows and WSL run this same test against native Git.
        with tempfile.TemporaryDirectory(prefix="r1-identity-git-") as folder:
            root = Path(folder)
            self.git(root, "init", "--quiet")
            (root / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
            for mode in ("true", "false"):
                for path in (CORE, SNAPSHOT):
                    with self.subTest(autocrlf=mode, path=path):
                        data = (ROOT / path).read_bytes()
                        args = ("-c", "core.autocrlf=" + mode, "-c", "core.safecrlf=false")
                        oid = self.git(root, *args, "hash-object", "-w", "--path=" + path,
                                       "--stdin", data=data).decode().strip()
                        self.assertEqual(self.git(root, "cat-file", "blob", oid), data)
                        checkout = self.git(root, *args, "cat-file", "--filters", "--path=" + path, oid)
                        self.assertEqual(checkout, data)
                        self.assertEqual(hashlib.sha256(checkout).digest(), hashlib.sha256(data).digest())

    def test_existing_lfs_rules_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="r1-identity-attrs-") as folder:
            root = Path(folder)
            self.git(root, "init", "--quiet")
            (root / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
            cases = {
                "experiments/scenarios/x/scene.json": {"filter": "lfs", "diff": "lfs", "merge": "lfs", "text": "unset", "eol": "unspecified"},
                "experiments/scenarios/x/provenance/scene.json": {"filter": "unset", "diff": "set", "merge": "set", "text": "set", "eol": "unspecified"},
                CORE: {"filter": "unspecified", "text": "set", "eol": "lf"},
                SNAPSHOT: {"filter": "unspecified", "text": "unset", "eol": "unspecified"},
            }
            for path, expected in cases.items():
                with self.subTest(path=path):
                    output = self.git(root, "check-attr", *expected, "--", path).decode()
                    actual = {line.split(": ", 2)[1]: line.split(": ", 2)[2] for line in output.splitlines()}
                    self.assertEqual(actual, expected)

    def historical_fixture(self, root, data=None):
        snapshot = root / SNAPSHOT
        snapshot.parent.mkdir(parents=True)
        snapshot.write_bytes((ROOT / SNAPSHOT).read_bytes() if data is None else data)
        index = {"schema_version": SCHEMA_VERSION, "raw_inputs": [], "scenario_artifacts": [],
                 "evidence": [deepcopy(self.historical)], "frozen_candidate_sha256": [], "lineage_edges": []}
        return snapshot, index

    def require_consistent_stat_timestamps(self):
        # The existing checker compares stat/fstat ctime. Some Windows Python
        # runtimes report creation time in one and modification time in the other.
        # Keep that production guard intact and report this host limitation.
        with tempfile.TemporaryDirectory(prefix="r1-identity-stat-") as folder:
            probe = Path(folder) / "probe"
            probe.write_bytes(b"timestamp probe")
            stamp = probe.stat()
            os.utime(probe, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000_000))
            with probe.open("rb") as stream:
                if probe.stat().st_ctime_ns != os.fstat(stream.fileno()).st_ctime_ns:
                    self.skipTest("host stat/fstat ctime disagree; verifier integration requires project WSL Python")

    def test_current_document_update_does_not_replace_historical_identity(self):
        self.require_consistent_stat_timestamps()
        with tempfile.TemporaryDirectory(prefix="r1-identity-version-") as folder:
            root = Path(folder)
            snapshot, index = self.historical_fixture(root)
            current = root / ORIGINAL
            for version in (b"new main schema\n", b"later main schema\r\n"):
                current.write_bytes(version)
                self.assertEqual(verify_index(index, repo_root=root)["status"], "PASS")
            current.unlink()
            self.assertEqual(verify_index(index, repo_root=root)["status"], "PASS")
        # A separate immutable fixture avoids NTFS delete/recreate timestamp reuse.
        # Repointing the historical identity to a newer same-named document must fail.
        with tempfile.TemporaryDirectory(prefix="r1-identity-repoint-") as folder:
            root = Path(folder)
            _, index = self.historical_fixture(root)
            current = root / ORIGINAL
            current.write_bytes(b"new main schema\n")
            index["evidence"][0]["location"]["path"] = ORIGINAL
            result = verify_index(index, repo_root=root)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["checks"][0]["code"], "FILE_IDENTITY_MISMATCH")

    def test_historical_byte_change_including_eol_is_a_failure(self):
        self.require_consistent_stat_timestamps()
        data = (ROOT / SNAPSHOT).read_bytes()
        for changed in (data.replace(b"\r\n", b"\n"), b"!" + data[1:], data[:-1]):
            with self.subTest(size=len(changed)), tempfile.TemporaryDirectory(prefix="r1-identity-mutation-") as folder:
                root = Path(folder)
                _, index = self.historical_fixture(root, data=changed)
                result = verify_index(index, repo_root=root)
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(result["checks"][0]["code"], "FILE_IDENTITY_MISMATCH")


if __name__ == "__main__":
    unittest.main()
