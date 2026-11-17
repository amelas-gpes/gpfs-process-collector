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
start/end in the map itself (the picture marks them; see Evidence and picture). Two approvals with unknown order do not imply either sequential or parallel execution.
Alternative branches may converge on an ordinary action or an explicit merge when needed to preserve
the routing logic; they do not require a join-all gateway. For example, an identity-check branch may
accept a document immediately or require correction. Those alternative outcomes converge before the
identity branch joins completed IT and facilities work; the join does not wait for both outcomes.

## Evidence and picture

The map the interview keeps is evidence: steps and connections a participant or a supplied file
stated, each with its sources. The rules above hold for it without exception. The first known
task is not typed as a start, the last is not typed as an end, and a branch the participant did
not name as a decision leaves an ordinary step. Maps read that way were hard to follow: of the
fourteen final maps of the November 17 stress run six had a start, one had an end and twelve had
branches leaving one point of a box.

The Workflow and Review diagrams therefore draw a **picture** of the evidence. It is derived each
time the map is drawn (`present` in `web/workflow-graph.js`) and adds three kinds of marker:

| Marker | Drawn as | When |
| --- | --- | --- |
| Start | Small dashed circle in front of the first step | The main route has no step the account itself states as the start |
| End | Small dashed circle with a heavier outline after a step | Nothing follows that step on the main route and it is not a stated end |
| Gateway | Small dashed diamond after a step | Several routes lead on from a step that is not itself a decision, split, join or merge; the routes and their captions leave the gateway |

A marker is not evidence and does not become any. It has an ID no step can have, cites no
source, is not a control, cannot be selected or followed, and is not saved, sent to the service
or written to a saved interview. The SVG file says of itself that its steps and routes carry their
evidence, so the markers are left out of it; the Mermaid, DOT and BPMN downloads are produced from
the evidence as before. The step list, the details panel, Follow path, the keyboard and the
screen-reader description speak of the reported steps and connections only. Steps that are not
joined to the main route are drawn as they are, detached, without markers. A map of a single
step, or of steps nobody connected, has no route to mark.

Not part of the picture yet: lanes by role, compact decision diamonds with the label outside,
a main path kept straight, positions that stay put between updates, and the open question of a
dead-end branch shown at that branch. An end marker says only that nothing reported follows.

## Layout and navigation

Titles, owners, systems and branch conditions wrap by measured text width. Node height and edge-label
space expand before layout, including for long identifiers and Unicode text. No title or branch
condition is silently shortened with an ellipsis. Concise titles are encouraged during extraction;
full operating detail remains in the step dialog and evidence references. Unestablished owner/system
fields remain explicit in details without filling every shape with repeated placeholder text.
A box is as wide as its longest line needs, up to the full width at which text wraps; decisions and
gateways keep their fixed diamond.

An arrow carries a caption in Diagram when it states a condition: every arrow out of a decision, and
every arrow out of a step that has more than one way out (including the branches of a parallel
split). The only way out of any other step is drawn as a plain arrow. Its recorded wording is not
discarded: it remains in the arrow's tooltip, in the exported SVG's arrow description and under
**Reported next steps** in the step dialog. Cinematic keeps its own captions.

Diagram places steps according to their reported connections. The order in which steps were listed
breaks ties between available steps. Rework and self-loops use separate return ports so the main
handoff remains visible. Both horizontal and vertical orientations are available. If a routed arrow
misses the port at either end, the text fallback shows the reported connections.
New canvases on narrow screens start vertically unless an orientation was explicitly supplied.

A process of eight or more steps whose single strip is much longer than the canvas can be folded
into rows (columns when vertical) aimed at the shape of the canvas. The strip is always calculated
first. The folded layout replaces it only when every arrow is still attached to its steps, nothing
overlaps or passes through another box or caption, it has no more crossings than the strip, and
**Fit** would show the whole map at least 15% larger; otherwise the strip is shown. A map with more
than 1.5 connections per step is not folded. Because the panel changes shape after the first drawing
and when the reply box opens or the map is expanded, the fold is decided again once the canvas has
kept a new shape for a moment; the map is redrawn only when that makes the whole map larger. Folding
makes a long map larger at **Fit**, but not reading size: use the opening view, **Step**, **Follow
path** or **Expand** to read.

Layout runs in a background worker shared by Diagram and Cinematic, so the page stays responsive.
A layout that is replaced by a newer map is stopped, and one that runs longer than eight seconds is
stopped and reported as a failed layout (see **Retry diagram** below). Maps with more than 60
connections use a faster, slightly less compact placement. Where the browser cannot start the
worker, layout runs in the page as before.

Large maps open at a readable starting point. Use **Fit** for the whole map, **Step** to locate an
action, **Follow path** to examine reported routes, and **Expand** for more room. Following a parallel
branch inspects that branch; it does not select one branch for execution or imply the others are
optional. The step dialog lists outgoing routes and their source references. **Diagram key** explains
only the components present in that map. Pan, zoom, orientation and selection do not call the model.

Panning by wheel, drag, arrow keys or the minimap stops while part of the map is still in view. At
that edge the mouse wheel scrolls the page instead; Ctrl or Cmd with the wheel always zooms the map.

When a new answer changes the map, the view stays on the steps the reader was looking at: a selected
step holds the view only while it is on screen, and an update never leaves an empty canvas. While
**Follow path** is on, the path is kept on the same steps even if the update gave them other
numbers. If the followed step was removed, the route behind it changed or the step now reads
differently, the path bar and the screen-reader status say so (“The map changed. Follow path was
reset.”, “… Follow path restarts at this step. …”, or the step's new title).

Keyboard users can Tab to steps, select with Enter/Space, move between steps with arrow keys, use
plus/minus to zoom, 0/Home for overview, F to follow a path, and Escape to leave path mode. A step
that takes keyboard focus off screen is brought into view at the current zoom in Diagram and
Cinematic. A click keeps the map in place. SVG export
includes the complete diagram and every route, independent of the current zoom or path highlighting.
Dragging or pinching can begin on a component as well as the background. A short tap still opens
details. Fit includes every supported component even in an 80-step map; selecting a step restores
reading size. Transient selection borders are removed from exported diagrams.

If the diagram engine fails, captured components and exact reported routes remain available as a
full-text list. **Retry diagram** reloads only the bundled local assets as needed and retries layout;
it does not reload the interview or make a model request. SVG export resumes after successful layout.

## Cinematic map

Choose **Cinematic** in Interview or Review to see the whole process at once. Each of the eleven supported component types has a reusable dimensional symbol. Select any component to inspect it and its incoming and outgoing connections. Select a connector or its label to inspect the reported direction, condition and evidence. The selector above the map can locate any component or connection, including on a small screen. Use **Fit map** to return to the overview or **Expand cinematic map** for more space.

Selecting a connection frames the source, destination and route together. A long, uninterrupted
chain can continue on the next row in the opposite direction, with a short arrow at the row end.
Decisions, joins, loops and separate groups use layered routing. Both views identify groups with
no recorded connection and keep them separate.

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

Under **Review → Steps → Connections between steps**, choose **From step** and **To step**
before adding a route. A step can return to itself. Different conditions can lead to the same
destination. Changing a route asks the reviewer whether the original sources still support it.
If an older saved graph repeats the same endpoints and condition, the maps show one arrow with
the combined citations. The underlying saved records remain available to review individually.

The supported map limit remains 80 components and 150 connections. A very large graph necessarily
needs pan/zoom or path navigation; fitting it all into a phone screen cannot preserve reading size.
Subprocesses are collapsed representations, not interactive nested diagrams. Actor labels identify
responsibility; the map does not claim to provide formal swimlanes or a workflow execution engine.

### Step details and role assignments

A cited step can record duration, deadline, frequency, systems used, controls, exceptions and
responsible, accountable, consulted or informed roles. Open its details to see the quoted wording and
source. A step can name several systems or several people in a role when the account supports each one.
The owner report and Markdown procedure preserve the individual citations. The Markdown role assignment
table lists only steps with an explicit assignment. A blank role has no recorded assignment.
Historical saves can omit all of these details. The map keeps its route layout when multiple roles
share a step, and the quoted assignments remain available in the step inspector.

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

In the bundled invoice example, total horizontal Diagram connector length fell from 10,444 to
7,674 layout units, and vertical length from 8,843 to 5,838. Selecting each of the 14 routes in
Cinematic kept both endpoint tiles visible for all 14 at 1024×768 and 390×844. Previously that
held for eight routes at the larger size and none at the smaller size. Loops, bypasses and branches
can still span several steps when the reported handoff requires it.

Two fictional provider replays checked route meaning as well as geometry. In crate intake, the
review retained all six reported transitions: a broken seal led to return and closure, and dispatch
followed acceptance only. In permit review, either rejection led to closure. Both approvals were
required for release, and the unknown order between the safety and finance reviews stayed open.
The source check verifies that the cited words are present. A reviewer still has to judge whether
those words establish the claimed business relationship.
