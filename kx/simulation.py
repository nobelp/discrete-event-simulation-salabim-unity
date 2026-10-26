"""Finite-capacity service network with blocking after service, seconds as time unit.

This is a reproducible reference model, not a calibrated conveyor or shuttle model.
Each job reserves its downstream slot before releasing the upstream slot. Capacity
is total occupied slots (processing + blocked), not an implicit server count.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import salabim as sim


def finite(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name}: finite number >= {minimum} required")
    return value


def validate(config):
    if not isinstance(config, dict) or config.get("schemaVersion") != 1:
        raise ValueError("Unsupported simulation schema")
    if config.get("dataStatus") != "synthetic":
        raise ValueError("This reference runner accepts explicitly synthetic scenarios only")
    horizon = finite(config.get("durationSeconds"), "durationSeconds", 1e-9)
    seed = config.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("An explicit nonnegative integer seed is required")
    nodes = config.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("A nonempty node list is required")
    by_id = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"] or node["id"] in by_id:
            raise ValueError("Node IDs must be unique nonempty strings")
        capacity = node.get("capacity")
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
            raise ValueError("Node capacity must be a positive integer")
        finite(node.get("processingSeconds"), "processingSeconds")
        by_id[node["id"]] = node
    connections = config.get("connections")
    if not isinstance(connections, list):
        raise ValueError("Explicit directed connections are required")
    edges = set()
    for edge in connections:
        if not isinstance(edge, list) or len(edge) != 2 or any(not isinstance(x, str) or x not in by_id for x in edge):
            raise ValueError("Connection references unknown nodes")
        edges.add(tuple(edge))
    jobs = config.get("jobs")
    if not isinstance(jobs, list) or len(jobs) > 100000:
        raise ValueError("jobs must be a list of at most 100000 items")
    ids = set()
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("id"), str) or not job["id"] or job["id"] in ids:
            raise ValueError("Job IDs must be unique nonempty strings")
        ids.add(job["id"])
        if finite(job.get("arrivalSeconds"), "arrivalSeconds") >= horizon:
            raise ValueError("Every job must arrive before the measurement end")
        route = job.get("route")
        if not isinstance(route, list) or not route or any(not isinstance(x, str) or x not in by_id for x in route):
            raise ValueError("Every job requires a route of existing node IDs")
        if len(set(route)) != len(route):
            raise ValueError("Repeated nodes in a route are not supported by this reference runner")
        if any(pair not in edges for pair in zip(route, route[1:])):
            raise ValueError("Route traverses an undefined directed connection")
    return by_id


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def diagnose_deadlocks(records, definitions):
    """Prove closed waits between full single-slot resources, not from WIP.

    The reference model has no timeout, capacity change or forced release.
    Multi-slot waits are outside this diagnostic's scope.
    """
    holders = {}
    for job_id, record in records.items():
        for visit in record["visits"]:
            if visit["releasedAt"] is None:
                holders.setdefault(visit["node"], []).append(job_id)
    successors = {}
    for job_id, record in records.items():
        target = record.get("waitingForNode")
        held = [v["node"] for v in record["visits"] if v["releasedAt"] is None]
        if record["state"] != "blocked" or len(held) != 1 or not target:
            continue
        if definitions[held[0]]["capacity"] == definitions[target]["capacity"] == 1 and len(holders.get(target, [])) == 1:
            successors[job_id] = holders[target][0]
    visited, cycles = set(), []
    for start in sorted(successors):
        if start in visited:
            continue
        path, positions, current = [], {}, start
        while current in successors and current not in visited and current not in positions:
            positions[current] = len(path)
            path.append(current)
            current = successors[current]
        if current in positions:
            members = path[positions[current]:]
            cycles.append({"jobs": members,
                           "heldNodes": [next(v["node"] for v in records[j]["visits"] if v["releasedAt"] is None) for j in members],
                           "waitingForNodes": [records[j]["waitingForNode"] for j in members]})
        visited.update(path)
    return {"status": "deadlock_detected" if cycles else "no_single_slot_cycle_detected", "cycles": cycles,
            "scope": "Closed wait cycles of single-slot nodes only; no absence proof for multi-slot networks."}


def run(config):
    config = copy.deepcopy(config)
    definitions = validate(config)
    duration = config["durationSeconds"]
    env = sim.Environment(trace=False, random_seed=config["seed"], time_unit="seconds", yieldless=False)
    env.animate(False)
    resources = {key: sim.Resource(name=key, capacity=d["capacity"], env=env) for key, d in definitions.items()}
    occupancy = {key: {"current": 0, "maximum": 0, "area": 0.0, "last": 0.0} for key in definitions}
    records = {}

    def occupied(key, delta):
        m = occupancy[key]
        m["area"] += m["current"] * (env.now() - m["last"])
        m["last"] = env.now()
        m["current"] += delta
        if not 0 <= m["current"] <= definitions[key]["capacity"]:
            raise AssertionError("Finite capacity violated")
        m["maximum"] = max(m["maximum"], m["current"])

    class Transport(sim.Component):
        def setup(self, job):
            self.job = job

        def process(self):
            job = self.job
            record = records[job["id"]] = {"id": job["id"], "arrivalSeconds": job["arrivalSeconds"], "completedAt": None, "state": "waiting_for_entry", "waitingForNode": None, "visits": []}
            previous = None
            for key in job["route"]:
                requested = env.now()
                if previous:
                    record["state"] = "blocked"
                record["waitingForNode"] = key
                yield self.request(resources[key])
                record["waitingForNode"] = None
                acquired = env.now()
                occupied(key, 1)
                if previous:
                    record["visits"][-1]["releasedAt"] = acquired
                    occupied(previous, -1)
                    self.release(resources[previous])
                visit = {"node": key, "requestedAt": requested, "enteredAt": acquired, "serviceEndedAt": None, "releasedAt": None}
                record["visits"].append(visit)
                record["state"] = "processing"
                yield self.hold(definitions[key]["processingSeconds"])
                visit["serviceEndedAt"] = env.now()
                previous = key
            occupied(previous, -1)
            self.release(resources[previous])
            record["visits"][-1]["releasedAt"] = env.now()
            record["state"] = "complete"
            record["completedAt"] = env.now()

    for job in config["jobs"]:
        Transport(job=job, name=job["id"], at=job["arrivalSeconds"], env=env)
    # Include completions at T; salabim's main event runs after finite-priority
    # component events at the same timestamp.
    env.run(till=duration, priority=math.inf)
    completed = [r for r in records.values() if r["completedAt"] is not None]
    unfinished = [r for r in records.values() if r["completedAt"] is None]
    flow_times = [r["completedAt"] - r["arrivalSeconds"] for r in completed]
    node_metrics = {}
    for key, d in definitions.items():
        m = occupancy[key]
        m["area"] += m["current"] * (duration - m["last"])
        busy = blocked = 0.0
        for record in records.values():
            for visit in record["visits"]:
                if visit["node"] != key:
                    continue
                end = visit["serviceEndedAt"] if visit["serviceEndedAt"] is not None else duration
                released = visit["releasedAt"] if visit["releasedAt"] is not None else duration
                busy += end - visit["enteredAt"]
                blocked += released - end
        node_metrics[key] = {"capacity": d["capacity"], "maximumOccupancy": m["maximum"], "meanOccupancy": m["area"] / duration, "occupiedSlotSeconds": m["area"], "processingSlotSeconds": busy, "blockedSlotSeconds": blocked, "occupiedFraction": m["area"] / (duration * d["capacity"])}
    if len(records) != len(config["jobs"]) or len(completed) + len(unfinished) != len(config["jobs"]):
        raise AssertionError("Transport conservation violated")
    model_hash = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schemaVersion": 1, "modelVersion": "kx-service-network-0.2", "engine": "salabim", "engineVersion": sim.__version__, "inputSha256": model_hash, "seed": config["seed"],
        "evidenceStatus": "synthetic_reference_only", "measurement": {"startSeconds": 0, "endSeconds": duration, "completionBoundary": "inclusive", "warmupSeconds": 0},
        "arrived": len(records), "completed": len(completed), "unfinished": len(unfinished), "completedPerHour": len(completed) * 3600 / duration,
        "flowSeconds": {"mean": sum(flow_times) / len(flow_times) if flow_times else None, "p95": percentile(flow_times, .95), "p99": percentile(flow_times, .99)},
        "unfinishedJobs": [{"id": r["id"], "state": r["state"], "waitingForNode": r["waitingForNode"], "ageSeconds": duration - r["arrivalSeconds"]} for r in unfinished], "nodes": node_metrics,
        "deadlockDiagnostic": diagnose_deadlocks(records, definitions),
        "limits": ["Synthetic service network only; slot capacities are explicit model assumptions.", "capacity > 1 represents parallel service slots, not a verified physical conveyor or lift.", "No continuous belt headway, pitch, acceleration, failures, priority policy or calibrated shuttle/lift mechanics.", "Unfinished transports may indicate normal WIP, overload or deadlock; only closed single-slot wait cycles are diagnosed.", "Unity editor integration and supplier evidence import remain separate work."],
    }


def main():
    parser = argparse.ArgumentParser(description="Run a synthetic finite-capacity KX reference network")
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = run(json.loads(args.scenario.read_text(encoding="utf-8")))
        text = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
    except (ValueError, TypeError, KeyError, OSError) as error:
        parser.exit(2, f"Simulation input error: {error}\n")


if __name__ == "__main__":
    main()
