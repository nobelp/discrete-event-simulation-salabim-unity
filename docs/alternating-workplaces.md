# Alternating carrier and individual workstation reference

The optional `alternating-in-out` lift dispatch policy keeps each physical carrier position and alternates one retrieval leg and one putaway leg. It does not optimize simultaneous two-load movements or implement a vendor stop mix. Idle carriers can wait for the opposite direction; `liftDispatchWaits` exposes this separately. Completed logical putaway/retrieval pairs are reported in `liftCycles`; an initial retrieval bootstrap is not a completed pair.

Explicit retrieval workstation targets create separate capacity-one resources and counters, alongside the aggregate workstation pool. If any retrieval has a target, every retrieval must have a valid target. Aggregate utilization must not sum both resource representations.

Reference tests cover hand-calculated pairs, opposite-direction waiting, a finite closed-return case and five explicit workstation targets. Dense loads may still block with finite transfer buffers; passing these cases is not validation of real WCS rules, optimized double cycles or plant performance. Initial stock validation permits up to 100000 bins; actual capacity and per-level stock checks still apply.

## Optional waiting buffers at individually assigned workplaces

`workstationBufferCapacity` adds this many finite waiting slots per workplace, in addition to its capacity-one processing position. Every retrieval must have an explicit workstation target. The common outfeed releases a container once admitted to its target waiting buffer; a full target buffer holds the common outfeed and can block other destinations. Once processing starts the waiting slot is released. Return-zone admission still occurs before releasing the processing position, so a full return zone can backpressure the station.

This is a FIFO handover reference, not a directed belt layout, bypass control, replenishment optimization or supplier WCS. Omitting the field retains direct handover. Buffer metrics and trace resources are `workplace-buffer-N`; do not include these waiting slots as additional workstation processing capacity.

Tests cover three waiting positions plus one processing position, release of common outfeed before a waiting job starts, subsequent target access, full-buffer backpressure, invalid capacities/missing targets and unchanged direct mode.
