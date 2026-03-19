# CartoSky Rendering Performance QA Runbook

## Purpose

Reusable, repeatable QA script for gathering comparable performance telemetry before and after rendering changes.

Use this document to:

- generate enough event volume to make p50 and p95 useful
- verify that all key metrics are still emitting
- compare results at each implementation phase gate

## When To Run

Run this full script:

- before a new performance phase starts (baseline)
- after a phase is merged and deployed (verification)
- after any major telemetry or rendering-path change

## Test Environment

## Required Environments

- Desktop browser (primary)
- Mobile browser or device emulator (secondary)

## Browser Setup

- Use one fresh private window for cold-start steps.
- Keep one normal window for repeated interaction steps.
- Disable throttling and network emulation unless running a specific stress profile.

## Data Hygiene

- Keep tests focused on a single session block.
- Avoid mixing unrelated exploratory behavior while collecting benchmark data.
- Keep the page visible and active; background tabs can distort timing metrics.

## 45-Minute Desktop Script

### Block A: Cold Start (10 minutes)

Actions:

1. Open viewer in a fresh private window.
2. Hard refresh 8 to 10 times.
3. Wait for first visible weather frame each run.

Primary metrics:

- viewer_first_frame
- tile_fetch

### Block B: Single-Seek Frame Changes (8 minutes)

Actions:

1. Keep playback paused.
2. Perform 30 to 40 single-step frame seeks.
3. Use click-and-release or one-step drag/release only.

Primary metrics:

- frame_change

### Block C: Drag Scrub Commits (8 minutes)

Actions:

1. Perform 15 to 20 true drag scrubs across multiple hours.
2. Release at varied target hours.

Primary metrics:

- scrub_latency

### Block D: Selection Changes (8 minutes)

Actions:

1. Switch variable 20 or more times across light and heavy variables.
2. Switch model 8 to 10 times.
3. Switch between latest and one concrete run several times.

Primary metrics:

- variable_switch
- loop_manifest_resolve

### Block E: Loop Stress (10 minutes)

Actions:

1. Zoom to loop-active level.
2. Start and stop playback at least 15 times.
3. Let playback run 2 to 3 minutes continuously.
4. While playing, pan and zoom aggressively.
5. Perform intermittent scrub interactions during playback.

Primary metrics:

- loop_start
- loop_decode_ready
- loop_queue_to_visible
- loop_first_visible_paint
- animation_stall
- loop_frame_drop_gap
- long_task_blocking

## Mobile Follow-Up Script (15 to 20 minutes)

Run a shorter version of Blocks A through E on mobile.

Goal:

- ensure desktop and mobile both have usable sample counts
- verify device split in admin breakdowns

## Admin Dashboard Capture Steps

Page:

- Admin Performance dashboard

Required filter checks:

1. Window: 24h
2. Latest runs: All runs
3. Latest runs: Latest run
4. Device: All
5. Device: Desktop
6. Device: Mobile

For each check:

- confirm non-zero count where expected
- capture p50, p95, sample count
- record notable anomalies

## Minimum Sample Targets Before Phase Progression

These are minimums for confident signal quality.

| Metric | Minimum samples |
| --- | ---: |
| viewer_first_frame | 30 |
| frame_change | 100 |
| scrub_latency | 50 |
| variable_switch | 40 |
| loop_start | 40 |
| tile_fetch | 300 |
| loop_manifest_resolve | 40 |
| loop_decode_ready | 80 |
| loop_queue_to_visible | 80 |
| loop_first_visible_paint | 80 |
| animation_stall | 20 |
| long_task_blocking | 20 |
| loop_frame_drop_gap | 20 |

## Pass-Fail Gate

Pass:

- all critical metrics emit non-zero counts
- minimum sample targets are met
- no obvious telemetry regressions or missing categories

Fail:

- critical metric count remains zero after targeted interaction block
- sample volume is too low for p95 to be trusted
- metric behavior contradicts expected interaction mapping

If fail:

1. isolate the interaction that should emit the metric
2. re-run only that interaction block for 5 to 10 minutes
3. inspect telemetry path before advancing to next rendering phase

## Session Record Template

Use one table per QA run.

| Field | Value |
| --- | --- |
| Run date |  |
| Environment |  |
| App version or commit |  |
| Tester |  |
| Window filter used |  |
| Latest runs filter used |  |

| Metric | Count | p50 ms | p95 ms | Target ms | Pass |
| --- | ---: | ---: | ---: | ---: | --- |
| viewer_first_frame |  |  |  | 1500 |  |
| frame_change |  |  |  | 250 |  |
| scrub_latency |  |  |  | 150 |  |
| variable_switch |  |  |  | 600 |  |
| loop_start |  |  |  | 1000 |  |
| tile_fetch |  |  |  | 800 |  |
| loop_manifest_resolve |  |  |  | 400 |  |
| loop_decode_ready |  |  |  | 250 |  |
| loop_queue_to_visible |  |  |  | 120 |  |
| loop_first_visible_paint |  |  |  | 80 |  |
| animation_stall |  |  |  | 750 |  |
| long_task_blocking |  |  |  | 50 |  |
| loop_frame_drop_gap |  |  |  | 500 |  |

## Notes And Anomalies

Record anything unusual that can affect comparability:

- upstream network instability
- browser updates
- backend restarts during run
- cache state deviations
- known feature flags enabled or disabled

## Reuse Guidance

For every new rendering phase:

1. run this script as-is
2. compare against prior session table
3. only tune thresholds after multiple runs show stable behavior
