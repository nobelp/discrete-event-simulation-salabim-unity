"""Convert a legacy Unity export into an explicitly incomplete topology draft.

Screen coordinates never become physical lengths or capacities automatically.
"""
import argparse
import json
from pathlib import Path


def draft(data):
    conveyors = data.get("conveyorDTOs")
    if not isinstance(conveyors, dict) or not conveyors:
        raise ValueError("Unity export contains no conveyorDTOs")
    nodes = [{"id": key, "screenPosition": {"x": value.get("x"), "y": value.get("y"), "rotation": value.get("rotation")}, "lengthM": None, "speedMps": None, "capacity": None, "processingSeconds": None, "status": "missing_physical_data"} for key, value in conveyors.items()]
    links = []
    for key, point in data.get("connectionPointDTOs", {}).items():
        a, b = point.get("conveyor1Id"), point.get("conveyor2Id")
        if a not in conveyors or b not in conveyors:
            raise ValueError("Connection references unknown conveyor")
        links.append({"id": key, "endpoints": [a, b], "directionStatus": "requires_confirmation"})
    return {"format": "kx-unity-topology-draft", "version": 1, "simulationReady": False, "nodes": nodes, "connections": links, "source": "legacy Unity screen-coordinate export", "missing": ["Physical segment lengths and speeds", "Useful slots / zones and transfer rules", "Confirmed directed connections and routes", "Arrival profile and measurement criteria"], "note": "This draft deliberately cannot be executed as a physical performance model."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(draft(json.loads(args.source.read_text(encoding="utf-8-sig"))), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
