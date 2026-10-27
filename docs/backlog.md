# Backlog and completed/censored flow samples

`kx-coupled-0.6` reports completed-only `flowSeconds` with count, mean, P95, P99
and maximum. Percentiles use the existing nearest-rank rule (sorted value at
ceil(p*n), one-based). Empty samples return null statistics, not zero.
Unfinished jobs are excluded from completed-flow percentiles and reported separately
in `pendingAgeSeconds`, measured from arrival until measurement end. These are
current ages, not predictions of their eventual completion times.

`backlog.timeline` aggregates all arrivals and complete-cycle departures at each
timestamp. Counts are after all events at that timestamp. It includes time zero and
measurement end. `maximum`, `timeWeightedMean` (exact step-function area divided by
duration), and `atEnd` describe the same order population. No sampling from the
5000-entry animation trace is used. Same-time events are combined rather than
creating a fictitious instantaneous extra backlog.

With returns enabled an order remains open until stored again; workplace processing
is an intermediate milestone. Otherwise completion is external putaway storage or
workplace processing. End backlog is checked against the number of unfinished jobs.
No acceptance criterion or general recovery-time claim is inferred.

Five independent tests cover an 11-second hand area, incomplete ages, simultaneous
events/empty sample, animation truncation, and the 22-second return-cycle boundary.
