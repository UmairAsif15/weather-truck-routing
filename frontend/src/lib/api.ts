import type { HeatmapResponse, Place, PlanRequest, PlanResponse } from "./types";

export class ApiError extends Error {}

/** Turn DRF's `{field: ["msg"]}` / `{error: "msg"}` bodies into one readable sentence. */
function describeError(body: unknown, status: number): string {
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    if (typeof record.error === "string") return record.error;
    const parts: string[] = [];
    const walk = (value: unknown, path: string) => {
      if (Array.isArray(value)) value.forEach((v) => walk(v, path));
      else if (value && typeof value === "object")
        Object.entries(value).forEach(([k, v]) => walk(v, k === "non_field_errors" ? path : k));
      else if (value != null) parts.push(path ? `${path.replace(/_/g, " ")}: ${value}` : String(value));
    };
    walk(record, "");
    if (parts.length) return parts.join(" · ");
  }
  return `Request failed (${status}).`;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError("Can't reach the server. Check your connection and try again.");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(describeError(body, res.status));
  return body as T;
}

const postJson = <T>(url: string, payload: unknown, signal?: AbortSignal) =>
  request<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });

export const searchPlaces = (q: string, signal?: AbortSignal) =>
  request<{ results: Place[] }>(`/api/geocode/?q=${encodeURIComponent(q)}`, { signal }).then((r) => r.results);

export const planTrip = (payload: PlanRequest, signal?: AbortSignal) =>
  postJson<PlanResponse>("/api/plan/", payload, signal);

export function fetchHeatmap(plan: PlanResponse, signal?: AbortSignal) {
  return postJson<HeatmapResponse>(
    "/api/heatmap/",
    {
      // Thin the polylines: the corridor only needs ~1 point per km.
      paths: plan.routes.map((r) => r.geometry.filter((_, i) => i % 3 === 0 || i === r.geometry.length - 1).map((g) => [g[0], g[1]])),
      departure: plan.departure,
      load_weight_lb: plan.load_weight_lb,
      weather_source: plan.weather_source,
      simulation: plan.simulation,
    },
    signal,
  );
}
