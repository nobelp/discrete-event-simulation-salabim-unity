import copy
import unittest
from kx.unity_bridge import convert, execute


def case():
    return {"format": "kx-unity-zones", "version": 1, "dataStatus": "synthetic", "durationSeconds": 30, "seed": 42,
            "segments": [{"id": "a", "mode": "constant_speed_exclusive_zone", "lengthM": 1, "speedMps": .5, "transferSeconds": 0, "nextIds": ["b"], "connectionsConfirmed": True},
                         {"id": "b", "mode": "constant_speed_exclusive_zone", "lengthM": 2, "speedMps": .25, "transferSeconds": 0, "nextIds": [], "connectionsConfirmed": True}],
            "jobs": [{"id": str(i), "arrivalSeconds": 0, "route": ["a", "b"]} for i in range(4)]}


class BridgeChecks(unittest.TestCase):
    def test_units_and_hand_schedule(self):
        data = case()
        before = copy.deepcopy(data)
        config = convert(data)
        self.assertEqual([n["processingSeconds"] for n in config["nodes"]], [2, 8])
        result = execute(data)
        self.assertEqual(result["completed"], 3)
        self.assertEqual(result["unfinished"], 1)
        self.assertEqual(data, before)

    def test_transfer_time_is_explicitly_added(self):
        data = case()
        data["segments"][0]["transferSeconds"] = 3
        self.assertEqual(convert(data)["nodes"][0]["processingSeconds"], 5)

    def test_missing_data_links_and_invalid_values_rejected(self):
        edits = [lambda d: d["segments"][0].update(speedMps=0), lambda d: d["segments"][0].update(lengthM=None),
                 lambda d: d["segments"][0].update(connectionsConfirmed=False), lambda d: d["segments"][0].update(nextIds=["missing"]),
                 lambda d: d["segments"][0].update(nextIds=[]), lambda d: d["segments"][0].update(transferSeconds=-1),
                 lambda d: d.update(dataStatus="real"), lambda d: d["segments"][0].update(mode="continuous_belt")]
        for edit in edits:
            with self.subTest(edit=edit):
                data = case()
                edit(data)
                with self.assertRaises(ValueError):
                    convert(data)


if __name__ == "__main__":
    unittest.main()
