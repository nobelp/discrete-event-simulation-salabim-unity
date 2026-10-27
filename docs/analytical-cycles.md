# Explicit analytical reference cycles

`python -m kx.cycle_times` accepts one JSON object on stdin. This is a simplified, independently testable analytical reference, not a verified implementation of FEM 9.860. It does not automatically replace the coupled simulator's input cycle time.

Required format/version: `kx-analytical-cycles`, `1`. Motion contains `speedMps`, `accelerationMps2`, `decelerationMps2`. Specify `pickupSeconds`, `dropoffSeconds`, `singleAuxSeconds`, `doubleAuxSeconds` explicitly. `singlePoints` contains `{distanceM, probability}`; `doublePairs` contains `{putawayM, retrievalM, probability}`. Each probability set must sum to one, without normalization. Distances are measured from a common transfer origin.

Single cycle: twice the travel time plus one pickup, one dropoff and single auxiliary time. Double cycle: origin to putaway, putaway to retrieval, retrieval to origin, two pickups, two dropoffs and double auxiliary time. A double cycle moves two containers, one in each direction. Average the times before calculating hourly cycles; container movements per hour are twice the double-cycle rate.

Travel supports triangular/trapezoidal rest-to-rest motion, including different acceleration and deceleration. No jerk limit, physical channel clearing, multi-load elevator dispatch, blocking or availability effects are included. Independent hand calculations and input rejection are covered by `tests/test_cycle_times.py`.

The coupled simulation separately exports resource/domain service, blocked, nominal-rate waiting, paused, other-held and idle fractions. Domain fractions are weighted by resource capacity and observation time. They describe the generated workload and are not spare throughput or a system acceptance proof.
