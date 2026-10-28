"""冻结矩阵、续跑身份和分发哈希的机制测试，不依赖个人数据目录。"""
from collections import Counter,defaultdict
import json
from pathlib import Path
import tempfile
import unittest
from scripts.build_final_dataset import plan
from scripts.final_dataset_release import verify,sha

class FinalDatasetTests(unittest.TestCase):
    def test_matrix_group_separation_and_resume_do_not_redraw_seeds(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);first=plan(root);raw=(root/'dataset_plan.json').read_bytes()
            self.assertEqual(len(first['allocation']),66)
            self.assertEqual(len(first['families']),18)
            self.assertEqual(Counter(r['split'] for r in first['allocation']),{'final_test':60,'smoke':6})
            groups=defaultdict(set)
            for row in first['allocation']:groups[row['split']].add(row['lineage_group_id'])
            self.assertEqual(len(groups['final_test']),15);self.assertEqual(len(groups['smoke']),3)
            self.assertFalse(groups['final_test']&groups['smoke'])
            for scale in ('small','medium','large'):
                counts=Counter(r['difficulty_profile'] for r in first['allocation'] if r['split']=='final_test' and r['scale']==scale)
                self.assertEqual(counts,{'low_conflict':5,'mixed':5,'high_conflict':5,'resource_overload':5})
            self.assertEqual(plan(root),first)
            self.assertEqual((root/'dataset_plan.json').read_bytes(),raw)

    def test_consumer_hash_check_rejects_modified_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data=root/'data.json';data.write_text('{}')
            (root/'SHA256SUMS.json').write_text(json.dumps({'data.json':sha(data)}))
            verify(root)
            data.write_text('{"modified":true}')
            with self.assertRaises(ValueError):verify(root)

    def test_consumer_hash_check_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'SHA256SUMS.json').write_text(json.dumps({'../outside.json':'0'*64}))
            with self.assertRaises(ValueError):verify(root)

if __name__=='__main__':unittest.main()
