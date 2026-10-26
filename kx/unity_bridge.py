"""Strict Unity contract for synthetic, constant-speed exclusive zones.

No pixel conversion, capacity inference, acceleration or multi-load behaviour.
"""
import argparse
import json
from pathlib import Path
from .simulation import finite, run, validate


def convert(data):
    if not isinstance(data, dict) or data.get("format") != "kx-unity-zones" or data.get("version") != 1:
        raise ValueError("Unsupported Unity physical-zone contract")
    if data.get("dataStatus") != "synthetic":
        raise ValueError("Only explicitly synthetic Unity scenarios are enabled")
    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("At least one configured zone is required")
    nodes, edges = [], []
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError("Invalid zone")
        length = finite(segment.get("lengthM"), "lengthM", 1e-9)
        speed = finite(segment.get("speedMps"), "speedMps", 1e-9)
        transfer = finite(segment.get("transferSeconds"), "transferSeconds")
        if segment.get("mode") != "constant_speed_exclusive_zone":
            raise ValueError("Explicit constant_speed_exclusive_zone mode required")
        if segment.get("connectionsConfirmed") is not True:
            raise ValueError("Directed connections must be explicitly confirmed")
        next_ids = segment.get("nextIds")
        if not isinstance(next_ids, list) or any(not isinstance(n, str) for n in next_ids):
            raise ValueError("nextIds must be an explicit list; empty for a terminal zone")
        nodes.append({"id": segment.get("id"), "capacity": 1, "processingSeconds": length / speed + transfer})
        edges.extend([[segment.get("id"), n] for n in next_ids])
    config = {"schemaVersion": 1, "dataStatus": "synthetic", "durationSeconds": data.get("durationSeconds"), "seed": data.get("seed"), "nodes": nodes, "connections": edges, "jobs": data.get("jobs")}
    validate(config)
    return config


def execute(data):
    result = run(convert(data))
    result["physicalModel"] = {"name": "constant_speed_exclusive_zone", "serviceTime": "lengthM / speedMps + transferSeconds", "capacity": "one transport per complete zone, including downstream blocking", "limits": ["Synthetic model only; no physical system release.", "No acceleration, belt headway, container geometry or moving multi-load conveyor.", "Positions and rotations are visual only; directed links and routes must be explicit."]}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        data = json.loads(args.scenario.read_text(encoding="utf-8-sig"))
        result = execute(data)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    except (ValueError, TypeError, KeyError, OSError) as error:
        parser.exit(2, f"Unity model input error: {error}\n")


if __name__ == "__main__":
    main()
