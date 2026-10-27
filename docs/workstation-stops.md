# Explicit workstation stop intervals

`kx-coupled-0.4` accepts optional `workstationStops: [[120,180],[300,360]]`, in
seconds from simulation start. Intervals are sorted, nonoverlapping, half-open
`[start,end)` and have positive duration. A stop may extend past measurement end;
reported downtime is clipped to the measurement window. At most 100 intervals.

The workstation may accept one container while stopped. The container occupies
the workstation while processing is paused, propagating backpressure through
finite buffers. Processing resumes with the remaining service time; it does not
restart the whole service. A service completed exactly at stop start is complete.
An idle stop does not add a delay to later work. Return loops remain coupled.

The resource reports `scheduledDowntimeSeconds` (occupied or idle),
`pausedOccupiedSeconds` (stopped while holding a container), and `processingSeconds`
actually elapsed in the measurement window. These are distinct quantities.
Occupancy already includes stopped occupied time; no additional availability
factor is applied to throughput. The explicit schedule is not a random failure
distribution, repair-resource model or WCS handshake validation.

Six new independent tests cover service-start interruptions, resuming partial
service across multiple stops, idle downtime, measurement-end clipping, lift
backpressure with return conservation, and invalid schedules. Full suite: 39 tests.
