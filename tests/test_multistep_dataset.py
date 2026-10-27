import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dataset.multistep import DatasetValidationError, build_dataset, load_task_specs


class MultiStepDatasetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = load_task_specs(ROOT / "data" / "multistep_tasks.json")

    def test_builds_trajectories_and_step_samples(self):
        result = build_dataset(self.tasks, seed=42)
        self.assertEqual(len(result["trajectories"]), 4)
        self.assertEqual(sum(map(len, result["samples"].values())), 22)

    def test_state_before_excludes_future_delta(self):
        result = build_dataset(self.tasks, seed=42)
        trajectory = next(x for x in result["trajectories"] if x["task_id"] == "torch_from_nearby_coal")
        first = next(x for x in result["samples"][trajectory["split"]] if x["sample_id"] == "torch_from_nearby_coal__v0__s0")
        second = next(x for x in result["samples"][trajectory["split"]] if x["sample_id"] == "torch_from_nearby_coal__v0__s1")
        self.assertEqual(first["state"]["inventory"], {"stick": 1, "coal": 0})
        self.assertEqual(second["state"]["inventory"], {"stick": 1, "coal": 1})
        self.assertNotIn("torch", first["state"]["inventory"])

    def test_unknown_tool_is_rejected(self):
        broken = json.loads(json.dumps(self.tasks))
        broken[0]["steps"][0]["tool"] = "not_a_tool"
        with self.assertRaises(DatasetValidationError):
            build_dataset(broken)

    def test_scenario_group_stays_in_one_split(self):
        related = json.loads(json.dumps(self.tasks[:2]))
        related[0]["scenario_group"] = "same_scenario"
        related[1]["scenario_group"] = "same_scenario"
        result = build_dataset(related, seed=11)
        splits = {row["split"] for row in result["trajectories"]}
        self.assertEqual(len(splits), 1)

    def test_schema_constraints_are_checked(self):
        broken = json.loads(json.dumps(self.tasks))
        broken[0]["steps"][0] = {"tool": "send_message", "args": {"message": "停"}}
        with self.assertRaises(DatasetValidationError):
            build_dataset(broken)

    def test_state_rules_reject_missing_material(self):
        broken = json.loads(json.dumps(self.tasks))
        broken[0]["steps"][1]["state_delta"]["inventory"]["stick"] = 0
        with self.assertRaises(DatasetValidationError):
            build_dataset(broken)

    def test_state_rules_require_source_update(self):
        broken = json.loads(json.dumps(self.tasks))
        broken[0]["steps"][0]["state_delta"].pop("set")
        with self.assertRaises(DatasetValidationError):
            build_dataset(broken)


if __name__ == "__main__":
    unittest.main()
