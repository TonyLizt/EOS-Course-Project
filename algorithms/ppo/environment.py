"""PPO-only adapter: retain legacy state features, use the Runner's constraints."""
import numpy as np

from algorithms.candidate_pool import enumerate_task_candidates
from algorithms.objectives import ObjectiveModel, ObjectiveWeights
from algorithms.ppo.protocol import MAX_ACTIONS, REWARD, WEIGHTS
from schedulers.constraint_model import Schedule
from schedulers.rl_env import RLSchedulingEnv, ActionCandidate


class SharedPPOEnv(RLSchedulingEnv):
    def __init__(self, checkpoint=lambda: None):
        super().__init__(max_actions=MAX_ACTIONS, objective_weights=ObjectiveWeights(**WEIGHTS))
        self.checkpoint = checkpoint
        self._mask = None

    def reset(self, problem, constraints):
        self.problem, self.cm = problem, constraints
        self.placement_mode = constraints.placement_mode
        self.downlink_duration_ratio = constraints.downlink_duration_ratio
        self.sorted_tasks = sorted(problem.tasks.values(), key=lambda t: (-t.priority, t.id))
        self.task_index = 0
        self.schedule = Schedule()
        self.obj_model = ObjectiveModel(problem, ObjectiveWeights(**WEIGHTS))
        self._last_score = float(self.obj_model.score(self.schedule))
        self._mask = None
        return self.observation()

    @property
    def done(self):
        return self.task_index >= len(self.sorted_tasks)

    def observation(self):
        return {'state': self._get_state(), 'action_mask': self._get_action_mask().copy()}

    def _get_action_mask(self):
        if self._mask is None:
            self._candidates = [ActionCandidate(None)]
            if not self.done:
                self.checkpoint()
                candidates = enumerate_task_candidates(
                    self.problem, self.sorted_tasks[self.task_index],
                    placement_mode=self.cm.placement_mode,
                    downlink_duration_ratio=self.cm.downlink_duration_ratio,
                    max_candidates=MAX_ACTIONS - 1, random_samples_per_window=0, seed=0)
                for assignment in candidates:
                    self.checkpoint()
                    if self.cm.is_feasible_assignment(assignment, self.schedule):
                        self._candidates.append(ActionCandidate(assignment))
            self._mask = np.zeros(MAX_ACTIONS, dtype=np.float32)
            self._mask[:len(self._candidates)] = 1.0
        return self._mask

    def step(self, action):
        if self.done:
            return self.observation(), 0.0, True, {'status': 'done'}
        self.checkpoint()
        mask = self._get_action_mask()
        status, reward = 'invalid_action', -REWARD['skip_penalty']
        # Never clip an invalid index into a valid assignment. Use the cached mapping.
        if isinstance(action, (int, np.integer)) and 0 <= action < MAX_ACTIONS and mask[action]:
            assignment = self._candidates[action].assignment
            status = 'skip'
            if assignment is not None:
                status = 'infeasible'
                if self.cm.is_feasible_assignment(assignment, self.schedule):
                    # Transactional update: replay in chronological order, as Verifier does.
                    proposed = sorted(self.schedule.assignments + [assignment],
                                      key=lambda a: (a.sat_start_time, a.task_id))
                    replay = Schedule()
                    for item in proposed:
                        self.checkpoint()
                        if not self.cm.is_feasible_assignment(item, replay):
                            break
                        replay.assignments.append(item)
                    else:
                        self.schedule = replay
                        score = float(self.obj_model.score(replay))
                        reward = REWARD['scale'] * (score - self._last_score)
                        self._last_score = score
                        status = 'ok'
        # Skip, stale candidates and invalid actions all advance safely.
        self.task_index += 1
        self._mask = None
        return self.observation(), reward, self.done, {'status': status}
