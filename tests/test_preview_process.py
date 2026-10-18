"""预览核验隔离回归：超时真实回收、临时副本清理和凭据绑定。"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from eos_system.contracts import RunConfig
from eos_system.storage import now
from eos_system import planning_preview as preview
from utils.continuous_exposure import ContinuousCertificationError, ExposureStatus, plan_digest


class PreviewProcessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='eos-preview-test-')
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        scene = root / 'scene.json'
        scene.write_text('{"scenario_id":"unit","metadata":{}}')
        self.data = root / 'data.zip'
        self.data.write_bytes(b'UNIT_TEST_DATA_ONLY')
        self.config = RunConfig(run_id='unit', scenario_id='unit', scenario_path=str(scene),
            scenario_sha256=hashlib.sha256(scene.read_bytes()).hexdigest(),
            algorithm_id='completion_first', algorithm_version='baseline-1',
            execution_mode='planning_preview', created_at=now())
        self.plan = {'scenario_id': 'unit', 'assignments': [{'task_id': 'UNIT_TEST_ONLY'}],
                     'unassigned_tasks': []}
        self.paths = []
        self.env = patch.dict('os.environ', {'EOS_OREKIT_DATA': str(self.data)})
        self.env.start(); self.addCleanup(self.env.stop)

    def response(self, **kwargs):
        # 仅测试传输与绑定；此模拟证据不进入正式数据库或真实物理验收。
        request = json.loads(kwargs['input'])
        local = Path(request['data_path']); self.paths.append(local)
        self.assertNotEqual(local, self.data)
        self.assertEqual(local.read_bytes(), self.data.read_bytes())
        evidence = dict(status='SAMPLED_PREVIEW', preview_version=preview.PREVIEW_VERSION,
            run_id=self.config.run_id, scenario_sha256=self.config.scenario_sha256,
            plan_sha256=plan_digest(self.plan), completed_tasks=1,
            warning='UNIT_TEST_INJECTION_ONLY')
        return subprocess.CompletedProcess([], 0, json.dumps({'evidence': evidence}), '')

    def audit(self):
        return preview.audit_preview(self.config, self.plan, deadline=time.monotonic()+5)

    def test_timeout_reaps_real_process_then_next_preview_can_run(self):
        real_run = subprocess.run
        def slow(*args, **kwargs):
            self.paths.append(Path(json.loads(kwargs['input'])['data_path']))
            # 真正启动会挂起的子进程，验证 run 的 kill/wait 路径，不只是抛模拟异常。
            return real_run([sys.executable, '-c', 'import time; time.sleep(60)'],
                            capture_output=True, text=True, timeout=.1)
        with patch.object(preview.subprocess, 'run', side_effect=slow):
            with self.assertRaisesRegex(ContinuousCertificationError, 'PREVIEW_VERIFICATION_TIMEOUT'):
                self.audit()
        self.assertTrue(all(not p.parent.exists() for p in self.paths))
        with patch.object(preview.subprocess, 'run', side_effect=lambda *a, **k: self.response(**k)):
            self.assertEqual(self.audit().evidence()['completed_tasks'], 1)
        self.assertTrue(all(not p.parent.exists() for p in self.paths))
        self.assertTrue(self.data.exists())

    def test_receipt_from_another_plan_is_rejected(self):
        def changed(*args, **kwargs):
            result = self.response(**kwargs)
            value = json.loads(result.stdout); value['evidence']['plan_sha256'] = 'forged'
            result.stdout = json.dumps(value); return result
        with patch.object(preview.subprocess, 'run', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'does not match'):
                self.audit()
        self.assertTrue(all(not p.parent.exists() for p in self.paths))

    def test_physics_rejection_is_preserved(self):
        response = subprocess.CompletedProcess([], 0,
            json.dumps({'status': ExposureStatus.REJECTED.value,
                        'error': 'PREVIEW_PHYSICS_CHECK_FAILED'}), '')
        with patch.object(preview.subprocess, 'run', return_value=response):
            with self.assertRaises(ContinuousCertificationError) as caught:
                self.audit()
        self.assertIs(caught.exception.status, ExposureStatus.REJECTED)

    def test_process_crash_and_invalid_json_fail_closed(self):
        for response, code in [(subprocess.CompletedProcess([], 1, '', 'boom'), 'PROCESS_FAILED'),
                               (subprocess.CompletedProcess([], 0, 'not json', ''), 'INVALID_RESPONSE')]:
            with self.subTest(code=code), patch.object(preview.subprocess, 'run', return_value=response):
                with self.assertRaisesRegex(ContinuousCertificationError, code): self.audit()

    def test_empty_preview_does_not_start_jvm(self):
        with patch.object(preview.subprocess, 'run') as child:
            plan = {**self.plan, 'assignments': []}
            receipt = preview.audit_preview(self.config, plan, deadline=time.monotonic()+5)
            self.assertEqual(receipt.evidence()['completed_tasks'], 0)
            child.assert_not_called()


if __name__ == '__main__':
    unittest.main()
