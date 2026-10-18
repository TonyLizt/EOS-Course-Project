"""Duplicate CLI startup must explain the live lock without modifying it."""
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from eos_system.__main__ import controller_is_running, main


class CliStartupTests(unittest.TestCase):
    def test_absent_lock_is_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / 'not-created' / 'controller.lock'
            self.assertFalse(controller_is_running(lock))
            self.assertFalse(lock.parent.exists())

    def test_existing_unlocked_file_does_not_block_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / 'controller.lock'
            lock.write_text('retained')
            with patch.dict(os.environ, {'EOS_RUNTIME_DIR': directory}), \
                    patch('eos_system.__main__.uvicorn.run') as run:
                self.assertEqual(main(), 0)
                run.assert_called_once()
            self.assertEqual(lock.read_text(), 'retained')

    def test_duplicate_cli_does_not_start_api_or_release_owner_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / 'controller.lock'
            lock.write_text('owner')
            with lock.open('r') as owner:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = subprocess.run(
                    [sys.executable, '-B', '-m', 'eos_system'],
                    cwd=Path(__file__).resolve().parents[1],
                    env={**os.environ, 'EOS_RUNTIME_DIR': directory},
                    capture_output=True, text=True, timeout=15,
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('无需重复启动', result.stderr)
                self.assertIn('http://127.0.0.1:8765/', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertNotIn('Started server process', result.stderr)
                self.assertFalse((Path(directory) / 'results.sqlite3').exists())
                self.assertTrue(controller_is_running(lock))
                self.assertEqual(lock.read_text(), 'owner')
            self.assertFalse(controller_is_running(lock))


if __name__ == '__main__':
    unittest.main()
