import maplibregl from "maplibre-gl";
import { toPng } from "html-to-image";

export type ScreenshotExportState = {
  style: any;
  center: [number, number];
  zoom: number;
  bearing?: number;
  pitch?: number;
  model: string;
  run: string;
  variable: { key: string; label: string };
  fh: number;
  region?: { id: string; label: string };
  loopEnabled: boolean;
};

export type ScreenshotExportOptions = {
  width?: number;
  height?: number;
  pixelRatio?: number;
  legendEl?: HTMLElement | null;
  overlayLines?: string[];
};

const DEFAULT_WIDTH = 1600;
const DEFAULT_HEIGHT = 900;
const DEFAULT_PIXEL_RATIO = 2;
const MAP_SETTLE_DELAY_MS = 150;
const MAP_IDLE_TIMEOUT_MS = 15_000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.decoding = "async";
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Failed to load image for screenshot compositing."));
    image.src = src;
  });
}

function canvasToPngBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          reject(new Error("Failed to encode screenshot PNG."));
          return;
        }
        resolve(blob);
      },
      "image/png",
      1
    );
  });
}

function drawRoundedRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number
): void {
  const r = Math.max(0, Math.min(radius, width / 2, height / 2));
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + r);
  ctx.lineTo(x + width, y + height - r);
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  ctx.lineTo(x + r, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function waitForMapLoad(map: maplibregl.Map): Promise<void> {
  if (map.loaded()) {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    map.once("load", () => resolve());
  });
}

function waitForMapIdle(map: maplibregl.Map): Promise<void> {
  return new Promise((resolve) => {
    let done = false;
    let timeoutId: number | null = null;

    const finish = () => {
      if (done) {
        return;
      }
      done = true;
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
      map.off("idle", onIdle);
      resolve();
    };

    const onIdle = () => finish();
    map.on("idle", onIdle);
    timeoutId = window.setTimeout(finish, MAP_IDLE_TIMEOUT_MS);

    if (map.loaded() && map.areTilesLoaded()) {
      finish();
    }
  });
}

function defaultOverlayLines(state: ScreenshotExportState): string[] {
  const model = state.model.trim() || "Model";
  const run = state.run.trim() || "Run";
  const variableLabel = state.variable.label.trim() || state.variable.key.trim() || "Variable";
  const regionLabel = state.region?.label?.trim() || state.region?.id?.trim() || "Region";
  return [`${model} • ${run} • FH ${state.fh}`, `${variableLabel} • ${regionLabel}`];
}

function drawOverlay(
  ctx: CanvasRenderingContext2D,
  lines: string[],
  width: number
): void {
  const cleaned = lines.map((line) => line.trim()).filter(Boolean);
  if (cleaned.length === 0) {
    return;
  }

  const paddingX = 16;
  const paddingY = 14;
  const lineHeight = 24;
  const boxX = 18;
  const boxY = 18;
  const maxWidth = Math.max(280, width * 0.6);
  const font = "700 18px system-ui, -apple-system, Segoe UI, sans-serif";

  ctx.save();
  ctx.font = font;
  let textWidth = 0;
  for (const line of cleaned) {
    textWidth = Math.max(textWidth, ctx.measureText(line).width);
  }
  const boxWidth = Math.min(maxWidth, Math.ceil(textWidth) + paddingX * 2);
  const boxHeight = cleaned.length * lineHeight + paddingY * 2 - 4;

  ctx.fillStyle = "rgba(0,0,0,0.55)";
  drawRoundedRect(ctx, boxX, boxY, boxWidth, boxHeight, 12);
  ctx.fill();

  ctx.fillStyle = "rgba(255,255,255,0.96)";
  ctx.textBaseline = "top";
  ctx.font = font;
  cleaned.forEach((line, index) => {
    ctx.fillText(line, boxX + paddingX, boxY + paddingY + index * lineHeight, boxWidth - paddingX * 2);
  });
  ctx.restore();
}

function buildLegendExportClone(legendEl: HTMLElement): { host: HTMLDivElement; clone: HTMLElement } {
  const rect = legendEl.getBoundingClientRect();
  const host = document.createElement("div");
  host.style.position = "fixed";
  host.style.left = "-10000px";
  host.style.top = "0";
  host.style.pointerEvents = "none";
  host.style.zIndex = "-1";
  host.style.padding = "0";
  host.style.margin = "0";

  const clone = legendEl.cloneNode(true) as HTMLElement;
  clone.style.position = "static";
  clone.style.left = "auto";
  clone.style.right = "auto";
  clone.style.top = "auto";
  clone.style.bottom = "auto";
  clone.style.transform = "none";
  clone.style.width = `${Math.max(120, Math.ceil(rect.width || legendEl.offsetWidth || 220))}px`;
  clone.style.maxHeight = "none";
  clone.style.height = "auto";
  clone.style.overflow = "visible";
  clone.style.backgroundColor = "rgba(0, 0, 0, 0.72)";
  clone.style.border = "1px solid rgba(255, 255, 255, 0.14)";
  clone.style.boxShadow = "0 8px 24px rgba(0, 0, 0, 0.32)";
  clone.style.backdropFilter = "none";
  clone.style.setProperty("-webkit-backdrop-filter", "none");
  clone.style.setProperty("--foreground", "0 0% 95%");
  clone.style.setProperty("--muted-foreground", "0 0% 62%");
  clone.style.setProperty("--border", "0 0% 100%");
  clone.style.setProperty("--secondary", "0 0% 100%");
  clone.style.setProperty("--muted", "0 0% 100%");

  const body = clone.querySelector<HTMLElement>("#legend-body");
  if (body) {
    body.style.gridTemplateRows = "1fr";
    body.style.overflow = "visible";
  }

  const headerButton = clone.querySelector<HTMLButtonElement>("button[aria-controls='legend-body']");
  if (headerButton) {
    headerButton.setAttribute("aria-expanded", "true");
  }

  clone.querySelectorAll<HTMLElement>("*").forEach((node) => {
    node.style.animation = "none";
    node.style.transition = "none";
    node.style.transform = "none";
    node.style.filter = "none";
    node.style.backdropFilter = "none";
    node.style.setProperty("-webkit-backdrop-filter", "none");
    node.style.textOverflow = "clip";
    node.style.maxHeight = "none";

    if (node.classList.contains("truncate")) {
      node.style.whiteSpace = "normal";
      node.style.overflow = "visible";
    }

    if (node.classList.contains("legend-scroll")) {
      node.style.maxHeight = "none";
      node.style.overflow = "visible";
      node.style.scrollbarWidth = "none";
    }
  });

  host.appendChild(clone);
  document.body.appendChild(host);
  return { host, clone };
}

async function drawLegend(
  ctx: CanvasRenderingContext2D,
  legendEl: HTMLElement,
  width: number,
  height: number,
  watermarkReserve: number
): Promise<void> {
  const { host, clone } = buildLegendExportClone(legendEl);

  try {
    if ("fonts" in document) {
      await document.fonts.ready;
    }

    const legendDataUrl = await toPng(clone, {
      cacheBust: true,
      backgroundColor: "transparent",
      pixelRatio: 2,
    });
    const legendImage = await loadImage(legendDataUrl);

    const maxWidth = 520;
    const maxHeight = 220;
    const scale = Math.min(1, maxWidth / legendImage.width, maxHeight / legendImage.height);
    const drawWidth = Math.max(1, Math.round(legendImage.width * scale));
    const drawHeight = Math.max(1, Math.round(legendImage.height * scale));
    const padding = 18;
    const platePadding = 10;
    const x = width - padding - drawWidth;
    const y = height - padding - watermarkReserve - drawHeight;

    ctx.save();
    ctx.fillStyle = "rgba(0,0,0,0.55)";
    drawRoundedRect(
      ctx,
      x - platePadding,
      y - platePadding,
      drawWidth + platePadding * 2,
      drawHeight + platePadding * 2,
      10
    );
    ctx.fill();
    ctx.drawImage(legendImage, x, y, drawWidth, drawHeight);
    ctx.restore();
  } finally {
    host.remove();
  }
}

function drawWatermark(ctx: CanvasRenderingContext2D, width: number, height: number): void {
  const text = "TheWeatherModels.com";
  const padding = 16;
  ctx.save();
  ctx.font = "600 12px system-ui, -apple-system, Segoe UI, sans-serif";
  ctx.fillStyle = "rgba(255,255,255,0.7)";
  ctx.textAlign = "right";
  ctx.textBaseline = "bottom";
  ctx.fillText(text, width - padding, height - padding);
  ctx.restore();
}

export async function exportViewerScreenshotPng(
  state: ScreenshotExportState,
  opts: ScreenshotExportOptions = {}
): Promise<Blob> {
  if (typeof document === "undefined" || typeof window === "undefined") {
    throw new Error("Screenshot export is only available in browser environments.");
  }

  const width = Number.isFinite(opts.width) ? Math.max(1, Math.round(Number(opts.width))) : DEFAULT_WIDTH;
  const height = Number.isFinite(opts.height) ? Math.max(1, Math.round(Number(opts.height))) : DEFAULT_HEIGHT;
  const pixelRatio = Number.isFinite(opts.pixelRatio)
    ? Math.max(1, Number(opts.pixelRatio))
    : DEFAULT_PIXEL_RATIO;
  const overlayLines = (opts.overlayLines ?? defaultOverlayLines(state)).filter(Boolean);

  const container = document.createElement("div");
  container.style.position = "fixed";
  container.style.left = "-10000px";
  container.style.top = "0";
  container.style.width = `${width}px`;
  container.style.height = `${height}px`;
  container.style.pointerEvents = "none";
  container.style.opacity = "0";

  document.body.appendChild(container);

  const map = new maplibregl.Map({
    container,
    style: state.style,
    center: state.center,
    zoom: state.zoom,
    bearing: state.bearing ?? 0,
    pitch: state.pitch ?? 0,
    interactive: false,
    attributionControl: false,
    preserveDrawingBuffer: true,
    pixelRatio,
  } as maplibregl.MapOptions);

  try {
    await waitForMapLoad(map);
    await waitForMapIdle(map);
    await sleep(MAP_SETTLE_DELAY_MS);

    const capturedMapCanvas = map.getCanvas();
    const rawCanvas = document.createElement("canvas");
    rawCanvas.width = Math.max(1, Math.round(width * pixelRatio));
    rawCanvas.height = Math.max(1, Math.round(height * pixelRatio));

    const rawCtx = rawCanvas.getContext("2d");
    if (!rawCtx) {
      throw new Error("Failed to create raw screenshot canvas context.");
    }
    rawCtx.drawImage(capturedMapCanvas, 0, 0, rawCanvas.width, rawCanvas.height);

    const outputCanvas = document.createElement("canvas");
    outputCanvas.width = width;
    outputCanvas.height = height;
    const outputCtx = outputCanvas.getContext("2d");
    if (!outputCtx) {
      throw new Error("Failed to create screenshot canvas context.");
    }

    outputCtx.imageSmoothingEnabled = true;
    outputCtx.imageSmoothingQuality = "high";
    outputCtx.drawImage(rawCanvas, 0, 0, width, height);
    drawOverlay(outputCtx, overlayLines, width);

    const watermarkReserve = 34;
    if (opts.legendEl) {
      try {
        await drawLegend(outputCtx, opts.legendEl, width, height, watermarkReserve);
      } catch (error) {
        console.warn("[screenshot] Legend capture failed; continuing without legend.", error);
      }
    }
    drawWatermark(outputCtx, width, height);

    return canvasToPngBlob(outputCanvas);
  } finally {
    map.remove();
    container.remove();
  }
}
