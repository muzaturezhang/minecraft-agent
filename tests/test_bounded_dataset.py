import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from dataset.multistep import DatasetValidationError, build_dataset
from dataset.scenario_generator import audit, digest, generate
from dataset.world_model import SimulationError, execute, is_complete


class BoundedDatasetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / 'configs/multistep_v1.json').read_text())
        cls.catalog = json.loads((ROOT / 'configs/recipe_catalog.json').read_text())
        cls.tasks, _ = generate(cls.config, cls.catalog)

    def test_quotas_and_disjoint_test_protocol(self):
        result = audit(self.tasks, self.config)
        self.assertEqual(len(self.tasks), 1400)
        self.assertEqual(result['composition_overlap'], 0)
        self.assertEqual(result['novel_target_leakage'], 0)

    def test_reproducible_scenarios(self):
        again, _ = generate(self.config, self.catalog)
        self.assertEqual(digest(again), digest(self.tasks))

    def test_all_trajectories_replay_and_have_no_future_input(self):
        result = build_dataset(self.tasks, recipe_catalog=self.catalog)
        task_by_id = {t['task_id']: t for t in self.tasks}
        for split, rows in result['samples'].items():
            for sample in rows:
                task = task_by_id[sample['task_id']]
                self.assertEqual(split, task['split'])
                self.assertEqual(len(sample['input']['history']), sample['step_index'])
                self.assertEqual(set(sample['input']), {'instruction', 'goal', 'state', 'history', 'recipe_knowledge'})
                if sample['step_index'] == 0:
                    self.assertEqual(sample['input']['state'], task['initial_state'])
                self.assertEqual(sample['target']['name'], task['steps'][sample['step_index']]['tool'])

    def test_forged_delta_or_use_event_is_rejected(self):
        task = copy.deepcopy(next(t for t in self.tasks if t['metadata']['category'] == 'E'))
        task['steps'][-1]['events'][0]['tool'] = 'iron_axe'
        with self.assertRaises(DatasetValidationError):
            build_dataset([task], recipe_catalog=self.catalog)
        task = copy.deepcopy(self.tasks[0])
        task['steps'][0]['state_delta']['inventory']['diamond'] = 1
        with self.assertRaises(DatasetValidationError):
            build_dataset([task], recipe_catalog=self.catalog)

    def test_inventory_tool_alone_does_not_complete_use_goal(self):
        task = next(t for t in self.tasks if t['metadata']['category'] == 'E')
        state = copy.deepcopy(task['initial_state'])
        state['inventory'][task['goal']['item']] = 1
        state['progress']['crafted'][task['goal']['item']] = 1
        self.assertFalse(is_complete(task['goal'], task['initial_state'], state))

    def test_outside_boundary_and_bad_tools_fail_closed(self):
        task = next(t for t in self.tasks if 'coal' in t['initial_state']['resources'])
        state = copy.deepcopy(task['initial_state'])
        state['inventory'] = {'wooden_axe': 1}
        state['equipment'] = {'hand': 'wooden_axe'}
        call = {'name': 'collect_resource', 'arguments': {'resource': 'coal', 'count': 1, 'tool': 'wooden_axe'}}
        with self.assertRaises(SimulationError):
            execute(state, call, self.catalog)
        state['inventory'] = {'wooden_pickaxe': 1}
        state['resources']['coal']['position'][0] += 100
        call['arguments'].pop('tool')
        with self.assertRaises(SimulationError):
            execute(state, call, self.catalog)

    def test_inventory_and_chest_fit_game_slots(self):
        for task in self.tasks:
            for inv, maximum in [(task['initial_state']['inventory'], 36),
                                 (task['initial_state']['containers']['supply_chest'], 27)]:
                slots = sum(n if item.endswith(('_pickaxe', '_axe', '_hoe', '_shovel')) else -(-n // 64)
                            for item, n in inv.items())
                self.assertLessEqual(slots, maximum)


if __name__ == '__main__':
    unittest.main()
