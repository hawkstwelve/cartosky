# Performance Plan

## Purpose

This document captures the merged implementation plan based on the recent frontend and backend performance review, the follow-up regression analysis, and the final synthesis between GPT and Opus.

The goal is to dramatically improve the following user-visible and telemetry-visible performance areas without reverting away from the current WebP-first loop architecture:

- first viewer frame after a hard refresh
- loop start latency
- loop decode readiness on the critical path
- loop queue to visible behavior
- animation stalls during playback
- stalls during fast scrub and click-seek
- variable-switch responsiveness when loop playback is active

This plan assumes the following product constraints remain fixed:

- loop/WebP remains the default animation path
- tile animation is not the default fallback for smooth playback
- performance work should improve the current architecture rather than back it out
- correctness fixes already made for playback and scrubbing must remain intact

## Core Diagnosis

The main problem is not simply that decoding is expensive. The main problem is that the current loop path decodes too much, too early, and blocks too many visible transitions on decoded bitmap readiness even when the image-source path can already present the frame.

The most important current observations are:

- the loop path still uses hard-coded decode thresholds and concurrency separate from the adaptive tile buffering policy
- loop preload currently waits for a large consecutive decoded-ahead buffer before allowing playback
- playback advancement still checks decoded bitmap readiness even when playback is biased toward the loop image-source path
- background decode-ahead can still compete with the next user-visible frame
- scrub interactions still share resources with speculative warming work
- loop manifest loading is deferred later than it should be for first-play responsiveness
- backend loop WebP generation can still occur on demand on the first viewer path
- the current `loop_queue_to_visible` metric is not a clean measure of user-visible latency

## Guiding Principles

- Fix control flow before micro-optimizing algorithms.
- Prioritize the next visible frame over speculative warming.
- Separate user-blocking work from best-effort background work.
- Keep telemetry definitions honest before optimizing against them.
- Favor feature-flagged rollouts for risky viewer-path changes.
- Preserve playback and scrub correctness while reducing latency.

## High-Level Strategy

The execution order should be:

1. fix telemetry semantics
2. relax the wrong loop-start and playback gates
3. split decode and prefetch into priority lanes
4. protect scrub and variable-switch interactions from background work
5. fetch loop metadata earlier in startup
6. prewarm backend WebP artifacts for the first-play path
7. only then tune concurrency and deeper decode pipeline mechanics
8. only pursue renderer-path simplification if the earlier changes still leave measurable React or commit bottlenecks

## Phase 1 - Telemetry Correction

### Objective

Make the key performance metrics reflect actual user-visible latency instead of internal queue age or stale intermediate events.

### Why first

The current performance plan risks optimizing to the wrong number. In particular, `loop_queue_to_visible` currently behaves more like decoded-frame age than true click-to-visible or commit-to-visible latency.

### Changes

- Split the current loop presentation telemetry into at least two metrics:
  - decoded-to-commit age
  - commit-to-first-visible-paint latency
- Redefine `loop_start` to mean play-click to first advancing visible loop frame.
- Keep `viewer_first_frame` tied to first visible weather imagery, not secondary readiness markers.
- Keep `scrub_latency` tied to the exact committed destination frame instead of nearest-ready fallback frames during live drag.
- Ensure model and variable refs used by viewer telemetry are synchronized early enough to avoid `unknown` attribution buckets.

### Primary touchpoints

- [frontend/src/App.tsx](../frontend/src/App.tsx)
- [frontend/src/lib/telemetry.ts](../frontend/src/lib/telemetry.ts)
- [backend/app/main.py](../backend/app/main.py)
- [backend/app/services/admin_telemetry.py](../backend/app/services/admin_telemetry.py)

### Exit criteria

- `loop_queue_to_visible` is no longer treated as the main playback KPI.
- There is a clean metric for commit-to-visible loop latency.
- `viewer_first_frame`, `scrub_latency`, and `loop_start` align with user experience.

## Phase 2 - Loop Playback Policy Refactor

### Objective

Replace hard-coded loop decode thresholds with an explicit loop playback policy that distinguishes start conditions, steady-state playback conditions, and idle warming targets.

### Current issue

The tile path already uses an adaptive playback policy, but the loop/WebP path still relies on separate hard-coded controls. That leaves the most important animation path using less disciplined buffer logic than the fallback path.

### Changes

- Introduce a dedicated loop playback policy alongside the existing tile buffering policy.
- Replace hard-coded loop constants with named policy fields such as:
  - `minStartBuffer`
  - `minAheadWhilePlaying`
  - `targetWarmAhead`
  - `maxCriticalInFlight`
  - `maxIdleInFlight`
- Start with a smaller minimum start buffer for loop playback, likely in the 3 to 5 frame range rather than requiring 8 consecutive decoded-ahead frames.
- Keep the policy dynamic by frame count and autoplay cadence rather than hard-coding one value for all models.

### Primary touchpoints

- [frontend/src/App.tsx](../frontend/src/App.tsx)
- [frontend/src/lib/config.ts](../frontend/src/lib/config.ts)

### Exit criteria

- Loop start gating is policy-driven instead of hard-coded.
- The loop path can start earlier without regressing visible correctness.
- Startup buffer behavior can be tuned centrally rather than by scattered constants.

## Phase 3 - Presentable-Ready Instead of Bitmap-Ready

### Objective

Stop blocking playback advancement on decoded bitmap readiness when the loop image-source path can already display the next frame.

### Current issue

Playback and some scrub paths still use decoded bitmap availability as the gate, even though the map already supports direct image-source updates for loop presentation.

### Changes

- Add a loop readiness concept that distinguishes:
  - URL-presentable readiness for image-source presentation
  - bitmap-ready availability for canvas presentation
- Update playback advancement logic so image-source playback does not require `hasDecodedLoopFrame(nextHour, mode)` in order to advance.
- Preserve bitmap decode as a warm-path accelerator rather than a universal gate.
- Ensure the visible frame selection remains latest-wins and exact for committed user interactions.

### Primary touchpoints

- [frontend/src/App.tsx](../frontend/src/App.tsx)
- [frontend/src/components/map-canvas.tsx](../frontend/src/components/map-canvas.tsx)

### Exit criteria

- Active playback can continue as long as the next frame is presentable, not only bitmap-decoded.
- Animation stalls caused by decode-gate exhaustion materially decrease.
- The existing image-source presentation path remains the default visible path during playback and scrub.

## Phase 4 - Priority Decode Lanes

### Objective

Separate critical-path frame work from speculative warming so the decoder spends time on the next frames the user is about to see.

### Current issue

The current preload and background decode behavior is still too flat. It can spend capacity on frames that are nice to have while the next visible frames are still not ready.

### Changes

- Split loop work into explicit priority lanes:
  - immediate next-frame lane
  - short-ahead lane for the next 3 to 4 forecast hours
  - idle warm lane for the remaining useful buffer
- Reserve critical slots for the immediate and short-ahead lanes.
- Allow idle warming only when no urgent user-visible work is waiting.
- Abort or pause idle lane work when playback falls behind, scrub starts, variable switch begins, or selection changes.
- Keep speculative warming bounded by a strict policy instead of opportunistically filling the cache.

### Primary touchpoints

- [frontend/src/App.tsx](../frontend/src/App.tsx)

### Exit criteria

- The next visible loop frames are always prioritized over deep-ahead warming.
- The common “stall after the initial ready buffer is consumed” pattern is materially reduced.
- Decode pressure aligns with what the viewer will show in the next second, not what it might show much later.

## Phase 5 - Scrub and Variable-Switch Protection

### Objective

Ensure scrub and variable-switch interactions cannot be starved by autoplay warming or deep-ahead decode work.

### Current issue

Scrubbing is better than before, but it still competes with other decode activity. The user-visible frame being requested should outrank everything except the exact next playback frame.

### Changes

- Reserve at least one dedicated decode or presentation slot for active scrub requests.
- Suspend idle decode-ahead while live scrubbing is active.
- Commit immediately to the exact requested loop image URL on the image-source path.
- Keep bitmap decode for scrub as best-effort warming rather than the gate for visible response.
- Apply the same priority discipline to variable-switch first-visible loop frames.

### Primary touchpoints

- [frontend/src/App.tsx](../frontend/src/App.tsx)

### Exit criteria

- Fast scrubbing no longer stalls because of deep-ahead decode work.
- Click-seek and scrub-commit land on the correct visible frame with lower p95 latency.
- Variable-switch responsiveness improves without reintroducing overlay lag.

## Phase 6 - Earlier Loop Manifest Availability

### Objective

Reduce first-play latency by making loop metadata available earlier in the startup flow.

### Current issue

Loop manifest loading is still deferred behind first weather frame paint in the non-critical bootstrap path. That helps protect paused cold start, but it pushes important work later than necessary for the first play interaction.

### Changes

- Remove the `firstWeatherFramePainted` gate from loop-manifest fetching.
- Keep non-critical bootstrap deferral for lower-value startup tasks such as anchors and other nonessential enrichment.
- Start loop-manifest fetching as soon as model, run, variable, and renderable selection are stable.
- Validate that earlier loop-manifest fetch does not regress first paused-frame paint.

### Primary touchpoints

- [frontend/src/App.tsx](../frontend/src/App.tsx)
- [frontend/src/lib/api.ts](../frontend/src/lib/api.ts)

### Exit criteria

- First play no longer waits on avoidably late loop-manifest resolution.
- Cold-start first-frame behavior stays stable or improves.

## Phase 7 - Backend WebP Prewarm

### Objective

Remove cold on-demand loop WebP generation from the most common first-viewer and first-play path.

### Current issue

The backend can still generate loop WebP assets on demand. That means the first viewer can pay an artifact-generation cost that should have been handled earlier.

### Changes

- Add publish-time or immediate post-publish prewarming for loop WebP artifacts.
- Start with tier 0 for the default variable and the first set of likely-played forecast hours.
- Expand to tier 1 only after measuring whether the added generation cost is justified.
- Consider prioritizing prewarm by model popularity and default selection behavior rather than trying to warm every variable equally.
- Add telemetry around prewarm hit rate versus on-demand generation fallback.

### Primary touchpoints

- [backend/app/main.py](../backend/app/main.py)
- [backend/app/services](../backend/app/services)
- [backend/scripts](../backend/scripts)

### Exit criteria

- First-play loop requests rarely trigger on-demand loop WebP generation.
- Cold-start loop start latency improves on newly published runs.

## Phase 8 - Concurrency and Decode Pipeline Tuning

### Objective

Increase throughput only after the viewer stops doing the wrong work first.

### Current issue

Blindly increasing decode concurrency before fixing scheduling will just do more noncritical work faster and may increase CPU pressure, memory pressure, and cache churn.

### Changes

- After Phases 2 through 7 land, increase critical-path decode concurrency modestly if telemetry still shows the short-ahead lane cannot stay ahead of autoplay.
- Keep idle lane concurrency lower than critical-path concurrency.
- Re-evaluate bitmap cache pressure after the control-flow changes. The cache may naturally become smaller and less problematic once speculative warming is reduced.
- If needed, test deeper pipeline improvements such as alternative decode APIs only after the main control-flow bottlenecks are resolved.

### Primary touchpoints

- [frontend/src/App.tsx](../frontend/src/App.tsx)

### Exit criteria

- Critical-path throughput improves without a large rise in stalls caused by CPU or memory contention.
- Cache churn and decode queue growth stay bounded during playback.

## Phase 9 - Optional Renderer-Path Simplification

### Objective

Reduce state-commit overhead only if measurable latency remains after the loop control-flow fixes are complete.

### Current issue

Playback still advances through the React state chain, but that is not the first-order problem right now. It becomes worth attacking only if commit latency remains materially high after the earlier phases land.

### Changes

- Measure commit-to-visible costs after the telemetry rewrite and playback-policy changes.
- If the React-mediated frame advancement path is still a bottleneck, isolate a thinner playback controller for loop frame advancement.
- Limit any renderer-path rewrite to the playback driver first rather than broad viewer-state re-architecture.

### Primary touchpoints

- [frontend/src/App.tsx](../frontend/src/App.tsx)
- [frontend/src/components/map-canvas.tsx](../frontend/src/components/map-canvas.tsx)

### Exit criteria

- This phase only proceeds if earlier work leaves a measurable commit bottleneck.
- Any simplification improves latency without breaking selection, telemetry, or pause/scrub correctness.

## Rollout Order

Implement in this order:

1. telemetry correction
2. loop playback policy refactor
3. presentable-ready playback gating
4. priority decode lanes
5. scrub and variable-switch protection
6. earlier loop-manifest availability
7. backend WebP prewarm
8. concurrency tuning
9. optional renderer-path simplification

## Suggested Feature Flags

Use flags for the risky viewer-path changes so they can be tested independently:

- `VITE_CARTOSKY_LOOP_POLICY_V2`
- `VITE_CARTOSKY_LOOP_PRESENTABLE_READY`
- `VITE_CARTOSKY_LOOP_PRIORITY_LANES`
- `VITE_CARTOSKY_EARLY_LOOP_MANIFEST`
- backend flag for loop WebP prewarm enablement

The exact names can change, but the separation should remain. Telemetry should identify which flags were active for the sampled interaction.

## Validation Plan

For each phase, validate using both telemetry and direct interaction checks.

### Viewer checks

- hard refresh to first visible weather frame
- first play after hard refresh
- continuous autoplay for 10 to 15 seconds on a fresh selection
- fast scrub drag across a long forecast range
- repeated click-seek on nonadjacent forecast hours
- variable switch while paused
- variable switch immediately before or during playback

### Primary metrics

- `viewer_first_frame`
- `loop_start`
- new commit-to-visible loop metric
- `loop_decode_ready`
- `scrub_latency`
- `animation_stall`
- `loop_frame_drop_gap`

### Success criteria

- viewer first frame improves without regressing first visible imagery correctness
- loop start p95 drops materially on hard refresh and first play
- animation stall frequency falls sharply during normal autoplay windows
- scrub latency p95 improves during fast drag and click-seek flows
- loop decode work becomes more aligned with the next visible frames rather than deep-ahead warming

## Risks and Mitigations

- Risk: starting playback earlier reintroduces visible overlay mismatch
- Mitigation: keep image-source presentation as the active playback path and validate exact hour commitment with telemetry

- Risk: earlier loop-manifest loading regresses cold-start first-frame paint
- Mitigation: move only the loop manifest earlier, not the rest of deferred bootstrap work

- Risk: server-side prewarm increases publish-time cost too much
- Mitigation: start with tier 0 and default-variable first-play hours only, then measure

- Risk: concurrency tuning reintroduces CPU spikes or memory churn
- Mitigation: tune concurrency only after lane prioritization is in place and measure cache high-water marks

## Definition of Done

This plan is successful when all of the following are true:

- first viewer frame is visibly faster on a cold load
- first play no longer feels delayed by loop preparation work
- autoplay does not predictably stall after the initial ready buffer is consumed
- fast scrub interactions remain responsive under load
- variable switch remains visually correct and faster than the current baseline
- telemetry cleanly distinguishes queue age, commit latency, and first visible paint
- on-demand backend loop WebP generation is uncommon on the common first-play path

At that point, deeper renderer-path or decode-pipeline work can be evaluated from a stronger baseline rather than used as a substitute for fixing the core control flow.