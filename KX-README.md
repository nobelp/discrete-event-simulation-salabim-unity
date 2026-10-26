# KX extension of the Unity and Salabim conveyor prototype

This fork preserves the upstream Unity layout editor and adds a tested, headless
reference simulator. The first extension implements finite-capacity service nodes,
explicit routes, downstream reservation before upstream release, shared resources,
and structured JSON results. All included scenarios are synthetic.

This is an initial engineering foundation. It is not a commissioned conveyor model,
a coupled shuttle/lift model, a FEM implementation, or a validated system capacity
certificate. The Unity simulation button is now wired in source to a runtime form and the new Python bridge. The actual Unity editor/player build has not yet been verified.

## Windows quick start

Python 3.10 or newer is required for this extension. From the repository folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-kx.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m kx.simulation examples/kx-backpressure.json --output results/reference.json
```

The pinned and tested engine is Salabim 26.0.8. No Unity installation or animation
window is required for these reference runs. Upstream's Unity project specifies
Unity 2022.3.11f1; the editor build has not been verified in this fork.

## What the reference case proves

Four transports arrive at t=0. An infeed service zone has one slot and a two-second
service time. The downstream workstation has one slot and an eight-second service
time. A hand schedule gives completion times 10, 18, 26 and 34 seconds.

At the 30-second measurement end:

| Metric | Reference result |
|---|---:|
| Arrived | 4 |
| Completed | 3 |
| Unfinished | 1 |
| Infeed blocked slot-seconds | 18 |
| Maximum occupancy per node | 1 |

The hourly rate in the JSON is a scaled count over the measured finite interval,
not a steady-state capacity estimate. Completed-flow percentiles exclude unfinished
jobs; their age and state are reported separately. The measurement includes
completions exactly at its endpoint and has no warmup phase.

`capacity` describes total service slots occupied by processing or blocked jobs.
With capacity above one, service is parallel. This does not establish physical belt
headway, pitch, zone control, or multi-load lift behavior. No implicit factors or
vendor capacities are substituted for missing inputs. The runner currently accepts
only scenarios explicitly marked `dataStatus: "synthetic"`.

## Closed single-slot deadlocks

Model version `kx-service-network-0.2` reports a `deadlockDiagnostic` in each result.
It identifies closed cycles in which every transport holds a single-slot node while
waiting for a single-slot node held by the next transport in the cycle. The model
has no forced releases, capacity changes or timeouts that could resolve such a cycle.

```powershell
.\.venv\Scripts\python.exe -m kx.simulation examples/kx-deadlock.json --output results/deadlock.json
```

In this synthetic case two transports enter opposite zones at time zero, finish
service at one second, and each waits for the other's zone. At ten seconds the
result retains both unfinished transports and reports their held/waiting nodes.
Ordinary queues, long service times and finite-horizon WIP are not classified as
deadlocks merely because transports remain unfinished. Multi-slot networks are
explicitly outside this diagnostic's scope: no detected cycle is not proof that
such a network is deadlock-free. Thirteen tests now cover the reference runner,
including closed cycles, noncyclic upstream waiters and these scope limits.

## Import the existing Unity layout

```powershell
.\.venv\Scripts\python.exe -m kx.import_layout unity/simulation.json --output results/unity-topology-draft.json
```

The draft retains component IDs, screen coordinates and connection endpoints. It
sets physical lengths, speeds, useful capacities and service times to null and
marks connection directions for confirmation. It cannot be executed as a physical
simulation without further modelling. This avoids treating pixels as metres or
one upstream animation object as one confirmed buffer slot.

## Differences from the upstream prototype

Code review of upstream commit `0873dc9` found these constraints:

- Carrier movement uses ten position increments with one-second holds, not
  parameterized physical conveyor motion.
- Occupancy uses an `isFree` flag for each conveyor object; useful zone capacity,
  headway, and transfer protocols need dedicated modelling.
- The connection handler maps one continuation per conveyor. Branching, route
  choice and merge priorities require further design.
- The old runner reports the removal count as a process exit code. The extension
  uses JSON output and conventional success/error exit codes.
- Random state in the original carrier is seeded from wall-clock time. The new
  reference runner uses an explicit seed and preserves all input data in a hash.

## Next work

- Verify the new physical-input forms and directed-route bridge in an actual Unity editor/player build.
- Introduce physical segment lengths, speeds, pitch and start/stop dynamics.
- Add transfer occupancy, merge priorities, routing, finite buffers and WCS rules.
- Add calibrated lift/shuttle modules and controlled distribution scenarios.
- Add outages, time profiles, observation windows and statistical replications.
- Validate against independent hand calculations and measured systems.

Customer and supplier documents belong in a separate private project. Do not add
them, their extracted contents or client layouts to this public fork.

## License and attribution

The upstream repository is licensed under GPL-3.0. This fork retains its LICENSE,
history and attribution. The KX additions are distributed under that same license.
See [upstream](https://github.com/markus-senger/discrete-event-simulation-salabim-unity).

## Unity bridge and parameter entry

The existing simulation button opens `KxSimulationPanel`. Right-click a placed
conveyor to enter a stable zone ID, travel length in metres, constant speed in
metres per second, explicit additional transfer time, and allowed downstream IDs.
Connections must be explicitly confirmed, including an empty terminal list. Cloning
an already configured object resets its identity. Zone IDs are editable for routing;
changing an ID requires updating references. No values are inferred from pixels.

The first physical-time model is deliberately narrow: one complete zone can hold
one transport; service time is `lengthM / speedMps + transferSeconds`, and the zone
remains occupied until the next slot is available. This is constant-speed exclusive
zone movement, not a moving multi-load belt, acceleration model or validated plant.

Enter transports as `ID;arrivalSeconds;zone1,zone2` (one per line), confirm the
synthetic scenario, and run. Alternatively provide an existing `kx-unity-zones`
scenario file, such as `examples/kx-unity-zones.json`. The selected virtual-environment
Python and repository paths can be adjusted in the form. Input and result files
are retained under `Application.persistentDataPath/kx-runs/<unique-run-id>/`.
The old animation-speed input is disabled because it does not control simulated
physical time. The old animation/exit-code-count route is no longer used.

The C# bridge starts Python without a shell or visible helper window, reads JSON
rather than an exit-code count, reports invalid inputs, and limits a run to 60
seconds. The bridge can also be tested without Unity:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m kx.unity_bridge examples/kx-unity-zones.json --output results/unity-zones.json
dotnet run --project tests/csharp-check/SyntaxCheck.csproj -- "C:\path\to\this-fork"
```

Sixteen Python tests pass. The C# check compiles the new scripts against explicit
API-shape stubs and the repository's real JSON library, then calls the real process
bridge against Python: three completed transports, one unfinished; invalid format
rejected. This checks C# compilation and interprocess data exchange, **not** Unity
scene rendering, input events, serialization or a Windows player build. Unity
2022.3.11f1 is required for that remaining integration check.

## Coupled conveyor and container-store reference model

`kx/coupled.py` connects putaway and retrieval jobs through shared resources:

- Putaway: reserve a rack slot, infeed conveyor, finite ground input buffer,
  shared lift, finite level input buffer, level shuttle, stock entry.
- Retrieval: reserve available stock, level shuttle, finite level output buffer,
  shared lift, finite ground output buffer, outfeed conveyor, workstation.

There is one single-load lift for both directions; its actual last height is kept.
Rest-to-rest triangular/trapezoidal motion uses explicitly provided velocity,
acceleration and deceleration. Each level has its own shuttle. Shuttle service is
an explicit assumed cycle time plus a specified number of relocation operations
multiplied by an explicit additional time. No ABC distribution is inferred.
Inventory tokens, physically occupied rack places and reservations are distinct.
Retrieval releases its physical rack slot at the end of the shuttle cycle; a
putaway becomes available stock after its shuttle cycle. This timing convention
is part of the reference model and requires calibration for a real system.

Blocking after service retains upstream resources when downstream buffers are
full. The result includes time-stamped resource/stock snapshots, completed and
unfinished jobs by direction, physical stock balance, reservations, maximum/mean
occupancy and blocked resource time. In this coupled model an unfinished queue
is not automatically diagnosed as a deadlock. FIFO admission and pre-reservation
of storage space are explicit reference WCS assumptions.

Only synthetic input is enabled. No double cycles, SKU/ABC stock placement,
calibrated multi-depth shuttle mechanics, failures or supplier guarantees are
implied. A container can visit the workstation once in a retrieval; automatic
return/re-putaway orders are not yet generated.

For a CLI run, send `examples/kx-coupled.json` to stdin of `python -m kx.coupled`.
Eight coupled-model tests include independent single-job hand calculations,
shared lift and inventory conservation, upstream backpressure from a slow
workstation, no phantom stock/space, new putaway supplying a waiting retrieval,
and explicit relocation-time sensitivity. The complete Python suite now has
24 passing tests. The private KX browser application uses this same module in an
isolated local subprocess and provides a material-flow diagram and event replay.
