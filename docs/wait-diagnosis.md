# Finite-resource wait diagnosis

The coupled result now includes `waitDiagnostics`, a read-only measurement-end diagnosis. Waiting transports and lift dispatchers are linked to explicitly requested full resources; resource nodes link to their current holders. Iterative strongly-connected-component analysis identifies circular groups without recursion limits on long queues.

`closedCircularWaitCount` counts groups where every outgoing wait/holder edge remains inside the group. A cycle containing a resource with another active holder outside the group is circular but not closed: that holder may still release capacity. Unfilled resources do not create blocking wait edges. Up to 20 groups are detailed with participants, held resources and requested targets; total counts remain complete.

This is not a proof of a real-plant deadlock. Rack-slot/stock waits, external controls, WCS recovery, interventions and unmodeled dependencies are outside the diagnostic scope. Absence of a detected cycle is not a throughput or liveness guarantee.

`examples/closed-loop-wait-reference.json` reproduces one synthetic closed-loop blocking case: after finite arrivals, workstation, return buffer, infeed, input buffer, lift and outfeed resources form a closed waiting group. Another regression case shows lift/level-in/shuttle/level-out circular waiting without returns. These are permitted outcomes of the current blocking-after-service reference dispatch, not calibrated supplier behavior. Detection does not silently change routing, reservations, priority or inventory.

Seven tests cover a closed two-resource group, an active outside holder, nonfull/unknown resources, a 1500-resource chain, a finite workload that fully drains, the closed-return-loop case, and the bidirectional level-buffer case. Additional deterministic stress runs vary buffers, carrier counts and collection delays; every incomplete test workload has an identified closed group and all cases preserve inventory and finite capacities.
