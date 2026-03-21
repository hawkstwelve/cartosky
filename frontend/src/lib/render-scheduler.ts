export type ScrubCommitIntent = {
  hour: number;
  direction: -1 | 0 | 1;
  startedAt: number;
};

export type PrefetchScheduleArgs = {
  frameHours: number[];
  forecastHour: number;
  maxRequests: number;
  targetReady: number;
  readyHours: Set<number>;
  failedHours: Set<number>;
  inFlightHours: Set<number>;
  isPreloadingForPlay: boolean;
  isScrubbing: boolean;
  scrubCommitIntent: ScrubCommitIntent | null;
  commitIntentTtlMs: number;
  neighborWindow: number;
  nowMs: number;
  retryAtByHour: Map<number, number>;
};

export function selectPrefetchFrameHours(args: PrefetchScheduleArgs): number[] {
  const {
    frameHours,
    forecastHour,
    maxRequests,
    targetReady,
    readyHours,
    failedHours,
    inFlightHours,
    isPreloadingForPlay,
    isScrubbing,
    scrubCommitIntent,
    commitIntentTtlMs,
    neighborWindow,
    nowMs,
    retryAtByHour,
  } = args;

  if (frameHours.length === 0 || maxRequests <= 0) {
    return [];
  }

  const activeInFlight = frameHours.filter((fh) => inFlightHours.has(fh)).slice(0, maxRequests);
  if (readyHours.size + inFlightHours.size >= targetReady) {
    return activeInFlight;
  }

  const commitIntentActive = Boolean(
    scrubCommitIntent
    && !isScrubbing
    && nowMs - scrubCommitIntent.startedAt <= commitIntentTtlMs
  );
  const activeCommitIntent = commitIntentActive ? scrubCommitIntent : null;
  const requestedPivotHour = Number.isFinite(activeCommitIntent?.hour)
    ? nearestFrame(frameHours, activeCommitIntent?.hour as number)
    : forecastHour;
  const currentIndex = frameHours.indexOf(requestedPivotHour);
  const pivot = currentIndex >= 0 ? currentIndex : 0;

  const candidates: number[] = [...activeInFlight];
  const seen = new Set<number>(activeInFlight);

  const pushCandidate = (fh: number) => {
    if (seen.has(fh)) return;
    seen.add(fh);
    if (readyHours.has(fh) || inFlightHours.has(fh)) return;
    if (failedHours.has(fh)) {
      if (isScrubbing) {
        return;
      }
      const retryAt = retryAtByHour.get(fh) ?? 0;
      if (nowMs < retryAt) {
        return;
      }
    }
    candidates.push(fh);
  };

  pushCandidate(frameHours[pivot]);

  const pushDirectionalNeighbors = (direction: 1 | -1) => {
    for (let step = 1; step <= neighborWindow; step += 1) {
      const index = pivot + direction * step;
      if (index < 0 || index >= frameHours.length) {
        continue;
      }
      pushCandidate(frameHours[index]);
      if (candidates.length >= maxRequests) {
        return;
      }
    }
  };

  const fillDirection = (direction: 1 | -1) => {
    const start = direction === 1 ? pivot + 1 : pivot - 1;
    for (let i = start; i >= 0 && i < frameHours.length; i += direction) {
      pushCandidate(frameHours[i]);
      if (candidates.length >= maxRequests) {
        return;
      }
    }
  };

  const preferredDirection = activeCommitIntent?.direction ?? 0;
  if (!isPreloadingForPlay && (preferredDirection === 1 || preferredDirection === -1)) {
    pushDirectionalNeighbors(preferredDirection);
    if (candidates.length >= maxRequests) {
      return candidates.slice(0, maxRequests);
    }

    pushDirectionalNeighbors(preferredDirection === 1 ? -1 : 1);
    if (candidates.length >= maxRequests) {
      return candidates.slice(0, maxRequests);
    }

    fillDirection(preferredDirection);
    if (candidates.length >= maxRequests) {
      return candidates.slice(0, maxRequests);
    }

    fillDirection(preferredDirection === 1 ? -1 : 1);
    return candidates.slice(0, maxRequests);
  }

  for (let i = pivot + 1; i < frameHours.length; i += 1) {
    pushCandidate(frameHours[i]);
    if (candidates.length >= maxRequests) {
      return candidates.slice(0, maxRequests);
    }
  }

  if (isPreloadingForPlay) {
    for (let i = 0; i < frameHours.length; i += 1) {
      pushCandidate(frameHours[i]);
      if (candidates.length >= maxRequests) {
        return candidates.slice(0, maxRequests);
      }
    }
  } else {
    for (let i = pivot - 1; i >= 0; i -= 1) {
      pushCandidate(frameHours[i]);
      if (candidates.length >= maxRequests) {
        return candidates.slice(0, maxRequests);
      }
    }
  }

  return candidates.slice(0, maxRequests);
}

function nearestFrame(frameHours: number[], requestedHour: number): number {
  return frameHours.reduce((best, candidate) => {
    const bestDelta = Math.abs(best - requestedHour);
    const candidateDelta = Math.abs(candidate - requestedHour);
    if (candidateDelta < bestDelta) {
      return candidate;
    }
    if (candidateDelta === bestDelta && candidate > best) {
      return candidate;
    }
    return best;
  }, frameHours[0]);
}
