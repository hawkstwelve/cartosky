# CartoSky Rendering Performance — Implementation Plan

## Status

Planning document only.

- This file describes the recommended implementation order, target files, validation steps, and example code sketches.
- It does not authorize behavioral changes by itself.
- The goal is to give future work a single reference point for performance fixes across frontend rendering, interaction orchestration, and backend bootstrap behavior.

## Objectives

Primary targets:

- Reduce `scrub_latency` p95 from ~5204 ms toward < 300 ms on the warm path.
- Reduce `viewer_first_frame` p95 from ~2893 ms toward < 1500 ms, with a stretch goal near 1000 ms.
- Reduce `variable_switch` p95 from ~1011 ms toward < 600 ms, with a stretch goal near 400 ms.
- Eliminate visible blank or flash during variable switch and loop-to-tile transitions.
- Improve perceived responsiveness even when cold-path latency remains non-trivial.

## Core Diagnosis Summary

The current system already has several good building blocks:

- dual tile buffers with delayed hide semantics
- hidden tile prefetch sources
- loop frame prefetch and `ImageBitmap` decode caching
- in-place MapLibre source/layer mutation
- viewer performance telemetry for `viewer_first_frame`, `frame_change`, `scrub_latency`, `variable_switch`, `loop_start`, `tile_fetch`, and `animation_stall`

The remaining bottlenecks are architectural, not just network:

1. Scrub work is too reactive.
2. Loop predecode is not the same as loop presentation.
3. Variable switching still behaves too much like a cold-path reset.
4. First weather paint is waiting on too much bootstrap work.
5. Current telemetry does not isolate fetch, decode, source-ready, and first-visible-paint well enough.

## Constraints and Invariants

- Preserve the current telemetry meaning recorded in repo memory:
  - `viewer_first_frame` means first visible weather imagery.
  - `scrub_latency` means committed scrub to the exact requested frame, not a nearest-ready fallback.
- Avoid large rewrites in the first pass.
- Prefer phaseable changes that can be shipped by a solo developer.
- Preserve current visual correctness and geographic alignment.
- Keep a simple rollback path for each phase.

## Current Touchpoints

Primary frontend files:

- `frontend/src/App.tsx`
- `frontend/src/components/map-canvas.tsx`
- `frontend/src/components/bottom-forecast-controls.tsx`
- `frontend/src/lib/telemetry.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/tiles.ts`
- `frontend/src/pages/admin/performance.tsx`

Primary backend files:

- `backend/app/main.py`
- `backend/app/services/admin_telemetry.py`

## Proposed Delivery Model

Use seven phases:

1. Phase 0a: minimal instrumentation for scrub and variable switch
2. Phase 0b: extended instrumentation and pressure signals
3. Phase 1: scrub redesign and request prioritization
4. Phase 2: anti-flash variable switching and stale-while-revalidate presentation
5. Phase 3: first viewer frame reduction
6. Phase 4: loop presentation path overhaul
7. Phase 5: backend/bootstrap refinements

Each phase should be shippable independently.

## Phase 0a — Minimal Instrumentation for Scrub and Variable Switch

### Goal

Measure the two most important interaction paths before changing behavior.

### Why this comes first

Current metrics are useful but aggregate too much. `variable_switch` and `scrub_latency` currently combine multiple stages:

- selector or commit event
- manifest/frames discovery
- network transfer
- decode
- source readiness
- visual promotion
- first visible paint

Without stage timings, fixes will be hard to validate.

This phase is intentionally narrow. It exists to avoid turning instrumentation into a full project before the highest-value interaction fixes begin.

### Files

- `frontend/src/App.tsx`
- `frontend/src/components/map-canvas.tsx`
- `frontend/src/lib/telemetry.ts`
- `backend/app/services/admin_telemetry.py`
- `frontend/src/pages/admin/performance.tsx`

### Work items

- Add client-side trace spans for:
  - scrub live preview start
  - scrub commit start
  - requested frame fetch start
  - request complete
  - decode complete
  - source ready
  - first visible frame
- Add client-side trace spans for:
  - variable selector click
  - manifest resolved
  - frames resolved
  - first target image request
  - first target image visible
- Add counters for:
  - superseded scrub requests
  - aborted or ignored tile swaps
  - nearest-ready preview uses
  - exact-target warm hits
  - exact-target cold commits
- Extend admin performance views only after raw events exist.
- Answer the prefetch-source effectiveness question during this phase:
  - do hidden prefetch sources reduce visible-path promotion latency?
  - or do they primarily improve network transfer while still leaving decode/upload costs on the visible path?

### Example sketch

```ts
type ViewerTraceSpan = {
  name:
    | "scrub_commit"
    | "variable_click"
    | "frames_ready"
    | "loop_decode_done"
    | "tile_source_ready"
    | "first_visible_paint";
  startedAt: number;
  meta?: Record<string, unknown>;
};

function finishTraceSpan(span: ViewerTraceSpan) {
  const durationMs = performance.now() - span.startedAt;
  trackPerfEvent({
    event_name: "frame_change",
    duration_ms: durationMs,
    meta: {
      trace_span: span.name,
      ...span.meta,
    },
  });
}
```

### Acceptance criteria

- For one bad hard refresh and one bad scrub, the team can attribute most latency to one of:
  - metadata
  - fetch
  - decode
  - source readiness
  - visible paint
- Admin telemetry remains backward compatible with current top-line metrics.
- The team can state whether the 8 prefetch sources are helping the visible-path commit or only warming browser cache.

### Rollback

- Remove new trace events while keeping existing headline metrics intact.

## Phase 0b — Extended Instrumentation and Pressure Signals

### Goal

Add the deeper observability that helps explain p95 outliers and loop-path instability once Phase 1 is already moving.

### Files

- `frontend/src/App.tsx`
- `frontend/src/components/map-canvas.tsx`
- `frontend/src/lib/telemetry.ts`
- `backend/app/services/admin_telemetry.py`
- `frontend/src/pages/admin/performance.tsx`

### Work items

- Add client-side trace spans for:
  - loop manifest resolved
  - loop decode complete
  - loop queued for display
  - loop first visible paint
- Add counters for:
  - loop frame decode cache hits
  - loop frame visible-path hits
  - loop frame drops
  - loop frame decode queue depth
- Add main-thread and pressure signals:
  - long tasks > 50 ms
  - active weather tile count in viewport
  - visible tile count by zoom bucket
  - decode queue depth
  - device-specific cache pressure samples

### Acceptance criteria

- One bad loop-start or animation-stall trace can be decomposed into fetch, decode, source-ready, and display stages.
- Device-type splits are usable for comparing desktop and mobile behavior.

### Rollback

- Remove extended spans and counters while keeping Phase 0a traces and headline metrics intact.

## Phase 1 — Scrub Redesign and Request Prioritization

### Goal

Make scrub feel instant even when exact-target content is not already visible.

### Problem statement

The slider currently emits live forecast-hour changes during drag and then commits again on release. That causes request churn and repeated state changes while the user is still moving.

### Design changes

- Separate scrub into three concepts:
  - thumb position
  - preview frame
  - committed target frame
- During drag:
  - move the thumb immediately
  - optionally show nearest-ready preview
  - do not treat every drag event as a canonical exact-target render request
- On release:
  - start one exact-target commit metric
  - prioritize only the exact target and a very small forward/backward window
- Add directional prioritization:
  - if moving forward, prefer `target`, `target + 1`, `target + 2`, then nearby fallback
  - if moving backward, reverse the order
- Add latest-wins cancellation or ignore semantics consistently across both tile and loop paths.

### Files

- `frontend/src/components/bottom-forecast-controls.tsx`
- `frontend/src/App.tsx`
- `frontend/src/components/map-canvas.tsx`

### Recommended implementation

#### 1. Change scrub emissions

- Keep the slider UI responsive.
- Reduce live drag updates.
- Make exact-target commit happen only on release.

#### 2. Add a foreground scheduler

- `priority 0`: committed exact target
- `priority 1`: immediate directional neighbors
- `priority 2`: background fill

#### 2a. Reassess swap timeout policy

Current tile swap behavior includes hard-coded timeout assumptions in the map layer orchestration. Phase 1 should explicitly decide whether the new scrub model keeps or changes those constants.

- review `SCRUB_SWAP_TIMEOUT_MS`
- review `AUTOPLAY_SWAP_TIMEOUT_MS`
- decide whether timeouts remain fixed, become adaptive, or become more conservative only for autoplay

The new scrub model should not quietly inherit old timeout tradeoffs.

#### 3. Preserve stale content until exact target is paint-ready

- old frame remains visible
- no blank frame during commit
- nearest-ready preview is optional and clearly treated as preview, not commit completion

### Example sketch

```ts
type ScrubIntent = {
  requestedHour: number;
  previewHour: number | null;
  committedHour: number | null;
  direction: 1 | -1 | 0;
};

function commitScrub(hour: number) {
  startPendingFrameMetric({
    eventName: "scrub_latency",
    renderTarget: isLoopDisplayActive ? "loop" : "tiles",
    forecastHour: hour,
  });

  enqueueForegroundTarget(hour);
  setScrubIntent((current) => ({
    ...current,
    committedHour: hour,
  }));
}
```

### Acceptance criteria

- Dragging the scrubber no longer floods exact-target commits.
- Releasing the scrubber lands on the exact requested frame without visible blanking.
- `scrub_latency` p95 drops materially before any loop overhaul.

### Rollback

- Revert to existing drag/commit semantics while keeping Phase 0 instrumentation.

## Phase 2 — Anti-Flash Variable Switching and Stale-While-Revalidate Presentation

### Goal

Make variable switching visually stable and faster-feeling.

### Problem statement

Variable changes currently clear dataset readiness and start the new variable load path immediately. Even with in-place source mutation, this is still too close to a cold-path reset.

### Design changes

- Keep old variable imagery visible until the new variable’s first frame is paint-ready.
- Treat selector state and visual state as separate.
- Update labels, controls, and loading indicators immediately.
- Delay image swap until the replacement content is actually ready.
- Use short opacity crossfade only after the new content is ready.

### Files

- `frontend/src/App.tsx`
- `frontend/src/components/map-canvas.tsx`
- `frontend/src/pages/admin/performance.tsx`

### Recommended implementation

#### 1. Add switch transaction state

- old variable key
- next variable key
- started timestamp
- old visual content retained until promotion

#### 2. Dual-stack the weather overlay during switch

- current stack: visible
- next stack: warming
- promote when paint-ready

#### 3. Retain tiny first-frame state for recent variables

- at minimum, retain the last variable’s first frame
- stretch goal: keep 2 recent variables if memory allows

### Example sketch

```ts
type VariableSwitchState = {
  fromVariable: string;
  toVariable: string;
  startedAt: number;
  visualState: "holding_old" | "warming_new" | "promoting_new";
};

function beginVariableSwitch(nextVariable: string) {
  pendingVariableSwitchRef.current = {
    startedAt: performance.now(),
    fromVariableId: variable || null,
    toVariableId: nextVariable,
    modelId: model || null,
    runId: telemetryRunId,
    regionId: region || null,
  };

  setVariableSwitchState({
    fromVariable: variable,
    toVariable: nextVariable,
    startedAt: performance.now(),
    visualState: "holding_old",
  });

  setVariable(nextVariable);
}
```

### Acceptance criteria

- Variable switching does not blank the map.
- Old imagery remains visible until the new first frame is ready.
- `variable_switch` measures the new visible frame, not selector churn.

### Rollback

- Fall back to current in-place variable mutation and existing completion rules.

## Phase 3 — First Viewer Frame Reduction

### Goal

Get meaningful weather imagery onto the screen much earlier on hard refresh.

### Problem statement

The initial viewer path currently waits on too many inputs before first visible weather paint.

### Design changes

- Prefer a tile-first first paint.
- Defer non-critical work until after the first weather frame.
- Collapse bootstrap work where possible.
- Treat backend bootstrap support as a likely accelerator, not a fully separate concern.

### Files

- `frontend/src/App.tsx`
- `frontend/src/lib/api.ts`
- `backend/app/main.py`

### Recommended implementation

#### 1. Make tile-first first-paint the default cold path

- do not require loop readiness for first weather paint
- upgrade to loop only after it is actually warm

#### 2. Defer non-critical work

- anchor sampling
- optional share payload setup
- secondary manifest reconciliation
- lower-priority prefetch windows

#### 3. Use manifest-hydrated frames as the earliest usable first frame source

- trust manifest-embedded frame rows for initial render
- reconcile with `/frames` in background

#### 4. Consider a backend bootstrap payload later

- current selection metadata
- first frame metadata
- optionally the first tile template URL

If manifest-hydrated first render is not sufficient in practice, introduce the smallest viable bootstrap payload before declaring this phase complete.

### Example sketch

```ts
const criticalBootstrap = await Promise.all([
  fetchCapabilities({ signal }),
  fetchManifest(model, run, { signal }),
]);

// Defer these until after first visible weather paint.
queueMicrotask(() => {
  void fetchLoopManifest(model, resolvedRun, variable);
  void fetchAnchorFeatureCollection();
});
```

### Acceptance criteria

- The first visible weather frame appears before anchors and loop assets are fully settled.
- `viewer_first_frame` improves without breaking permalink hydration or selection correctness.
- The team has explicitly verified whether frontend-only bootstrap ordering is sufficient or whether a minimal backend bootstrap payload is required.

### Rollback

- Restore the current bootstrap ordering while retaining new telemetry.

## Phase 4 — Loop Presentation Path Overhaul

### Goal

Stop doing loop decode work twice.

### Problem statement

The app prefetches and decodes loop frames into `ImageBitmap`, but the map still displays loops through URL-based `ImageSource.updateImage`. That likely causes a second fetch/decode/upload cost on the real visible path.

### Files

- `frontend/src/App.tsx`
- `frontend/src/components/map-canvas.tsx`

### Recommended implementation

This is the riskiest phase and should begin with a spike rather than an immediate full rewrite.

### Required spike before commitment

- Validate whether a canvas-backed overlay can preserve geographic alignment through zoom, pan, DPR changes, and loop-to-tile handoff.
- Validate whether a MapLibre-compatible in-memory source path exists that materially reduces duplicate visible-path work.
- Measure memory and upload behavior on lower-memory devices before choosing the final presentation architecture.

#### Option A — preferred medium-term approach

Move loop presentation onto a dedicated canvas-backed overlay that consumes decoded frames directly.

Benefits:

- decoded frame cache becomes the display cache
- playback and scrub use the same actual presentation path
- easier control over frame pacing and crossfade

#### Option B — interim approach

If MapLibre must remain the presentation layer, reduce duplicate work by:

- minimizing URL-driven loop swaps
- keeping a smaller active ring of visible frames
- testing whether a canvas source can be updated from an in-memory surface

### Example sketch

```ts
type DecodedLoopFrame = {
  hour: number;
  bitmap: ImageBitmap;
};

function drawLoopFrame(ctx: CanvasRenderingContext2D, frame: DecodedLoopFrame) {
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
  ctx.drawImage(frame.bitmap, 0, 0, ctx.canvas.width, ctx.canvas.height);
}
```

### Required sub-work

- create a small loop frame ring buffer
- unify playback and scrub over the same decoded-frame source
- add visible-loop metrics:
  - decode ready
  - queued for display
  - actually painted

### Acceptance criteria

- `loop_start` and `animation_stall` both improve.
- The decoded frame cache directly reduces visible latency.
- Loop mode no longer depends on URL-only image swaps for every frame.
- The chosen presentation path is verified not to introduce alignment drift or unacceptable mobile memory behavior.

### Rollback

- Leave tile-mode improvements intact and revert loop presentation to URL-based updates.

## Phase 5 — Backend and Bootstrap Refinements

### Goal

Reduce mutable metadata latency and cold-path overhead.

### Files

- `backend/app/main.py`
- `frontend/src/lib/api.ts`
- optionally a new bootstrap endpoint

### Recommended implementation

#### 1. Add optional bootstrap endpoint

Candidate response shape:

- capabilities subset for active model
- latest run
- manifest summary
- first renderable variable
- first frame rows for selected variable

This endpoint is best treated as Phase 3 support when frontend-only boot ordering is not enough.

#### 2. Add timing headers for investigation

- `Server-Timing`
- manifest resolve time
- frames build time
- loop manifest build time
- loop runtime render fallback time if applicable

#### 3. Preserve simple cache behavior

- keep immutable caching for concrete run/image assets
- keep short TTL plus ETag for mutable latest endpoints
- avoid introducing cache invalidation complexity unless traces demand it

### Example sketch

```py
return JSONResponse(
    content=payload,
    headers={
        "Cache-Control": "public, max-age=60",
        "ETag": etag,
        "Server-Timing": "manifest;dur=12,frames;dur=6",
    },
)
```

### Acceptance criteria

- Hard refresh traces show fewer blocking round trips before first weather paint.
- Latest-run metadata becomes easier to debug when it is slow.

### Rollback

- Remove bootstrap endpoint consumers while leaving existing endpoints unchanged.

## Cross-Cutting Refactors

These can happen incrementally after Phase 1.

### Reusable request scheduler

Create a small shared scheduler for weather imagery work:

- exact-target foreground
- near-window prefetch
- background fill
- cancellation or ignore-on-completion semantics

Likely location:

- new file `frontend/src/lib/render-scheduler.ts`

### Viewport-aware readiness model

Current readiness is keyed only by URL and TTL. Add a lightweight viewport or tile-set signature so “ready” means ready for the current visible area.

Likely location:

- `frontend/src/App.tsx`
- `frontend/src/components/map-canvas.tsx`

### Performance feature flags

Add guarded rollout flags for riskier changes:

- scrub-commit-only exact mode
- stale-while-revalidate variable switch
- tile-first initial paint
- canvas-based loop presentation

Likely location:

- `frontend/src/lib/config.ts`

## Suggested Delivery Order

### Week 1

- Phase 0a instrumentation
- scrub trace spans
- variable switch trace spans
- prefetch-source effectiveness measurement

### Week 2

- Phase 1 scrub redesign
- preview versus commit separation
- latest-wins foreground scheduler

Phase 0b can begin in parallel only if it does not block scrub work.

### Week 3

- Phase 2 stale-while-revalidate variable switching
- anti-flash promotion logic

### Week 4

- Phase 3 first-frame reduction
- defer anchors and non-critical bootstrap work
- tile-first initial paint
- add minimal bootstrap payload if frontend-only changes are not enough

### Week 5+

- Phase 4 loop presentation overhaul
- Phase 5 backend bootstrap improvements

## Validation Matrix

For every phase, validate:

- hard refresh on latest run
- hard refresh on concrete historical run
- variable switch within same model/run
- scrub drag then commit on tiles
- scrub drag then commit on loop
- loop start at low zoom
- loop-to-tile transition at high zoom
- mobile-width viewport
- desktop-width viewport
- mobile memory-pressure case with lower loop decode cache budget

## Testing and Telemetry Checklist

- Add targeted frontend tests where logic is isolated enough to test deterministically.
- Keep telemetry meaning stable while extending detail.
- Capture before/after traces for:
  - one bad hard refresh
  - one bad scrub
  - one bad variable switch
- Record p50 and p95 changes after every phase.

## Expected Impact by Phase

### After Phase 1

- biggest likely improvement: `scrub_latency`
- secondary improvement: perceived responsiveness during drag

### After Phase 2

- biggest likely improvement: reduced flashing and lower perceived variable-switch latency

### After Phase 3

- biggest likely improvement: `viewer_first_frame`

### After Phase 4

- biggest likely improvement: `loop_start` and `animation_stall`

### After Phase 5

- biggest likely improvement: cold-path consistency and easier diagnosis of remaining outliers

## Open Questions to Resolve During Implementation

- How many visible weather tiles are typically in viewport by zoom bucket and device class?
- How often is `loop.webp` runtime-generated for latest runs versus served from cached artifacts?
- Does MapLibre image-source presentation support a practical in-memory path, or should loop mode move to a dedicated canvas overlay?
- Which variables produce the highest decode cost and why?
- Are the current scrub and autoplay swap timeout constants still appropriate after the interaction model changes?

## Final Recommendation

Do not start with a full rendering rewrite.

Start with:

1. instrumentation
2. scrub semantics
3. stale-while-revalidate visual switching
4. first-paint critical-path cuts

Only after those land should the project take on the bigger loop presentation refactor.

That order gives the highest confidence path to meaningful p95 improvement without destabilizing the viewer.