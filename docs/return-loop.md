# Optional closed return loop

The synthetic `kx-coupled-0.3` model accepts `returnToStorage: true` only with an
explicit nonnegative `returnSeconds` and positive integer `returnCapacity`.
It returns every retrieved container to its original level. No plant data or
customer strategy is implied. The default remains a retrieval ending at the workplace.

After processing, the workplace remains occupied until a finite return-zone place
is available. The transport then spends the explicit transfer time there. It holds
that place while waiting for a free rack slot and until the shared infeed accepts it.
The return uses the existing infeed, input buffer, aisle lift pool, level input buffer
and shuttle. Normal capacity limits, travel times and nominal rate limits apply.
The return shuttle cycle uses the explicit base cycle, not the retrieval relocation count.

`retrievedAt` counts processing completed at the workplace. `returnedAt` and
`completedAt` count a complete return cycle. `retrievalCompleted` and `returnCompleted`
are separate; a return is not an external `putawayCompleted`. `returnsPending` counts
workplace-processed containers not yet returned. `unfinished` includes both initial
retrievals and pending returns; flow times measure complete cycles in return mode.

Inventory conservation is:

`initialStock + externalPutaways + returnsStored - retrievalsPicked = physicalRackStock`.

In-transit containers are not counted as physical rack stock. Return trips do not
reserve the original slot at retrieval: external putaways may fill it. A return can
therefore wait indefinitely for rack capacity and propagate backpressure. This is
an explicit reference policy, not a recommended or validated WCS policy.

Six independent tests cover the 11 s retrieval + 3 s return transfer + 8 s putaway
hand schedule, measurement-end open returns, reuse of returned stock, return-zone
backpressure, full-rack waiting, and required inputs. Full suite: 33 Python tests.
No alternate-level routing, empty-container supply, optimized double cycles,
SKU identities or actual WCS handshakes are implemented by this extension.
