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
from .cycle_times import travel


def integer(value, name, minimum=0, maximum=100000):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name}: integer {minimum}..{maximum} required")
    return value


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
    integer(data.get("workstationCapacity", 1), "workstationCapacity", 1, 100)
    stops = data.get("workstationStops", [])
    if not isinstance(stops, list) or len(stops) > 100:
        raise ValueError("workstationStops: at most 100 explicit intervals required")
    previous_end = -1
    for stop in stops:
        if not isinstance(stop, list) or len(stop) != 2:
            raise ValueError("workstationStops: [startSeconds,endSeconds] required")
        start, end = finite(stop[0], "stop start"), finite(stop[1], "stop end")
        if start >= end or start >= horizon or start < previous_end:
            raise ValueError("Workstation stops must be sorted, nonoverlapping, positive-length and start before measurement end")
        previous_end = end
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
    integer(lift.get("loadCapacity", 1), "lift loadCapacity", 1, 2)
    if lift.get("loadCapacity", 1) == 2:
        if lift.get("dispatchPolicy") != "same-level-fifo-batch":
            raise ValueError("Two-load lift needs explicit same-level-fifo-batch reference policy")
        finite(lift.get("batchWaitSeconds"), "batchWaitSeconds")
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
    if "returnLevel" in data and (not isinstance(data["returnLevel"], str) or data["returnLevel"] not in ids):
        raise ValueError("returnLevel must identify an existing storage level")
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
    batch_queues = {a: [] for a in aisle_ids}
    batch_workers, worker_records, lift_batches = [], [], []

    def resource(key, capacity):
        resources[key] = sim.Resource(name=key, capacity=capacity, env=env)
        metrics[key] = {"capacity": capacity, "occupancy": 0, "maximumOccupancy": 0, "area": 0.0, "last": 0.0, "blockedSeconds": 0.0, "serviceSeconds": 0.0, "rateWaitSeconds": 0.0, "visits": 0}

    for key, capacity in [("infeed", 1), ("in-buffer", data["inBufferCapacity"]), ("out-buffer", data["outBufferCapacity"]), ("outfeed", 1), ("workstation", data.get("workstationCapacity", 1))]:
        resource(key, capacity)
    metrics["workstation"].update(scheduledDowntimeSeconds=sum(max(0, min(horizon, end)-start) for start, end in data.get("workstationStops", [])), pausedOccupiedSeconds=0.0, processingSeconds=0.0)
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
            metrics[key]["visits"] += 1
            change(key, 1)
            self.mark(key)

        def release_node(self, key):
            # Keep accounting separate from salabim's resource method.
            change(key, -1)
            self.record["held"].remove(key)
            super().release(resources[key])

        def acquire_lift(self, level=None):
            self.aisle = definitions[level or self.job["level"]].get("aisle", "A1")
            yield from self.acquire(lift_keys[self.aisle])
            self.lift_unit = next(unit for unit in lift_units[self.aisle] if not unit["busy"])
            self.lift_unit["busy"] = True
            self.lift_started = env.now()
            self.record["returnLiftUnit" if self.record.get("phase") == "return" else "liftUnit"] = self.lift_unit["id"]

        def release_lift(self):
            rate = data["lift"].get("rateBEhPerUnit")
            if rate:
                yield from self.service(lift_keys[self.aisle], max(0, 3600 / rate - (env.now() - self.lift_started)), rate_wait=True)
            self.lift_unit["busy"] = False
            self.release_node(lift_keys[self.aisle])

        def service(self, key, seconds, rate_wait=False):
            # Count only time actually inside the measurement window.
            metrics[key]["rateWaitSeconds" if rate_wait else "serviceSeconds"] += max(0, min(seconds, horizon-env.now()))
            yield self.hold(seconds)

        def shuttle_cycle(self, key, seconds):
            yield from self.service("shuttle-"+key, seconds)
            if data.get("shuttleRateBEhPerUnit"):
                yield from self.service("shuttle-"+key, max(0, 3600/data["shuttleRateBEhPerUnit"]-seconds), rate_wait=True)

        def move_lift(self, target):
            lift = data["lift"]
            seconds = travel(abs(target - self.lift_unit["height"]), lift["speedMps"], lift["accelerationMps2"], lift["decelerationMps2"])
            yield from self.service(lift_keys[self.aisle], seconds)
            self.lift_unit["height"] = target

        def transfer_lift(self, origin, target, source, destination, level):
            if data["lift"].get("loadCapacity", 1) == 1:
                yield from self.acquire_lift(level)
                yield from self.move_lift(origin)
                yield from self.service(lift_keys[self.aisle], data["lift"].get("pickupSeconds", data["pickupSeconds"]))
                self.release_node(source)
                yield from self.move_lift(target)
                yield from self.acquire(destination)
                yield from self.service(lift_keys[self.aisle], data["lift"].get("dropoffSeconds", data["dropoffSeconds"]))
                yield from self.release_lift()
                return
            aisle = definitions[level].get("aisle", "A1")
            request = {"transport": self, "origin": origin, "target": target,
                       "source": source, "destination": destination, "level": level}
            self.record["waitingSince"] = env.now()
            self.record["waitingHeld"] = list(self.record["held"])
            self.mark("waiting:two-load-lift")
            batch_queues[aisle].append(request)
            for worker in batch_workers:
                if worker.aisle_id == aisle and worker.ispassive() and not worker.delivering:
                    worker.activate()
                    break
            yield self.passivate()  # Carrier has arrived at the destination.
            yield from self.acquire(destination)  # This transport owns its buffer slot.
            request["worker"].activate()
            yield self.passivate()  # Individual handover must finish before onward travel.

        def return_container(self, key, height):
            # Return to the explicit target via the shared infeed/lift/shuttle path.
            r = self.record
            r["waitingSince"], r["waitingHeld"] = env.now(), list(r["held"])
            self.mark("waiting:storage-slot")
            yield self.request(rack[key])
            for held in r["waitingHeld"]:
                metrics[held]["blockedSeconds"] += env.now() - r["waitingSince"]
            r["waitingSince"], r["waitingHeld"] = None, []
            yield from self.acquire("infeed")
            self.release_node("return")
            yield from self.service("infeed", data["infeedSeconds"])
            yield from self.acquire("in-buffer")
            self.release_node("infeed")
            yield from self.transfer_lift(0, height, "in-buffer", "level-in-" + key, key)
            yield from self.acquire("shuttle-" + key)
            yield from self.service("shuttle-"+key, data["pickupSeconds"])
            self.release_node("level-in-" + key)
            yield from self.shuttle_cycle(key, data["shuttleCycleSeconds"])
            physical[key] += 1
            yield self.to_store(stock[key], sim.Component(env=env))
            self.release_node("shuttle-" + key)

        def process_workstation(self):
            # The workstation may hold one container while stopped. Processing
            # resumes with its remaining service time, without restarting it.
            remaining = data["workstationSeconds"]
            while remaining > 0:
                now = env.now()
                stop = next(((start, end) for start, end in data.get("workstationStops", []) if end > now), None)
                if stop and stop[0] <= now:
                    self.mark("workstation-stopped")
                    metrics["workstation"]["pausedOccupiedSeconds"] += max(0, min(horizon, stop[1])-now)
                    yield self.hold(stop[1]-now)
                    continue
                seconds = min(remaining, stop[0]-now) if stop else remaining
                self.mark("workstation-processing")
                metrics["workstation"]["processingSeconds"] += max(0, min(horizon-now, seconds))
                yield from self.service("workstation", seconds)
                remaining -= seconds

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
                yield from self.service("infeed", data["infeedSeconds"])
                yield from self.acquire("in-buffer")
                self.release_node("infeed")
                yield from self.transfer_lift(0, height, "in-buffer", "level-in-" + key, key)
                yield from self.acquire("shuttle-" + key)
                yield from self.service("shuttle-"+key, data["pickupSeconds"])
                self.release_node("level-in-" + key)
                yield from self.shuttle_cycle(key, shuttle_time)
                physical[key] += 1
                yield self.to_store(stock[key], sim.Component(env=env))
                self.release_node("shuttle-" + key)
            else:
                self.mark("waiting:available-stock")
                yield self.from_store(stock[key])
                yield from self.acquire("shuttle-" + key)
                yield from self.shuttle_cycle(key, shuttle_time)
                physical[key] -= 1
                counts["picked"] += 1
                rack[key].release(1)
                yield from self.acquire("level-out-" + key)
                yield from self.service("shuttle-"+key, data["dropoffSeconds"])
                self.release_node("shuttle-" + key)
                yield from self.transfer_lift(height, 0, "level-out-" + key, "out-buffer", key)
                yield from self.acquire("outfeed")
                self.release_node("out-buffer")
                yield from self.service("outfeed", data["outfeedSeconds"])
                yield from self.acquire("workstation")
                self.release_node("outfeed")
                yield from self.process_workstation()
                counts["retrieved"] += 1
                r["retrievedAt"] = env.now()
                self.mark("workstation-complete")
                if data.get("returnToStorage"):
                    r["phase"] = "return"
                    yield from self.acquire("return")
                self.release_node("workstation")
                if data.get("returnToStorage"):
                    yield self.hold(data["returnSeconds"])
                    target = data.get("returnLevel", key)
                    r["returnLevel"] = target
                    yield from self.return_container(target, definitions[target]["heightM"])
                    counts["returned"] += 1
                    r["returnedAt"] = env.now()
            if job["type"] == "putaway":
                counts["stored"] += 1
            r["completedAt"] = env.now()
            self.mark("complete")

    class BatchLift(Transport):
        """One physical carrier, two slots; explicit non-optimized reference dispatch."""
        def setup(self, aisle):
            self.aisle_id = aisle
            self.delivering = False

        def process(self):
            queue = batch_queues[self.aisle_id]
            while True:
                while not queue:
                    yield self.passivate()
                first = queue.pop(0)
                self.delivering = True
                # Wait before claiming the carrier; never wait indefinitely for a pair.
                yield self.hold(data["lift"]["batchWaitSeconds"])
                batch = [first]
                partner = next((r for r in queue if r["origin"] == first["origin"]
                                and r["target"] == first["target"]
                                and r["destination"] == first["destination"]), None)
                if partner is not None:
                    queue.remove(partner)
                    batch.append(partner)
                self.job = {"level": first["level"]}
                self.record = {"id": "lift-batch-" + str(len(lift_batches)+1),
                               "type": "lift-batch", "stage": "dispatch", "held": [],
                               "waitingSince": None, "waitingHeld": []}
                worker_records.append(self.record)
                report = {"id": self.record["id"], "dispatchAt": env.now(),
                          "jobs": [r["transport"].job["id"] for r in batch],
                          "originM": first["origin"], "targetM": first["target"],
                          "loaded": 0, "unloaded": 0, "completedAt": None}
                lift_batches.append(report)
                yield from self.acquire_lift(first["level"])
                report["liftUnit"] = self.lift_unit["id"]
                yield from self.move_lift(first["origin"])
                for request in batch:
                    transport = request["transport"]
                    yield from self.service(lift_keys[self.aisle], data["lift"].get("pickupSeconds", data["pickupSeconds"]))
                    record = transport.record
                    for held in record["waitingHeld"]:
                        metrics[held]["blockedSeconds"] += env.now()-record["waitingSince"]
                    record["waitingSince"], record["waitingHeld"] = None, []
                    transport.release_node(request["source"])
                    record["returnLiftUnit" if record.get("phase") == "return" else "liftUnit"] = self.lift_unit["id"]
                    report["loaded"] += 1
                    transport.mark("two-load-lift-loaded")
                yield from self.move_lift(first["target"])
                rate = data["lift"].get("rateBEhPerUnit")
                if rate:
                    drop_time = data["lift"].get("dropoffSeconds", data["dropoffSeconds"])
                    yield from self.service(lift_keys[self.aisle], max(0, 3600*len(batch)/rate-(env.now()-self.lift_started)-len(batch)*drop_time), rate_wait=True)
                for request in batch:
                    transport = request["transport"]
                    request["worker"] = self
                    self.record["waitingSince"] = env.now()
                    self.record["waitingHeld"] = [lift_keys[self.aisle]]
                    self.mark("waiting:two-load-drop-buffer")
                    transport.activate()
                    yield self.passivate()
                    metrics[lift_keys[self.aisle]]["blockedSeconds"] += env.now()-self.record["waitingSince"]
                    self.record["waitingSince"], self.record["waitingHeld"] = None, []
                    yield from self.service(lift_keys[self.aisle], data["lift"].get("dropoffSeconds", data["dropoffSeconds"]))
                    report["unloaded"] += 1
                    transport.mark("two-load-lift-unloaded")
                    transport.activate()
                self.lift_unit["busy"] = False
                self.release_node(lift_keys[self.aisle])
                report["completedAt"] = env.now()
                self.delivering = False

    snapshot({"id": "initial", "type": "system", "stage": "simulation-start"})
    if data["lift"].get("loadCapacity", 1) == 2:
        for aisle in aisle_ids:
            for _ in range(data.get("liftsPerAisle", 1)):
                batch_workers.append(BatchLift(aisle=aisle, env=env))
    for job in data["jobs"]:
        Transport(job=job, at=job["arrivalSeconds"], env=env)
    env.run(till=horizon, priority=math.inf)
    for record in list(records.values()) + worker_records:
        if record["waitingSince"] is not None:
            for held in record["waitingHeld"]:
                metrics[held]["blockedSeconds"] += horizon - record["waitingSince"]
    for m in metrics.values():
        m["area"] += m["occupancy"] * (horizon - m["last"])
        m["meanOccupancy"] = m["area"] / horizon
        m["occupiedFraction"] = m["area"] / (horizon * m["capacity"])
        denominator = horizon*m["capacity"]
        m["serviceFraction"] = m["serviceSeconds"]/denominator
        m["blockedFraction"] = m["blockedSeconds"]/denominator
        m["rateWaitFraction"] = m["rateWaitSeconds"]/denominator
        m["pausedFraction"] = m.get("pausedOccupiedSeconds",0)/denominator
        residual = m["area"]-m["serviceSeconds"]-m["blockedSeconds"]-m["rateWaitSeconds"]-m.get("pausedOccupiedSeconds",0)
        if residual < -1e-6:
            raise AssertionError("Overlapping resource-state accounting")
        m["otherHeldFraction"] = max(0,residual)/denominator
        m["idleFraction"] = 1-m["occupiedFraction"]
    groups = {"conveyors": ["infeed","outfeed"], "lifts": list(lift_keys.values()), "rocketShuttles": ["shuttle-"+k for k in definitions], "workplaces": ["workstation"]}
    domain_metrics = {}
    for name, keys in groups.items():
        capacity = sum(metrics[k]["capacity"] for k in keys)
        domain_metrics[name] = {"resources":keys,"capacity":capacity,"visits":sum(metrics[k]["visits"] for k in keys)}
        for field in ["occupiedFraction","serviceFraction","blockedFraction","rateWaitFraction","pausedFraction","otherHeldFraction","idleFraction"]:
            domain_metrics[name][field] = sum(metrics[k][field]*metrics[k]["capacity"] for k in keys)/capacity
        domain_metrics[name]["maximumSingleResourceOccupancy"] = max(metrics[k]["occupiedFraction"] for k in keys)
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
    ages = [horizon-r["arrivalSeconds"] for r in records.values() if r["completedAt"] is None]
    events = {0: [0, 0], horizon: [0, 0]}
    for r in records.values():
        events.setdefault(r["arrivalSeconds"], [0, 0])[0] += 1
        if r["completedAt"] is not None:
            events.setdefault(r["completedAt"], [0, 0])[1] += 1
    outstanding, maximum, area, previous, timeline = 0, 0, 0.0, 0.0, []
    for time, (arrivals, completions) in sorted(events.items()):
        area += outstanding * (time-previous)
        outstanding += arrivals-completions
        if outstanding < 0:
            raise AssertionError("Negative order backlog")
        maximum = max(maximum, outstanding)
        timeline.append({"time": time, "outstanding": outstanding, "arrivals": arrivals, "completions": completions})
        previous = time
    if outstanding != len(ages):
        raise AssertionError("Order backlog conservation violated")
    workload = {k:{"putaway":0,"retrieve":0,"plannedReturns":0,"relocations":{}} for k in definitions}
    for job in data["jobs"]:
        workload[job["level"]][job["type"]] += 1
        if job["type"] == "retrieve":
            bucket = workload[job["level"]]["relocations"]
            bucket[str(job["relocations"])] = bucket.get(str(job["relocations"]),0)+1
            if data.get("returnToStorage"):
                workload[data.get("returnLevel",job["level"])]["plannedReturns"] += 1
    return {"modelVersion": "kx-coupled-0.7", "dataStatus": "synthetic", "evidenceStatus": "reference_only", "inputSha256": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(), "durationSeconds": horizon,
            "topology": {"aisles": len(aisle_ids), "liftsPerAisle": data.get("liftsPerAisle", 1), "totalLifts": sum(len(v) for v in lift_units.values()), "shuttles": len(definitions), "liftLoadCapacity": data["lift"].get("loadCapacity", 1)},
            "liftBatches": lift_batches,
            "arrived": len(records), "completed": len(completed), "unfinished": len(records) - len(completed), "putawayCompleted": put, "retrievalCompleted": counts["retrieved"], "returnCompleted": counts["returned"], "returnsPending": counts["retrieved"] - counts["returned"] if data.get("returnToStorage") else 0,
            "flowSeconds": {"count": len(flows), "mean": sum(flows) / len(flows) if flows else None, "p95": percentile(flows, .95), "p99": percentile(flows, .99), "max": max(flows) if flows else None}, "resources": metrics, "domains": domain_metrics, "workloadByLevel": workload,
            "pendingAgeSeconds": {"count": len(ages), "mean": sum(ages)/len(ages) if ages else None, "max": max(ages) if ages else None, "p95": percentile(ages, .95), "p99": percentile(ages, .99)},
            "backlog": {"atEnd": outstanding, "maximum": maximum, "timeWeightedMean": area/horizon, "timeline": timeline, "completionBoundary": "return-stored" if data.get("returnToStorage") else "putaway-stored-or-workplace-processed", "percentileMethod": "nearest-rank; completed flow times exclude unfinished jobs; pending ages reported separately"},
            "inventory": {k: {"initial": definitions[k]["initialStock"], "physical": physical[k], "available": len(stock[k]), "reservedForRetrieval": physical[k] - len(stock[k]), "reservedForPutaway": rack[k].claimed_quantity() - physical[k], "capacity": definitions[k]["storageCapacity"]} for k in definitions},
            "balance": {"initialStock": initial, "stored": put, "returned": counts["returned"], "pickedForRetrieval": retrieved_picked, "finalPhysicalStock": sum(physical.values())},
            "jobs": [{k: v for k, v in r.items() if k not in ["waitingHeld", "waitingSince"]} for r in records.values()], "trace": trace, "traceTruncated": len(trace) >= 5000,
            "limits": ["Synthetic reference case only; no validated plant performance. Explicit workstation downtime pauses remaining service while keeping the container; no additional availability factor.", "Separate lift pool per aisle, individual positions, one shuttle per level. Default single-load; explicit two-load mode batches FIFO requests with identical origin/destination, shared physical travel, sequential handovers and bounded collection wait. No optimized mixed-direction double cycles or verified supplier WCS. Optional BE/h limits are nominal throughput budgets, not calibrated double-cycle mechanics.", "Shuttle cycle and extra relocation time are explicit assumptions, not inferred from ABC or supplier percentages.", "Putaway reserves a rack slot before entering infeed. Retrieval reserves stock, releases physical slot at the end of its shuttle cycle.", "Finite buffers retain upstream resources; unfinished jobs may be queued, blocked or deadlocked, not an automatic deadlock proof.", "Optional return loop sends every retrieved container to its original or explicitly selected level via a finite return zone and shared infeed/lift/shuttle; no automatic alternate-level policy, empty-container supply, stochastic failures, real WCS handshakes, continuous belt headway, SKU/ABC placement or calibrated multi-depth storage."]}


if __name__ == "__main__":
    try:
        print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=False, allow_nan=False))
    except (ValueError, TypeError, KeyError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
