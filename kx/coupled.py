"""Coupled synthetic infeed/lift/level-shuttle/storage/outfeed reference model.

Each aisle has a lift pool with individual positions. Each level has one
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
    integer(data.get("liftsPerAisle", 1), "liftsPerAisle", 1, 8)
    if not isinstance(data.get("returnToStorage", False), bool):
        raise ValueError("returnToStorage: boolean required")
    if data.get("returnToStorage"):
        finite(data.get("returnSeconds"), "returnSeconds")
        integer(data.get("returnCapacity"), "returnCapacity", 1, 1000)
    for rate in [data.get("shuttleRateBEhPerUnit"), data.get("lift", {}).get("rateBEhPerUnit") if isinstance(data.get("lift"), dict) else None]:
        if rate is not None: finite(rate, "component BE/h rate", 1e-9)
    for name in ["infeedSeconds", "outfeedSeconds", "workstationSeconds", "shuttleCycleSeconds", "relocationSeconds", "pickupSeconds", "dropoffSeconds"]:
        finite(data.get(name), name)
    for name in ["inBufferCapacity", "outBufferCapacity", "levelBufferCapacity"]:
        integer(data.get(name), name, 1, 1000)
    lift = data.get("lift")
    if not isinstance(lift, dict):
        raise ValueError("Lift motion data required")
    for key in ["pickupSeconds", "dropoffSeconds"]:
        if key in lift: finite(lift[key], key)
    for key in ["speedMps", "accelerationMps2", "decelerationMps2"]:
        finite(lift.get(key), key, 1e-9)
    levels = data.get("levels")
    if not isinstance(levels, list) or not 1 <= len(levels) <= 120:
        raise ValueError("1..120 explicit levels required")
    ids = set()
    for level in levels:
        if not isinstance(level, dict) or not isinstance(level.get("id"), str) or not level["id"] or level["id"] in ids:
            raise ValueError("Unique nonempty level IDs required")
        ids.add(level["id"])
        if not isinstance(level.get("aisle", "A1"), str) or not level.get("aisle", "A1"):
            raise ValueError("Nonempty aisle ID required")
        finite(level.get("heightM"), "heightM", 1e-9)
        capacity = integer(level.get("storageCapacity"), "storageCapacity", 1)
        integer(level.get("initialStock"), "initialStock", 0, capacity)
    if sum(level["initialStock"] for level in levels) > 20000:
        raise ValueError("Maximum initial stock: 20000")
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
    aisle_ids = sorted({level.get("aisle", "A1") for level in data["levels"]})
    lift_keys = {a: "lift" if len(aisle_ids) == 1 else "lift-" + a for a in aisle_ids}
    lift_units = {a: [{"id": a + "-H" + str(i+1), "height": 0.0, "busy": False} for i in range(data.get("liftsPerAisle", 1))] for a in aisle_ids}
    counts = {"stored": 0, "picked": 0, "retrieved": 0, "returned": 0}

    def resource(key, capacity):
        resources[key] = sim.Resource(name=key, capacity=capacity, env=env)
        metrics[key] = {"capacity": capacity, "occupancy": 0, "maximumOccupancy": 0, "area": 0.0, "last": 0.0, "blockedSeconds": 0.0}

    for key, capacity in [("infeed", 1), ("in-buffer", data["inBufferCapacity"]), ("out-buffer", data["outBufferCapacity"]), ("outfeed", 1), ("workstation", 1)]:
        resource(key, capacity)
    for aisle in aisle_ids:
        resource(lift_keys[aisle], data.get("liftsPerAisle", 1))
    if data.get("returnToStorage"):
        resource("return", data["returnCapacity"])
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
            trace.append({"time": env.now(), "job": record["id"], "type": record["type"], "stage": record["stage"], "resources": {k: m["occupancy"] for k, m in metrics.items()}, "stock": dict(physical), "putaway": counts["stored"], "retrieved": counts["retrieved"], "returned": counts["returned"]})

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

        def acquire_lift(self):
            self.aisle = definitions[self.job["level"]].get("aisle", "A1")
            yield from self.acquire(lift_keys[self.aisle])
            self.lift_unit = next(unit for unit in lift_units[self.aisle] if not unit["busy"])
            self.lift_unit["busy"] = True
            self.lift_started = env.now()
            self.record["liftUnit"] = self.lift_unit["id"]

        def release_lift(self):
            rate = data["lift"].get("rateBEhPerUnit")
            if rate:
                yield self.hold(max(0, 3600 / rate - (env.now() - self.lift_started)))
            self.lift_unit["busy"] = False
            self.release_node(lift_keys[self.aisle])

        def move_lift(self, target):
            lift = data["lift"]
            seconds = travel(abs(target - self.lift_unit["height"]), lift["speedMps"], lift["accelerationMps2"], lift["decelerationMps2"])
            yield self.hold(seconds)
            self.lift_unit["height"] = target

        def return_container(self, key, height):
            # Return to the same level via the shared infeed/lift/shuttle path.
            r = self.record
            r["waitingSince"], r["waitingHeld"] = env.now(), list(r["held"])
            self.mark("waiting:storage-slot")
            yield self.request(rack[key])
            for held in r["waitingHeld"]:
                metrics[held]["blockedSeconds"] += env.now() - r["waitingSince"]
            r["waitingSince"], r["waitingHeld"] = None, []
            yield from self.acquire("infeed")
            self.release_node("return")
            yield self.hold(data["infeedSeconds"])
            yield from self.acquire("in-buffer")
            self.release_node("infeed")
            yield from self.acquire_lift()
            yield from self.move_lift(0)
            yield self.hold(data["lift"].get("pickupSeconds", data["pickupSeconds"]))
            self.release_node("in-buffer")
            yield from self.move_lift(height)
            yield from self.acquire("level-in-" + key)
            yield self.hold(data["lift"].get("dropoffSeconds", data["dropoffSeconds"]))
            yield from self.release_lift()
            yield from self.acquire("shuttle-" + key)
            yield self.hold(data["pickupSeconds"])
            self.release_node("level-in-" + key)
            seconds = data["shuttleCycleSeconds"]
            if data.get("shuttleRateBEhPerUnit"):
                seconds = max(seconds, 3600 / data["shuttleRateBEhPerUnit"])
            yield self.hold(seconds)
            physical[key] += 1
            yield self.to_store(stock[key], sim.Component(env=env))
            self.release_node("shuttle-" + key)

        def process(self):
            job, key = self.job, self.job["level"]
            r = self.record = {**job, "completedAt": None, "stage": "arrival", "held": [], "waitingSince": None, "waitingHeld": []}
            records[job["id"]] = r
            self.mark("arrival")
            height = definitions[key]["heightM"]
            shuttle_time = data["shuttleCycleSeconds"] + job["relocations"] * data["relocationSeconds"]
            if data.get("shuttleRateBEhPerUnit"):
                shuttle_time = max(shuttle_time, 3600 / data["shuttleRateBEhPerUnit"])
            if job["type"] == "putaway":
                self.mark("waiting:storage-slot")
                yield self.request(rack[key])
                yield from self.acquire("infeed")
                yield self.hold(data["infeedSeconds"])
                yield from self.acquire("in-buffer")
                self.release_node("infeed")
                yield from self.acquire_lift()
                yield from self.move_lift(0)
                yield self.hold(data["lift"].get("pickupSeconds", data["pickupSeconds"]))
                self.release_node("in-buffer")
                yield from self.move_lift(height)
                yield from self.acquire("level-in-" + key)
                yield self.hold(data["lift"].get("dropoffSeconds", data["dropoffSeconds"]))
                yield from self.release_lift()
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
                yield from self.acquire_lift()
                yield from self.move_lift(height)
                yield self.hold(data["lift"].get("pickupSeconds", data["pickupSeconds"]))
                self.release_node("level-out-" + key)
                yield from self.move_lift(0)
                yield from self.acquire("out-buffer")
                yield self.hold(data["lift"].get("dropoffSeconds", data["dropoffSeconds"]))
                yield from self.release_lift()
                yield from self.acquire("outfeed")
                self.release_node("out-buffer")
                yield self.hold(data["outfeedSeconds"])
                yield from self.acquire("workstation")
                self.release_node("outfeed")
                yield self.hold(data["workstationSeconds"])
                counts["retrieved"] += 1
                r["retrievedAt"] = env.now()
                self.mark("workstation-complete")
                if data.get("returnToStorage"):
                    r["phase"] = "return"
                    yield from self.acquire("return")
                self.release_node("workstation")
                if data.get("returnToStorage"):
                    yield self.hold(data["returnSeconds"])
                    yield from self.return_container(key, height)
                    counts["returned"] += 1
                    r["returnedAt"] = env.now()
            if job["type"] == "putaway":
                counts["stored"] += 1
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
    if initial + put + counts["returned"] - retrieved_picked != sum(physical.values()):
        raise AssertionError("Physical inventory conservation violated")
    snapshot({"id": "measurement", "type": "system", "stage": "measurement-end"})
    if any(not 0 <= physical[k] <= definitions[k]["storageCapacity"] for k in physical):
        raise AssertionError("Storage capacity violated")
    if len(records) != len(data["jobs"]):
        raise AssertionError("Transport arrivals not conserved")
    flows = [r["completedAt"] - r["arrivalSeconds"] for r in completed]
    return {"modelVersion": "kx-coupled-0.3", "dataStatus": "synthetic", "evidenceStatus": "reference_only", "inputSha256": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(), "durationSeconds": horizon,
            "topology": {"aisles": len(aisle_ids), "liftsPerAisle": data.get("liftsPerAisle", 1), "totalLifts": sum(len(v) for v in lift_units.values()), "shuttles": len(definitions)},
            "arrived": len(records), "completed": len(completed), "unfinished": len(records) - len(completed), "putawayCompleted": put, "retrievalCompleted": counts["retrieved"], "returnCompleted": counts["returned"], "returnsPending": counts["retrieved"] - counts["returned"] if data.get("returnToStorage") else 0,
            "flowSeconds": {"mean": sum(flows) / len(flows) if flows else None, "p95": percentile(flows, .95)}, "resources": metrics,
            "inventory": {k: {"initial": definitions[k]["initialStock"], "physical": physical[k], "available": len(stock[k]), "reservedForRetrieval": physical[k] - len(stock[k]), "reservedForPutaway": rack[k].claimed_quantity() - physical[k], "capacity": definitions[k]["storageCapacity"]} for k in definitions},
            "balance": {"initialStock": initial, "stored": put, "returned": counts["returned"], "pickedForRetrieval": retrieved_picked, "finalPhysicalStock": sum(physical.values())},
            "jobs": [{k: v for k, v in r.items() if k not in ["waitingHeld", "waitingSince"]} for r in records.values()], "trace": trace, "traceTruncated": len(trace) >= 5000,
            "limits": ["Synthetic reference case only; no validated plant performance.", "Separate shared single-load lift pool per aisle; individual positions; one shuttle per level; FIFO; no optimized double cycles. Optional BE/h limits are nominal throughput budgets, not calibrated double-cycle mechanics.", "Shuttle cycle and extra relocation time are explicit assumptions, not inferred from ABC or supplier percentages.", "Putaway reserves a rack slot before entering infeed. Retrieval reserves stock, releases physical slot at the end of its shuttle cycle.", "Finite buffers retain upstream resources; unfinished jobs may be queued, blocked or deadlocked, not an automatic deadlock proof.", "Optional return loop sends every retrieved container to its original level via a finite return zone and shared infeed/lift/shuttle; no alternate-level policy, empty-container supply, failures, real WCS handshakes, continuous belt headway, SKU/ABC placement or calibrated multi-depth storage."]}


if __name__ == "__main__":
    try:
        print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=False, allow_nan=False))
    except (ValueError, TypeError, KeyError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
