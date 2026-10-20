"""机会成本监督的反例与协议门禁，不注入虚假物理凭证。"""
import unittest
from unittest.mock import patch
from tests.test_lavis import tiny
from schedulers.constraint_model import Schedule
from algorithms.lavis.candidates import build_pool, key
from algorithms.lavis.protocol import Control, LABEL_VERSION
from algorithms.lavis.model import _known_label_protocol
from scripts.train_lavis_opportunity import opportunity_target, label_state

class Flat:
    def predict(self, rows): return [0.] * len(rows)

class OpportunityTests(unittest.TestCase):
    def test_blocking_only_satellite_has_worse_label_than_spare_satellite(self):
        problem,cm=tiny();pool,_=build_pool(problem,cm,Control(),strategy='expanded')
        rows=label_state(problem,cm,pool,Schedule(),Flat(),
            {'artifact_id':'tiny','scenario_sha256':'tiny-sha','lineage_group_id':'tiny-family'},'0')
        t1=[r for r in rows if r['candidate'][0]=='T1']
        blocked=[r for r in t1 if r['candidate'][1]=='S1']
        spare=[r for r in t1 if r['candidate'][1]=='S2']
        self.assertTrue(blocked and spare)
        # 小窗口中同星任一真实位置均排斥T2；空闲S2保留T2。
        self.assertGreater(min(r['raw_target'] for r in spare),max(r['raw_target'] for r in blocked))
        self.assertAlmostEqual(sum(r['y'] for r in rows),0.)
        self.assertTrue(all(len(r['features'])==24 for r in rows))
        self.assertEqual(rows,label_state(problem,cm,pool,Schedule(),Flat(),
            {'artifact_id':'tiny','scenario_sha256':'tiny-sha','lineage_group_id':'tiny-family'},'0'))

    def test_chosen_task_alternatives_are_not_counted_as_other_task_loss(self):
        problem,cm=tiny();pool,_=build_pool(problem,cm,Control())
        current=[a for a in pool if a.task_id=='T1']
        self.assertEqual(opportunity_target(current,[],'T1'),(0.,0,0.))

    def test_new_label_contract_cannot_be_mislabeled_as_old_rollout(self):
        self.assertTrue(_known_label_protocol({'label_version':LABEL_VERSION}))
        self.assertFalse(_known_label_protocol({'label_version':'unknown'}))
        new={'label_version':'lavis-opportunity-cost-v1','training_protocol':'lavis-opportunity-cost-v1','training_candidate_strategy':'expanded'}
        self.assertTrue(_known_label_protocol(new))
        self.assertFalse(_known_label_protocol(new|{'training_candidate_strategy':'configured'}))
        self.assertFalse(_known_label_protocol(new|{'training_protocol':'unknown'}))

if __name__=='__main__':unittest.main()
