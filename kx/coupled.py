"""Coupled synthetic infeed/lift/level-shuttle/storage/outfeed reference model.

One shared, single-load lift remembers its last height. Each level has one
shuttle and finite separate transfer buffers. Full downstream buffers retain
upstream resources (blocking after service). Inventory and rack slots are separate
from resource occupancy; there is no ABC or random relocation assumption.
"""
import copy
import hashlib
import json
import math
import sys
import salabim as sim
from .simulation import finite, percentile


def integer(value, name, minimum=0, maximum=100000):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name}: integer {minimum}..{maximum} required")
    return value


def travel(distance, speed, acceleration, deceleration):
    if distance == 0:
        return 0
    ramps = speed * speed / (2 * acceleration) + speed * speed / (2 * deceleration)
    if distance <= ramps:
        peak = math.sqrt(2 * distance / (1 / acceleration + 1 / deceleration))
        return peak / acceleration + peak / deceleration
    return speed / acceleration + speed / deceleration + (distance - ramps) / speed


def validate(data):
    if not isinstance(data, dict) or data.get("format") != "kx-coupled" or data.get("version") != 1:
        raise ValueError("Unsupported coupled-system format")
    if data.get("dataStatus") != "synthetic":
        raise ValueError("Only explicitly synthetic reference scenarios are enabled")
    horizon = finite(data.get("durationSeconds"), "durationSeconds", .001)
    if horizon > 86400:
        raise ValueError("Maximum duration: 86400 seconds")
    integer(data.get("seed"), "seed")
    for name in ["infeedSeconds", "outfeedSeconds", "workstationSeconds", "shuttleCycleSeconds", "relocationSeconds", "pickupSeconds", "dropoffSeconds"]:
        finite(data.get(name), name)
    for name in ["inBufferCapacity", "outBufferCapacity", "levelBufferCapacity"]:
        integer(data.get(name), name, 1, 1000)
    lift = data.get("lift")
    if not isinstance(lift, dict):
        raise ValueError("Lift motion data required")
    for key in ["speedMps", "accelerationMps2", "decelerationMps2"]:
        finite(lift.get(key), key, 1e-9)
    levels = data.get("levels")
    if not isinstance(levels, list) or not 1 <= len(levels) <= 30:
        raise ValueError("1..30 explicit levels required")
    ids = set()
    for level in levels:
        if not isinstance(level, dict) or not isinstance(level.get("id"), str) or not level["id"] or level["id"] in ids:
            raise ValueError("Unique nonempty level IDs required")
        ids.add(level["id"])
        finite(level.get("heightM"), "heightM", 1e-9)
        capacity = integer(level.get("storageCapacity"), "storageCapacity", 1)
        integer(level.get("initialStock"), "initialStock", 0, capacity)
    if sum(level["initialStock"] for level in levels) > 10000:
        raise ValueError("Maximum initial stock: 10000")
    jobs = data.get("jobs")
    if not isinstance(jobs, list) or len(jobs) > 5000:
        raise ValueError("Explicit list of at most 5000 jobs required")
    ids_job = set()
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("id"), str) or not job["id"] or job["id"] in ids_job:
            raise ValueError("Unique nonempty job IDs required")
        ids_job.add(job["id"])
        if job.get("type") not in ["putaway", "retrieve"] or job.get("level") not in ids:
            raise ValueError("Every job requires type putaway/retrieve and an existing level")
        if finite(job.get("arrivalSeconds"), "arrivalSeconds") >= horizon:
            raise ValueError("Job arrivals must precede measurement end")
        integer(job.get("relocations"), "relocations", 0, 100)
    return data


def run(data):
    data = copy.deepcopy(validate(data))
    horizon = data["durationSeconds"]
    env = sim.Environment(trace=False, random_seed=data["seed"], time_unit="seconds", yieldless=False)
    env.animate(False)
    resources, metrics, records, trace = {}, {}, {}, []
    definitions = {level["id"]: level for level in data["levels"]}
    stock, rack, physical = {}, {}, {}
    for level in data["levels"]:
        key = level["id"]
        stock[key] = sim.Store(name="stock-" + key, fill=[sim.Component(env=env) for _ in range(level["initialStock"])], env=env)
        rack[key] = sim.Resource(name="rack-" + key, capacity=level["storageCapacity"], initial_claimed_quantity=level["initialStock"], anonymous=True, env=env)
        physical[key] = level["initialStock"]
    lift_height = [0.0]
    counts = {"stored": 0, "picked": 0, "retrieved": 0}

    def resource(key, capacity):
        resources[key] = sim.Resource(name=key, capacity=capacity, env=env)
        metrics[key] = {"capacity": capacity, "occupancy": 0, "maximumOccupancy": 0, "area": 0.0, "last": 0.0, "blockedSeconds": 0.0}

    for key, capacity in [("infeed", 1), ("in-buffer", data["inBufferCapacity"]), ("lift", 1), ("out-buffer", data["outBufferCapacity"]), ("outfeed", 1), ("workstation", 1)]:
        resource(key, capacity)
    for key in definitions:
        resource("shuttle-" + key, 1)
        resource("level-in-" + key, data["levelBufferCapacity"])
        resource("level-out-" + key, data["levelBufferCapacity"])

    def change(key, delta):
        m = metrics[key]
        m["area"] += m["occupancy"] * (env.now() - m["last"])
        m["last"] = env.now()
        m["occupancy"] += delta
        m["maximumOccupancy"] = max(m["maximumOccupancy"], m["occupancy"])
        if not 0 <= m["occupancy"] <= m["capacity"]:
            raise AssertionError("Finite resource capacity violated")

    def snapshot(record):
        if len(trace) < 5000:
            trace.append({"time": env.now(), "job": record["id"], "type": record["type"], "stage": record["stage"], "resources": {k: m["occupancy"] for k, m in metrics.items()}, "stock": dict(physical), "putaway": counts["stored"], "retrieved": counts["retrieved"]})

    class Transport(sim.Component):
        def setup(self, job):
            self.job = job

        def mark(self, stage):
            self.record["stage"] = stage
            snapshot(self.record)

        def acquire(self, key):
            r = self.record
            r["waitingSince"] = env.now()
            r["waitingHeld"] = list(r["held"])
            self.mark("waiting:" + key)
            yield self.request(resources[key])
            for held in r["waitingHeld"]:
                metrics[held]["blockedSeconds"] += env.now() - r["waitingSince"]
            r["waitingSince"] = None
            r["waitingHeld"] = []
            r["held"].append(key)
            change(key, 1)
            self.mark(key)

        def release_node(self, key):
            # Keep accounting separate from salabim's resource method.
            change(key, -1)
            self.record["held"].remove(key)
            super().release(resources[key])

        def move_lift(self, target):
            lift = data["lift"]
            seconds = travel(abs(target - lift_height[0]), lift["speedMps"], lift["accelerationMps2"], lift["decelerationMps2"])
            yield self.hold(seconds)
            lift_height[0] = target

        def process(self):
            job, key = self.job, self.job["level"]
            r = self.record = {**job, "completedAt": None, "stage": "arrival", "held": [], "waitingSince": None, "waitingHeld": []}
            records[job["id"]] = r
            self.mark("arrival")
            height = definitions[key]["heightM"]
            shuttle_time = data["shuttleCycleSeconds"] + job["relocations"] * data["relocationSeconds"]
            if job["type"] == "putaway":
                self.mark("waiting:storage-slot")
                yield self.request(rack[key])
                yield from self.acquire("infeed")
                yield self.hold(data["infeedSeconds"])
                yield from self.acquire("in-buffer")
                self.release_node("infeed")
                yield from self.acquire("lift")
                yield from self.move_lift(0)
                yield self.hold(data["pickupSeconds"])
                self.release_node("in-buffer")
                yield from self.move_lift(height)
                yield from self.acquire("level-in-" + key)
                yield self.hold(data["dropoffSeconds"])
                self.release_node("lift")
                yield from self.acquire("shuttle-" + key)
                yield self.hold(data["pickupSeconds"])
                self.release_node("level-in-" + key)
                yield self.hold(shuttle_time)
                physical[key] += 1
                yield self.to_store(stock[key], sim.Component(env=env))
                self.release_node("shuttle-" + key)
            else:
                self.mark("waiting:available-stock")
                yield self.from_store(stock[key])
                yield from self.acquire("shuttle-" + key)
                yield self.hold(shuttle_time)
                physical[key] -= 1
                counts["picked"] += 1
                rack[key].release(1)
                yield from self.acquire("level-out-" + key)
                yield self.hold(data["dropoffSeconds"])
                self.release_node("shuttle-" + key)
                yield from self.acquire("lift")
                yield from self.move_lift(height)
                yield self.hold(data["pickupSeconds"])
                self.release_node("level-out-" + key)
                yield from self.move_lift(0)
                yield from self.acquire("out-buffer")
                yield self.hold(data["dropoffSeconds"])
                self.release_node("lift")
                yield from self.acquire("outfeed")
                self.release_node("out-buffer")
                yield self.hold(data["outfeedSeconds"])
                yield from self.acquire("workstation")
                self.release_node("outfeed")
                yield self.hold(data["workstationSeconds"])
                self.release_node("workstation")
            counts["stored" if job["type"] == "putaway" else "retrieved"] += 1
            r["completedAt"] = env.now()
            self.mark("complete")

    for job in data["jobs"]:
        Transport(job=job, at=job["arrivalSeconds"], env=env)
    env.run(till=horizon, priority=math.inf)
    for record in records.values():
        if record["waitingSince"] is not None:
            for held in record["waitingHeld"]:
                metrics[held]["blockedSeconds"] += horizon - record["waitingSince"]
    for m in metrics.values():
        m["area"] += m["occupancy"] * (horizon - m["last"])
        m["meanOccupancy"] = m["area"] / horizon
        m["occupiedFraction"] = m["area"] / (horizon * m["capacity"])
    completed = [r for r in records.values() if r["completedAt"] is not None]
    initial = sum(l["initialStock"] for l in data["levels"])
    put = sum(r["type"] == "putaway" for r in completed)
    retrieved_picked = counts["picked"]
    if initial + put - retrieved_picked != sum(physical.values()):
        raise AssertionError("Physical inventory conservation violated")
    snapshot({"id": "measurement", "type": "system", "stage": "measurement-end"})
    if any(not 0 <= physical[k] <= definitions[k]["storageCapacity"] for k in physical):
        raise AssertionError("Storage capacity violated")
    if len(records) != len(data["jobs"]):
        raise AssertionError("Transport arrivals not conserved")
    flows = [r["completedAt"] - r["arrivalSeconds"] for r in completed]
    return {"modelVersion": "kx-coupled-0.1", "dataStatus": "synthetic", "evidenceStatus": "reference_only", "inputSha256": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(), "durationSeconds": horizon,
            "arrived": len(records), "completed": len(completed), "unfinished": len(records) - len(completed), "putawayCompleted": put, "retrievalCompleted": len(completed) - put,
            "flowSeconds": {"mean": sum(flows) / len(flows) if flows else None, "p95": percentile(flows, .95)}, "resources": metrics,
            "inventory": {k: {"initial": definitions[k]["initialStock"], "physical": physical[k], "available": len(stock[k]), "reservedForRetrieval": physical[k] - len(stock[k]), "reservedForPutaway": rack[k].claimed_quantity() - physical[k], "capacity": definitions[k]["storageCapacity"]} for k in definitions},
            "balance": {"initialStock": initial, "stored": put, "pickedForRetrieval": retrieved_picked, "finalPhysicalStock": sum(physical.values())},
            "jobs": [{k: v for k, v in r.items() if k not in ["waitingHeld", "waitingSince"]} for r in records.values()], "trace": trace, "traceTruncated": len(trace) >= 5000,
            "limits": ["Synthetic reference case only; no validated plant performance.", "One shared single-load lift; one shuttle per level; FIFO resource requests; no optimized double cycles.", "Shuttle cycle and extra relocation time are explicit assumptions, not inferred from ABC or supplier percentages.", "Putaway reserves a rack slot before entering infeed. Retrieval reserves stock, releases physical slot at the end of its shuttle cycle.", "Finite buffers retain upstream resources; unfinished jobs may be queued, blocked or deadlocked, not an automatic deadlock proof.", "No failures, real WCS handshakes, continuous belt headway, SKU/ABC placement or calibrated multi-depth storage."]}


if __name__ == "__main__":
    try:
        print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=False, allow_nan=False))
    except (ValueError, TypeError, KeyError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
