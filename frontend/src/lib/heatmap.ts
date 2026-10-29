import { scaleRgb, toScale } from "./risk";
import type { GeometryRow, HeatLayer, HeatmapResponse } from "./types";

const UPSCALE = 8;

/**
 * Render one heatmap frame as a PNG data URL.
 *
 * The backend grid is square in Web Mercator, so one pixel per grid cell maps exactly onto the
 * overlay bounds. Fractional hours are blended between neighbouring hourly frames, which lets
 * the slider move in 15-minute steps and makes playback smooth.
 */
export function renderFrame(heat: HeatmapResponse, layer: HeatLayer, hour: number): string {
  const frames = heat.layers[layer];
  const h0 = Math.max(0, Math.min(frames.length - 1, Math.floor(hour)));
  const h1 = Math.min(frames.length - 1, h0 + 1);
  const f = hour - h0;
  const a = frames[h0];
  const b = frames[h1];

  const small = document.createElement("canvas");
  small.width = heat.cols;
  small.height = heat.rows;
  const ctx = small.getContext("2d")!;
  const img = ctx.createImageData(heat.cols, heat.rows);
  const transparentWhenCalm = layer === "rain" || layer === "snow";

  heat.cells.forEach(([row, col], i) => {
    const va = a[i];
    const vb = b[i];
    const value = va == null ? vb : vb == null ? va : va + (vb - va) * f;
    if (value == null) return;
    const score = toScale(layer, value);
    if (transparentWhenCalm && score < 0.02) return;
    const [r, g, bl] = scaleRgb(score);
    const alpha = 0.18 + 0.62 * Math.min(1, score / 3);
    const p = (row * heat.cols + col) * 4;
    img.data[p] = r;
    img.data[p + 1] = g;
    img.data[p + 2] = bl;
    img.data[p + 3] = Math.round(alpha * 255);
  });
  ctx.putImageData(img, 0, 0);

  // Upscale with smoothing so cells blend into a continuous field instead of blocks.
  const big = document.createElement("canvas");
  big.width = heat.cols * UPSCALE;
  big.height = heat.rows * UPSCALE;
  const bctx = big.getContext("2d")!;
  bctx.imageSmoothingEnabled = true;
  bctx.imageSmoothingQuality = "high";
  bctx.drawImage(small, 0, 0, big.width, big.height);
  return big.toDataURL("image/png");
}

/** Where the truck is `elapsedS` seconds after departure, or null before/after the trip. */
export function positionAt(geometry: GeometryRow[], elapsedS: number): [number, number] | null {
  if (!geometry.length || elapsedS < 0 || elapsedS > geometry[geometry.length - 1][3]) return null;
  let lo = 0;
  let hi = geometry.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (geometry[mid][3] <= elapsedS) lo = mid;
    else hi = mid;
  }
  const [aLat, aLon, , aT] = geometry[lo];
  const [bLat, bLon, , bT] = geometry[hi];
  const f = bT === aT ? 0 : (elapsedS - aT) / (bT - aT);
  return [aLat + (bLat - aLat) * f, aLon + (bLon - aLon) * f];
}
