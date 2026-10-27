"""Offline handoff regressions. No Solver, Controller, Verifier or Builder calls."""
import ast
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'scripts/hmt_scene_handoff/cli.py'
spec = importlib.util.spec_from_file_location('handoff_cli', TOOL)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
DATA = ROOT / 'data/scenarios/hmt-web-10-30-v1'


class HandoffTests(unittest.TestCase):
    def test_actual_four_bundles_bytes_and_counts(self):
        self.assertEqual(len(tool.verify_bytes(DATA)['scenarios']), 4)

    def test_mutation_fails_before_loader(self):
        with tempfile.TemporaryDirectory() as temp:
            copy = Path(temp) / 'scenes'
            shutil.copytree(DATA, copy)
            scene = copy / 'R10-show-01/scenario.json'
            scene.write_bytes(scene.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'SCENE_SHA_MISMATCH'):
                tool.verify_bytes(copy)

    def test_manifest_path_escape_rejected(self):
        with self.assertRaisesRegex(ValueError, 'OUTSIDE_ROOT'):
            tool.bounded(DATA, '../escape')

    def test_empty_runtime_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(tool.runtime_check(temp)['status'], 'RUNTIME_PREREQUISITE_REQUIRED')
            with patch.object(tool.subprocess, 'run', side_effect=AssertionError('must not load')):
                with self.assertRaisesRegex(RuntimeError, 'RUNTIME_PREREQUISITE_REQUIRED'):
                    tool.verify(temp, DATA, True)

    def test_original_generator_hashes(self):
        for path in (tool.ARTIFACTS / 'generators').glob('*.py'):
            self.assertEqual(path.stem, tool.sha(path))

    def test_only_path_assignments_relocated(self):
        replacements = {key: Path('/portable') / key for key in ('ROOT', 'OUT', 'WORK', 'DATA')}
        for path in (tool.ARTIFACTS / 'generators').glob('*.py'):
            before = ast.parse(path.read_text())
            after = tool.relocate_generator(path.read_text(), replacements)
            fns = lambda tree: [ast.dump(n) for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
            self.assertEqual(fns(before), fns(after))
            for a, b in zip(before.body, after.body):
                if ast.dump(a) != ast.dump(b):
                    self.assertIsInstance(a, ast.Assign)
                    self.assertIn(a.targets[0].id, replacements)

    def test_register_reuses_unique_existing_root(self):
        import io
        root = str(DATA.resolve())
        response = io.BytesIO(json.dumps({'items': [{'source_id': 'already', 'root_path': root}]}).encode())
        with patch.object(tool.urllib.request, 'urlopen', return_value=response) as request:
            result = tool.register('http://recipient.invalid:8920', DATA)
        self.assertEqual(result['action'], 'REUSED_EXISTING_ROOT')
        self.assertEqual(request.call_count, 1)

    def test_import_contains_no_service_or_execution(self):
        tree = ast.parse(TOOL.read_text())
        # Definitions/imports/constants only before the explicit __main__ guard.
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                self.fail('import-time call found')

    def test_original_metadata_does_not_claim_continuous_certification(self):
        for row in tool.read(DATA / 'MANIFEST.json')['scenarios']:
            self.assertEqual(row['continuous_certification'], 'NOT_CERTIFIED')
            self.assertEqual(row['structure_status'], 'WARN')

    def test_fifty_star_body_not_in_git_scope(self):
        self.assertFalse((DATA / 'R50-show-01').exists())


if __name__ == '__main__':
    unittest.main()
