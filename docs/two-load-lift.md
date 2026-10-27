# Two-load carrier reference

The coupled model defaults to one load per physical lift. To explicitly select the two-load reference, supply these fields inside `lift`:

```json
{"loadCapacity":2,"dispatchPolicy":"same-level-fifo-batch","batchWaitSeconds":2}
```

This models two container slots on a common moving carrier, not two independently moving elevators. Requests enter a queue per aisle. Each dispatcher selects the oldest request, waits the specified bounded collection time, and may take one additional ready request with the same origin, target and destination buffer. It then claims one physical lift, approaches the source once, picks up each container sequentially, travels once and hands containers over individually. A singleton departs after the bounded collection time. Collection time is explicit dispatch waiting outside the occupied lift; it is not active service.

Transfers release the requesting transport's source buffer only after pickup. Each transport reserves its own destination buffer before dropoff. A full destination retains the physical carrier and remaining loads, and the associated time is reported as blockage. The same path is used for putaway, retrieval and explicitly configured returns, including cross-aisle return destinations. Multiple physical lifts maintain separate positions and share the aisle queue.

If a nominal per-lift BE/h ceiling is supplied, a two-container batch consumes two container budgets; waiting is separate from physical service. The budget is applied before dropoffs so an entire batch cannot bypass it by completing early. Nominal ceilings are not calibrated cycle mechanics.

`topology.liftLoadCapacity` states the chosen capacity. `liftBatches` records dispatch time, origin/target, job IDs, physical lift ID, loaded/unloaded counts and completion time. An unfinished batch is retained rather than reported completed. Resource occupancy counts physical carriers; it does not double merely because a carrier holds two containers.

This is an explicit non-optimized comparison policy. It does not implement mixed-direction putaway/retrieval double cycles, different-height multipoint tours, independent or simultaneous LAM handovers, supplier WCS rules, FEM test cycles or a supplier's lift-stop distribution. Two same-direction containers in one trip are not an inbound/outbound double cycle. Site data and validated dispatch rules remain necessary for plant performance claims.

Eight dedicated tests cover a hand-calculated two-load trip, singleton progress and fresh initialization, differing destinations, finite-buffer blockage, multiple carriers and returns, explicit policy validation, nominal container budgeting, and cross-aisle return routing. Existing single-load tests remain unchanged.
