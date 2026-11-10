# Workflow diagrams

The working map and reviewed map use the same locally bundled ELK layout engine and SVG renderer.
The diagram represents the participant's account. A symbol cannot establish a fact that was never
reported, and an attractive layout is not evidence that a process is complete.

## Components and meaning

| Component | Appearance | When it applies |
| --- | --- | --- |
| Activity | Rounded rectangle | A reported task or action; the default |
| Decision | Diamond | A reported test or choice; edge labels identify reported outcomes |
| Start | Capsule | An explicitly reported initiating event |
| End | Double-outline capsule | An explicitly reported terminal result for a route |
| Parallel split | Diamond marked + | All named branches begin concurrently or proceed independently |
| Join all | Diamond marked + | All reported parallel prerequisites must finish before proceeding |
| Merge alternatives | Diamond marked × | Any one of the reported alternative routes continues |
| Wait / event | D-shaped symbol | An explicit hold, delay or waiting-for-event step |
| Subprocess | Rectangle with inset vertical borders | A named procedure whose internal actions remain collapsed |
| Document | Wavy-bottom document | An action that creates, completes, sends or handles a document |
| Data store | Cylinder | An action that reads or writes a persistent register, log or database |

These are process-map conventions, not formal BPMN conformance. A document or system mentioned as an
input does not become an invented extra action. The first/last known task is not automatically a
start/end. Two approvals with unknown order do not imply either sequential or parallel execution.
Alternative branches may converge on an ordinary action or an explicit merge when needed to preserve
the routing logic; they do not require a join-all gateway. For example, an identity-check branch may
accept a document immediately or require correction. Those alternative outcomes converge before the
identity branch joins completed IT and facilities work; the join does not wait for both outcomes.

## Layout and navigation

Titles, owners, systems and branch conditions wrap by measured text width. Node height and edge-label
space expand before layout, including for long identifiers and Unicode text. No title or branch
condition is silently shortened with an ellipsis. Concise titles are encouraged during extraction;
full operating detail remains in the step dialog and evidence references. Unestablished owner/system
fields remain explicit in details without filling every shape with repeated placeholder text.

The layered layout routes orthogonal connections around nodes, with separate decision branches,
reported return loops, independent fragments and all-branch dependencies preserved. Rendering cannot
add, delete or reverse a process connection. Both horizontal and vertical orientations are available.
New canvases on narrow screens start vertically unless an orientation was explicitly supplied.

Large maps open at a readable starting point. Use **Fit** for the whole map, **Step** to locate an
action, **Follow path** to examine reported routes, and **Expand** for more room. Following a parallel
branch inspects that branch; it does not select one branch for execution or imply the others are
optional. The step dialog lists outgoing routes and their source references. **Diagram key** explains
only the components present in that map. Pan, zoom, orientation and selection do not call the model.

Keyboard users can Tab to steps, select with Enter/Space, move between steps with arrow keys, use
plus/minus to zoom, 0/Home for overview, F to follow a path, and Escape to leave path mode. SVG export
includes the complete diagram and every route, independent of the current zoom or path highlighting.
Dragging or pinching can begin on a component as well as the background. A short tap still opens
details. Fit includes every supported component even in an 80-step map; selecting a step restores
reading size. Transient selection borders are removed from exported diagrams.

If the diagram engine fails, captured components and exact reported routes remain available as a
full-text list. **Retry diagram** reloads only the bundled local assets as needed and retries layout;
it does not reload the interview or make a model request. SVG export resumes after successful layout.

## Cinematic map

Choose **Cinematic** in Interview or Review to see the whole process at once. Each of the eleven supported component types has a reusable dimensional symbol. Select any component to inspect it and its incoming and outgoing connections. Select a connector or its label to inspect the reported direction, condition and evidence. The selector above the map can locate any component or connection, including on a small screen. Use **Fit map** to return to the overview or **Expand cinematic map** for more space.

The browser uses the standard workflow's step IDs, types, labels and connections. A completed interview capture or draft edit refreshes the visualization and retains the selection while its component or connection exists. Layout, selection, zoom and directional animation run locally and add no AI request. The normal interview and extraction still use their configured providers. **Flow motion** illustrates the directions work can travel. It can be paused, and the map honors the device's reduced-motion preference.

## Component library

Open **Component library** in the session menu or above a cinematic map. Search by name or filter by family, then select a tile to see its enlarged artwork, purpose and identifying features. The same reusable drawings appear on the map and in the step inspector. The palette uses GPFS copper, taupe, Bermuda Grey and Feldspar against light neutral surfaces.

The 91 business designs cover operations such as waterfall calculations, investment discounts, cash application, beneficiary verification, migration, billing and preparation of an audit response. Eleven structural symbols describe the routing and record types. An explicitly captured document, data store or subprocess can carry an operational symbol on its corresponding base. Decisions, parallel gateways, waits, starts and ends retain their structural identity.

In a reviewed draft, select an eligible step and choose **Change design**. **Use this design** saves a presentation choice. **Use automatic design** restores local matching. **Save copy** retains those choices alongside the draft in the interview file. Replacing the draft starts a fresh set of choices. The working capture, interview evidence and provider requests stay independent of presentation preferences.

## Evidence, editing and bounds

Every generated component and connection needs participant evidence or scoped documentary citations. Documentary evidence remains distinct from participant confirmation. Incomplete decision
outcomes and parallel dependencies become open questions; validation does not fabricate routes to
make the symbols look complete. Working updates retain stable IDs and apply scoped changes as
described in [Workflow updates](WORKFLOW_UPDATES.md). Existing activity/decision interviews remain
compatible; all eleven types are preserved through saving, reopening, draft editing and export.

The supported map limit remains 80 components and 150 connections. A very large graph necessarily
needs pan/zoom or path navigation; fitting it all into a phone screen cannot preserve reading size.
Subprocesses are collapsed representations, not interactive nested diagrams. Actor labels identify
responsibility; the map does not claim to provide formal swimlanes or a workflow execution engine.

## Regression scenarios

The committed fictional fixtures in `tests/fixtures/workflow-scenarios.json` cover incoming requests,
nested approval/rework, multi-way routing, parallel preparation and synchronization, waiting and
timeouts, document/data operations, collapsed procedures, multi-stage retries, self-loops, unknown
boundaries and disconnected fragments, long/Unicode text, and an 80-component stress case.

`tests/test_workflow_scenarios.cjs` uses the actual bundled ELK engine in both orientations, checking
topology, node/label collisions, connector routing, order and text geometry. Browser checks use the
actual app and measured SVG glyph bounds at multiple viewport sizes. Synthetic provider checks
separately assess whether extraction preserves the narrative's meaning. See
[build verification](BUILD_VERIFICATION.md) for observed results and limitations.
