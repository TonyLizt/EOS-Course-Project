"""Fresh-process import and JVM lifecycle guards, no certificate injection."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class WorkerRuntimeTests(unittest.TestCase):
    def child(self, code):
        result = subprocess.run([sys.executable, "-B", "-c", code],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_worker_import_does_not_load_algorithms_before_started_handshake(self):
        self.child("import sys; import eos_system.worker_reference; "
                   "assert 'eos_system.runner' not in sys.modules; "
                   "assert 'algorithms.factory' not in sys.modules; "
                   "assert 'orekit_jpype' not in sys.modules")

    def test_initial_jvm_start_in_background_thread_is_rejected_without_hang(self):
        self.child("""
import threading,sys
from utils.visibility import ensure_orekit
errors=[]
def run():
    try: ensure_orekit('/not-used-no-jvm-start.zip')
    except RuntimeError as e: errors.append(str(e))
t=threading.Thread(target=run);t.start();t.join(3)
assert not t.is_alive()
assert len(errors)==1 and 'OREKIT_MAIN_THREAD_INITIALIZATION_REQUIRED' in errors[0]
assert 'orekit_jpype' not in sys.modules
""")


if __name__ == "__main__":
    unittest.main()
