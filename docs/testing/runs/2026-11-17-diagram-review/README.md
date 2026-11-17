# Workflow diagram review, November 17, 2026

This review continued from GitHub commit `b71f6fc` after [PR #3](https://github.com/amelas-dev/ai-process-collector/pull/3). It covers background scheduling, the interview page, and diagram rendering and export. The [earlier run](../2026-11-17-map-lanes/README.md) covers the provider client, map helpers and document service.

| Area | Failure reproduced | Fix |
| --- | --- | --- |
| Scheduling | An older failed source check could mark a newer diagram as failed. A failed redraw after an edit could keep scheduling checks of the old wording. | Each failure belongs to the version it checked. Queued checks verify the source is still current before calling the provider. |
| Map continuity | A change of intake could reuse a map that cited the old intake. Switching document workspaces could reuse the previous workspace's map. A refused incremental update could hide the last good map. | A changed workspace or changed intake evidence starts a fresh draw. A process rename preserves a map supported entirely by participant answers. A refused update keeps the published checkpoint available. |
| Wrap up and shutdown | Wrap up could queue another comparison of the same account, lose a requested retry, or return a ready status without the map that had just finished. Workers could carry requests past shutdown. | The comparison runs once per revision, an explicit retry survives the comparison, and a ready reply includes the completed map. Shutdown cancels active work and skips discarded jobs. |
| Interview page | A poll for a late diagram could overwrite synchronized notes with older notes. A notes failure before the first draw could stop the page from fetching the map. | After Wrap up the page applies only the late diagram. During an interview it continues fetching the drawing and source check even if notes fail. |
| Status and retry | Routine polling could hide which answer the displayed diagram covered. Failures of both notes and the map could leave Workflow claiming it was still updating. | An earlier diagram identifies its last answer. Each panel reports its own failure and the diagram offers a retry when its draw or source check fails. |
| Diagram export | Removing a display-only gateway left exported arrows disconnected. Rework routes could cut diagonally across the gateway. Duplicate routes in an older draft could receive the coordinates of an unrelated route in BPMN. | SVG, PNG, print and BPMN use the reported source step for each exported branch. Rework routes follow the gateway bends. BPMN matches a saved route by its endpoints and label. |
| Diagram display | A step with a repeat route and an onward route lacked a gateway. The miniature overview omitted links to implied markers, and step tooltips omitted source IDs. | Both alternatives leave a gateway. The overview includes its connecting lines, and step tooltips carry the citations through SVG export. |

## Browser verification

In headless Chrome on macOS, the same typed interview ran against the project's synthetic provider with a delayed map. The status response reported a notes failure before the first draw. On `b71f6fc` the page made one status request and never displayed the diagram. With the fixes it showed the diagram, received the completed source check and retained the notes error.

The export check rendered all 22 nonempty maps saved in the [stress run](../2026-11-17-stress/README.md), covering 378 reported connections. It read the start of each exported SVG path in Chrome and checked it against both the corresponding route and the edge of the reported source step. Before the fix, 130 arrows were detached. After the fix, all 378 started at their source steps, within one SVG unit. All 22 exports retained the recorded step and connection counts and excluded implied markers.

Two further Chrome cases exercised **Update workflow** after a failed source check, once during an ordinary interview and once after Wrap up. Each click issued one workflow request, kept the notes and updated the diagram. The three-answer typed interview and the 36-action navigation, save and discard check also completed without page errors.

## Regression tests

The scheduling scenarios use controlled workers in `tests/test_map_lanes.py`. The interview page tests are in `tests/test_map_lanes.cjs` and `tests/test_wrap_up_map_status.cjs`. The presentation and export cases are in `tests/test_workflow_presentation.cjs` and `tests/test_workflow_local_exports.cjs`.

On macOS with Python 3.12.14 and Node 24.22.1, all 95 JavaScript suites and 125 of 128 Python suites passed. Five logging and trace suites passed after their temporary directories were placed under a path with no symlink components. The same three suites also failed or timed out on the untouched GitHub checkout.

- `test_knowledge_graph.py` failed its Windows-specific process checks.
- `test_workflow_updates.py` failed two assertions that compare elapsed-time-adjusted timeouts with exact integers.
- `test_rejected_requests.py` exceeded 90 seconds.

All 31 scheduling tests passed in the final run. During a separate run under load, the paced simulation recorded a map three answers behind on one sample against a limit of two. Untouched `b71f6fc` reproduced the same sequence in four of twelve runs under load. The regression suite retains that limit.

These checks use stand-in providers and recorded diagrams. Live model timing, diagram fidelity against new answers, and physical microphone behavior remain unmeasured.
