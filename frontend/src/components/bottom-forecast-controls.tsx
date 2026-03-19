import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, Clock, Pause, Play } from "lucide-react";

import type { ViewerLayoutMode } from "@/lib/viewer-layout";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

type BottomForecastControlsProps = {
  forecastHour: number;
  availableFrames: number[];
  onForecastHourChange: (fh: number, reason?: "standard" | "scrub-live" | "scrub-commit") => void;
  onScrubStateChange?: (isScrubbing: boolean) => void;
  isPlaying: boolean;
  setIsPlaying: (value: boolean) => void;
  runDateTimeISO: string | null;
  disabled: boolean;
  playDisabled?: boolean;
  transientStatus?: string | null;
  layoutMode?: ViewerLayoutMode;
};

function formatValidTime(runDateISO: string | null, forecastHour: number): {
  primary: string;
  secondary: string;
} | null {
  if (!runDateISO) return null;

  try {
    const runDate = new Date(runDateISO);
    if (Number.isNaN(runDate.getTime())) return null;

    const validDate = new Date(runDate.getTime() + forecastHour * 60 * 60 * 1000);

    const primary = new Intl.DateTimeFormat("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZoneName: "short",
    }).format(validDate);

    const secondary = `FH ${forecastHour}`;

    return { primary, secondary };
  } catch {
    return null;
  }
}

export function BottomForecastControls({
  forecastHour,
  availableFrames,
  onForecastHourChange,
  onScrubStateChange,
  isPlaying,
  setIsPlaying,
  runDateTimeISO,
  disabled,
  playDisabled = false,
  transientStatus,
  layoutMode = "desktop",
}: BottomForecastControlsProps) {
  const DRAG_UPDATE_MS = 80;
  const [previewHour, setPreviewHour] = useState<number | null>(null);
  const [isScrubbing, setIsScrubbing] = useState(false);
  const lastDragEmitAtRef = useRef(0);
  const lastSentHourRef = useRef<number | null>(null);

  const validTime = useMemo(
    () => formatValidTime(runDateTimeISO, previewHour ?? forecastHour),
    [runDateTimeISO, forecastHour, previewHour]
  );

  const hasFrames = availableFrames.length > 0;
  const isDesktopLayout = layoutMode === "desktop";
  const isTabletTouchLayout = layoutMode === "tablet-touch";
  const effectiveHour = previewHour ?? forecastHour;
  const sliderIndex = Math.max(0, availableFrames.indexOf(effectiveHour));

  useEffect(() => {
    setPreviewHour(null);
  }, [forecastHour]);

  useEffect(() => {
    onScrubStateChange?.(isScrubbing);
  }, [isScrubbing, onScrubStateChange]);

  useEffect(() => {
    if (isPlaying && isScrubbing) {
      setIsScrubbing(false);
    }
  }, [isPlaying, isScrubbing]);

  useEffect(() => {
    lastSentHourRef.current = forecastHour;
  }, [forecastHour]);

  const emitForecastHour = (next: number, force: boolean) => {
    const now = Date.now();
    const shouldEmit =
      force ||
      (lastSentHourRef.current !== next && now - lastDragEmitAtRef.current >= DRAG_UPDATE_MS);
    if (!shouldEmit) {
      return;
    }
    lastDragEmitAtRef.current = now;
    lastSentHourRef.current = next;
    onForecastHourChange(next, force ? "scrub-commit" : "scrub-live");
  };

  return (
    <TooltipProvider delayDuration={300}>
      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex items-end justify-center px-2 pb-3 sm:px-4 sm:pb-5">
        <div
          className={cn(
            "pointer-events-auto flex flex-col glass-strong",
            isDesktopLayout
              ? "w-full max-w-3xl gap-2.5 rounded-2xl px-3 py-2.5 sm:px-4 sm:py-3"
              : isTabletTouchLayout
                ? "w-[min(90vw,560px)] gap-2 rounded-xl px-2.5 py-2"
                : "w-full max-w-3xl gap-2.5 rounded-2xl px-3 py-2.5 sm:px-4 sm:py-3"
          )}
        >
          <div className={isDesktopLayout ? "hidden" : "block"}>
            <div className={cn("flex items-start justify-between gap-2", isTabletTouchLayout ? "mb-1.5" : "mb-2")}>
              <div className="min-w-0">
                {validTime ? (
                  <div className="truncate text-xs font-semibold text-foreground">{validTime.primary}</div>
                ) : (
                  <div className="text-[10px] text-muted-foreground">Valid time unavailable</div>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {transientStatus ? (
                  <div className="flex items-center gap-1 rounded-md border border-border/35 bg-background/35 px-2 py-1 text-[9px] text-foreground/90">
                    <AlertCircle className="h-3 w-3" />
                    {transientStatus}
                  </div>
                ) : null}
              </div>
            </div>

            <div className={cn("flex items-center", isTabletTouchLayout ? "gap-2.5" : "gap-3")}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant={isPlaying ? "default" : "outline"}
                    size="sm"
                    onClick={() => setIsPlaying(!isPlaying)}
                    disabled={disabled || !hasFrames || playDisabled}
                    aria-label={isPlaying ? "Pause animation" : "Play animation"}
                    className={cn(
                      "shrink-0 p-0 transition-all duration-150",
                      isTabletTouchLayout ? "h-9 w-9 rounded-lg" : "h-10 w-10 rounded-xl"
                    )}
                  >
                    {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4 translate-x-px" />}
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top">
                  {isPlaying ? "Pause" : "Play"} animation
                </TooltipContent>
              </Tooltip>

              <div className="min-w-0 flex-1">
                <Slider
                  value={[sliderIndex]}
                  onValueChange={([value]) => {
                    const next = availableFrames[Math.round(value ?? 0)];
                    if (Number.isFinite(next)) {
                      if (!isScrubbing) {
                        setIsScrubbing(true);
                      }
                      setPreviewHour(next);
                      emitForecastHour(next, false);
                    }
                  }}
                  onValueCommit={([value]) => {
                    const next = availableFrames[Math.round(value ?? 0)];
                    if (Number.isFinite(next)) {
                      setPreviewHour(null);
                      setIsScrubbing(false);
                      emitForecastHour(next, true);
                    }
                  }}
                  min={0}
                  max={Math.max(0, availableFrames.length - 1)}
                  step={1}
                  disabled={disabled || isPlaying || !hasFrames}
                  className="w-full transition-opacity duration-150 [&>*:first-child]:h-2 [&>*:first-child]:bg-secondary/55 [&>*:nth-child(2)]:h-5 [&>*:nth-child(2)]:w-5"
                />
                {validTime ? (
                  <div className="pt-1 text-right text-[10px] font-medium uppercase tracking-wider text-foreground/60">
                    {validTime.secondary}
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          <div className={isDesktopLayout ? "flex items-center gap-5" : "hidden"}>
            <div className="flex shrink-0 items-center gap-2">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant={isPlaying ? "default" : "outline"}
                    size="sm"
                    onClick={() => setIsPlaying(!isPlaying)}
                    disabled={disabled || !hasFrames || playDisabled}
                    aria-label={isPlaying ? "Pause animation" : "Play animation"}
                    className="h-10 w-10 p-0 transition-all duration-150 hover:scale-105 active:scale-95"
                  >
                    {isPlaying ? (
                      <Pause className="h-4 w-4" />
                    ) : (
                      <Play className="h-4 w-4 translate-x-px" />
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top">
                  {isPlaying ? "Pause" : "Play"} animation
                </TooltipContent>
              </Tooltip>
            </div>

            <div className="flex flex-1 flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-foreground/65">
                  <Clock className="h-3 w-3" />
                  Forecast Hour
                </span>
                <span className="font-mono text-xs font-semibold tabular-nums tracking-tight text-foreground/95 transition-all duration-150">
                  {forecastHour}h
                </span>
              </div>
              <Slider
                value={[sliderIndex]}
                onValueChange={([value]) => {
                  const next = availableFrames[Math.round(value ?? 0)];
                  if (Number.isFinite(next)) {
                    if (!isScrubbing) {
                      setIsScrubbing(true);
                    }
                    setPreviewHour(next);
                    emitForecastHour(next, false);
                  }
                }}
                onValueCommit={([value]) => {
                  const next = availableFrames[Math.round(value ?? 0)];
                  if (Number.isFinite(next)) {
                    setPreviewHour(null);
                    setIsScrubbing(false);
                    emitForecastHour(next, true);
                  }
                }}
                min={0}
                max={Math.max(0, availableFrames.length - 1)}
                step={1}
                disabled={disabled || isPlaying || !hasFrames}
                className="w-full transition-opacity duration-150 [&>*:first-child]:h-2.5 [&>*:first-child]:bg-secondary/55 [&>*:nth-child(2)]:h-[22px] [&>*:nth-child(2)]:w-[22px]"
              />
            </div>

            <div className="flex shrink-0 flex-col items-end gap-1 border-l border-border/30 pl-5 sm:min-w-[220px]">
              {transientStatus ? (
                <div className="flex items-center gap-1.5 rounded-md border border-border/40 bg-background/40 px-2 py-1 text-[10px] text-foreground/90">
                  <AlertCircle className="h-3 w-3" />
                  {transientStatus}
                </div>
              ) : null}
              {validTime ? (
                <>
                  <span className="text-sm font-semibold leading-tight tracking-tight text-foreground transition-all duration-200">
                    {validTime.primary}
                  </span>
                  <span className="text-[10px] font-medium uppercase tracking-wider text-foreground/65 transition-all duration-200">
                    {validTime.secondary}
                  </span>
                </>
              ) : (
                <div className="flex items-center gap-1.5">
                  <AlertCircle className="h-3 w-3 text-muted-foreground" />
                  <span className="text-[10px] text-muted-foreground">Valid time unavailable</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
}
