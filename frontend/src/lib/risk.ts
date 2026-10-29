import type { HeatLayer, RiskLevel } from "./types";

export const RISK_LABELS = ["Low", "Moderate", "High", "Severe", "No Travel"] as const;
export const RISK_KEYS = ["low", "moderate", "high", "severe", "no_travel"] as const;

/** One palette for markers, route segments, bars and the heatmap. */
export const RISK_RGB: [number, number, number][] = [
  [38, 166, 91], // Low
  [232, 185, 35], // Moderate
  [242, 125, 38], // High
  [214, 40, 57], // Severe
  [111, 38, 163], // No Travel
];
export const UNKNOWN_COLOR = "#9aa5b1";

export const riskColor = (level: RiskLevel | null | undefined) =>
  level == null ? UNKNOWN_COLOR : `rgb(${RISK_RGB[level].join(",")})`;

/** Lower edges of Moderate, High, Severe, No Travel — same as the backend rules. */
export const THRESHOLDS: Record<Exclude<HeatLayer, "risk">, { unit: string; edges: number[] }> = {
  wind: { unit: "mph", edges: [25, 35, 45, 55] },
  rain: { unit: "in/hr", edges: [0.1, 0.25, 0.5, 1.0] },
  snow: { unit: "in/hr", edges: [0.5, 1.0, 2.0, 3.0] },
};

/** Map a raw value to the continuous 0–4 risk scale (agrees with the bands at their edges). */
export function toScale(layer: HeatLayer, value: number): number {
  if (layer === "risk") return value;
  const edges = [0, ...THRESHOLDS[layer].edges];
  for (let i = 1; i < edges.length; i++) {
    if (value < edges[i]) return i - 1 + (value - edges[i - 1]) / (edges[i] - edges[i - 1]);
  }
  return 4;
}

/** Colour on the continuous 0–4 scale, blended between the level colours. */
export function scaleRgb(score: number): [number, number, number] {
  const s = Math.max(0, Math.min(4, score));
  const i = Math.min(3, Math.floor(s));
  const f = s - i;
  const a = RISK_RGB[i];
  const b = RISK_RGB[i + 1];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

// --- formatting -------------------------------------------------------------------------------

export function formatDuration(seconds: number): string {
  const m = Math.round(seconds / 60);
  const h = Math.floor(m / 60);
  return h ? `${h} h ${String(m % 60).padStart(2, "0")} m` : `${m} min`;
}

const timeFmt = new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
const timeOnly = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });

export const formatTime = (iso: string | Date) => timeFmt.format(typeof iso === "string" ? new Date(iso) : iso);
export const formatClock = (iso: string | Date) => timeOnly.format(typeof iso === "string" ? new Date(iso) : iso);

export const formatMiles = (mi: number) => (mi >= 100 ? `${Math.round(mi)} mi` : `${mi.toFixed(mi >= 10 ? 0 : 1)} mi`);

export const localTimeZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;
