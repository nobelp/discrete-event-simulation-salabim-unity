import copy
import json
from pathlib import Path
import unittest
from kx.simulation import run
from kx.import_layout import draft


def case():
    return json.loads((Path(__file__).parents[1] / "examples/kx-backpressure.json").read_text())


class ReferenceChecks(unittest.TestCase):
    def test_independent_schedule_and_conservation(self):
        # Hand schedule: first exits at 10, then 18, 26, 34 seconds.
        result = run(case())
        self.assertEqual(result["completed"], 3)
        self.assertEqual(result["unfinished"], 1)
        self.assertEqual(result["arrived"], 4)
        self.assertEqual(result["flowSeconds"]["mean"], 18)
        self.assertEqual(result["flowSeconds"]["p95"], 26)
        self.assertEqual(result["completedPerHour"], 360)

    def test_downstream_reservation_causes_upstream_backpressure(self):
        result = run(case())
        # Infeed occupied [0,26]; processing = 4*2, blocking = 26-8.
        self.assertEqual(result["nodes"]["infeed-zone"]["blockedSlotSeconds"], 18)
        self.assertEqual(result["nodes"]["infeed-zone"]["occupiedSlotSeconds"], 26)
        self.assertTrue(all(n["maximumOccupancy"] <= n["capacity"] for n in result["nodes"].values()))
        for node in result["nodes"].values():
            self.assertAlmostEqual(node["occupiedSlotSeconds"], node["processingSlotSeconds"] + node["blockedSlotSeconds"])

    def test_incomplete_blocking_and_processing_count_at_measurement_end(self):
        data = case()
        data["durationSeconds"] = 7
        result = run(data)
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["unfinished"], 4)
        self.assertEqual(result["nodes"]["infeed-zone"]["blockedSlotSeconds"], 3)
        self.assertEqual(result["nodes"]["workstation"]["processingSlotSeconds"], 5)

    def test_same_inputs_same_result_and_input_unchanged(self):
        data = case()
        before = copy.deepcopy(data)
        self.assertEqual(run(data), run(data))
        self.assertEqual(data, before)

    def test_measurement_includes_completion_at_endpoint(self):
        data = case()
        data["durationSeconds"] = 10
        self.assertEqual(run(data)["completed"], 1)

    def test_shared_resource_merge(self):
        data = case()
        data["nodes"].append({"id": "second-infeed", "capacity": 1, "processingSeconds": 2})
        data["connections"].append(["second-infeed", "workstation"])
        data["jobs"][1]["route"] = ["second-infeed", "workstation"]
        result = run(data)
        self.assertEqual(result["nodes"]["workstation"]["maximumOccupancy"], 1)
        self.assertEqual(result["completed"], 3)

    def test_no_jobs(self):
        data = case()
        data["jobs"] = []
        result = run(data)
        self.assertEqual(result["completed"], 0)
        self.assertIsNone(result["flowSeconds"]["p95"])

    def test_invalid_physical_or_route_inputs_rejected(self):
        for change in [lambda d: d["nodes"][0].update(capacity=0), lambda d: d["nodes"][0].update(processingSeconds=float("nan")), lambda d: d["jobs"][0].update(route=["unknown"]), lambda d: d.update(connections=[]), lambda d: d["jobs"][0].update(route=["infeed-zone", "infeed-zone"]), lambda d: d.update(dataStatus="supplier-confirmed")]:
            data = case()
            change(data)
            with self.assertRaises(ValueError):
                run(data)

    def test_unity_coordinates_are_not_physical_lengths(self):
        result = draft({"conveyorDTOs": {"a": {"x": 10, "y": 20, "rotation": 0}}})
        self.assertFalse(result["simulationReady"])
        self.assertIsNone(result["nodes"][0]["lengthM"])
        self.assertIsNone(result["nodes"][0]["capacity"])


if __name__ == "__main__":
    unittest.main()
