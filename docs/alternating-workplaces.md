# Alternating carrier and individual workstation reference

The optional `alternating-in-out` lift dispatch policy keeps each physical carrier position and alternates one retrieval leg and one putaway leg. It does not optimize simultaneous two-load movements or implement a vendor stop mix. Idle carriers can wait for the opposite direction; `liftDispatchWaits` exposes this separately. Completed logical putaway/retrieval pairs are reported in `liftCycles`; an initial retrieval bootstrap is not a completed pair.

Explicit retrieval workstation targets create separate capacity-one resources and counters, alongside the aggregate workstation pool. If any retrieval has a target, every retrieval must have a valid target. Aggregate utilization must not sum both resource representations.

Reference tests cover hand-calculated pairs, opposite-direction waiting, a finite closed-return case and five explicit workstation targets. Dense loads may still block with finite transfer buffers; passing these cases is not validation of real WCS rules, optimized double cycles or plant performance. Initial stock validation permits up to 100000 bins; actual capacity and per-level stock checks still apply.
